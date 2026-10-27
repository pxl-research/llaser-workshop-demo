#!/usr/bin/env python3
import logging
import os
from typing import List

from .Document_Loader import BaseDocumentLoader

logger = logging.getLogger(__name__)

ENDPOINT_ENV = "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"
KEY_ENV = "AZURE_DOCUMENT_INTELLIGENCE_KEY"
TIMEOUT_ENV = "AZURE_DOCUMENT_INTELLIGENCE_TIMEOUT"
DEFAULT_TIMEOUT_SECONDS = 300


class AzureDocumentIntelligenceLoader(BaseDocumentLoader):
    def __init__(self, endpoint: str | None = None, key: str | None = None):
        try:
            from azure.ai.documentintelligence import DocumentIntelligenceClient
            from azure.core.credentials import AzureKeyCredential
        except ImportError as e:
            raise ImportError(
                "azure-ai-documentintelligence is not installed. "
                "Install with `pip install azure-ai-documentintelligence`."
            ) from e

        endpoint = endpoint or os.getenv(ENDPOINT_ENV)
        key = key or os.getenv(KEY_ENV)

        missing = [
            name for name, value in ((ENDPOINT_ENV, endpoint), (KEY_ENV, key)) if not value
        ]
        if missing:
            raise RuntimeError(f"{' and '.join(missing)} must be set.")

        self.timeout = float(os.getenv(TIMEOUT_ENV) or DEFAULT_TIMEOUT_SECONDS)
        self.client = DocumentIntelligenceClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(key),
        )

    def load_document(self, file_path: str) -> List[str]:
        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            poller = self.client.begin_analyze_document(
                model_id="prebuilt-layout",
                body=file_bytes,
                content_type="application/octet-stream",
                output_content_format="markdown",
            )
            result = poller.result(timeout=self.timeout)  # avoid an infinite hang
        except Exception:
            logger.exception(
                "Azure Document Intelligence failed for %s", os.path.basename(file_path)
            )
            raise

        return [result.content] if result.content else []
