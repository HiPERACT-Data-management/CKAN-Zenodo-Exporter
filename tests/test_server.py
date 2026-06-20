"""Integration-style tests for server.py Flask routes."""
import json
import pytest
from unittest.mock import patch, MagicMock
import ckan_zenodo


# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------

class TestHome:
    def test_returns_200_unauthenticated(self, client):
        response = client.get('/')
        assert response.status_code == 200

    def test_returns_200_authenticated(self, client):
        with client.session_transaction() as sess:
            sess['user'] = {'username': 'alice', 'given_name': 'Alice', 'family_name': 'Smith'}
        response = client.get('/')
        assert response.status_code == 200
        assert b'alice' in response.data


# ---------------------------------------------------------------------------
# /export
# ---------------------------------------------------------------------------

class TestExport:
    def test_redirects_to_login_when_unauthenticated(self, client):
        response = client.get('/export?resource=abc')
        assert response.status_code == 302
        assert '/login' in response.headers['Location']

    def test_returns_400_for_invalid_resource_id(self, client):
        with client.session_transaction() as sess:
            sess['user'] = {'username': 'alice', 'given_name': 'Alice', 'family_name': 'Smith'}

        with patch('ckan_zenodo.get_ckan_resource') as mock_res, \
             patch('ckan_zenodo.get_ckan_package'):
            response = client.get('/export?resource=not-a-uuid')

        assert response.status_code == 400

    def test_renders_export_page_when_authenticated(self, client):
        with client.session_transaction() as sess:
            sess['user'] = {'username': 'alice', 'given_name': 'Alice', 'family_name': 'Smith'}

        mock_resource = {'id': '12345678-1234-1234-1234-123456789abc', 'name': 'dataset.csv', 'url': 'http://x', 'package_id': 'pkg1'}
        mock_package = {'title': 'My Dataset', 'notes': 'Desc', 'resources': []}

        with patch('ckan_zenodo.get_ckan_resource', return_value=mock_resource), \
             patch('ckan_zenodo.get_ckan_package', return_value=mock_package):

            response = client.get('/export?resource=12345678-1234-1234-1234-123456789abc')

        assert response.status_code == 200
        assert b'dataset.csv' in response.data


# ---------------------------------------------------------------------------
# /ajax  — CSRF is disabled for tests (WTF_CSRF_ENABLED=False)
# ---------------------------------------------------------------------------

