"""Possible states of a ticket.

The values are the Spanish labels the user sees (section 3.12), so the
interface and tickets.json use TicketStatus.PENDING.value as is.
"""

from enum import Enum


class TicketStatus(Enum):
    """Ticket states: Pendiente, En atención, Atendido and Cancelado."""

    PENDING = "Pendiente"
    IN_PROGRESS = "En atención"
    SERVED = "Atendido"
    CANCELLED = "Cancelado"

    @property
    def is_active(self) -> bool:
        """True for Pendiente and En atención, the states RN-07 counts."""
        return self in (TicketStatus.PENDING, TicketStatus.IN_PROGRESS)
