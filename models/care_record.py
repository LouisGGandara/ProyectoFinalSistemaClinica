"""Row of the history of patients served.

A record copies the data it shows instead of pointing to the ticket and the
patient. It describes a care that already happened, so it keeps the name and
care type as they were at that moment, and care_records.json can be read on
its own.
"""

from models.ticket import Ticket
from models.ticket_status import TicketStatus
from utils.dates import parse_date
from utils.exceptions import ValidationError


class CareRecord:
    """Record of a finished care, with dates and the user who served the patient."""

    def __init__(
        self,
        ticket_number: str,
        patient_code: str,
        patient_name: str,
        care_type: str,
        registered_at: str,
        served_at: str,
        served_by: str,
    ) -> None:
        parse_date(registered_at)
        parse_date(served_at)
        self._ticket_number = ticket_number
        self._patient_code = patient_code
        self._patient_name = patient_name
        self._care_type = care_type
        self._registered_at = registered_at
        self._served_at = served_at
        self._served_by = served_by

    @property
    def ticket_number(self) -> str:
        return self._ticket_number

    @property
    def patient_code(self) -> str:
        return self._patient_code

    @property
    def patient_name(self) -> str:
        return self._patient_name

    @property
    def care_type(self) -> str:
        """Care type as shown in the table, such as "Prioritaria (Embarazo)"."""
        return self._care_type

    @property
    def registered_at(self) -> str:
        """Date the ticket was generated."""
        return self._registered_at

    @property
    def served_at(self) -> str:
        """Date the care finished."""
        return self._served_at

    @property
    def served_by(self) -> str:
        """Username of the person who finished the care."""
        return self._served_by

    @classmethod
    def from_ticket(cls, ticket: Ticket, username: str) -> "CareRecord":
        """Build the record of a ticket whose care just finished.

        The registration date is the date the ticket was generated, since that
        is when the patient arrived for this visit.
        """
        if ticket.status is not TicketStatus.SERVED:
            raise ValidationError(
                f"El turno {ticket.number} todavía no está Atendido."
            )
        return cls(
            ticket.number,
            ticket.patient.code,
            ticket.patient.full_name,
            ticket.care_type.description(),
            ticket.created_at,
            ticket.served_at,
            username,
        )

    def to_dict(self) -> dict:
        """Return the row saved in care_records.json."""
        return {
            "ticket_number": self._ticket_number,
            "patient_code": self._patient_code,
            "patient_name": self._patient_name,
            "care_type": self._care_type,
            "registered_at": self._registered_at,
            "served_at": self._served_at,
            "served_by": self._served_by,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CareRecord":
        """Build a record from a row of care_records.json."""
        try:
            return cls(
                data["ticket_number"],
                data["patient_code"],
                data["patient_name"],
                data["care_type"],
                data["registered_at"],
                data["served_at"],
                data["served_by"],
            )
        except KeyError as error:
            raise ValidationError(
                f"Falta el dato «{error.args[0]}» de una atención "
                "en care_records.json."
            ) from error

    def __str__(self) -> str:
        return f"{self._ticket_number} - {self._patient_name} ({self._served_at})"
