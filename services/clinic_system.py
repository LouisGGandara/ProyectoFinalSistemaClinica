"""Facade of the system: the only class of the logic that the interface uses.

ClinicSystem creates the repository, the managers, the action history and
the statistics, and loads everything when it starts. The interface calls its
methods and never touches a manager, a queue or a file.

Every operation that changes data follows the same order:
1. require the permission of the current user,
2. validate the data,
3. run the operation in the manager (which saves the JSON files),
4. register the action in the history.

The permission check lives here and not only in the interface (RNF-08).
A hidden button is not enough if some other code can still call the method.
"""

from models.actions import (
    LOGIN,
    LOGOUT,
    USER_MANAGEMENT,
    Action,
    CallNextAction,
    CancelTicketAction,
    CreateTicketAction,
    FinishCareAction,
    LogOnlyAction,
    RegisterPatientAction,
    UpdatePatientAction,
)
from models.care_record import CareRecord
from models.care_type import CARE_TYPE_NAMES, PriorityCare, make_care_type
from models.patient import Patient
from models.permissions import Permission
from models.ticket import Ticket
from models.user import ROLES, User
from persistence.json_repository import JsonRepository
from services.action_history import ActionHistory
from services.patient_manager import PatientManager
from services.search import CRITERIA, search
from services.stats import ClinicStats
from services.ticket_manager import TicketManager
from services.user_manager import UserManager
from utils.exceptions import (
    CorruptedFileError,
    DuplicateError,
    PermissionDeniedError,
    ValidationError,
)
from utils.validator import Validator


