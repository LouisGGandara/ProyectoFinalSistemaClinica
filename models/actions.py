"""Actions saved in the action history (sections 3.6 to 3.8).

Every operation of the staff becomes an Action. Some actions only stay as
evidence (LogOnlyAction). The others are UndoableAction subclasses, and each
one knows how to revert its own operation in _revert().

The actions never import ClinicSystem. undo() receives a context, which is
any object with the attributes patient_manager and ticket_manager. In the
program that object is ClinicSystem; in the tests it can be a SimpleNamespace.
That keeps models free of a circular import with services.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Protocol

from utils.dates import now_text
from utils.exceptions import NotUndoableError

if TYPE_CHECKING:
    # Only for the type hints. At run time nothing is imported from services.
    from models.care_record import CareRecord
    from models.patient import Patient
    from models.ticket import Ticket
    from services.patient_manager import PatientManager
    from services.ticket_manager import TicketManager

# Action types. The history tab shows these values as they are.
LOGIN = "Inicio de sesión"
LOGOUT = "Cierre de sesión"
PATIENT_REGISTRATION = "Registro de paciente"
TICKET_CREATION = "Generación de turno"
PATIENT_UPDATE = "Modificación de paciente"
CALL_NEXT = "Atención"
CARE_FINISHED = "Finalización de atención"
TICKET_CANCELLATION = "Cancelación de turno"
USER_MANAGEMENT = "Gestión de usuarios"
UNDONE = "Acción deshecha"

ACTION_TYPES = (
    LOGIN,
    LOGOUT,
    PATIENT_REGISTRATION,
    TICKET_CREATION,
    PATIENT_UPDATE,
    CALL_NEXT,
    CARE_FINISHED,
    TICKET_CANCELLATION,
    USER_MANAGEMENT,
    UNDONE,
)


class UndoContext(Protocol):
    """What an action needs to revert itself: the two managers."""

    patient_manager: PatientManager
    ticket_manager: TicketManager


class Action(ABC):
    """Any action of the history: type, description, user, data and timestamp."""

    def __init__(
        self,
        action_type: str,
        description: str,
        username: str,
        data: dict | None = None,
        timestamp: str | None = None,
    ) -> None:
        self._action_type = action_type
        self._description = description
        self._username = username
        # A copy, so whoever built the dict cannot change the action later.
        self._data = dict(data or {})
        self._timestamp = timestamp or now_text()

    @property
    def action_type(self) -> str:
        """One of the constants above, such as "Cancelación de turno"."""
        return self._action_type

    @property
    def description(self) -> str:
        """Spanish sentence that says what happened."""
        return self._description

    @property
    def username(self) -> str:
        """Username of the person who did the action."""
        return self._username

    @property
    def data(self) -> dict[str, Any]:
        """Related information, such as the ticket number. Returned as a copy."""
        return dict(self._data)

    @property
    def timestamp(self) -> str:
        """Date and time of the action, in the format of utils.dates."""
        return self._timestamp

    @property
    @abstractmethod
    def is_undoable(self) -> bool:
        """True if the action goes to the undo stack."""

    def __str__(self) -> str:
        return f"{self._timestamp} {self._action_type}: {self._description}"


class LogOnlyAction(Action):
    """Action kept only as evidence: login, logout, users and undo itself."""

    @property
    def is_undoable(self) -> bool:
        return False


class UndoableAction(Action, ABC):
    """Action that can be reverted once.

    undo() is the same for every subclass: it checks that the action was not
    undone already, calls _revert() and marks the action. Only _revert()
    changes from one subclass to another.
    """

    def __init__(
        self,
        action_type: str,
        description: str,
        username: str,
        data: dict | None = None,
        timestamp: str | None = None,
    ) -> None:
        super().__init__(action_type, description, username, data, timestamp)
        self._undone = False

    @property
    def is_undoable(self) -> bool:
        return True

    @property
    def undone(self) -> bool:
        """True once the action has been reverted. The history tab marks it."""
        return self._undone

    def undo(self, context: UndoContext) -> None:
        """Revert the operation and mark the action as undone.

        Raises NotUndoableError if it was undone before. If _revert() raises,
        the action stays not undone, so ActionHistory can put it back on the
        undo stack.
        """
        if self._undone:
            raise NotUndoableError("Esta acción ya se deshizo.")
        self._revert(context)
        self._undone = True

    @abstractmethod
    def _revert(self, context: UndoContext) -> None:
        """Bring the data back to how it was before the action (section 3.6)."""


class RegisterPatientAction(UndoableAction):
    """Undoes a patient registration: the first ticket and the patient go away."""

    def __init__(self, username: str, patient: Patient, ticket: Ticket) -> None:
        super().__init__(
            PATIENT_REGISTRATION,
            f"Registro de {patient.code} ({patient.full_name}) "
            f"con el turno {ticket.number}.",
            username,
            {"patient_code": patient.code, "ticket_number": ticket.number},
        )
        self._patient = patient
        self._ticket = ticket

    def _revert(self, context: UndoContext) -> None:
        # get() raises NotFoundError before anything changes if the patient
        # is gone, so the ticket is not deleted alone.
        context.patient_manager.get(self._patient.code)
        # The ticket goes first: remove_pending_ticket refuses a ticket that
        # is no longer Pendiente, and then the patient is left untouched.
        context.ticket_manager.remove_pending_ticket(self._ticket.number)
        context.patient_manager.delete(self._patient.code)


class CreateTicketAction(UndoableAction):
    """Undoes a ticket created for a patient who was already registered."""

    def __init__(self, username: str, ticket: Ticket) -> None:
        super().__init__(
            TICKET_CREATION,
            f"Turno {ticket.number} para {ticket.patient.code} "
            f"({ticket.care_type.description()}).",
            username,
            {"patient_code": ticket.patient.code, "ticket_number": ticket.number},
        )
        self._ticket = ticket

    def _revert(self, context: UndoContext) -> None:
        # The counter does not go back, so this number is never given again.
        context.ticket_manager.remove_pending_ticket(self._ticket.number)


class UpdatePatientAction(UndoableAction):
    """Restores the name, age and phone a patient had before an update."""

    def __init__(
        self, username: str, patient: Patient, previous_values: dict
    ) -> None:
        super().__init__(
            PATIENT_UPDATE,
            f"Modificación de los datos de {patient.code} ({patient.full_name}).",
            username,
            {"patient_code": patient.code, "previous_values": dict(previous_values)},
        )
        self._patient = patient
        self._previous = dict(previous_values)

    def _revert(self, context: UndoContext) -> None:
        # Going through the manager validates the values again and saves
        # patients.json. The keys are the ones update_details returned.
        context.patient_manager.update(
            self._patient.code,
            self._previous["full_name"],
            self._previous["age"],
            self._previous["phone"],
        )


class CallNextAction(UndoableAction):
    """Returns a called ticket to Pendiente, at the front of its queue."""

    def __init__(self, username: str, ticket: Ticket) -> None:
        super().__init__(
            CALL_NEXT,
            f"Se llamó al turno {ticket.number} ({ticket.patient.full_name}).",
            username,
            {"ticket_number": ticket.number, "patient_code": ticket.patient.code},
        )
        self._ticket = ticket

    def _revert(self, context: UndoContext) -> None:
        context.ticket_manager.return_to_front(self._ticket)


class FinishCareAction(UndoableAction):
    """Returns a served ticket to En atención and deletes its care record."""

    def __init__(self, username: str, ticket: Ticket, record: CareRecord) -> None:
        super().__init__(
            CARE_FINISHED,
            f"Se finalizó la atención del turno {ticket.number} "
            f"({ticket.patient.full_name}).",
            username,
            {
                "ticket_number": ticket.number,
                "patient_code": ticket.patient.code,
                "served_at": record.served_at,
            },
        )
        self._ticket = ticket
        self._record = record

    def _revert(self, context: UndoContext) -> None:
        context.ticket_manager.revert_finish(self._ticket)


class CancelTicketAction(UndoableAction):
    """Returns a cancelled ticket to Pendiente in the position it had."""

    def __init__(self, username: str, ticket: Ticket, position: int) -> None:
        super().__init__(
            TICKET_CANCELLATION,
            f"Se canceló el turno {ticket.number} ({ticket.patient.full_name}), "
            f"que estaba en la posición {position + 1} de su cola.",
            username,
            {
                "ticket_number": ticket.number,
                "patient_code": ticket.patient.code,
                "position": position,
            },
        )
        self._ticket = ticket
        self._position = position

    @property
    def position(self) -> int:
        """Position the ticket had in its queue, 0 being the front."""
        return self._position

    def _revert(self, context: UndoContext) -> None:
        context.ticket_manager.restore_cancelled(self._ticket, self._position)
