#!/usr/bin/env python3
# -----------------------------------------------------------------
# Base document loader interface
# -----------------------------------------------------------------
from abc import ABC, abstractmethod
from typing import List


class BaseDocumentLoader(ABC):
    """Abstract base for all document loaders."""

    @abstractmethod
    def load_document(self, file_path: str) -> List[str]:
        """
        Return a list of text chunks extracted from the given file.
        Concrete loaders decide how to split.
        """
        raise NotImplementedError
