import configparser

# --- Reads database connection configuration from settings.ini ---
def get_db_config():
    """
    Load MySQL database configuration from settings.ini.
    """
    config = configparser.ConfigParser()
    config.read('settings.ini')
    return {
        'host': config['mysql']['host'],
        'user': config['mysql']['user'],
        'password': config['mysql']['password'],
        'database': config['mysql']['database']
    }


# --- Reads CKAN connection configuration from settings.ini ---
def get_ckan_config():
    """
    Load CKAN server URL and API key from settings.ini.
    """
    config = configparser.ConfigParser()
    config.read('settings.ini')
    return {
        'server': config['ckan']['server'],
        'apikey': config['ckan']['apikey'],
        'resources_path': config['ckan']['resources_path'],
        'resources_usr_path': config['ckan']['resources_usr_path'],
        'resources_usr_url': config['ckan']['resources_usr_url']
    }


# --- Reads SSO (Keycloak) configuration from settings.ini ---
def get_sso_config():
    """
    Load Keycloak SSO configuration from settings.ini.
    """
    config = configparser.ConfigParser()
    config.read('settings.ini')
    return {
        'keycloak_server_url': config['sso']['keycloak_server_url'],
        'realm_name': config['sso']['realm_name'],
        'client_id': config['sso']['client_id'],
        'client_secret': config['sso']['client_secret'],
        'redirect_uri': config['sso']['redirect_uri']
    }

def get_rabbitmq_config():
    """
    Load RabbitMQ configuration from settings.ini.
    """
    config = configparser.ConfigParser()
    config.read('settings.ini')
    return {
        'host': config['rabbitmq']['host'],
        'queue': config['rabbitmq']['queue'],
    }

def get_zenodo_config():
    """
    Load ZENODO configuration from settings.ini.
    """
    config = configparser.ConfigParser()
    config.read('settings.ini')
    return {
        'api_url': config['zenodo']['api_url']
    }

def get_app_config():
    """
    Load APPLICATION configuration from settings.ini.
    """
    config = configparser.ConfigParser()
    config.read('settings.ini')
    return {
        'secret_key': config['app']['secret_key'],
        'log_file': config['app']['log_file']
    }
