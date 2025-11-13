# Piotr Dzierżak 2024

from waitress import serve
from flask import Flask, render_template, request, redirect, url_for, session, render_template_string
import datetime
import logging
import requests
import ckan_zenodo
import configs

app = Flask(__name__)
app_conf = configs.get_app_config()

logging.basicConfig(filename=app_conf.get('log_file'), format='%(asctime)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

app.secret_key = app_conf.get('secret_key')

sso_conf = configs.get_sso_config()
keycloak_server_url = sso_conf.get('keycloak_server_url')
realm_name = sso_conf.get('realm_name')
client_id = sso_conf.get('client_id')
client_secret = sso_conf.get('client_secret')
redirect_uri = sso_conf.get('redirect_uri')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Initiates the login process using Keycloak's OpenID Connect authorization flow.
    Redirects the user to the Keycloak authorization endpoint where they can authenticate.
    """
    authorize_endpoint = f"{keycloak_server_url}/realms/{realm_name}/protocol/openid-connect/auth"

    params = {
        'client_id': client_id,
        'response_type': 'code',
        'redirect_uri': redirect_uri,
        'scope': 'openid profile email'
    }
    return redirect(f"{authorize_endpoint}?{'&'.join([f'{key}={value}' for key, value in params.items()])}")


@app.route('/callback')
def callback():
    """
    Handles the OAuth2 callback from Keycloak after a successful login.
    Exchanges the authorization code for access, refresh, and ID tokens.
    Retrieves user profile information and stores it in the session.
    Redirects the user either to the export page (if a resource was requested before login)
    or to the home page.
    """
    code = request.args.get('code')

    logging.debug(f"Callback received with code: {code}")

    token_endpoint = f"{keycloak_server_url}/realms/{realm_name}/protocol/openid-connect/token"
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
        'client_id': client_id,
        'client_secret': client_secret
    }

    try:
        response = requests.post(token_endpoint, data=payload)
        token_data = response.json()

        if 'access_token' in token_data:
            userinfo_endpoint = f"{keycloak_server_url}/realms/{realm_name}/protocol/openid-connect/userinfo"
            userinfo_response = requests.get(userinfo_endpoint,
                                             headers={'Authorization': f"Bearer {token_data['access_token']}"})
            userinfo = userinfo_response.json()

            session['user'] = {
                'id_token': token_data.get('id_token'),
                'access_token': token_data.get('access_token'),
                'refresh_token': token_data.get('refresh_token'),
                'username': userinfo.get('preferred_username'),
                'email': userinfo.get('email'),
                'given_name': userinfo.get('given_name'),
                'family_name': userinfo.get('family_name')
            }

            logging.debug("User logged in successfully.")
            if 'resource' in session:
                return redirect("/export?resource={}".format(session['resource']))
            else:
                return redirect(url_for('home'))
        else:
            logging.error("Failed to fetch tokens.")
            return "Failed to fetch tokens."

    except Exception as e:
        logging.error(f"Exception during token exchange: {e}")
        return "Failed to fetch tokens."


@app.route('/logout')
def logout():
    """
    Logs the user out of both the application and Keycloak.
    Calls the Keycloak end-session endpoint to terminate the identity provider session.
    Clears the Flask session and returns a confirmation message.
    """
    logging.debug('Attempting to logout...')
    try:

        session.clear()  # Clear session data upon successful logout
        logging.debug('Session cleared. Redirecting to login...')

        return render_template_string("Successfully logged out.", **session)

    except requests.exceptions.RequestException as e:
        logging.error(f"Exception during logout: {e}")
        return "Failed to logout. Please try again."


@app.route('/')
def home():
    """
    Renders the home page.
    If the user is logged in, displays their username and the current datetime.
    If not, renders the home page without user information.
    """
    if 'user' in session:
        return render_template('home.html', username=session['user']['username'], curdt=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    else:
        return render_template('home.html', curdt=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        #return redirect(url_for('login'))


@app.route('/export', methods=['GET'])
def export():
    """
    Displays the export page for a CKAN resource.
    If the user is authenticated, retrieves the CKAN resource and its package metadata
    and renders them in the export template.
    If not authenticated, stores the resource ID in the session and redirects to login.
    """
    if 'user' in session:
        resource_id = request.args.get('resource')
        resource = ckan_zenodo.get_ckan_resource(resource_id)
        package = ckan_zenodo.get_ckan_package(resource['package_id'])
        return render_template('export.html', username=session['user']['username'], res=resource, pac=package, curdt=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    else:
        session["resource"] = request.args.get('resource')
        return redirect(url_for('login'))


@app.route('/ajax', methods=['POST'])
def ajax():
    """
    Handles AJAX requests for different Zenodo-related actions:
      - export_to_zenodo: Exports a CKAN resource to an existing Zenodo deposition.
      - create_deposit_and_export: Creates a new Zenodo deposition and exports the CKAN resource into it.
      - list_depositions: Lists existing Zenodo depositions for the provided API key.
    Returns the appropriate HTML template with success or error messages.
    """
    #print(request.form)
    action = request.form['action']
    message = ""

    if action == "export_to_zenodo":
        zenodo_apikey = request.form['zenodo_apikey']
        deposition_id = request.form['deposition_id']
        ckan_resource_id = request.form['ckan_resource_id']
        res = ckan_zenodo.get_ckan_resource(ckan_resource_id)

        if ckan_zenodo.export_to_zenodo(zenodo_apikey, ckan_resource_id, res['name'], res['url'], deposition_id) == 201:
            message = "The resource has been exported to Zenodo <button onclick=\"history.back()\">Go Back</button>"
        else:
            message = "The resource has not been exported to Zenodo"

        return render_template('result.html', message=message)
    elif action == "create_deposit_and_export":
        zenodo_apikey = request.form['zenodo_apikey']
        ckan_resource_id = request.form['ckan_resource_id']
        deposit_name = request.form['deposit_name']
        deposit_desc = request.form['deposit_desc']
        res = ckan_zenodo.get_ckan_resource(ckan_resource_id)

        if ckan_zenodo.create_deposit_and_export(zenodo_apikey, ckan_resource_id, res['name'], res['url'], deposit_name, deposit_desc) == 201:
            message = "The resource has been exported to Zenodo <button onclick=\"history.back()\">Go Back</button>"
        else:
            message = "The resource has not been exported to Zenodo"

        return render_template('result.html', message=message)
    elif action == "list_depositions":
        try:
            zenodo_apikey = request.form['zenodo_apikey']
            dep = ckan_zenodo.get_depositions(zenodo_apikey)
            return render_template('zenodo_deposit.html', dep=dep, message=message)
        except requests.exceptions.RequestException as e:
            message = f"Failed to fetch depositions: {e}"
            return render_template("result.html", message=message)

    return render_template('result.html', message=message)


@app.route('/transfers')
def transfers():
    """
    Displays the transfer history for the logged-in user.
    Retrieves transfer records from CKAN-Zenodo integration based on the username.
    If the user is not authenticated, redirects to the login page.
    """
    if 'user' in session:
        username = session['user']['username']
        transfers = ckan_zenodo.get_transfers_for_user(username)
        return render_template("transfers.html", username=session['user']['username'], transfers=transfers)
    else:
        return redirect(url_for('login'))


serve(app, host='0.0.0.0', port=8090)
