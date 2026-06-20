"""
Shared pytest fixtures and configuration.

Config getters are patched at session startup (pytest_configure) so that
module-level code in server.py and worker.py can import safely without a
real settings.ini on disk.
"""
import pytest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Canonical test config values — used both in patches and directly in tests
# ---------------------------------------------------------------------------

DB_CONFIG = {
    'host': 'localhost',
    'user': 'test_user',
    'password': 'test_pass',
    'database': 'test_db',
}

CKAN_CONFIG = {
    'server': 'http://ckan.test',
    'apikey': 'ckan-test-apikey',
    'resources_path': '/mnt/resources',
    'resources_usr_path': '/mnt/homes/{user}',
    'resources_usr_url': 'http://ckan.test/~',
}

ZENODO_CONFIG = {
    'api_url': 'https://zenodo.org/api/deposit/depositions',
    'use_sandbox': False,
    'upload_type': 'dataset',
    'access_right': 'restricted',
}

RABBITMQ_CONFIG = {
    'host': 'localhost',
    'queue': 'zenodo_upload',
    'max_retries': '3',
}

APP_CONFIG = {
    'secret_key': 'test-secret-key',
    'log_file': '/dev/null',
    'max_file_size_mb': '0',
    'notify_on_completion': False,
}

SSO_CONFIG = {
    'keycloak_server_url': 'http://keycloak.test',
    'realm_name': 'test',
    'client_id': 'test-client',
    'client_secret': 'test-client-secret',
    'redirect_uri': 'http://localhost:8090/callback',
}

SMTP_CONFIG = {
    'enabled': False,
    'host': 'localhost',
    'port': 587,
    'use_tls': True,
    'username': '',
    'password': '',
    'from_addr': 'noreply@test.com',
}

# ---------------------------------------------------------------------------
# Patch configs before any test module imports server.py / worker.py
# ---------------------------------------------------------------------------

_patches = [
    patch('configs.get_db_config', return_value=DB_CONFIG),
    patch('configs.get_ckan_config', return_value=CKAN_CONFIG),
    patch('configs.get_zenodo_config', return_value=ZENODO_CONFIG),
    patch('configs.get_rabbitmq_config', return_value=RABBITMQ_CONFIG),
    patch('configs.get_app_config', return_value=APP_CONFIG),
    patch('configs.get_sso_config', return_value=SSO_CONFIG),
    patch('configs.get_smtp_config', return_value=SMTP_CONFIG),
]


def pytest_configure(config):
    for p in _patches:
        p.start()


def pytest_unconfigure(config):
    for p in _patches:
        p.stop()


# ---------------------------------------------------------------------------
# Reusable fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_configs():
    """Yield per-test overrides on top of the session-level patches."""
    yield {
        'db': DB_CONFIG,
        'ckan': CKAN_CONFIG,
        'zenodo': ZENODO_CONFIG,
        'rabbitmq': RABBITMQ_CONFIG,
        'app': APP_CONFIG,
        'smtp': SMTP_CONFIG,
    }


@pytest.fixture
def mock_session():
    """Patch ckan_zenodo.session with a fake logged-in user."""
    fake_session = {
        'user': {
            'username': 'testuser',
            'email': 'testuser@test.com',
            'given_name': 'Test',
            'family_name': 'User',
        }
    }
    with patch('ckan_zenodo.session', fake_session):
        yield fake_session['user']


@pytest.fixture
def mock_db_connection():
    """Mock db.get_connection() and return the mock cursor for assertions."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.lastrowid = 1
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    with patch('db.get_connection', return_value=mock_conn):
        yield mock_conn, mock_cursor


@pytest.fixture
def flask_app():
    """Import and return the Flask app with CSRF and testing flags set."""
    import server  # noqa: import triggers module-level setup
    server.app.config['TESTING'] = True
    server.app.config['WTF_CSRF_ENABLED'] = False
    return server.app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()
