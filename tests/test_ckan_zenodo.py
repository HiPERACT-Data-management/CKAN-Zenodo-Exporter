"""Unit tests for ckan_zenodo.py — all I/O is mocked."""
import pytest
import requests as req_lib
from unittest.mock import patch, MagicMock, call

import ckan_zenodo
from ckan_zenodo import (
    ResourceFileNotFound,
    FileTooLarge,
    ZenodoAPIError,
    DuplicateTransfer,
    get_file_path,
    export_to_zenodo,
    create_deposit_and_export,
    get_depositions,
    insert_transfer_record,
    get_transfers_for_user,
    check_duplicate_transfer,
    get_transfer_by_id,
    reset_transfer_for_retry,
)


# ---------------------------------------------------------------------------
# get_file_path
# ---------------------------------------------------------------------------

class TestGetFilePath:
    def test_default_ckan_storage(self, mock_configs):
        resource_id = "abcdef1234567890abcdef1234567890"
        url = "http://other.example.com/resource/" + resource_id

        path = get_file_path(resource_id, url)

        assert path == "/mnt/resources/abc/def/1234567890abcdef1234567890"

    def test_user_home_storage_expands_user_placeholder(self, mock_configs):
        """resources_usr_path {user} placeholder is expanded with the username from the URL."""
        resource_id = "abc123"
        url = "http://ckan.test/~johndoe/myfile.csv"

        path = get_file_path(resource_id, url)

        assert path == "/mnt/homes/johndoe/myfile.csv"

    def test_user_home_different_users_get_different_paths(self, mock_configs):
        resource_id = "abc123"

        path_alice = get_file_path(resource_id, "http://ckan.test/~alice/report.csv")
        path_bob = get_file_path(resource_id, "http://ckan.test/~bob/report.csv")

        assert "alice" in path_alice
        assert "bob" in path_bob
        assert path_alice != path_bob


# ---------------------------------------------------------------------------
# check_duplicate_transfer
# ---------------------------------------------------------------------------

