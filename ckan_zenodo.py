import os
import pika
import json
import requests
import pymysql
from ckanapi import RemoteCKAN, NotAuthorized, NotFound
from flask import session
import configs

#logging.basicConfig(filename='app.log', format='%(asctime)s - %(levelname)s - %(message)s',
#                    level=logging.INFO)


# --- Returns the local file path for a CKAN resource based on its URL ---
def get_file_path(resourse_id, url):
    """
    Resolve a CKAN resource URL into a local file system path.
    Supports user home resources and default CKAN storage path.
    """

    config = configs.get_ckan_config()
    resources_path = config.get['resources_path']

    if config['resources_usr_url'] in url:
        # User home storage
        start = url.find("~") + 1
        end = url.find("/", start)
        user = url[start:end]

        to_replace = f"{config['resources_usr_url']}{user}"
        replacement = config['resources_usr_path']

        file_path = url.replace(to_replace, replacement)
    else:
        # Default CKAN resource path
        file_path = f"{resources_path}/{resourse_id[:3]}/{resourse_id[3:6]}/{resourse_id[6:]}"

    return file_path

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
def insert_transfer_record(username, file_path, filename, deposition_id, deposition_name):
    """
    Create a new transfer record in the zenodo_transfers table with 'pending' status.
    Returns the newly created transfer ID.
    """
    db_config = configs.get_db_config()
    connection = pymysql.connect(**db_config)
    try:
        with connection.cursor() as cursor:
            sql = "INSERT INTO zenodo_transfers (username, file_path, filename, deposition_id, deposition_name, status) VALUES (%s, %s, %s, %s, %s, 'pending')"
            cursor.execute(sql, (username, file_path, filename, deposition_id, deposition_name))
            transfer_id = cursor.lastrowid
        connection.commit()
        return transfer_id
    finally:
        connection.close()


# --- Sends an upload task to RabbitMQ for asynchronous processing ---
def send_upload_task(username, file_path, zenodo_token, deposition_id, deposition_name, filename, transfer_id):
    """
    Publish an upload task message to the 'zenodo_upload' queue in RabbitMQ.
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
        'transfer_id': transfer_id
    })

    channel.basic_publish(exchange='',
                          routing_key='zenodo_upload',
                          body=message)

    print(f"[x] Upload task sent: {file_path} as {filename} to deposition '{deposition_name}', transfer_id: {transfer_id}, user: {username}")
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
    print(f"[x] Get CKAN resource: {res['name']}")
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
    print(f"[x] Get CKAN package: {pac['title']}")
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
    print(f"[x] Get ZENODO depositions")
    return r.json()


# --- Exports a CKAN resource into an existing Zenodo deposition ---
def export_to_zenodo(zenodo_apikey, resource_id, filename, res_url, deposition_id):
    """
    Export a CKAN resource file to an existing Zenodo deposition.
    Creates a transfer record and enqueues an upload task in RabbitMQ.
    """
    deposition_name = get_deposition_name(zenodo_apikey, deposition_id)
    file_path = get_file_path(resource_id, res_url)

    if not os.path.exists(file_path):
        print(f"File {file_path} does not exist")
        return 100

    username = session['user']['username']

    transfer_id = insert_transfer_record(username, file_path, filename, deposition_id, deposition_name)
    send_upload_task(username, file_path, zenodo_apikey, deposition_id, deposition_name, filename, transfer_id)

    return 201


# --- Creates a new Zenodo deposition and exports a CKAN resource into it ---
def create_deposit_and_export(zenodo_apikey, resource_id, filename, res_url, deposition_name, deposition_desc):
    """
    Create a new Zenodo deposition with metadata and restricted access.
    Then export a CKAN resource file into this deposition by enqueuing an upload task.
    """
    headers = {"Content-Type": "application/json"}
    params = {'access_token': zenodo_apikey}

    # Step 1: Create new deposition with metadata
    metadata_payload = {
        "metadata": {
            "upload_type": "dataset",
            "title": deposition_name,
            "description": deposition_desc,
            "access_right": "restricted",
            'creators': [
                {'name': session['user']['family_name'] + ', ' + session['user']['given_name'], 'affiliation': 'MyAffiliation'}
            ]
        }
    }

    response = requests.post("https://zenodo.org/api/deposit/depositions", params=params, json=metadata_payload, headers=headers)

    if response.status_code != 201:
        print("Error while creating deposition")
        print(f"Status code: {response.status_code}")
        print(response.text)
        return response.status_code

    deposition = response.json()
    deposition_id = deposition['id']

    print(f"[x] New ZENODO deposition created, title: {deposition_name}")

    # Step 2: Check if CKAN file exists
    file_path = get_file_path(resource_id, res_url)
    if not os.path.exists(file_path):
        print(f"File {file_path} does not exist")
        return 100

    username = session['user']['username']

    # Step 3: Create transfer record and enqueue upload
    transfer_id = insert_transfer_record(username, file_path, filename, deposition_id, deposition_name)
    send_upload_task(username, file_path, zenodo_apikey, deposition_id, deposition_name, filename, transfer_id)

    return 201


# --- Retrieves transfer records for a given user ---
def get_transfers_for_user(username):
    """
    Get all Zenodo transfer records from the database for the given username.
    Returns results ordered by creation date (newest first).
    """
    db_config = configs.get_db_config()
    connection = pymysql.connect(**db_config)
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            sql = "SELECT * FROM zenodo_transfers WHERE username = %s ORDER BY created_at DESC"
            cursor.execute(sql, (username,))
            results = cursor.fetchall()
        return results
    finally:
        connection.close()
