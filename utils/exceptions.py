"""Custom exceptions of the system.

Every exception inherits from ClinicError and carries a Spanish message ready
to show to the user. The interface catches ClinicError and shows str(error),
so the logic never builds messages for the screen in any other way.
"""


class ClinicError(Exception):
    """Base class of every custom exception in the system.

    Each subclass overrides default_message. A caller can pass a more specific
    message, for example one that names the field or the ticket involved.
    """

    default_message: str = "Ocurrió un error inesperado en el sistema."

    def __init__(self, message: str | None = None) -> None:
        self._message = message or self.default_message
        super().__init__(self._message)

    @property
    def message(self) -> str:
        """Spanish text ready to show to the user."""
        return self._message


class ValidationError(ClinicError):
    """Raised when a value does not follow its format or rule."""

    default_message = "El dato ingresado no es válido."


class DuplicateError(ClinicError):
    """Raised when a patient code or username already exists."""

    default_message = "Ese registro ya existe."


class InvalidCredentialsError(ClinicError):
    """Raised when the username or password is wrong.

    The message never says which of the two failed (RNF-09).
    """

    default_message = "Usuario o contraseña incorrectos."


class PermissionDeniedError(ClinicError):
    """Raised when the current user lacks a permission."""

    default_message = "Tu usuario no tiene permiso para esta acción."


class NotFoundError(ClinicError):
    """Raised when a patient, ticket or user does not exist."""

    default_message = "No se encontró el registro solicitado."


class EmptyQueueError(ClinicError):
    """Raised when both ticket queues are empty."""

    default_message = "No hay pacientes en espera."


class EmptyStackError(ClinicError):
    """Raised when a stack has no items."""

    default_message = "No hay acciones que se puedan deshacer."


class NotUndoableError(ClinicError):
    """Raised when an action cannot be undone or was already undone."""

    default_message = "Esta acción no se puede deshacer."


class CorruptedFileError(ClinicError):
    """Raised when a JSON file is damaged or is not UTF-8.

    It keeps the file name so the interface can say which file failed.
    """

    def __init__(self, filename: str, message: str | None = None) -> None:
        self._filename = filename
        super().__init__(
            message
            or f"El archivo {filename} está dañado o no está en UTF-8. "
            "Se guardó una copia y el sistema siguió con esa lista vacía."
        )

    @property
    def filename(self) -> str:
        """Name of the damaged file, for example tickets.json."""
        return self._filename


class StorageError(ClinicError):
    """Raised when a JSON file cannot be saved."""

    default_message = (
        "No se pudo guardar la información. "
        "Los datos siguen en memoria; intenta de nuevo."
    )