class TestCheckDuplicateTransfer:
    def test_raises_when_active_transfer_exists(self, mock_configs, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.return_value = {'id': 5}

        with pytest.raises(DuplicateTransfer):
            check_duplicate_transfer('res-123', '999')

    def test_passes_when_no_active_transfer(self, mock_configs, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.return_value = None

        check_duplicate_transfer('res-new', '999')  # should not raise


# ---------------------------------------------------------------------------
# export_to_zenodo
# ---------------------------------------------------------------------------

class TestExportToZenodo:
    def test_raises_duplicate_transfer(self, mock_configs, mock_session, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.return_value = {'id': 5}  # duplicate exists

        with pytest.raises(DuplicateTransfer):
            export_to_zenodo('key', 'res-id', 'file.csv', 'http://url', '123')

    def test_raises_resource_file_not_found(self, mock_configs, mock_session, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.return_value = None  # no duplicate

        with patch('ckan_zenodo.get_deposition_name', return_value='Deposit'), \
             patch('ckan_zenodo.get_file_path', return_value='/missing/file.csv'), \
             patch('os.path.exists', return_value=False):

            with pytest.raises(ResourceFileNotFound):
                export_to_zenodo('key', 'res-id', 'file.csv', 'http://url', '123')

    def test_raises_file_too_large(self, mock_configs, mock_session, mock_db_connection, tmp_path):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.return_value = None  # no duplicate

        test_file = tmp_path / "big.csv"
        test_file.write_text("data")

        big_app_config = {**mock_configs['app'], 'max_file_size_mb': '1'}

        with patch('ckan_zenodo.get_deposition_name', return_value='Deposit'), \
             patch('ckan_zenodo.get_file_path', return_value=str(test_file)), \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=2 * 1024 * 1024), \
             patch('configs.get_app_config', return_value=big_app_config):

            with pytest.raises(FileTooLarge):
                export_to_zenodo('key', 'res-id', 'file.csv', 'http://url', '123')

    def test_no_size_limit_when_max_file_size_mb_is_zero(self, mock_configs, mock_session, mock_db_connection, tmp_path):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.return_value = None  # no duplicate
        mock_cursor.lastrowid = 1

        test_file = tmp_path / "huge.csv"
        test_file.write_text("data")

        with patch('ckan_zenodo.get_deposition_name', return_value='Deposit'), \
             patch('ckan_zenodo.get_file_path', return_value=str(test_file)), \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=999 * 1024 * 1024), \
             patch('ckan_zenodo.send_upload_task'):

            export_to_zenodo('key', 'res-id', 'file.csv', 'http://url', '123')

    def test_success_creates_transfer_and_queues_task(self, mock_configs, mock_session, mock_db_connection, tmp_path):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.return_value = None  # no duplicate

        test_file = tmp_path / "data.csv"
        test_file.write_text("col1,col2\n1,2")

        with patch('ckan_zenodo.get_deposition_name', return_value='My Deposit') as mock_dep, \
             patch('ckan_zenodo.get_file_path', return_value=str(test_file)), \
             patch('os.path.exists', return_value=True), \
             patch('ckan_zenodo.insert_transfer_record', return_value=42) as mock_insert, \
             patch('ckan_zenodo.send_upload_task') as mock_send:

            export_to_zenodo('api-key', 'res-id', 'data.csv', 'http://url', '99')

            mock_dep.assert_called_once_with('api-key', '99')
            mock_insert.assert_called_once_with(
                'testuser', str(test_file), 'data.csv', '99', 'My Deposit',
                'res-id', 'testuser@test.com'
            )
            # transfer_id 42 must be passed to send_upload_task
            assert mock_send.call_args[0][6] == 42


# ---------------------------------------------------------------------------
# create_deposit_and_export
# ---------------------------------------------------------------------------

class TestCreateDepositAndExport:
    def _good_create_response(self, deposition_id=7777):
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {'id': deposition_id}
        return resp

    def test_raises_zenodo_error_on_non_201(self, mock_configs, mock_session):
        bad_resp = MagicMock()
        bad_resp.status_code = 400

        with patch('requests.post', return_value=bad_resp):
            with pytest.raises(ZenodoAPIError) as exc_info:
                create_deposit_and_export('key', 'res', 'f.csv', 'url', 'Title', 'Desc')

            assert exc_info.value.status_code == 400

    def test_deletes_orphan_when_file_missing(self, mock_configs, mock_session):
        with patch('requests.post', return_value=self._good_create_response(9999)), \
             patch('ckan_zenodo.get_file_path', return_value='/missing/file.csv'), \
             patch('os.path.exists', return_value=False), \
             patch('requests.delete') as mock_delete:

            with pytest.raises(ResourceFileNotFound):
                create_deposit_and_export('key', 'res', 'f.csv', 'url', 'Title', 'Desc')

            mock_delete.assert_called_once()
            assert '9999' in mock_delete.call_args[0][0]

    def test_raises_file_too_large_after_creating_deposit(self, mock_configs, mock_session, tmp_path):
        test_file = tmp_path / "big.csv"
        test_file.write_text("data")

        big_config = {**mock_configs['app'], 'max_file_size_mb': '1'}

        with patch('requests.post', return_value=self._good_create_response()), \
             patch('ckan_zenodo.get_file_path', return_value=str(test_file)), \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=2 * 1024 * 1024), \
             patch('configs.get_app_config', return_value=big_config):

            with pytest.raises(FileTooLarge):
                create_deposit_and_export('key', 'res', 'f.csv', 'url', 'Title', 'Desc')

    def test_success_queues_upload(self, mock_configs, mock_session, tmp_path):
        test_file = tmp_path / "data.csv"
        test_file.write_text("data")

        with patch('requests.post', return_value=self._good_create_response()), \
             patch('ckan_zenodo.get_file_path', return_value=str(test_file)), \
             patch('os.path.exists', return_value=True), \
             patch('ckan_zenodo.insert_transfer_record', return_value=1), \
             patch('ckan_zenodo.send_upload_task') as mock_send:

            create_deposit_and_export('key', 'res', 'f.csv', 'url', 'Title', 'Desc')

            mock_send.assert_called_once()

    def test_uses_configured_upload_type_and_access_right(self, mock_configs, mock_session, tmp_path):
        test_file = tmp_path / "data.csv"
        test_file.write_text("data")

        custom_zenodo = {**mock_configs['zenodo'], 'upload_type': 'software', 'access_right': 'open'}

        with patch('configs.get_zenodo_config', return_value=custom_zenodo), \
             patch('requests.post', return_value=self._good_create_response()) as mock_post, \
             patch('ckan_zenodo.get_file_path', return_value=str(test_file)), \
             patch('os.path.exists', return_value=True), \
             patch('ckan_zenodo.insert_transfer_record', return_value=1), \
             patch('ckan_zenodo.send_upload_task'):

            create_deposit_and_export('key', 'res', 'f.csv', 'url', 'Title', 'Desc')

            metadata = mock_post.call_args[1]['json']['metadata']
            assert metadata['upload_type'] == 'software'
            assert metadata['access_right'] == 'open'

    def test_upload_type_and_access_right_params_override_config(self, mock_configs, mock_session, tmp_path):
        test_file = tmp_path / "data.csv"
        test_file.write_text("data")

        with patch('requests.post', return_value=self._good_create_response()) as mock_post, \
             patch('ckan_zenodo.get_file_path', return_value=str(test_file)), \
             patch('os.path.exists', return_value=True), \
             patch('ckan_zenodo.insert_transfer_record', return_value=1), \
             patch('ckan_zenodo.send_upload_task'):

            create_deposit_and_export('key', 'res', 'f.csv', 'url', 'Title', 'Desc',
                                      upload_type='image', access_right='open')

            metadata = mock_post.call_args[1]['json']['metadata']
            assert metadata['upload_type'] == 'image'
            assert metadata['access_right'] == 'open'


# ---------------------------------------------------------------------------
# get_depositions
# ---------------------------------------------------------------------------

class TestGetDepositions:
    def test_returns_list_on_success(self, mock_configs):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = [{'id': 1, 'title': 'Test Deposit'}]

        with patch('requests.get', return_value=mock_resp):
            result = get_depositions('valid-api-key')

        assert result == [{'id': 1, 'title': 'Test Deposit'}]

    def test_raises_on_http_error(self, mock_configs):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req_lib.exceptions.HTTPError("403 Forbidden")

        with patch('requests.get', return_value=mock_resp):
            with pytest.raises(req_lib.exceptions.HTTPError):
                get_depositions('bad-key')


# ---------------------------------------------------------------------------
# insert_transfer_record
# ---------------------------------------------------------------------------

class TestInsertTransferRecord:
    def test_inserts_row_and_returns_id(self, mock_configs, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.lastrowid = 99

        result = insert_transfer_record('user', '/path/f.csv', 'f.csv', '123', 'Deposit')

        assert result == 99
        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_inserts_resource_id_and_email(self, mock_configs, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.lastrowid = 5

        insert_transfer_record('user', '/p/f.csv', 'f.csv', '123', 'Dep',
                               resource_id='res-abc', user_email='u@test.com')

        args = mock_cursor.execute.call_args[0]
        assert 'res-abc' in args[1]
        assert 'u@test.com' in args[1]

    def test_closes_connection_on_success(self, mock_configs, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.lastrowid = 1

        insert_transfer_record('user', '/path/f.csv', 'f.csv', '123', 'Deposit')

        mock_conn.close.assert_called_once()

    def test_closes_connection_on_db_error(self, mock_configs, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.execute.side_effect = Exception("DB error")

        with pytest.raises(Exception):
            insert_transfer_record('user', '/path/f.csv', 'f.csv', '123', 'Deposit')

        mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# get_transfer_by_id
# ---------------------------------------------------------------------------

class TestGetTransferById:
    def test_returns_transfer_for_owner(self, mock_configs, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.return_value = {'id': 7, 'username': 'alice', 'status': 'failed'}

        result = get_transfer_by_id(7, 'alice')

        assert result['id'] == 7
        args = mock_cursor.execute.call_args[0]
        assert 7 in args[1]
        assert 'alice' in args[1]

    def test_returns_none_when_not_found(self, mock_configs, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.return_value = None

        result = get_transfer_by_id(999, 'alice')

        assert result is None


# ---------------------------------------------------------------------------
# reset_transfer_for_retry
# ---------------------------------------------------------------------------

class TestResetTransferForRetry:
    def test_resets_status_and_retry_count(self, mock_configs, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection

        reset_transfer_for_retry(42)

        sql = mock_cursor.execute.call_args[0][0]
        assert 'pending' in sql
        assert 'retry_count' in sql
        assert mock_cursor.execute.call_args[0][1] == (42,)
        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# get_transfers_for_user
# ---------------------------------------------------------------------------

class TestGetTransfersForUser:
    def test_returns_rows_for_user(self, mock_configs, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = [
            {'id': 1, 'filename': 'f.csv', 'status': 'completed'},
        ]

        result = get_transfers_for_user('testuser')

        assert len(result) == 1
        assert result[0]['status'] == 'completed'
        mock_cursor.execute.assert_called_once()
        args = mock_cursor.execute.call_args[0]
        assert 'testuser' in args[1]

    def test_returns_empty_list_when_no_transfers(self, mock_configs, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = []

        result = get_transfers_for_user('newuser')

        assert result == []