class ClinicSystem:
    """Joins the managers, checks permissions, records actions and saves the data."""

    def __init__(self, data_folder: str = "data") -> None:
        """Create every part of the logic and load the JSON files.

        A damaged file does not stop the start: its manager begins with an
        empty list and the message goes to warnings, for the interface to
        show. A file that reads fine but has wrong data, such as a ticket
        number written twice by hand, raises ValidationError instead. Going
        on with an empty list would overwrite that file on the next save, so
        the system refuses to start until someone fixes it.
        StorageError (a folder or file that cannot be read) is raised too.
        """
        self._repository = JsonRepository(data_folder)
        self._user_manager = UserManager(self._repository)
        self._patient_manager = PatientManager(self._repository)
        self._ticket_manager = TicketManager(self._repository)
        self._history = ActionHistory()
        self._stats = ClinicStats(self._patient_manager, self._ticket_manager)
        self._current_user: User | None = None
        self._warnings: list[str] = []
        self._load_all()

    def _load_all(self) -> None:
        """Load users, patients and tickets, in that order.

        Tickets go last because they need the patients to point to.
        """
        loaders = (
            self._user_manager.load,
            self._patient_manager.load,
            lambda: self._ticket_manager.load(
                self._patient_manager.patients_by_code()
            ),
        )
        for load in loaders:
            try:
                load()
            except CorruptedFileError as error:
                self._warnings.append(error.message)
            except ValidationError as error:
                # A damaged patients.json often shows up later as a ticket
                # whose patient is missing, so the earlier warnings travel
                # with the error to explain where it came from.
                raise ValidationError(
                    " ".join([*self._warnings, error.message])
                ) from error

    # ------------------------------------------------- session and permissions

    @property
    def warnings(self) -> list[str]:
        """Messages about damaged files found while loading. Returned as a copy."""
        return list(self._warnings)

    @property
    def patient_manager(self) -> PatientManager:
        """Patient manager. It is public only because undo needs it as context.

        The interface must not use it: going through the manager skips the
        permission checks and the action history.
        """
        return self._patient_manager

    @property
    def ticket_manager(self) -> TicketManager:
        """Ticket manager. Public for the same reason as patient_manager."""
        return self._ticket_manager

    @property
    def current_user(self) -> User | None:
        """User who logged in, or None when nobody has."""
        return self._current_user

    def login(self, username: str, password: str) -> User:
        """Check the credentials, open the session and register the login.

        Raises ValidationError if a session is already open, and the errors
        of UserManager.login when a field is empty or the credentials are wrong.
        A failed attempt is not registered, because there is no user to
        hold responsible for it.
        """
        if self._current_user is not None:
            raise ValidationError(
                "Ya hay una sesión abierta. Cierra sesión antes de entrar "
                "con otro usuario."
            )
        user = self._user_manager.login(username, password)
        self._current_user = user
        self._history.register(
            LogOnlyAction(
                LOGIN,
                f"{user.full_name} inició sesión como {user.role}.",
                user.username,
                {"role": user.role},
            )
        )
        return user

    def logout(self) -> None:
        """Register the logout and close the session.

        The history stays in memory, so the next user who logs in can still
        undo what was done before (section 3.8). With no session open it
        does nothing.
        """
        user = self._current_user
        if user is None:
            return
        self._history.register(
            LogOnlyAction(
                LOGOUT,
                f"{user.full_name} cerró sesión.",
                user.username,
                {"role": user.role},
            )
        )
        self._current_user = None

    def has_permission(self, permission: Permission | None) -> bool:
        """Tell whether the current user has the permission.

        None means the function is open to every role, which is how the
        tabs without required_permission ask (step D3). With no session,
        the answer is always False.
        """
        if self._current_user is None:
            return False
        if permission is None:
            return True
        return self._current_user.has_permission(permission)

    def _require_permission(self, permission: Permission) -> None:
        """Raise PermissionDeniedError unless the current user has the permission."""
        if self._current_user is None:
            raise PermissionDeniedError("Inicia sesión para continuar.")
        if not self._current_user.has_permission(permission):
            raise PermissionDeniedError()

    def _username(self) -> str:
        """Username of the session, for the actions and the care records."""
        return self._current_user.username

    # --------------------------------------------------------------- patients

    def next_code(self) -> str:
        """Code proposed for the next patient, such as PAC-0008 (RF-11)."""
        self._require_permission(Permission.REGISTER_PATIENT)
        return self._patient_manager.next_code()

    @staticmethod
    def care_type_names() -> list[str]:
        """Care types for the Combobox: Normal and Prioritaria."""
        return list(CARE_TYPE_NAMES)

    @staticmethod
    def priority_criteria() -> list[str]:
        """Priority criteria of section 3.2, for the Combobox."""
        return list(PriorityCare.CRITERIA)

    def register_patient(
        self,
        code: str,
        full_name: str,
        age: int | str,
        phone: str,
        reason: str,
        care_type: str,
        criterion: str | None = None,
    ) -> Ticket:
        """Register a patient, create their first ticket and return the ticket.

        Every value is checked before anything is saved, in the order of the
        form, so an error never leaves a patient without a ticket (CP-06 to
        CP-11). The code is checked for duplicates right after its format,
        before the rest of the form.
        """
        self._require_permission(Permission.REGISTER_PATIENT)

        clean_code = Validator.patient_code(code)
        if self._patient_manager.exists(clean_code):
            raise DuplicateError(
                f"Ya existe un paciente con el código {clean_code}."
            )
        patient = Patient(clean_code, full_name, age, phone)
        clean_reason = Validator.reason(reason)
        chosen_type = make_care_type(care_type, criterion)
        chosen_type.validate_for(patient)

        self._patient_manager.register(patient)
        ticket = self._ticket_manager.create_ticket(
            patient, chosen_type, clean_reason
        )
        self._history.register(
            RegisterPatientAction(self._username(), patient, ticket)
        )
        return ticket

    def create_ticket(
        self,
        code: str,
        reason: str,
        care_type: str,
        criterion: str | None = None,
    ) -> Ticket:
        """Create a new ticket for a patient who is already registered (RF-17).

        TicketManager checks the reason, the criterion against the patient's
        age and RN-07 before it changes anything.
        """
        self._require_permission(Permission.CREATE_TICKET)
        patient = self._patient_manager.get(Validator.required(code, "Código"))
        chosen_type = make_care_type(care_type, criterion)
        ticket = self._ticket_manager.create_ticket(patient, chosen_type, reason)
        self._history.register(CreateTicketAction(self._username(), ticket))
        return ticket

    def update_patient(
        self, code: str, full_name: str, age: int | str, phone: str
    ) -> None:
        """Change a patient's name, age and phone (RF-14).

        The previous values go into the action, so undo can restore them.
        """
        self._require_permission(Permission.UPDATE_PATIENT)
        clean_code = Validator.required(code, "Código")
        previous = self._patient_manager.update(clean_code, full_name, age, phone)
        patient = self._patient_manager.get(clean_code)
        self._history.register(
            UpdatePatientAction(self._username(), patient, previous)
        )

    def list_patients(self) -> list[Patient]:
        """Every patient, sorted by code (RF-15)."""
        self._require_permission(Permission.REGISTER_PATIENT)
        return self._patient_manager.list_all()

    # ---------------------------------------------------------------- tickets

    def peek_next(self) -> Ticket | None:
        """Ticket that will be called next, or None if nobody waits (RF-22)."""
        self._require_permission(Permission.VIEW_QUEUES)
        return self._ticket_manager.peek_next()

    def in_progress(self) -> Ticket | None:
        """Ticket En atención right now, or None."""
        self._require_permission(Permission.VIEW_QUEUES)
        return self._ticket_manager.in_progress

    def pending_priority(self) -> list[Ticket]:
        """Priority queue in arrival order (RF-21)."""
        self._require_permission(Permission.VIEW_QUEUES)
        return self._ticket_manager.pending_priority()

    def pending_normal(self) -> list[Ticket]:
        """Normal queue in arrival order (RF-21)."""
        self._require_permission(Permission.VIEW_QUEUES)
        return self._ticket_manager.pending_normal()

    def queues_empty(self) -> bool:
        """True when nobody waits in either queue (RF-26)."""
        self._require_permission(Permission.VIEW_QUEUES)
        return self._ticket_manager.queues_empty()

    def call_next(self) -> Ticket:
        """Call the next ticket, priority first (RF-23), and register the action."""
        self._require_permission(Permission.SERVE)
        ticket = self._ticket_manager.call_next()
        self._history.register(CallNextAction(self._username(), ticket))
        return ticket

    def finish_care(self) -> CareRecord:
        """Finish the care in progress in the name of the current user (RF-24)."""
        self._require_permission(Permission.SERVE)
        # Read before finishing, because finish_care leaves the office free.
        ticket = self._ticket_manager.in_progress
        record = self._ticket_manager.finish_care(self._username())
        self._history.register(FinishCareAction(self._username(), ticket, record))
        return record

    def cancel_ticket(self, number: str) -> None:
        """Cancel a Pendiente ticket (RF-19). Only the administrator may.

        The action keeps the position the ticket had, so undo puts it back
        in the same place. The interface asks for confirmation first.
        """
        self._require_permission(Permission.CANCEL_TICKET)
        ticket = self._ticket_manager.get(
            Validator.required(number, "Número de turno")
        )
        position = self._ticket_manager.cancel_ticket(ticket.number)
        self._history.register(
            CancelTicketAction(self._username(), ticket, position)
        )

    def get_status(self, number: str) -> str:
        """Status of a ticket as the user sees it, such as "Pendiente" (RF-18)."""
        self._require_permission(Permission.VIEW_QUEUES)
        clean_number = Validator.required(number, "Número de turno")
        return self._ticket_manager.get_status(clean_number).value

    # ---------------------------------------------------------------- queries

    def search(self, criterion_name: str, text: str) -> list[Ticket]:
        """Tickets that match the text under the chosen criterion (RF-32).

        An empty list means no matches; the interface shows the message of
        RF-34.
        """
        self._require_permission(Permission.SEARCH)
        return search(self._ticket_manager.list_tickets(), criterion_name, text)

    @staticmethod
    def search_criteria() -> list[str]:
        """Names of the search criteria, in the order the Combobox shows them."""
        return list(CRITERIA)

    def list_care_records(self) -> list[CareRecord]:
        """Finished cares, the most recent first (RF-36)."""
        self._require_permission(Permission.VIEW_CARE_HISTORY)
        return self._ticket_manager.list_care_records()

    def stats(self) -> dict:
        """Counts of RF-37 and RF-38, computed again on every call."""
        self._require_permission(Permission.VIEW_STATS)
        return self._stats.compute()

    # --------------------------------------------------------- action history

    def last_action(self) -> Action:
        """Most recent action of any kind (RF-28)."""
        self._require_permission(Permission.VIEW_ACTION_LOG)
        return self._history.last_action()

    def action_history(self) -> list[Action]:
        """Every action, the most recent first (RF-29)."""
        self._require_permission(Permission.VIEW_ACTION_LOG)
        return self._history.list_all()

    def can_undo(self) -> bool:
        """True if there is an action left to undo, to enable the button."""
        self._require_permission(Permission.UNDO)
        return self._history.can_undo()

    def undo(self) -> Action:
        """Undo the last undoable action and return it (RF-30).

        The system itself is the context of the undo: it has the
        patient_manager and ticket_manager attributes the actions need.
        Raises EmptyStackError when nothing is left to undo (RF-31).
        """
        self._require_permission(Permission.UNDO)
        return self._history.undo_last(self, self._username())

    # ------------------------------------------------------------------ users

    @staticmethod
    def roles() -> list[str]:
        """Role names for the Combobox: Administrador and Recepcionista."""
        return list(ROLES)

    def list_users(self) -> list[User]:
        """Every user, sorted by username (RF-08)."""
        self._require_permission(Permission.MANAGE_USERS)
        return self._user_manager.list_all()

    def create_user(
        self, full_name: str, username: str, password: str, role: str
    ) -> User:
        """Create a user (RF-06). It stays only as evidence in the history."""
        self._require_permission(Permission.MANAGE_USERS)
        user = self._user_manager.create_user(full_name, username, password, role)
        self._history.register(
            LogOnlyAction(
                USER_MANAGEMENT,
                f"Se creó el usuario {user.username} ({user.role}).",
                self._username(),
                {"username": user.username, "role": user.role},
            )
        )
        return user

    def delete_user(self, username: str) -> None:
        """Delete a user other than oneself (RF-07, RN-12). Evidence only."""
        self._require_permission(Permission.MANAGE_USERS)
        clean_username = Validator.required(username, "Usuario")
        self._user_manager.delete_user(clean_username, self._current_user)
        self._history.register(
            LogOnlyAction(
                USER_MANAGEMENT,
                f"Se eliminó el usuario {clean_username}.",
                self._username(),
                {"username": clean_username},
            )
        )
