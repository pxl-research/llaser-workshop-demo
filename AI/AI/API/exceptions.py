class SystemNotReadyError(Exception):
    """Raised when the configured AI system is still loading or failed to start."""

    def __init__(self, message: str = "System is not ready yet"):
        super().__init__(message)
        self.message = message


class DocumentProcessingError(Exception):
    """Raised when an uploaded document cannot be indexed.

    The message shown to clients always comes from a fixed set, never from the
    wrapped exception text, which may carry paths or upstream service details.
    """

    UNREADABLE = "The document could not be read or contains no text."
    SPLIT_FAILED = "The document could not be split into chunks."
    INDEX_FAILED = "Indexing failed: the embedding or vector store service returned an error."
    GENERIC = "Document processing failed."

    CLIENT_ERROR_MESSAGES = frozenset({UNREADABLE, SPLIT_FAILED})
    USER_MESSAGES = CLIENT_ERROR_MESSAGES | {INDEX_FAILED, GENERIC}

    def __init__(self, user_message: str = GENERIC):
        if user_message not in self.USER_MESSAGES:
            user_message = self.GENERIC
        super().__init__(user_message)
        self.user_message = user_message

    @property
    def status_code(self) -> int:
        return 422 if self.user_message in self.CLIENT_ERROR_MESSAGES else 500
