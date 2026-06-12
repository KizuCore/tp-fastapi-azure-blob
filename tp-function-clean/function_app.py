import datetime
import logging
import os

import azure.functions as func
from azure.storage.blob import BlobServiceClient


app = func.FunctionApp()

CONTAINER_NAME = "fichiers-api"
MAX_AGE_MINUTES = 5


@app.timer_trigger(
    schedule="0 */30 * * * *",
    arg_name="myTimer",
    run_on_startup=True,
    use_monitor=False,
)
def clean_blob_storage(myTimer: func.TimerRequest) -> None:
    logging.info("Début du nettoyage du Storage Account...")

    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

    if not connection_string:
        logging.error("Variable AZURE_STORAGE_CONNECTION_STRING manquante.")
        return

    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(CONTAINER_NAME)

    now = datetime.datetime.now(datetime.timezone.utc)
    max_age = datetime.timedelta(minutes=MAX_AGE_MINUTES)

    deleted_count = 0

    for blob in container_client.list_blobs():
        blob_age = now - blob.creation_time

        if blob_age > max_age:
            blob_client = container_client.get_blob_client(blob.name)
            blob_client.delete_blob()
            deleted_count += 1
            logging.info("Blob supprimé : %s", blob.name)

    logging.info("Nettoyage terminé. Nombre de blobs supprimés : %s", deleted_count)