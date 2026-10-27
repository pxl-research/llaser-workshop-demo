#!/usr/bin/env python3
from typing import List

from .Document_Loader import BaseDocumentLoader

try:
    import pymupdf4llm
except ImportError:
    pymupdf4llm = None


class PyMuPDF4LLMLoader(BaseDocumentLoader):
    def __init__(self):
        if pymupdf4llm is None:
            raise ImportError(
                "pymupdf4llm is not installed. Install with `pip install pymupdf4llm`."
            )

    def load_document(self, file_path: str) -> List[str]:
        text = pymupdf4llm.to_markdown(file_path)
        return [text]
