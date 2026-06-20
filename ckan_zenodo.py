import os
import logging
import pika
import json
import requests
import pymysql
from ckanapi import RemoteCKAN
from flask import session
import configs
import db


class ResourceFileNotFound(Exception):
    """Raised when the CKAN resource file does not exist on the local filesystem."""
    pass


class FileTooLarge(Exception):
    """Raised when a resource file exceeds the configured max_file_size_mb limit."""
    pass


class ZenodoAPIError(Exception):
    """Raised when the Zenodo API returns an unexpected error response."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class DuplicateTransfer(Exception):
    """Raised when the same resource + deposition combination was already exported successfully."""
    pass


# --- Returns the local file path for a CKAN resource based on its URL ---
def get_file_path(resourse_id, url):
    """
    Resolve a CKAN resource URL into a local file system path.
    Supports user home resources and default CKAN storage path.
    """
    config = configs.get_ckan_config()
    resources_path = config['resources_path']

    if config['resources_usr_url'] in url:
        # User home storage
        start = url.find("~") + 1
        end = url.find("/", start)
        user = url[start:end]

        to_replace = f"{config['resources_usr_url']}{user}"
        replacement = config['resources_usr_path'].format(user=user)

        file_path = url.replace(to_replace, replacement)
    else:
        # Default CKAN resource path
        file_path = f"{resources_path}/{resourse_id[:3]}/{resourse_id[3:6]}/{resourse_id[6:]}"

    return file_path


def _check_file_size(file_path):
    """Raise FileTooLarge if the file exceeds the configured max_file_size_mb limit (0 = unlimited)."""
    app_config = configs.get_app_config()
    max_mb = int(app_config.get('max_file_size_mb', 0))
    if max_mb > 0:
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if size_mb > max_mb:
            raise FileTooLarge(
                f"File size {size_mb:.1f} MB exceeds the {max_mb} MB limit."
            )


def check_duplicate_transfer(resource_id, deposition_id):
    """
    Raise DuplicateTransfer if this resource + deposition was already exported
    and that transfer is still pending, in-progress, or completed.
    Only considers records that have resource_id populated (post-migration records).
    """
    connection = db.get_connection()
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            sql = """SELECT id FROM zenodo_transfers
                     WHERE resource_id = %s AND deposition_id = %s
                       AND status NOT IN ('failed')
                       AND resource_id IS NOT NULL"""
            cursor.execute(sql, (resource_id, deposition_id))
            if cursor.fetchone():
                raise DuplicateTransfer(
                    f"Resource {resource_id} is already associated with deposition {deposition_id}."
                )
    finally:
        connection.close()


# --- Fetches the name/title of a Zenodo deposition ---
def get_deposition_name(zenodo_apikey, deposition_id):
    """
    Retrieve the title (name) of a Zenodo deposition by its ID.
    """
    zc = configs.get_zenodo_config()
    headers = {"Content-Type": "application/json"}
    params = {'access_token': zenodo_apikey}
    r = requests.get(f"{zc['api_url']}/{deposition_id}", params=params, headers=headers)
    r.raise_for_status()
    return r.json()['metadata']['title']


# --- Inserts a transfer record into the MySQL database ---
def insert_transfer_record(username, file_path, filename, deposition_id, deposition_name,
                           resource_id='', user_email=''):
    """
    Create a new transfer record in the zenodo_transfers table with 'pending' status.
    Returns the newly created transfer ID.
    """
    connection = db.get_connection()
    try:
        with connection.cursor() as cursor:
            sql = """INSERT INTO zenodo_transfers
                         (username, user_email, file_path, filename, deposition_id,
                          deposition_name, resource_id, status)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')"""
            cursor.execute(sql, (username, user_email, file_path, filename,
                                 deposition_id, deposition_name, resource_id))
            transfer_id = cursor.lastrowid
        connection.commit()
        return transfer_id
    finally:
        connection.close()


