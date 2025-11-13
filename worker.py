import pika
import json
import requests
import pymysql
import configs

# Base API URL for interacting with Zenodo depositions
zc = configs.get_zenodo_config()
ZENODO_API_URL = zc['api_url']

# --- Update transfer status in the database ---
def update_transfer_status(transfer_id, status, response):
    """
    Update the status and response of a Zenodo transfer record in the database.

    Args:
        transfer_id (int): The ID of the transfer record in the database.
        status (str): New status (e.g., 'in_progress', 'completed', 'failed').
        response (str): Response or error message from Zenodo API.
    """
    db_config = configs.get_db_config()
    connection = pymysql.connect(**db_config)
    try:
        with connection.cursor() as cursor:
            sql = "UPDATE zenodo_transfers SET status=%s, zenodo_response=%s WHERE id=%s"
            cursor.execute(sql, (status, response, transfer_id))
        connection.commit()
    finally:
        connection.close()


# --- Upload a file to Zenodo deposition bucket ---
def upload_to_zenodo(file_path, filename, zenodo_token, deposition_id):
    """
    Upload a local file to the Zenodo deposition storage bucket.

    Steps:
        1. Fetch the bucket URL for the deposition.
        2. Upload the file using HTTP PUT request.

    Args:
        file_path (str): Path to the file on the local filesystem.
        filename (str): Name of the file in Zenodo.
        zenodo_token (str): API key for Zenodo authentication.
        deposition_id (int): ID of the Zenodo deposition.

    Returns:
        str: Zenodo API response text after upload.
    """
    headers = {"Content-Type": "application/json"}
    params = {'access_token': zenodo_token}

    # Get deposition details -> extract bucket URL
    r = requests.get(f"{ZENODO_API_URL}/{deposition_id}", params=params, headers=headers)
    r.raise_for_status()
    bucket_url = r.json()['links']['bucket']

    # Upload the file directly to the deposition's bucket
    with open(file_path, "rb") as fp:
        r = requests.put(f"{bucket_url}/{filename}",
                         data=fp,
                         params=params)
        r.raise_for_status()

    return r.text


# --- RabbitMQ consumer callback ---
def callback(ch, method, properties, body):
    """
    Process a single upload task received from RabbitMQ queue.

    Steps:
        1. Parse the task details (username, file, deposition, etc.).
        2. Mark transfer as 'in_progress' in DB.
        3. Upload the file to Zenodo.
        4. Update DB status to 'completed' (or 'failed' if error).
        5. Acknowledge message so it's removed from queue.
    """
    print(f"[x] Received upload task: {body}")

    # Parse task data from queue
    task = json.loads(body)
    username = task['username']
    file_path = task['file_path']
    filename = task['filename']
    zenodo_token = task['zenodo_token']
    deposition_id = task['deposition_id']
    transfer_id = task['transfer_id']

    try:
        # Update DB -> in progress
        update_transfer_status(transfer_id, 'in_progress', '')

        # Upload file
        response = upload_to_zenodo(file_path, filename, zenodo_token, deposition_id)

        # Update DB -> success
        update_transfer_status(transfer_id, 'completed', response)
        print(f"[✓] User: {username} – file {filename} uploaded to Zenodo (ID: {deposition_id}) successfully")

    except Exception as e:
        # Update DB -> failure
        update_transfer_status(transfer_id, 'failed', str(e))
        print(f"[!] User: {username} – upload error: {e}")

    # Acknowledge message (remove from queue)
    ch.basic_ack(delivery_tag=method.delivery_tag)


# --- Worker entrypoint ---
def start_worker():
    """
    Start a RabbitMQ worker that listens for Zenodo upload tasks.

    Workflow:
        - Connect to RabbitMQ (host from config).
        - Declare 'zenodo_upload' queue.
        - Consume messages from queue, using 'callback' to process each.
        - Keep running until manually stopped (CTRL+C).
    """
    rc = configs.get_rabbitmq_config()
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=rc['host']))
    channel = connection.channel()
    channel.queue_declare(queue=rc['queue'], durable=True)
    channel.basic_qos(prefetch_count=1)  # Fair dispatch: one task at a time
    channel.basic_consume(queue=rc['queue'], on_message_callback=callback)

    print('[*] Waiting for upload tasks. To exit press CTRL+C')
    channel.start_consuming()


# --- Run worker when executed directly ---
if __name__ == '__main__':
    start_worker()
