#!/usr/bin/env python3
import os
from typing import List
from .Document_Loader import BaseDocumentLoader

class LlamaParseLoader(BaseDocumentLoader):
    def __init__(self, api_key: str | None = None, result_type: str = "text"):
        # We only store configuration in __init__, we do NOT create the client yet
        self.api_key = api_key or os.getenv("LLAMA_KEY")
        if not self.api_key:
            raise RuntimeError("LLAMA_KEY is not set in the environment.")
        self.result_type = result_type

    def load_document(self, file_path: str) -> List[str]:
        print(f"llama loader processing: {file_path}")
        
        try:
            from llama_parse import LlamaParse
        except ImportError as e:
            raise ImportError(
                "llama-parse is not installed. Install with `pip install llama-parse`."
            ) from e

        # Initialize the client HERE, for every single file
        # This prevents the "TCPTransport closed" error on subsequent calls
        parser = LlamaParse(
            api_key=self.api_key,
            result_type=self.result_type,
        )

        try:
            # load_data handles the file loading (supports PDF, Docx, etc. automatically)
            docs = parser.load_data(file_path)
            
            chunks: List[str] = []
            for d in docs:
                text = getattr(d, "text", None) or getattr(d, "page_content", "")
                if text:
                    chunks.append(text)
            return chunks
            
        except Exception as e:
            print(f"Error parsing {file_path} with LlamaParse: {e}")
            return []
