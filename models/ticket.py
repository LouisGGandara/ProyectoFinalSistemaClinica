"""Ticket generated for a patient.

Every attribute is read only from outside. The status changes only through
start_care(), finish_care() and cancel(), which follow the table of section
3.4, and through revert_to(), which the undo actions use to go one step back.
"""

import re

from models.care_type import CareType, make_care_type
from models.patient import Patient
from models.ticket_status import TicketStatus
from utils.dates import now_text, parse_date
from utils.exceptions import NotUndoableError, ValidationError
from utils.validator import Validator


class Ticket:
    """Ticket with number, patient, care type, reason, dates and status."""

    NUMBER_DIGITS = 3

    # Each state a ticket can leave by undoing, and the state it goes back to.
    # It is the table of section 3.4 read backwards.
    _PREVIOUS_STATUS = {
        TicketStatus.IN_PROGRESS: TicketStatus.PENDING,
        TicketStatus.SERVED: TicketStatus.IN_PROGRESS,
        TicketStatus.CANCELLED: TicketStatus.PENDING,
    }

    def __init__(
        self,
        number: str,
        patient: Patient,
        care_type: CareType,
        reason: str,
        created_at: str | None = None,
        status: TicketStatus = TicketStatus.PENDING,
        served_at: str | None = None,
    ) -> None:
        self._care_type = care_type
        self._number = self._check_number(number, care_type)
        self._patient = patient
        self._reason = Validator.reason(reason)
        if created_at is None:
            self._created_at = now_text()
        else:
            parse_date(created_at)
            self._created_at = created_at
        if not isinstance(status, TicketStatus):
            raise ValidationError(f"El estado «{status}» no es válido.")
        self._status = status
        self._served_at = self._check_served_at(served_at)

    @staticmethod
    def format_number(prefix: str, sequence: int) -> str:
        """Join prefix and counter as in section 3.5: ("N", 4) gives "N-004"."""
        return f"{prefix}-{sequence:0{Ticket.NUMBER_DIGITS}d}"

    @staticmethod
    def _check_number(number: str, care_type: CareType) -> str:
        # The prefix has to match the care type. Otherwise a hand-edited
        # tickets.json could put a P ticket in the normal queue.
        text = "" if number is None else str(number).strip().upper()
        pattern = rf"{care_type.prefix}-[0-9]{{{Ticket.NUMBER_DIGITS},}}"
        if not re.fullmatch(pattern, text):
            raise ValidationError(
                f"El número de turno «{number}» no es válido para atención "
                f"{care_type.name}. Debe ser como "
                f"{Ticket.format_number(care_type.prefix, 1)}."
            )
        return text

    def _check_served_at(self, served_at: str | None) -> str | None:
        # Only a served ticket has a care date, and it always has one.
        if self._status is TicketStatus.SERVED:
            if served_at is None:
                raise ValidationError(
                    f"El turno {self._number} está Atendido "
                    "pero no tiene fecha de atención."
                )
            parse_date(served_at)
            return served_at
        if served_at is not None:
            raise ValidationError(
                f"El turno {self._number} tiene fecha de atención "
                f"pero su estado es {self._status.value}."
            )
        return None

    @property
    def number(self) -> str:
        """Ticket number, such as N-001. Never reused (RN-04)."""
        return self._number

    @property
    def patient(self) -> Patient:
        """Patient the ticket belongs to. The patient exists on its own."""
        return self._patient

    @property
    def care_type(self) -> CareType:
        """Care type chosen for this visit."""
        return self._care_type

    @property
    def reason(self) -> str:
        """Reason for this visit."""
        return self._reason

    @property
    def created_at(self) -> str:
        """Date and time the ticket was generated."""
        return self._created_at

    @property
    def status(self) -> TicketStatus:
        """Current status. It has no setter: use the methods below."""
        return self._status

    @property
    def served_at(self) -> str | None:
        """Date and time the care finished, or None if it has not."""
        return self._served_at

    @property
    def sequence(self) -> int:
        """Numeric part of the number: 3 for P-003. Sorting by it gives arrival order."""
        return int(self._number.split("-")[1])

    @property
    def is_active(self) -> bool:
        """True while the ticket is Pendiente or En atención."""
        return self._status.is_active

    def start_care(self) -> None:
        """Move from Pendiente to En atención."""
        if self._status is not TicketStatus.PENDING:
            raise ValidationError(
                f"Solo se puede atender un turno pendiente. "
                f"El turno {self._number} está {self._status.value}."
            )
        self._status = TicketStatus.IN_PROGRESS

    def finish_care(self) -> None:
        """Move from En atención to Atendido and record the care date."""
        if self._status is not TicketStatus.IN_PROGRESS:
            raise ValidationError(
                f"Solo se puede finalizar un turno en atención. "
                f"El turno {self._number} está {self._status.value}."
            )
        self._status = TicketStatus.SERVED
        self._served_at = now_text()

    def cancel(self) -> None:
        """Move from Pendiente to Cancelado (RN-05)."""
        if self._status is not TicketStatus.PENDING:
            raise ValidationError("Solo se pueden cancelar turnos pendientes.")
        self._status = TicketStatus.CANCELLED

    def revert_to(self, status: TicketStatus) -> None:
        """Go back one step of section 3.4. Only the undo actions call this.

        It accepts only the state the ticket had before its last change, so
        an undo cannot jump, for example, from Atendido straight to Pendiente.
        Leaving Atendido erases the care date.
        """
        if self._PREVIOUS_STATUS.get(self._status) is not status:
            raise NotUndoableError(
                f"El turno {self._number} no puede volver de "
                f"{self._status.value} a {status.value}."
            )
        self._status = status
        self._served_at = None

    def to_dict(self) -> dict:
        """Return the row saved in tickets.json.

        It stores the patient code, not the whole patient: the patient's data
        lives in patients.json, so a later change of name or phone is saved
        in one place.
        """
        data = {
            "number": self._number,
            "patient_code": self._patient.code,
        }
        data.update(self._care_type.to_dict())
        data.update(
            {
                "reason": self._reason,
                "created_at": self._created_at,
                "status": self._status.value,
                "served_at": self._served_at,
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: dict, patients_by_code: dict) -> "Ticket":
        """Build a ticket from a row of tickets.json.

        patients_by_code relates each code to its Patient, so the ticket points
        to the same object PatientManager holds. The age rule of Adulto mayor
        is not checked here: it applies when the ticket is created, and a
        later fix to the patient's age must not make the file unreadable.
        """
        try:
            number = data["number"]
            patient_code = data["patient_code"]
            care_type = make_care_type(data["care_type"], data.get("criterion"))
            status_text = data["status"]
            reason = data["reason"]
            created_at = data["created_at"]
        except KeyError as error:
            raise ValidationError(
                f"Falta el dato «{error.args[0]}» de un turno en tickets.json."
            ) from error

        # str() for the same reason as user_from_dict: a list or an object
        # written by hand would make the lookup raise TypeError.
        patient = patients_by_code.get(str(patient_code))
        if patient is None:
            raise ValidationError(
                f"El turno {number} es del paciente {patient_code}, "
                "que no existe en patients.json."
            )
        try:
            status = TicketStatus(status_text)
        except ValueError as error:
            raise ValidationError(
                f"El turno {number} tiene un estado desconocido: «{status_text}»."
            ) from error

        return cls(
            number,
            patient,
            care_type,
            reason,
            created_at,
            status,
            data.get("served_at"),
        )

    def __str__(self) -> str:
        return f"{self._number} - {self._patient.full_name} ({self._status.value})"
