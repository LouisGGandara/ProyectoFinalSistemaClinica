"""Ticket search criteria (RF-32 to RF-34).

Each criterion compares one piece of a ticket with the text the user typed.
search() looks up the criterion by the name shown in the interface and calls
matches() without checking which class it got. A new criterion is one more
subclass and one more entry in CRITERIA.
"""

import unicodedata
from abc import ABC, abstractmethod

from models.care_type import CARE_TYPE_NAMES
from models.ticket import Ticket
from models.ticket_status import TicketStatus
from utils.exceptions import ValidationError


class SearchCriterion(ABC):
    """Abstract search criterion that decides whether a ticket matches a text."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Spanish name shown in the criterion Combobox."""

    @abstractmethod
    def matches(self, ticket: Ticket, text: str) -> bool:
        """Return True if the ticket fits the text under this criterion."""

    def suggestions(self) -> list[str]:
        """Values the search field can offer as a list for this criterion.

        A code, a name or a ticket number can be anything, so by default
        there is nothing to offer and the user types freely. ByStatus and
        ByCareType override it, because those criteria only match a few
        fixed words.
        """
        return []

    @staticmethod
    def _normalize(text: str) -> str:
        """Lower case, single spaces and no accents: " María  López" gives "maria lopez".

        NFD splits each accented letter into the base letter plus a combining
        mark (category "Mn"), and dropping the marks leaves the base letter.
        The ñ loses its tilde too, so "Pena" also finds "Peña". That helps
        when the keyboard has no ñ at hand.
        """
        decomposed = unicodedata.normalize("NFD", str(text))
        without_marks = "".join(
            char for char in decomposed if unicodedata.category(char) != "Mn"
        )
        return " ".join(without_marks.casefold().split())


class ByPatientCode(SearchCriterion):
    """Exact match on the patient code. "pac-0001" finds PAC-0001."""

    @property
    def name(self) -> str:
        return "Código de paciente"

    def matches(self, ticket: Ticket, text: str) -> bool:
        return self._normalize(ticket.patient.code) == self._normalize(text)


class ByPatientName(SearchCriterion):
    """Partial match on the patient name, ignoring case and accents (RF-33)."""

    @property
    def name(self) -> str:
        return "Nombre"

    def matches(self, ticket: Ticket, text: str) -> bool:
        return self._normalize(text) in self._normalize(ticket.patient.full_name)


class ByTicketNumber(SearchCriterion):
    """Exact match on the ticket number. "n-004" finds N-004."""

    @property
    def name(self) -> str:
        return "Número de turno"

    def matches(self, ticket: Ticket, text: str) -> bool:
        return self._normalize(ticket.number) == self._normalize(text)


class ByStatus(SearchCriterion):
    """Match on the whole status name. "en atencion" finds En atención."""

    @property
    def name(self) -> str:
        return "Estado"

    def matches(self, ticket: Ticket, text: str) -> bool:
        return self._normalize(ticket.status.value) == self._normalize(text)

    def suggestions(self) -> list[str]:
        return [status.value for status in TicketStatus]


class ByCareType(SearchCriterion):
    """Match on the care type name: Normal or Prioritaria."""

    @property
    def name(self) -> str:
        return "Tipo de atención"

    def matches(self, ticket: Ticket, text: str) -> bool:
        return self._normalize(ticket.care_type.name) == self._normalize(text)

    def suggestions(self) -> list[str]:
        return list(CARE_TYPE_NAMES)


# Visible name of each criterion, in the order the Combobox shows them.
# The dictionary is built from the instances, so a name is written only once,
# inside its class.
CRITERIA: dict[str, SearchCriterion] = {
    criterion.name: criterion
    for criterion in (
        ByPatientCode(),
        ByPatientName(),
        ByTicketNumber(),
        ByStatus(),
        ByCareType(),
    )
}


def search(tickets: list[Ticket], criterion_name: str, text: str) -> list[Ticket]:
    """Return the tickets that match the text, in the order they came in.

    An empty list means no matches; the interface shows the RF-34 message.
    Raises ValidationError if no criterion is chosen, the criterion does not
    exist or the text is empty.
    """
    name = "" if criterion_name is None else str(criterion_name).strip()
    if not name:
        raise ValidationError("Selecciona un criterio de búsqueda.")
    criterion = CRITERIA.get(name)
    if criterion is None:
        raise ValidationError(f"El criterio de búsqueda «{name}» no existe.")

    clean_text = "" if text is None else str(text).strip()
    if not clean_text:
        raise ValidationError("Escribe el texto que quieres buscar.")

    return [ticket for ticket in tickets if criterion.matches(ticket, clean_text)]
