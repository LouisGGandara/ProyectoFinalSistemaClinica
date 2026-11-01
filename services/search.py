"""Ticket search criteria.

Will also contain the CRITERIA dictionary and the function search(tickets, criterion_name, text).
Implemented in step C11.
"""

from abc import ABC


class SearchCriterion(ABC):
    """Abstract search criterion that decides whether a ticket matches a text."""

    pass


class ByPatientCode(SearchCriterion):
    """Exact match on the patient code."""

    pass


class ByPatientName(SearchCriterion):
    """Partial match on the patient name, ignoring case and accents."""

    pass


class ByTicketNumber(SearchCriterion):
    """Exact match on the ticket number."""

    pass


class ByStatus(SearchCriterion):
    """Match on the ticket status."""

    pass


class ByCareType(SearchCriterion):
    """Match on the care type."""

    pass
