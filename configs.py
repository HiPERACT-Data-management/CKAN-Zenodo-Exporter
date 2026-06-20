import configparser

_config = configparser.ConfigParser()
_config.read('settings.ini')


def get_db_config():
    return {
        'host': _config['mysql']['host'],
        'user': _config['mysql']['user'],
        'password': _config['mysql']['password'],
        'database': _config['mysql']['database']
    }


def get_ckan_config():
    return {
        'server': _config['ckan']['server'],
        'apikey': _config['ckan']['apikey'],
        'resources_path': _config['ckan']['resources_path'],
        'resources_usr_path': _config['ckan']['resources_usr_path'],
        'resources_usr_url': _config['ckan']['resources_usr_url']
    }


def get_sso_config():
    return {
        'keycloak_server_url': _config['sso']['keycloak_server_url'],
        'realm_name': _config['sso']['realm_name'],
        'client_id': _config['sso']['client_id'],
        'client_secret': _config['sso']['client_secret'],
        'redirect_uri': _config['sso']['redirect_uri']
    }


def get_rabbitmq_config():
    return {
        'host': _config['rabbitmq']['host'],
        'queue': _config['rabbitmq']['queue'],
        'max_retries': _config.get('rabbitmq', 'max_retries', fallback='3'),
    }


def get_zenodo_config():
    use_sandbox = _config.getboolean('zenodo', 'use_sandbox', fallback=False)
    api_url = _config['zenodo']['api_url']
    if use_sandbox:
        api_url = api_url.replace('zenodo.org', 'sandbox.zenodo.org')
    return {
        'api_url': api_url,
        'use_sandbox': use_sandbox,
        'upload_type': _config.get('zenodo', 'upload_type', fallback='dataset'),
        'access_right': _config.get('zenodo', 'access_right', fallback='restricted'),
    }


def get_app_config():
    return {
        'secret_key': _config['app']['secret_key'],
        'log_file': _config['app']['log_file'],
        'max_file_size_mb': _config.get('app', 'max_file_size_mb', fallback='0'),
        'notify_on_completion': _config.getboolean('app', 'notify_on_completion', fallback=False),
    }


def get_smtp_config():
    return {
        'enabled': _config.getboolean('smtp', 'enabled', fallback=False),
        'host': _config.get('smtp', 'host', fallback='localhost'),
        'port': _config.getint('smtp', 'port', fallback=587),
        'use_tls': _config.getboolean('smtp', 'use_tls', fallback=True),
        'username': _config.get('smtp', 'username', fallback=''),
        'password': _config.get('smtp', 'password', fallback=''),
        'from_addr': _config.get('smtp', 'from_addr', fallback='noreply@example.com'),
    }
