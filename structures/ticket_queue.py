"""FIFO queue of tickets built on collections.deque.

TicketManager keeps two of these, one for priority care and one for normal
care. Tickets join at the back with enqueue() and leave from the front with
dequeue(), so each queue keeps its own arrival order (RN-02).
"""

from collections import deque

from models.ticket import Ticket
from utils.exceptions import EmptyQueueError, NotFoundError, ValidationError
from utils.validator import Validator


class TicketQueue:
    """First-in, first-out queue of pending tickets."""

    def __init__(self, name: str) -> None:
        self._name = Validator.required(name, "Nombre de la cola")
        # deque adds and removes at both ends in O(1). A list would pay O(n)
        # on every dequeue, because pop(0) shifts every remaining item.
        self._items: deque[Ticket] = deque()

    @property
    def name(self) -> str:
        """Name shown to the user, for example "Prioritaria" or "Normal"."""
        return self._name

    def enqueue(self, ticket: Ticket) -> None:
        """Add the ticket at the back of the queue."""
        self._items.append(ticket)

    def dequeue(self) -> Ticket:
        """Remove and return the ticket at the front.

        Raises EmptyQueueError if the queue has no tickets.
        """
        self._check_not_empty()
        return self._items.popleft()

    def peek(self) -> Ticket:
        """Return the ticket at the front without removing it.

        Raises EmptyQueueError if the queue has no tickets.
        """
        self._check_not_empty()
        return self._items[0]

    def is_empty(self) -> bool:
        """True when the queue has no tickets."""
        return not self._items

    def count(self) -> int:
        """Number of tickets waiting in the queue."""
        return len(self._items)

    def __len__(self) -> int:
        return self.count()

    def list_all(self) -> list[Ticket]:
        """Copy of the tickets in arrival order, the front first.

        It is a new list, so the interface can sort or change it without
        touching the queue.
        """
        return list(self._items)

    def remove(self, ticket: Ticket) -> int:
        """Take the ticket out of the queue and return the position it had.

        Position 0 is the front. Cancelling a ticket uses this method, and the
        returned position is what lets the undo put it back in the same place.
        Raises NotFoundError if the ticket is not in this queue.
        """
        # The search compares with "is" because the queue holds the same
        # Ticket objects that TicketManager keeps, not copies of them.
        for position, item in enumerate(self._items):
            if item is ticket:
                del self._items[position]
                return position
        raise NotFoundError(
            f"El turno {ticket.number} no está en la cola {self._name}."
        )

    def insert_at(self, position: int, ticket: Ticket) -> None:
        """Put the ticket back at the given position. Only the undo uses it.

        Raises ValidationError if the position is outside 0..count(). deque
        would accept any number and silently move the ticket to one end, which
        would hide a wrong position instead of reporting it.
        """
        if not 0 <= position <= len(self._items):
            raise ValidationError(
                f"La posición {position} no existe en la cola {self._name}."
            )
        self._items.insert(position, ticket)

    def push_front(self, ticket: Ticket) -> None:
        """Put the ticket at the front of the queue. Only the undo uses it.

        Undoing "call next" brings the ticket back here, because it was the
        first in line before it was called.
        """
        self._items.appendleft(ticket)

    def _check_not_empty(self) -> None:
        if not self._items:
            raise EmptyQueueError(
                f"No hay turnos en espera en la cola {self._name}."
            )

    def __repr__(self) -> str:
        numbers = ", ".join(ticket.number for ticket in self._items)
        return f"TicketQueue({self._name!r}: [{numbers}])"