# --- Sends an upload task to RabbitMQ for asynchronous processing ---
def send_upload_task(username, file_path, zenodo_token, deposition_id, deposition_name,
                     filename, transfer_id, user_email=''):
    """
    Publish an upload task message to the RabbitMQ queue.
    This task will be processed by a background worker to upload the file to Zenodo.
    """
    rc = configs.get_rabbitmq_config()
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=rc['host']))
    channel = connection.channel()
    channel.queue_declare(queue=rc['queue'], durable=True)

    message = json.dumps({
        'username': username,
        'file_path': file_path,
        'filename': filename,
        'zenodo_token': zenodo_token,
        'deposition_id': deposition_id,
        'deposition_name': deposition_name,
        'transfer_id': transfer_id,
        'user_email': user_email,
    })

    channel.basic_publish(exchange='', routing_key=rc['queue'], body=message,
                          properties=pika.BasicProperties(delivery_mode=2))
    logging.info(f"Upload task queued: {filename} to deposition '{deposition_name}' "
                 f"(transfer_id={transfer_id}, user={username})")
    connection.close()


# --- Retrieves CKAN resource metadata ---
def get_ckan_resource(resource_id):
    """
    Fetch a CKAN resource by its ID.
    Returns full resource metadata.
    """
    config = configs.get_ckan_config()
    mysite = RemoteCKAN(config['server'], apikey=config['apikey'], user_agent='ckan-zenodo-1')
    res = mysite.action.resource_show(id=resource_id)
    logging.info(f"Fetched CKAN resource: {res['name']}")
    return res


# --- Retrieves CKAN package metadata ---
def get_ckan_package(package_id):
    """
    Fetch a CKAN package (dataset) by its ID.
    Returns full package metadata.
    """
    config = configs.get_ckan_config()
    mysite = RemoteCKAN(config['server'], apikey=config['apikey'], user_agent='ckan-zenodo-1')
    pac = mysite.action.package_show(id=package_id)
    logging.info(f"Fetched CKAN package: {pac['title']}")
    return pac


# --- Retrieves all Zenodo depositions for the given API key ---
def get_depositions(zenodo_apikey):
    """
    List all depositions available for the given Zenodo API key.
    """
    zc = configs.get_zenodo_config()
    params = {'access_token': zenodo_apikey}
    r = requests.get(zc['api_url'], params=params)
    r.raise_for_status()
    logging.info("Fetched Zenodo depositions")
    return r.json()


# --- Retrieves a single transfer record owned by the given user ---
def get_transfer_by_id(transfer_id, username):
    """
    Fetch one transfer record from the database, verified against username.
    Returns None if not found or if the record belongs to a different user.
    """
    connection = db.get_connection()
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            sql = "SELECT * FROM zenodo_transfers WHERE id = %s AND username = %s"
            cursor.execute(sql, (transfer_id, username))
            return cursor.fetchone()
    finally:
        connection.close()


# --- Resets a failed transfer so it can be re-queued ---
def reset_transfer_for_retry(transfer_id):
    """
    Set status to 'pending' and retry_count to 0 so the worker processes it fresh.
    """
    connection = db.get_connection()
    try:
        with connection.cursor() as cursor:
            sql = ("UPDATE zenodo_transfers "
                   "SET status = 'pending', retry_count = 0, zenodo_response = '' "
                   "WHERE id = %s")
            cursor.execute(sql, (transfer_id,))
        connection.commit()
    finally:
        connection.close()


