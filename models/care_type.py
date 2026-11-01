"""Care types of a ticket: normal or priority.

Will also contain the function make_care_type(name, criterion). Implemented in step C4.
"""

from abc import ABC


class CareType(ABC):
    """Abstract care type that decides the queue and the ticket prefix."""

    pass


class NormalCare(CareType):
    """Normal care, prefix N."""

    pass


class PriorityCare(CareType):
    """Priority care, prefix P, with a priority criterion."""

    pass
