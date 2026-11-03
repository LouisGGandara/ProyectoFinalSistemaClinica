"""Care types of a ticket: normal or priority.

The rest of the system works with CareType and never asks which subclass it
has. The queue comes from is_priority, the ticket prefix from prefix, and the
extra checks from validate_for(), which each subclass answers in its own way.
"""

from abc import ABC, abstractmethod

from models.patient import Patient
from utils.exceptions import ValidationError

NORMAL = "Normal"
PRIORITY = "Prioritaria"
# Order shown in the care type Combobox of the interface.
CARE_TYPE_NAMES = (NORMAL, PRIORITY)


class CareType(ABC):
    """Abstract care type that decides the queue and the ticket prefix."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Spanish name shown to the user and saved in tickets.json."""

    @property
    @abstractmethod
    def prefix(self) -> str:
        """Letter that starts the ticket number, such as the N of N-001."""

    @property
    @abstractmethod
    def is_priority(self) -> bool:
        """True if tickets of this type go to the priority queue."""

    def validate_for(self, patient: Patient) -> None:
        """Raise ValidationError if this care type does not fit the patient.

        Normal care has no conditions, so the base version accepts everyone.
        """

    def description(self) -> str:
        """Return the text shown in the tables, such as "Normal"."""
        return self.name

    def to_dict(self) -> dict:
        """Return the care type fields of a row of tickets.json."""
        return {"care_type": self.name, "criterion": None}

    def __str__(self) -> str:
        return self.description()


class NormalCare(CareType):
    """Normal care, prefix N."""

    @property
    def name(self) -> str:
        return NORMAL

    @property
    def prefix(self) -> str:
        return "N"

    @property
    def is_priority(self) -> bool:
        return False


class PriorityCare(CareType):
    """Priority care, prefix P, with one of the criteria of section 3.2."""

    CRITERIA = ("Adulto mayor", "Embarazo", "Discapacidad", "Urgencia")
    SENIOR = "Adulto mayor"
    SENIOR_AGE = 60

    def __init__(self, criterion: str) -> None:
        text = "" if criterion is None else str(criterion).strip()
        if not text:
            raise ValidationError("Selecciona el criterio de prioridad.")
        if text not in self.CRITERIA:
            raise ValidationError(
                f"El criterio «{text}» no existe. "
                f"Usa uno de estos: {', '.join(self.CRITERIA)}."
            )
        self._criterion = text

    @property
    def criterion(self) -> str:
        """Reason for the priority. Read only: a new criterion means a new ticket."""
        return self._criterion

    @property
    def name(self) -> str:
        return PRIORITY

    @property
    def prefix(self) -> str:
        return "P"

    @property
    def is_priority(self) -> bool:
        return True

    def validate_for(self, patient: Patient) -> None:
        """Require SENIOR_AGE years or more for the Adulto mayor criterion.

        Embarazo, Discapacidad and Urgencia have no condition the system can
        check, so they are accepted as chosen.
        """
        if self._criterion == self.SENIOR and patient.age < self.SENIOR_AGE:
            raise ValidationError(
                f"El criterio Adulto mayor requiere {self.SENIOR_AGE} años o más."
            )

    def description(self) -> str:
        """Return the type with its criterion, such as "Prioritaria (Embarazo)"."""
        return f"{self.name} ({self._criterion})"

    def to_dict(self) -> dict:
        return {"care_type": self.name, "criterion": self._criterion}


def make_care_type(name: str, criterion: str | None = None) -> CareType:
    """Build the care type the user chose in the form or saved in tickets.json.

    The criterion only counts for Prioritaria. With Normal it is ignored, so
    a value left in the disabled criterion Combobox does no harm.
    """
    text = "" if name is None else str(name).strip()
    if not text:
        raise ValidationError("Selecciona el tipo de atención.")
    if text == NORMAL:
        return NormalCare()
    if text == PRIORITY:
        return PriorityCare(criterion)
    raise ValidationError(f"El tipo de atención «{text}» no existe.")