# --- Exports a CKAN resource into an existing Zenodo deposition ---
def export_to_zenodo(zenodo_apikey, resource_id, filename, res_url, deposition_id):
    """
    Export a CKAN resource file to an existing Zenodo deposition.
    Creates a transfer record and enqueues an upload task in RabbitMQ.
    Raises DuplicateTransfer if this resource + deposition combo already has a live transfer.
    Raises ResourceFileNotFound if the local file does not exist.
    Raises FileTooLarge if the file exceeds the configured size limit.
    """
    check_duplicate_transfer(resource_id, deposition_id)

    deposition_name = get_deposition_name(zenodo_apikey, deposition_id)
    file_path = get_file_path(resource_id, res_url)

    if not os.path.exists(file_path):
        logging.error(f"Resource file not found: {file_path}")
        raise ResourceFileNotFound(f"File not found: {file_path}")

    _check_file_size(file_path)

    username = session['user']['username']
    user_email = session['user'].get('email', '')
    transfer_id = insert_transfer_record(username, file_path, filename, deposition_id,
                                         deposition_name, resource_id, user_email)
    send_upload_task(username, file_path, zenodo_apikey, deposition_id, deposition_name,
                     filename, transfer_id, user_email)


# --- Creates a new Zenodo deposition and exports a CKAN resource into it ---
def create_deposit_and_export(zenodo_apikey, resource_id, filename, res_url,
                               deposition_name, deposition_desc,
                               upload_type=None, access_right=None):
    """
    Create a new Zenodo deposition with metadata and export a CKAN resource file into it.
    upload_type and access_right override the config values when provided.
    Raises ZenodoAPIError if deposition creation fails.
    Raises ResourceFileNotFound if the local file does not exist; the orphaned deposition is deleted.
    Raises FileTooLarge if the file exceeds the configured size limit.
    """
    zc = configs.get_zenodo_config()
    headers = {"Content-Type": "application/json"}
    params = {'access_token': zenodo_apikey}

    effective_upload_type = upload_type or zc['upload_type']
    effective_access_right = access_right or zc['access_right']

    # Step 1: Create new deposition with configurable metadata
    metadata_payload = {
        "metadata": {
            "upload_type": effective_upload_type,
            "title": deposition_name,
            "description": deposition_desc,
            "access_right": effective_access_right,
            'creators': [
                {'name': session['user']['family_name'] + ', ' + session['user']['given_name'],
                 'affiliation': 'MyAffiliation'}
            ]
        }
    }

    response = requests.post(zc['api_url'], params=params, json=metadata_payload, headers=headers)

    if response.status_code != 201:
        logging.error(f"Failed to create Zenodo deposition: HTTP {response.status_code}")
        raise ZenodoAPIError(
            f"Zenodo returned HTTP {response.status_code} when creating deposition.",
            status_code=response.status_code
        )

    deposition = response.json()
    deposition_id = deposition['id']
    logging.info(f"Created Zenodo deposition: '{deposition_name}' (id={deposition_id})")

    # Step 2: Check if CKAN file exists — clean up the deposition if not
    file_path = get_file_path(resource_id, res_url)
    if not os.path.exists(file_path):
        logging.error(f"Resource file not found: {file_path} — deleting orphaned deposition {deposition_id}")
        try:
            requests.delete(f"{zc['api_url']}/{deposition_id}", params=params)
            logging.info(f"Deleted orphaned deposition {deposition_id}")
        except Exception as del_err:
            logging.error(f"Failed to delete orphaned deposition {deposition_id}: {del_err}")
        raise ResourceFileNotFound(f"File not found: {file_path}")

    _check_file_size(file_path)

    # Step 3: Create transfer record and enqueue upload
    username = session['user']['username']
    user_email = session['user'].get('email', '')
    transfer_id = insert_transfer_record(username, file_path, filename, deposition_id,
                                         deposition_name, resource_id, user_email)
    send_upload_task(username, file_path, zenodo_apikey, deposition_id, deposition_name,
                     filename, transfer_id, user_email)


# --- Retrieves transfer records for a given user ---
def get_transfers_for_user(username):
    """
    Get all Zenodo transfer records from the database for the given username.
    Returns results ordered by creation date (newest first).
    """
    connection = db.get_connection()
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            sql = "SELECT * FROM zenodo_transfers WHERE username = %s ORDER BY created_at DESC"
            cursor.execute(sql, (username,))
            results = cursor.fetchall()
        return results
    finally:
        connection.close()
