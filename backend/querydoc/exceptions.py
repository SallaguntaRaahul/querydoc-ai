"""Domain exceptions. Each carries a user-presentable message."""


class QueryDocError(Exception):
    """Base class for all QueryDoc errors."""


class PDFValidationError(QueryDocError):
    """The uploaded file is not an acceptable PDF (wrong type, corrupt, too big, ...)."""


class PasswordProtectedPDFError(PDFValidationError):
    """The PDF is encrypted and cannot be opened without a password."""


class DuplicateDocumentError(QueryDocError):
    """A document with identical content is already indexed."""

    def __init__(self, doc_id: str, filename: str) -> None:
        super().__init__(f"'{filename}' is already indexed (document id {doc_id}).")
        self.doc_id = doc_id
        self.filename = filename


class DocumentNotFoundError(QueryDocError):
    """The referenced document id does not exist."""


class IndexCompatibilityError(QueryDocError):
    """A persisted index does not match the configured embedding model or is corrupt."""


class GenerationError(QueryDocError):
    """The local LLM failed to produce an answer."""


class GenerationUnavailableError(GenerationError):
    """The local LLM could not be loaded; the system runs in retrieval-only mode."""


class QueueFullError(QueryDocError):
    """Too many generation requests are queued."""


class GenerationTimeoutError(QueryDocError):
    """A generation request waited too long for a free slot."""