class TestAjax:
    def test_list_depositions_rejects_empty_api_key(self, client):
        response = client.post('/ajax', data={'action': 'list_depositions', 'zenodo_apikey': ''})
        assert response.status_code == 200
        assert b'valid Zenodo API key' in response.data

    def test_list_depositions_rejects_key_with_whitespace(self, client):
        response = client.post('/ajax', data={'action': 'list_depositions', 'zenodo_apikey': 'key with space'})
        assert response.status_code == 200
        assert b'valid Zenodo API key' in response.data

    def test_list_depositions_stores_key_in_session(self, client):
        mock_deps = [{'id': 1, 'title': 'Test'}]
        with patch('ckan_zenodo.get_depositions', return_value=mock_deps):
            client.post('/ajax', data={'action': 'list_depositions', 'zenodo_apikey': 'validkey123'})

        with client.session_transaction() as sess:
            assert sess.get('zenodo_apikey') == 'validkey123'

    def test_export_to_zenodo_returns_session_expired_without_key(self, client):
        response = client.post('/ajax', data={
            'action': 'export_to_zenodo',
            'ckan_resource_id': '12345678-1234-1234-1234-123456789abc',
            'deposition_id': '99',
        })
        assert response.status_code == 200
        assert b'Session expired' in response.data

    def test_export_to_zenodo_rejects_invalid_uuid(self, client):
        with client.session_transaction() as sess:
            sess['zenodo_apikey'] = 'validkey'

        response = client.post('/ajax', data={
            'action': 'export_to_zenodo',
            'ckan_resource_id': 'not-a-uuid',
            'deposition_id': '99',
        })
        assert response.status_code == 200
        assert b'Invalid resource ID' in response.data

    def test_export_to_zenodo_rejects_non_numeric_deposition_id(self, client):
        with client.session_transaction() as sess:
            sess['zenodo_apikey'] = 'validkey'

        response = client.post('/ajax', data={
            'action': 'export_to_zenodo',
            'ckan_resource_id': '12345678-1234-1234-1234-123456789abc',
            'deposition_id': 'abc',
        })
        assert response.status_code == 200
        assert b'Invalid deposition ID' in response.data

    def test_create_deposit_rejects_empty_title(self, client):
        with client.session_transaction() as sess:
            sess['zenodo_apikey'] = 'validkey'

        response = client.post('/ajax', data={
            'action': 'create_deposit_and_export',
            'ckan_resource_id': '12345678-1234-1234-1234-123456789abc',
            'deposit_name': '',
            'deposit_desc': 'Some description',
        })
        assert response.status_code == 200
        assert b'required' in response.data

    def test_create_deposit_rejects_session_expired(self, client):
        response = client.post('/ajax', data={
            'action': 'create_deposit_and_export',
            'ckan_resource_id': '12345678-1234-1234-1234-123456789abc',
            'deposit_name': 'Title',
            'deposit_desc': 'Desc',
        })
        assert response.status_code == 200
        assert b'Session expired' in response.data

    def test_create_deposit_rejects_invalid_upload_type(self, client):
        with client.session_transaction() as sess:
            sess['zenodo_apikey'] = 'validkey'

        response = client.post('/ajax', data={
            'action': 'create_deposit_and_export',
            'ckan_resource_id': '12345678-1234-1234-1234-123456789abc',
            'deposit_name': 'Title',
            'deposit_desc': 'Desc',
            'upload_type': 'bogus_type',
        })
        assert response.status_code == 200
        assert b'Invalid upload type' in response.data

    def test_unknown_action_returns_unknown_action_message(self, client):
        response = client.post('/ajax', data={'action': 'invalid_action'})
        assert response.status_code == 200
        assert b'Unknown action' in response.data

    def test_export_handles_resource_file_not_found(self, client):
        with client.session_transaction() as sess:
            sess['zenodo_apikey'] = 'validkey'
            sess['user'] = {'username': 'alice', 'given_name': 'Alice', 'family_name': 'Smith'}

        mock_resource = {'id': '12345678-1234-1234-1234-123456789abc', 'name': 'f.csv', 'url': 'http://x'}

        with patch('ckan_zenodo.get_ckan_resource', return_value=mock_resource), \
             patch('ckan_zenodo.export_to_zenodo', side_effect=ckan_zenodo.ResourceFileNotFound("not found")):
            response = client.post('/ajax', data={
                'action': 'export_to_zenodo',
                'ckan_resource_id': '12345678-1234-1234-1234-123456789abc',
                'deposition_id': '99',
            })

        assert response.status_code == 200
        assert b'not found on the server' in response.data

    def test_export_handles_file_too_large(self, client):
        with client.session_transaction() as sess:
            sess['zenodo_apikey'] = 'validkey'
            sess['user'] = {'username': 'alice', 'given_name': 'Alice', 'family_name': 'Smith'}

        mock_resource = {'id': '12345678-1234-1234-1234-123456789abc', 'name': 'f.csv', 'url': 'http://x'}

        with patch('ckan_zenodo.get_ckan_resource', return_value=mock_resource), \
             patch('ckan_zenodo.export_to_zenodo', side_effect=ckan_zenodo.FileTooLarge("File 5.0 MB exceeds the 2 MB limit.")):

            response = client.post('/ajax', data={
                'action': 'export_to_zenodo',
                'ckan_resource_id': '12345678-1234-1234-1234-123456789abc',
                'deposition_id': '99',
            })

        assert response.status_code == 200
        assert b'MB' in response.data

    def test_export_handles_duplicate_transfer(self, client):
        with client.session_transaction() as sess:
            sess['zenodo_apikey'] = 'validkey'
            sess['user'] = {'username': 'alice', 'given_name': 'Alice', 'family_name': 'Smith'}

        mock_resource = {'id': '12345678-1234-1234-1234-123456789abc', 'name': 'f.csv', 'url': 'http://x'}

        with patch('ckan_zenodo.get_ckan_resource', return_value=mock_resource), \
             patch('ckan_zenodo.export_to_zenodo', side_effect=ckan_zenodo.DuplicateTransfer("already exported")):

            response = client.post('/ajax', data={
                'action': 'export_to_zenodo',
                'ckan_resource_id': '12345678-1234-1234-1234-123456789abc',
                'deposition_id': '99',
            })

        assert response.status_code == 200
        assert b'already been exported' in response.data

    def test_export_package_rejects_invalid_package_id(self, client):
        with client.session_transaction() as sess:
            sess['zenodo_apikey'] = 'validkey'

        response = client.post('/ajax', data={
            'action': 'export_package_to_zenodo',
            'package_id': '../../etc/passwd',
            'deposition_id': '99',
        })
        assert response.status_code == 200
        assert b'Invalid package ID' in response.data

    def test_export_package_queues_all_resources(self, client):
        with client.session_transaction() as sess:
            sess['zenodo_apikey'] = 'validkey'
            sess['user'] = {'username': 'alice', 'given_name': 'Alice', 'family_name': 'Smith'}

        mock_package = {
            'resources': [
                {'id': '12345678-1234-1234-1234-123456789ab1', 'name': 'f1.csv', 'url': 'http://x/f1'},
                {'id': '12345678-1234-1234-1234-123456789ab2', 'name': 'f2.csv', 'url': 'http://x/f2'},
            ]
        }

        with patch('ckan_zenodo.get_ckan_package', return_value=mock_package), \
             patch('ckan_zenodo.export_to_zenodo') as mock_export:

            response = client.post('/ajax', data={
                'action': 'export_package_to_zenodo',
                'package_id': 'my-dataset',
                'deposition_id': '99',
            })

        assert response.status_code == 200
        assert mock_export.call_count == 2
        assert b'2 file(s) queued' in response.data

    def test_export_package_counts_duplicates_as_skipped(self, client):
        with client.session_transaction() as sess:
            sess['zenodo_apikey'] = 'validkey'
            sess['user'] = {'username': 'alice', 'given_name': 'Alice', 'family_name': 'Smith'}

        mock_package = {
            'resources': [
                {'id': '12345678-1234-1234-1234-123456789ab1', 'name': 'f1.csv', 'url': 'http://x/f1'},
            ]
        }

        with patch('ckan_zenodo.get_ckan_package', return_value=mock_package), \
             patch('ckan_zenodo.export_to_zenodo', side_effect=ckan_zenodo.DuplicateTransfer("dup")):

            response = client.post('/ajax', data={
                'action': 'export_package_to_zenodo',
                'package_id': 'my-dataset',
                'deposition_id': '99',
            })

        assert response.status_code == 200
        assert b'skipped' in response.data

    def test_retry_transfer_requires_session_key(self, client):
        with client.session_transaction() as sess:
            sess['user'] = {'username': 'alice', 'given_name': 'Alice', 'family_name': 'Smith'}

        response = client.post('/ajax', data={'action': 'retry_transfer', 'transfer_id': '5'})
        assert response.status_code == 200
        assert b'Session expired' in response.data

    def test_retry_transfer_rejects_non_failed_status(self, client):
        with client.session_transaction() as sess:
            sess['zenodo_apikey'] = 'validkey'
            sess['user'] = {'username': 'alice', 'given_name': 'Alice', 'family_name': 'Smith'}

        mock_transfer = {'id': 5, 'status': 'completed', 'username': 'alice',
                         'file_path': '/f.csv', 'filename': 'f.csv',
                         'deposition_id': '99', 'deposition_name': 'Dep'}

        with patch('ckan_zenodo.get_transfer_by_id', return_value=mock_transfer):
            response = client.post('/ajax', data={'action': 'retry_transfer', 'transfer_id': '5'})

        assert response.status_code == 200
        assert b'Only failed' in response.data

    def test_retry_transfer_requeues_failed_transfer(self, client):
        with client.session_transaction() as sess:
            sess['zenodo_apikey'] = 'validkey'
            sess['user'] = {'username': 'alice', 'email': 'alice@test.com',
                            'given_name': 'Alice', 'family_name': 'Smith'}

        mock_transfer = {'id': 5, 'status': 'failed', 'username': 'alice',
                         'file_path': '/f.csv', 'filename': 'f.csv',
                         'deposition_id': '99', 'deposition_name': 'Dep'}

        with patch('ckan_zenodo.get_transfer_by_id', return_value=mock_transfer), \
             patch('ckan_zenodo.reset_transfer_for_retry') as mock_reset, \
             patch('ckan_zenodo.send_upload_task') as mock_send:

            response = client.post('/ajax', data={'action': 'retry_transfer', 'transfer_id': '5'})

        assert response.status_code == 200
        assert b're-queued' in response.data
        mock_reset.assert_called_once_with(5)
        mock_send.assert_called_once()


