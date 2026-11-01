"""Custom exceptions of the system.

Every exception inherits from ClinicError and carries a Spanish message ready to show to the user.
Implemented in step C1.
"""


class ClinicError(Exception):
    """Base class of every custom exception in the system."""

    pass


class ValidationError(ClinicError):
    """Raised when a value does not follow its format or rule."""

    pass


class DuplicateError(ClinicError):
    """Raised when a patient code or username already exists."""

    pass


class InvalidCredentialsError(ClinicError):
    """Raised when the username or password is wrong."""

    pass


class PermissionDeniedError(ClinicError):
    """Raised when the current user lacks a permission."""

    pass


class NotFoundError(ClinicError):
    """Raised when a patient, ticket or user does not exist."""

    pass


class EmptyQueueError(ClinicError):
    """Raised when both ticket queues are empty."""

    pass


class EmptyStackError(ClinicError):
    """Raised when a stack has no items."""

    pass


class NotUndoableError(ClinicError):
    """Raised when an action cannot be undone or was already undone."""

    pass


class CorruptedFileError(ClinicError):
    """Raised when a JSON file is damaged or is not UTF-8."""

    pass


class StorageError(ClinicError):
    """Raised when a JSON file cannot be saved."""

    pass
