"""Clinic statistics (RF-37 to RF-39).

ClinicStats keeps no counts of its own. compute() counts again from the
managers each time it is called, so the numbers cannot fall out of step with
the data after a registration, a cancellation or an undo.
"""

from models.ticket_status import TicketStatus
from services.patient_manager import PatientManager
from services.ticket_manager import TicketManager


class ClinicStats:
    """Computes the counts shown in the statistics tab."""

    def __init__(
        self, patient_manager: PatientManager, ticket_manager: TicketManager
    ) -> None:
        self._patient_manager = patient_manager
        self._ticket_manager = ticket_manager

    def compute(self) -> dict:
        """Return every count of RF-37 and RF-38 in one dictionary.

        Keys: registered_patients, pending, in_progress, served, cancelled,
        normal, priority, normal_queue and priority_queue.

        normal and priority count tickets of that type in any status, so a
        served or cancelled ticket still counts. normal_queue and
        priority_queue count only the tickets waiting right now.
        """
        tickets = self._ticket_manager.list_tickets()

        by_status = {status: 0 for status in TicketStatus}
        priority = 0
        for ticket in tickets:
            by_status[ticket.status] += 1
            # The care type answers whether it is priority, the same way
            # TicketManager._queue_for picks the queue.
            if ticket.care_type.is_priority:
                priority += 1

        return {
            "registered_patients": self._patient_manager.count(),
            "pending": by_status[TicketStatus.PENDING],
            "in_progress": by_status[TicketStatus.IN_PROGRESS],
            "served": by_status[TicketStatus.SERVED],
            "cancelled": by_status[TicketStatus.CANCELLED],
            "normal": len(tickets) - priority,
            "priority": priority,
            "normal_queue": self._ticket_manager.normal_count(),
            "priority_queue": self._ticket_manager.priority_count(),
        }
