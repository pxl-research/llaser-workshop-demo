# RAG_Helpers.py
from typing import Optional
import os
import logging
import tempfile
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError
from dotenv import load_dotenv

from AI.API import settings

def download_container_documents(
    container_name: str,
    download_dir: Optional[str] = None,
) -> str:
    load_dotenv()
    raw_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL")
    if not raw_url:
        raise RuntimeError("AZURE_STORAGE_ACCOUNT_URL is not set in the environment")
    BLOB_SERVICE_URL = raw_url.strip('"')

    DOC_EXTENSIONS = settings.allowed_document_extensions()

    if download_dir is None:
        download_dir = tempfile.mkdtemp(prefix=f"{container_name}_")
        logging.info(f"Using temp download directory: {download_dir}")
    else:
        os.makedirs(download_dir, exist_ok=True)
        logging.info(f"Using provided download directory: {download_dir}")

    try:
        credential = DefaultAzureCredential()
        logging.info(f"Connecting to storage account: {BLOB_SERVICE_URL}")
        blob_service_client = BlobServiceClient(
            account_url=BLOB_SERVICE_URL,
            credential=credential,
        )

        logging.info(f"Processing container: {container_name}")
        container_client = blob_service_client.get_container_client(container_name)

        logging.info("  -> Listing all blobs in container.")
        blob_list = container_client.list_blobs()

        for blob in blob_list:
            blob_name = blob.name
            if blob_name.endswith("/"):
                continue

            _, ext = os.path.splitext(blob_name.lower())
            if ext not in DOC_EXTENSIONS:
                logging.info(f"  -> Skipping non-document blob: {blob_name}")
                continue

            logging.info(f"  -> Document detected, downloading: {blob_name}")
            blob_client = container_client.get_blob_client(blob_name)

            local_path = os.path.join(download_dir, blob_name)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            try:
                download_stream = blob_client.download_blob()
                with open(local_path, "wb") as f:
                    f.write(download_stream.readall())
                logging.info(f"  -> Downloaded to: {local_path}")
            except Exception as e:
                logging.warning(f"  -> Error downloading blob '{blob_name}': {e}")
                continue

    except ResourceNotFoundError:
        logging.warning(f"Container not found: {container_name}")
    except Exception as e:
        logging.warning(
            f"An unexpected error occurred during client connection or container access: {e}"
        )

    return download_dir