# ---------------------------------------------------------------------------
# /transfers
# ---------------------------------------------------------------------------

class TestTransfers:
    def test_redirects_unauthenticated_to_login(self, client):
        response = client.get('/transfers')
        assert response.status_code == 302
        assert '/login' in response.headers['Location']

    def test_renders_transfers_when_authenticated(self, client):
        with client.session_transaction() as sess:
            sess['user'] = {'username': 'alice', 'given_name': 'Alice', 'family_name': 'Smith'}

        with patch('ckan_zenodo.get_transfers_for_user', return_value=[]):
            response = client.get('/transfers')

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# /api/transfer/<id>
# ---------------------------------------------------------------------------

class TestApiTransferStatus:
    def test_returns_401_when_unauthenticated(self, client):
        response = client.get('/api/transfer/1')
        assert response.status_code == 401

    def test_returns_404_when_transfer_not_found(self, client):
        with client.session_transaction() as sess:
            sess['user'] = {'username': 'alice', 'given_name': 'Alice', 'family_name': 'Smith'}

        with patch('ckan_zenodo.get_transfer_by_id', return_value=None):
            response = client.get('/api/transfer/999')

        assert response.status_code == 404

    def test_returns_status_json(self, client):
        with client.session_transaction() as sess:
            sess['user'] = {'username': 'alice', 'given_name': 'Alice', 'family_name': 'Smith'}

        mock_transfer = {'id': 7, 'status': 'completed', 'retry_count': 1, 'updated_at': '2026-01-01 12:00:00'}

        with patch('ckan_zenodo.get_transfer_by_id', return_value=mock_transfer):
            response = client.get('/api/transfer/7')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'completed'
        assert data['retry_count'] == 1


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_returns_200_when_all_ok(self, client):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch('db.get_connection', return_value=mock_conn), \
             patch('pika.BlockingConnection'):
            response = client.get('/health')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'healthy'
        assert data['db'] == 'ok'
        assert data['rabbitmq'] == 'ok'

    def test_returns_503_when_db_down(self, client):
        with patch('db.get_connection', side_effect=Exception("DB connection failed")), \
             patch('pika.BlockingConnection'):
            response = client.get('/health')

        assert response.status_code == 503
        data = json.loads(response.data)
        assert data['status'] == 'degraded'
        assert 'error' in data['db']

    def test_returns_503_when_rabbitmq_down(self, client):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch('db.get_connection', return_value=mock_conn), \
             patch('pika.BlockingConnection', side_effect=Exception("Connection refused")):
            response = client.get('/health')

        assert response.status_code == 503
        data = json.loads(response.data)
        assert data['status'] == 'degraded'
        assert 'error' in data['rabbitmq']
