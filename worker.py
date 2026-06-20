import time
import logging
import smtplib
from email.mime.text import MIMEText
import pika
import json
import requests
import configs
import db


# --- Send email notification (no-op when SMTP disabled or no address) ---
def send_email_notification(to_addr, subject, body):
    try:
        sc = configs.get_smtp_config()
        if not sc.get('enabled') or not to_addr:
            return
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = sc['from_addr']
        msg['To'] = to_addr
        with smtplib.SMTP(sc['host'], sc['port']) as smtp:
            if sc.get('use_tls'):
                smtp.starttls()
            if sc.get('username'):
                smtp.login(sc['username'], sc['password'])
            smtp.send_message(msg)
        logging.info(f"Sent notification email to {to_addr}: {subject}")
    except Exception as e:
        logging.error(f"Failed to send notification email to {to_addr}: {e}")


# --- Update transfer status in the database ---
def update_transfer_status(transfer_id, status, response, retry_count=None):
    """
    Update the status, response, and optionally retry_count of a transfer record.
    """
    connection = db.get_connection()
    try:
        with connection.cursor() as cursor:
            if retry_count is not None:
                sql = "UPDATE zenodo_transfers SET status=%s, zenodo_response=%s, retry_count=%s WHERE id=%s"
                cursor.execute(sql, (status, response, retry_count, transfer_id))
            else:
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

    Returns:
        str: Zenodo API response text after upload.
    """
    zc = configs.get_zenodo_config()
    zenodo_api_url = zc['api_url']

    headers = {"Content-Type": "application/json"}
    params = {'access_token': zenodo_token}

    r = requests.get(f"{zenodo_api_url}/{deposition_id}", params=params, headers=headers)
    r.raise_for_status()
    bucket_url = r.json()['links']['bucket']

    with open(file_path, "rb") as fp:
        r = requests.put(f"{bucket_url}/{filename}", data=fp, params=params)
        r.raise_for_status()

    return r.text


# --- RabbitMQ consumer callback ---
def callback(ch, method, properties, body):
    """
    Process a single upload task from the queue.

    On failure, re-queues with an incremented retry_count and exponential backoff
    up to max_retries times. After all attempts are exhausted, marks the transfer
    as 'failed'. Always acknowledges the message so it is removed from the queue.
    Sends an email notification on completion or final failure if configured.
    """
    task = json.loads(body)
    username = task['username']
    file_path = task['file_path']
    filename = task['filename']
    zenodo_token = task['zenodo_token']
    deposition_id = task['deposition_id']
    transfer_id = task['transfer_id']
    retry_count = task.get('retry_count', 0)
    user_email = task.get('user_email', '')

    rc = configs.get_rabbitmq_config()
    max_retries = int(rc.get('max_retries', 3))

    logging.info(
        f"Processing: {filename} (transfer_id={transfer_id}, "
        f"attempt={retry_count + 1}/{max_retries + 1}, user={username})"
    )

    try:
        update_transfer_status(transfer_id, 'in_progress', '', retry_count)
        response = upload_to_zenodo(file_path, filename, zenodo_token, deposition_id)
        update_transfer_status(transfer_id, 'completed', response, retry_count)
        logging.info(f"Upload completed: {filename} -> deposition {deposition_id} (user={username})")
        send_email_notification(
            user_email,
            f"Transfer completed: {filename}",
            f"Your file '{filename}' was successfully uploaded to Zenodo deposition {deposition_id}."
        )

    except Exception as e:
        logging.error(f"Upload attempt {retry_count + 1} failed for transfer {transfer_id}: {e}")

        if retry_count < max_retries:
            next_attempt = retry_count + 1
            # Exponential backoff: 10s, 20s, 40s … capped at 5 minutes
            delay = min(2 ** retry_count * 10, 300)
            logging.info(f"Retrying in {delay}s (attempt {next_attempt}/{max_retries}) ...")
            time.sleep(delay)

            task['retry_count'] = next_attempt
            ch.basic_publish(
                exchange='',
                routing_key=rc['queue'],
                body=json.dumps(task),
                properties=pika.BasicProperties(delivery_mode=2),
            )
            try:
                update_transfer_status(
                    transfer_id, 'pending',
                    f"Retry {next_attempt}/{max_retries}: {e}",
                    next_attempt,
                )
            except Exception as db_err:
                logging.error(f"Could not update retry status for transfer {transfer_id}: {db_err}")
        else:
            logging.error(f"All {max_retries + 1} attempts exhausted for transfer {transfer_id}")
            try:
                update_transfer_status(transfer_id, 'failed', str(e), retry_count)
            except Exception as db_err:
                logging.error(f"Could not mark transfer {transfer_id} as failed: {db_err}")
            send_email_notification(
                user_email,
                f"Transfer failed: {filename}",
                f"Your file '{filename}' failed to upload to Zenodo after all retry attempts. "
                f"Error: {e}"
            )

    finally:
        ch.basic_ack(delivery_tag=method.delivery_tag)


# --- Worker entrypoint ---
def start_worker():
    """
    Start a RabbitMQ worker that listens for Zenodo upload tasks.
    """
    rc = configs.get_rabbitmq_config()
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=rc['host']))
    channel = connection.channel()
    channel.queue_declare(queue=rc['queue'], durable=True)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=rc['queue'], on_message_callback=callback)

    logging.info('Worker started. Waiting for upload tasks.')
    channel.start_consuming()


if __name__ == '__main__':
    start_worker()
