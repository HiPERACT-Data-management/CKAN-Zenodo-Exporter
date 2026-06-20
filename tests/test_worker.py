"""Unit tests for worker.py — RabbitMQ callback and Zenodo upload logic."""
import json
import pytest
import requests as req_lib
from unittest.mock import patch, MagicMock, call

from worker import callback, upload_to_zenodo, update_transfer_status
from tests.conftest import RABBITMQ_CONFIG


def _make_task(**overrides):
    task = {
        'username': 'testuser',
        'file_path': '/path/to/file.csv',
        'filename': 'file.csv',
        'zenodo_token': 'zenodo-token',
        'deposition_id': '12345',
        'transfer_id': 1,
    }
    task.update(overrides)
    return task


def _make_channel_and_method(delivery_tag=1):
    ch = MagicMock()
    method = MagicMock()
    method.delivery_tag = delivery_tag
    return ch, method


# ---------------------------------------------------------------------------
# callback
# ---------------------------------------------------------------------------

class TestCallback:
    def test_marks_in_progress_then_completed_on_success(self, mock_configs, mock_db_connection):
        ch, method = _make_channel_and_method()
        body = json.dumps(_make_task()).encode()

        with patch('worker.update_transfer_status') as mock_update, \
             patch('worker.upload_to_zenodo', return_value='{"status":"ok"}'):

            callback(ch, method, None, body)

            mock_update.assert_any_call(1, 'in_progress', '', 0)
            mock_update.assert_any_call(1, 'completed', '{"status":"ok"}', 0)

    def test_marks_failed_on_upload_exception(self, mock_configs, mock_db_connection):
        # retry_count=3 equals max_retries so the else branch fires (no more retries)
        ch, method = _make_channel_and_method(delivery_tag=5)
        body = json.dumps(_make_task(transfer_id=5, retry_count=3)).encode()

        with patch('worker.update_transfer_status') as mock_update, \
             patch('worker.upload_to_zenodo', side_effect=Exception("Connection refused")):

            callback(ch, method, None, body)

            mock_update.assert_any_call(5, 'failed', 'Connection refused', 3)

    def test_always_acks_on_success(self, mock_configs, mock_db_connection):
        ch, method = _make_channel_and_method(delivery_tag=3)
        body = json.dumps(_make_task(transfer_id=3)).encode()

        with patch('worker.update_transfer_status'), \
             patch('worker.upload_to_zenodo', return_value='ok'):

            callback(ch, method, None, body)

            ch.basic_ack.assert_called_once_with(delivery_tag=3)

    def test_always_acks_on_failure(self, mock_configs, mock_db_connection):
        ch, method = _make_channel_and_method(delivery_tag=4)
        body = json.dumps(_make_task(transfer_id=4)).encode()

        with patch('worker.update_transfer_status'), \
             patch('worker.upload_to_zenodo', side_effect=RuntimeError("boom")):

            callback(ch, method, None, body)

            ch.basic_ack.assert_called_once_with(delivery_tag=4)

    def test_acks_even_if_status_update_raises(self, mock_configs, mock_db_connection):
        ch, method = _make_channel_and_method(delivery_tag=6)
        body = json.dumps(_make_task(transfer_id=6)).encode()

        with patch('worker.update_transfer_status', side_effect=Exception("DB down")), \
             patch('worker.upload_to_zenodo', return_value='ok'):

            callback(ch, method, None, body)

            ch.basic_ack.assert_called_once_with(delivery_tag=6)


# ---------------------------------------------------------------------------
# upload_to_zenodo
# ---------------------------------------------------------------------------

class TestUploadToZenodo:
    def _mock_get_response(self, bucket_url='https://zenodo.org/api/files/bucket-abc'):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {'links': {'bucket': bucket_url}}
        return resp

    def _mock_put_response(self, text='{"state":"done"}'):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.text = text
        return resp

    def test_returns_zenodo_response_text(self, mock_configs, tmp_path):
        test_file = tmp_path / "data.csv"
        test_file.write_text("col1\n1")

        with patch('requests.get', return_value=self._mock_get_response()), \
             patch('requests.put', return_value=self._mock_put_response('{"state":"done"}')):

            result = upload_to_zenodo(str(test_file), 'data.csv', 'token', '12345')

        assert result == '{"state":"done"}'

    def test_puts_to_correct_bucket_url(self, mock_configs, tmp_path):
        test_file = tmp_path / "data.csv"
        test_file.write_text("data")

        with patch('requests.get', return_value=self._mock_get_response('https://zenodo.org/bucket/xyz')), \
             patch('requests.put', return_value=self._mock_put_response()) as mock_put:

            upload_to_zenodo(str(test_file), 'data.csv', 'token', '999')

            put_url = mock_put.call_args[0][0]
            assert put_url == 'https://zenodo.org/bucket/xyz/data.csv'

    def test_raises_on_get_http_error(self, mock_configs, tmp_path):
        test_file = tmp_path / "data.csv"
        test_file.write_text("data")

        bad_resp = MagicMock()
        bad_resp.raise_for_status.side_effect = req_lib.exceptions.HTTPError("401 Unauthorized")

        with patch('requests.get', return_value=bad_resp):
            with pytest.raises(req_lib.exceptions.HTTPError):
                upload_to_zenodo(str(test_file), 'data.csv', 'bad-token', '999')

    def test_raises_on_put_http_error(self, mock_configs, tmp_path):
        test_file = tmp_path / "data.csv"
        test_file.write_text("data")

        bad_put = MagicMock()
        bad_put.raise_for_status.side_effect = req_lib.exceptions.HTTPError("403 Forbidden")

        with patch('requests.get', return_value=self._mock_get_response()), \
             patch('requests.put', return_value=bad_put):

            with pytest.raises(req_lib.exceptions.HTTPError):
                upload_to_zenodo(str(test_file), 'data.csv', 'token', '999')


