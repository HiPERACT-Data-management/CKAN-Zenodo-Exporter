# Piotr Dzierżak 2024

import re
import uuid as uuid_mod
from waitress import serve
from flask import Flask, render_template, request, redirect, url_for, session, render_template_string, jsonify
from flask_wtf.csrf import CSRFProtect, CSRFError
import datetime
import logging
import requests
import pika
import ckan_zenodo
import configs
import db

app = Flask(__name__)
app_conf = configs.get_app_config()

logging.basicConfig(filename=app_conf.get('log_file'), format='%(asctime)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

app.secret_key = app_conf.get('secret_key')
csrf = CSRFProtect(app)

sso_conf = configs.get_sso_config()
keycloak_server_url = sso_conf.get('keycloak_server_url')
realm_name = sso_conf.get('realm_name')
client_id = sso_conf.get('client_id')
client_secret = sso_conf.get('client_secret')
redirect_uri = sso_conf.get('redirect_uri')

_VALID_UPLOAD_TYPES = {
    'publication', 'poster', 'presentation', 'dataset', 'image',
    'video', 'software', 'lesson', 'physicalobject', 'other',
}
_VALID_ACCESS_RIGHTS = {'open', 'embargoed', 'restricted', 'closed'}


def _valid_api_key(value):
    """Zenodo API keys: non-empty printable ASCII, no whitespace, max 200 chars."""
    return bool(value) and len(value) <= 200 and bool(re.match(r'^[^\s]+$', value))


def _valid_uuid(value):
    """CKAN resource IDs are UUIDs."""
    try:
        uuid_mod.UUID(str(value))
        return True
    except (ValueError, AttributeError):
        return False


def _valid_deposition_id(value):
    """Zenodo deposition IDs are positive integers."""
    return bool(value) and str(value).isdigit()


def _valid_package_id(value):
    """CKAN package IDs are UUIDs or URL-safe slugs."""
    return bool(value) and 1 <= len(value) <= 100 and bool(re.match(r'^[a-zA-Z0-9_-]+$', value))


@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    logging.warning(f"CSRF validation failed: {e.description}")
    return render_template('error.html', message="Request validation failed. Please reload the page and try again."), 400


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

            logging.info(f"User logged in: {userinfo.get('preferred_username')}")
            if 'resource' in session:
                return redirect("/export?resource={}".format(session['resource']))
            else:
                return redirect(url_for('home'))
        else:
            logging.error("Failed to fetch tokens from Keycloak.")
            return render_template('error.html', message="Login failed. Please try again.")

    except Exception as e:
        logging.error(f"Exception during token exchange: {e}")
        return render_template('error.html', message="Login failed. Please try again.")


@app.route('/logout')
def logout():
    """
    Logs the user out of the application.
    Clears the Flask session and returns a confirmation message.
    """
    username = session.get('user', {}).get('username', 'unknown')
    session.clear()
    logging.info(f"User logged out: {username}")
    return render_template_string("Successfully logged out. <a href='/login'>Log in again</a>")


@app.route('/')
def home():
    """
    Renders the home page.
    If the user is logged in, displays their username and the current datetime.
    """
    if 'user' in session:
        return render_template('home.html', username=session['user']['username'], curdt=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    else:
        return render_template('home.html', curdt=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


@app.route('/export', methods=['GET'])
def export():
    """
    Displays the export page for a CKAN resource.
    If the user is authenticated, retrieves the CKAN resource and its package metadata
    and renders them in the export template.
    If not authenticated, stores the resource ID in the session and redirects to login.
    """
    if 'user' in session:
        resource_id = request.args.get('resource', '')
        if not _valid_uuid(resource_id):
            return render_template('error.html', message="Invalid resource ID."), 400
        resource = ckan_zenodo.get_ckan_resource(resource_id)
        package = ckan_zenodo.get_ckan_package(resource['package_id'])
        return render_template('export.html', username=session['user']['username'],
                               res=resource, pac=package,
                               curdt=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    else:
        session["resource"] = request.args.get('resource')
        return redirect(url_for('login'))


@app.route('/ajax', methods=['POST'])
def ajax():
    """
    Handles AJAX requests for Zenodo-related actions:
      - list_depositions: List the user's Zenodo depositions (stores API key in session).
      - export_to_zenodo: Export a CKAN resource to an existing Zenodo deposition.
      - create_deposit_and_export: Create a new Zenodo deposition and export the resource into it.
      - export_package_to_zenodo: Export all resources of a CKAN package to an existing deposition.
      - retry_transfer: Re-queue a previously failed transfer.
    """
    action = request.form.get('action', '')

    # ── list_depositions ──────────────────────────────────────────────────────
    if action == "list_depositions":
        zenodo_apikey = request.form.get('zenodo_apikey', '').strip()

        if not _valid_api_key(zenodo_apikey):
            return render_template('result.html', message="Please enter a valid Zenodo API key.", back_button=False)

        # Store key server-side — subsequent export calls read from session
        session['zenodo_apikey'] = zenodo_apikey

        try:
            dep = ckan_zenodo.get_depositions(zenodo_apikey)
            zc = configs.get_zenodo_config()
            return render_template('zenodo_deposit.html', dep=dep, message="",
                                   default_upload_type=zc['upload_type'],
                                   default_access_right=zc['access_right'])
        except requests.exceptions.HTTPError as e:
            logging.error(f"Zenodo API error fetching depositions: {e}")
            return render_template('result.html',
                                   message="Failed to fetch depositions. Check your API key and try again.",
                                   back_button=True)
        except requests.exceptions.RequestException as e:
            logging.error(f"Network error fetching depositions: {e}")
            return render_template('result.html',
                                   message="Could not connect to Zenodo. Please try again later.",
                                   back_button=True)

    # ── export_to_zenodo ──────────────────────────────────────────────────────
    elif action == "export_to_zenodo":
        zenodo_apikey = session.get('zenodo_apikey')
        if not zenodo_apikey:
            return render_template('result.html',
                                   message="Session expired. Please re-enter your Zenodo API key and select a deposition again.",
                                   back_button=True)

        ckan_resource_id = request.form.get('ckan_resource_id', '').strip()
        deposition_id = request.form.get('deposition_id', '').strip()

        if not _valid_uuid(ckan_resource_id):
            return render_template('result.html', message="Invalid resource ID.", back_button=False)
        if not _valid_deposition_id(deposition_id):
            return render_template('result.html', message="Invalid deposition ID.", back_button=False)

        try:
            res = ckan_zenodo.get_ckan_resource(ckan_resource_id)
            ckan_zenodo.export_to_zenodo(zenodo_apikey, ckan_resource_id, res['name'], res['url'], deposition_id)
            return render_template('result.html',
                                   message="Export queued successfully. Track progress on the Transfers page.",
                                   back_button=True)
        except ckan_zenodo.DuplicateTransfer:
            return render_template('result.html',
                                   message="This resource has already been exported to this deposition and is not in a failed state. Check the Transfers page for its current status.",
                                   back_button=True)
        except ckan_zenodo.ResourceFileNotFound:
            logging.warning(f"File not found for resource {ckan_resource_id}")
            return render_template('result.html',
                                   message="The resource file was not found on the server. Contact the administrator.",
                                   back_button=True)
        except ckan_zenodo.FileTooLarge as e:
            return render_template('result.html', message=str(e), back_button=True)
        except ckan_zenodo.ZenodoAPIError as e:
            logging.error(f"Zenodo API error during export: {e}")
            return render_template('result.html',
                                   message="A Zenodo API error occurred. Check your API key and try again.",
                                   back_button=True)
        except requests.exceptions.RequestException as e:
            logging.error(f"Network error during export: {e}")
            return render_template('result.html',
                                   message="Network error communicating with Zenodo. Please try again.",
                                   back_button=True)
        except Exception as e:
            logging.error(f"Unexpected error during export_to_zenodo: {e}")
            return render_template('result.html',
                                   message="An unexpected error occurred. Please try again.",
                                   back_button=True)

    # ── create_deposit_and_export ─────────────────────────────────────────────
    elif action == "create_deposit_and_export":
        zenodo_apikey = session.get('zenodo_apikey')
        if not zenodo_apikey:
            return render_template('result.html',
                                   message="Session expired. Please re-enter your Zenodo API key and try again.",
                                   back_button=True)

        ckan_resource_id = request.form.get('ckan_resource_id', '').strip()
        deposit_name = request.form.get('deposit_name', '').strip()
        deposit_desc = request.form.get('deposit_desc', '').strip()
        upload_type = request.form.get('upload_type', '').strip()
        access_right = request.form.get('access_right', '').strip()

        if not _valid_uuid(ckan_resource_id):
            return render_template('result.html', message="Invalid resource ID.", back_button=False)
        if not deposit_name or len(deposit_name) > 1000:
            return render_template('result.html',
                                   message="Deposition title is required (max 1000 characters).",
                                   back_button=True)
        if len(deposit_desc) > 10000:
            return render_template('result.html',
                                   message="Deposition description is too long (max 10 000 characters).",
                                   back_button=True)
        if upload_type and upload_type not in _VALID_UPLOAD_TYPES:
            return render_template('result.html', message="Invalid upload type.", back_button=True)
        if access_right and access_right not in _VALID_ACCESS_RIGHTS:
            return render_template('result.html', message="Invalid access right.", back_button=True)

        try:
            res = ckan_zenodo.get_ckan_resource(ckan_resource_id)
            ckan_zenodo.create_deposit_and_export(
                zenodo_apikey, ckan_resource_id, res['name'], res['url'],
                deposit_name, deposit_desc,
                upload_type=upload_type or None,
                access_right=access_right or None,
            )
            return render_template('result.html',
                                   message="Export queued successfully. Track progress on the Transfers page.",
                                   back_button=True)
        except ckan_zenodo.ResourceFileNotFound:
            logging.warning(f"File not found for resource {ckan_resource_id}")
            return render_template('result.html',
                                   message="The resource file was not found on the server. The Zenodo deposition has been removed.",
                                   back_button=True)
        except ckan_zenodo.FileTooLarge as e:
            return render_template('result.html', message=str(e), back_button=True)
        except ckan_zenodo.ZenodoAPIError as e:
            logging.error(f"Zenodo API error creating deposition: {e}")
            return render_template('result.html',
                                   message="Failed to create Zenodo deposition. Check your API key and try again.",
                                   back_button=True)
        except requests.exceptions.RequestException as e:
            logging.error(f"Network error during create_deposit_and_export: {e}")
            return render_template('result.html',
                                   message="Network error communicating with Zenodo. Please try again.",
                                   back_button=True)
        except Exception as e:
            logging.error(f"Unexpected error during create_deposit_and_export: {e}")
            return render_template('result.html',
                                   message="An unexpected error occurred. Please try again.",
                                   back_button=True)

    # ── export_package_to_zenodo ──────────────────────────────────────────────
    elif action == "export_package_to_zenodo":
        zenodo_apikey = session.get('zenodo_apikey')
        if not zenodo_apikey:
            return render_template('result.html',
                                   message="Session expired. Please re-enter your Zenodo API key and select a deposition again.",
                                   back_button=True)

        package_id = request.form.get('package_id', '').strip()
        deposition_id = request.form.get('deposition_id', '').strip()

        if not _valid_package_id(package_id):
            return render_template('result.html', message="Invalid package ID.", back_button=False)
        if not _valid_deposition_id(deposition_id):
            return render_template('result.html', message="Invalid deposition ID.", back_button=False)

        try:
            package = ckan_zenodo.get_ckan_package(package_id)
            resources = package.get('resources', [])
            if not resources:
                return render_template('result.html',
                                       message="No resources found in this package.",
                                       back_button=True)

            queued, skipped, errors = 0, 0, []
            for res in resources:
                try:
                    ckan_zenodo.export_to_zenodo(
                        zenodo_apikey, res['id'], res['name'], res['url'], deposition_id
                    )
                    queued += 1
                except ckan_zenodo.DuplicateTransfer:
                    skipped += 1
                except ckan_zenodo.ResourceFileNotFound:
                    errors.append(f"File not found: {res['name']}")
                except ckan_zenodo.FileTooLarge:
                    errors.append(f"File too large: {res['name']}")
                except Exception as e:
                    logging.error(f"Error exporting resource {res.get('id')}: {e}")
                    errors.append(f"Error: {res['name']}")

            parts = [f"{queued} file(s) queued for export."]
            if skipped:
                parts.append(f"{skipped} already exported (skipped).")
            if errors:
                parts.append("Issues: " + "; ".join(errors))
            return render_template('result.html', message=" ".join(parts), back_button=True)

        except Exception as e:
            logging.error(f"Unexpected error in export_package_to_zenodo: {e}")
            return render_template('result.html',
                                   message="An unexpected error occurred. Please try again.",
                                   back_button=True)

    # ── retry_transfer ────────────────────────────────────────────────────────
    elif action == "retry_transfer":
        if 'user' not in session:
            return render_template('result.html', message="Not authenticated.", back_button=False)

        zenodo_apikey = session.get('zenodo_apikey')
        if not zenodo_apikey:
            return render_template('result.html',
                                   message="Session expired. Re-enter your Zenodo API key first, then retry.",
                                   back_button=True)

        transfer_id_str = request.form.get('transfer_id', '').strip()
        if not transfer_id_str.isdigit():
            return render_template('result.html', message="Invalid transfer ID.", back_button=False)

        transfer_id = int(transfer_id_str)
        username = session['user']['username']
        transfer = ckan_zenodo.get_transfer_by_id(transfer_id, username)

        if not transfer:
            return render_template('result.html', message="Transfer not found.", back_button=True)
        if transfer['status'] != 'failed':
            return render_template('result.html',
                                   message="Only failed transfers can be retried.",
                                   back_button=True)

        ckan_zenodo.reset_transfer_for_retry(transfer_id)
        user_email = session['user'].get('email', '')
        ckan_zenodo.send_upload_task(
            username, transfer['file_path'], zenodo_apikey,
            transfer['deposition_id'], transfer['deposition_name'],
            transfer['filename'], transfer_id, user_email,
        )
        return render_template('result.html',
                               message="Transfer has been re-queued. Check the Transfers page for its status.",
                               back_button=True)

    logging.warning(f"Unknown ajax action received: {action!r}")
    return render_template('result.html', message="Unknown action.", back_button=False)


@app.route('/transfers')
def transfers():
    """
    Displays the transfer history for the logged-in user.
    """
    if 'user' in session:
        username = session['user']['username']
        user_transfers = ckan_zenodo.get_transfers_for_user(username)
        return render_template("transfers.html", username=session['user']['username'], transfers=user_transfers)
    else:
        return redirect(url_for('login'))


@app.route('/api/transfer/<int:transfer_id>')
@csrf.exempt
def api_transfer_status(transfer_id):
    """
    Returns current status of a transfer as JSON (for live polling).
    Only returns data for transfers owned by the logged-in user.
    """
    if 'user' not in session:
        return jsonify({'error': 'unauthenticated'}), 401

    transfer = ckan_zenodo.get_transfer_by_id(transfer_id, session['user']['username'])
    if not transfer:
        return jsonify({'error': 'not found'}), 404

    return jsonify({
        'id': transfer['id'],
        'status': transfer['status'],
        'retry_count': transfer['retry_count'],
        'updated_at': str(transfer['updated_at']),
    })


@app.route('/health')
@csrf.exempt
def health():
    """
    Liveness/readiness check. Returns 200 when both DB and RabbitMQ are reachable,
    503 otherwise. Response body is JSON with per-component status.
    """
    status = {}

    try:
        conn = db.get_connection()
        with conn.cursor() as cur:
            cur.execute('SELECT 1')
        conn.close()
        status['db'] = 'ok'
    except Exception as e:
        status['db'] = f'error: {e}'

    try:
        rc = configs.get_rabbitmq_config()
        rmq_conn = pika.BlockingConnection(
            pika.ConnectionParameters(host=rc['host'], socket_timeout=2, connection_attempts=1)
        )
        rmq_conn.close()
        status['rabbitmq'] = 'ok'
    except Exception as e:
        status['rabbitmq'] = f'error: {e}'

    all_ok = all(v == 'ok' for v in status.values())
    status['status'] = 'healthy' if all_ok else 'degraded'
    return jsonify(status), 200 if all_ok else 503


if __name__ == '__main__':
    serve(app, host='0.0.0.0', port=8090)