# ---------------------------------------------------------------------------
# update_transfer_status
# ---------------------------------------------------------------------------

class TestUpdateTransferStatus:
    def test_updates_correct_row(self, mock_configs, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection

        update_transfer_status(7, 'completed', '{"ok":true}')

        mock_cursor.execute.assert_called_once()
        args = mock_cursor.execute.call_args[0]
        assert args[1] == ('completed', '{"ok":true}', 7)
        mock_conn.commit.assert_called_once()

    def test_includes_retry_count_when_provided(self, mock_configs, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection

        update_transfer_status(3, 'pending', 'Retry 1/3', retry_count=1)

        args = mock_cursor.execute.call_args[0]
        assert args[1] == ('pending', 'Retry 1/3', 1, 3)

    def test_closes_connection_after_update(self, mock_configs, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection

        update_transfer_status(1, 'failed', 'error msg')

        mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

class TestCallbackRetry:
    def test_requeues_on_first_failure_with_incremented_retry_count(self, mock_configs):
        """First upload failure re-queues the task with retry_count=1."""
        rc = {**RABBITMQ_CONFIG, 'max_retries': '2'}
        ch, method = _make_channel_and_method()
        body = json.dumps(_make_task(retry_count=0)).encode()

        with patch('configs.get_rabbitmq_config', return_value=rc), \
             patch('worker.update_transfer_status'), \
             patch('worker.upload_to_zenodo', side_effect=Exception("Zenodo down")), \
             patch('time.sleep'):

            callback(ch, method, None, body)

        ch.basic_publish.assert_called_once()
        published = json.loads(ch.basic_publish.call_args[1]['body'])
        assert published['retry_count'] == 1

    def test_marks_failed_when_max_retries_exhausted(self, mock_configs):
        """When retry_count already equals max_retries, marks transfer as failed."""
        rc = {**RABBITMQ_CONFIG, 'max_retries': '2'}
        ch, method = _make_channel_and_method()
        body = json.dumps(_make_task(retry_count=2)).encode()  # already at max

        with patch('configs.get_rabbitmq_config', return_value=rc), \
             patch('worker.update_transfer_status') as mock_update, \
             patch('worker.upload_to_zenodo', side_effect=Exception("Zenodo down")):

            callback(ch, method, None, body)

        ch.basic_publish.assert_not_called()
        statuses = [c[0][1] for c in mock_update.call_args_list]
        assert 'failed' in statuses

    def test_acks_message_even_when_retry_is_scheduled(self, mock_configs):
        """ACK fires on every attempt so the original message leaves the queue."""
        rc = {**RABBITMQ_CONFIG, 'max_retries': '3'}
        ch, method = _make_channel_and_method(delivery_tag=10)
        body = json.dumps(_make_task(retry_count=0)).encode()

        with patch('configs.get_rabbitmq_config', return_value=rc), \
             patch('worker.update_transfer_status'), \
             patch('worker.upload_to_zenodo', side_effect=Exception("down")), \
             patch('time.sleep'):

            callback(ch, method, None, body)

        ch.basic_ack.assert_called_once_with(delivery_tag=10)

    def test_exponential_backoff_delay(self, mock_configs):
        """Sleep duration doubles with each successive retry."""
        rc = {**RABBITMQ_CONFIG, 'max_retries': '5'}
        ch, method = _make_channel_and_method()

        for retry_count, expected_sleep in [(0, 10), (1, 20), (2, 40)]:
            body = json.dumps(_make_task(retry_count=retry_count)).encode()
            with patch('configs.get_rabbitmq_config', return_value=rc), \
                 patch('worker.update_transfer_status'), \
                 patch('worker.upload_to_zenodo', side_effect=Exception("down")), \
                 patch('time.sleep') as mock_sleep:

                callback(ch, method, None, body)

            assert mock_sleep.call_args[0][0] == expected_sleep, \
                f"retry_count={retry_count}: expected sleep {expected_sleep}s"

    def test_backoff_capped_at_300_seconds(self, mock_configs):
        """Sleep never exceeds 300s regardless of retry count."""
        rc = {**RABBITMQ_CONFIG, 'max_retries': '10'}
        ch, method = _make_channel_and_method()
        body = json.dumps(_make_task(retry_count=8)).encode()  # 2^8 * 10 = 2560s uncapped

        with patch('configs.get_rabbitmq_config', return_value=rc), \
             patch('worker.update_transfer_status'), \
             patch('worker.upload_to_zenodo', side_effect=Exception("down")), \
             patch('time.sleep') as mock_sleep:

            callback(ch, method, None, body)

        assert mock_sleep.call_args[0][0] == 300
