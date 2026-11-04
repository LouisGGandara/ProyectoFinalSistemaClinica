"""Ticket management: the two queues, ticket creation, care, cancellation and care records.

Step C8 added creating tickets, loading and saving them, and the read-only
queries. Step C9 adds calling the next ticket, finishing and cancelling, and
four methods that only the undo actions use.

The manager keeps three views of the same Ticket objects: the dictionary
_tickets with every ticket by number, and the two queues with the pending
ones in arrival order. A ticket in a queue is the same object as the one in
the dictionary, so a status change shows in both places.

Every method that changes data checks first and changes after. If a check
fails, the queues, the statuses and the files stay as they were.
"""

import re

from models.care_record import CareRecord
from models.care_type import NORMAL, PRIORITY, CareType
from models.patient import Patient
from models.ticket import Ticket
from models.ticket_status import TicketStatus
from persistence.json_repository import JsonRepository
from structures.ticket_queue import TicketQueue
from utils.exceptions import (
    CorruptedFileError,
    EmptyQueueError,
    NotFoundError,
    NotUndoableError,
    ValidationError,
)
from utils.validator import Validator


class TicketManager:
    """Keeps the tickets, the priority and normal queues and the care records."""

    TICKETS_FILE = "tickets.json"
    CARE_RECORDS_FILE = "care_records.json"
    # Holds one row, {"next_sequence": N}. Without it the counter would be
    # rebuilt from the tickets alone, and the number of a ticket removed by
    # undo would come back after reopening the program (RN-04, test E2-30).
    COUNTER_FILE = "ticket_counter.json"
    COUNTER_KEY = "next_sequence"

    # Any prefix letter, a dash and the counter, such as N-004 or P-1000.
    _NUMBER_PATTERN = re.compile(r"[A-Z]-([0-9]+)")

    def __init__(self, repository: JsonRepository) -> None:
        self._repository = repository
        self._priority_queue = TicketQueue(PRIORITY)
        self._normal_queue = TicketQueue(NORMAL)
        self._tickets: dict[str, Ticket] = {}
        self._care_records: list[CareRecord] = []
        # Sequence the next ticket will get. It is global, so N and P
        # tickets never share a number (section 3.5).
        self._counter = 1
        self._in_progress: Ticket | None = None

    # ------------------------------------------------------------- loading

    def load(self, patients_by_code: dict) -> None:
        """Read both files, rebuild the queues and recover the ticket in care.

        The queues are not saved as such. They are rebuilt with the Pendiente
        tickets sorted by sequence, which is the order they arrived in.
        The counter is the larger of two values: the one saved in
        ticket_counter.json and the highest number in use plus one.

        If one file is damaged, the other one still loads and
        CorruptedFileError is raised at the end, so ClinicSystem can warn
        the user. Raises ValidationError if a row is wrong, a number repeats,
        a patient has two active tickets or more than one ticket is
        En atención, which only happens when tickets.json was edited by hand.
        """
        self._reset()

        damaged: list[str] = []
        ticket_rows = self._load_rows(self.TICKETS_FILE, damaged)
        record_rows = self._load_rows(self.CARE_RECORDS_FILE, damaged)

        tickets = self._build_tickets(ticket_rows, patients_by_code)
        records = [CareRecord.from_dict(row) for row in record_rows]
        in_progress = self._check_active(tickets)

        # Everything is checked before the manager changes, so an error
        # above leaves it empty instead of half loaded.
        self._tickets = {ticket.number: ticket for ticket in tickets}
        self._care_records = records
        self._in_progress = in_progress
        for ticket in tickets:
            if ticket.status is TicketStatus.PENDING:
                self._queue_for(ticket.care_type).enqueue(ticket)
        # Read last, after every check above passed, so a start that stops
        # on a hand-edited tickets.json does not create this file.
        saved_counter = self._load_counter(damaged)
        self._counter = max(
            saved_counter, self._highest_sequence(tickets, records) + 1
        )

        if damaged:
            raise self._damaged_error(damaged)

    def _reset(self) -> None:
        """Empty every list, queue and counter before loading."""
        self._priority_queue = TicketQueue(PRIORITY)
        self._normal_queue = TicketQueue(NORMAL)
        self._tickets = {}
        self._care_records = []
        self._counter = 1
        self._in_progress = None

    def _load_rows(self, filename: str, damaged: list[str]) -> list:
        """Read one file, or note it as damaged and return an empty list."""
        try:
            return self._repository.load(filename)
        except CorruptedFileError:
            damaged.append(filename)
            return []

    def _build_tickets(self, rows: list, patients_by_code: dict) -> list[Ticket]:
        """Turn the rows into tickets sorted by sequence, rejecting repeated numbers.

        The check uses the sequence and not the whole number, because N-004
        and P-004 would also break the global counter.
        """
        by_sequence: dict[int, Ticket] = {}
        for row in rows:
            ticket = Ticket.from_dict(row, patients_by_code)
            other = by_sequence.get(ticket.sequence)
            if other is not None:
                if other.number == ticket.number:
                    message = f"El turno {ticket.number} ya existe."
                else:
                    message = (
                        f"Los turnos {other.number} y {ticket.number} "
                        "usan el mismo número."
                    )
                raise ValidationError(f"{message} Revisa {self.TICKETS_FILE}.")
            by_sequence[ticket.sequence] = ticket
        return [by_sequence[sequence] for sequence in sorted(by_sequence)]

    def _check_active(self, tickets: list[Ticket]) -> Ticket | None:
        """Apply RN-07 and RN-08 to the loaded tickets and return the one in care."""
        active_by_patient: dict[str, Ticket] = {}
        in_progress: Ticket | None = None
        for ticket in tickets:
            if not ticket.is_active:
                continue
            code = ticket.patient.code
            if code in active_by_patient:
                raise ValidationError(
                    f"El paciente {code} tiene dos turnos activos: "
                    f"{active_by_patient[code].number} y {ticket.number}. "
                    f"Revisa {self.TICKETS_FILE}."
                )
            active_by_patient[code] = ticket
            if ticket.status is TicketStatus.IN_PROGRESS:
                if in_progress is not None:
                    raise ValidationError(
                        f"Los turnos {in_progress.number} y {ticket.number} "
                        f"están En atención a la vez. Revisa {self.TICKETS_FILE}."
                    )
                in_progress = ticket
        return in_progress

    def _highest_sequence(
        self, tickets: list[Ticket], records: list[CareRecord]
    ) -> int:
        """Return the highest sequence used by a ticket or a care record.

        The care records count too. If tickets.json was damaged and started
        empty, the served tickets still live in care_records.json, and their
        numbers must not come back (RN-04).
        """
        highest = max((ticket.sequence for ticket in tickets), default=0)
        for record in records:
            match = self._NUMBER_PATTERN.fullmatch(str(record.ticket_number))
            if match is None:
                raise ValidationError(
                    f"El número de turno «{record.ticket_number}» no es válido. "
                    f"Revisa {self.CARE_RECORDS_FILE}."
                )
            highest = max(highest, int(match.group(1)))
        return highest

    def _load_counter(self, damaged: list[str]) -> int:
        """Return the next sequence saved in ticket_counter.json, or 1 if there is none.

        A missing or empty file gives 1, so the counter comes only from the
        tickets, as before this file existed. A damaged file is noted like
        the other two. A row with a value that is not a whole number of 1 or
        more raises ValidationError, which stops the start.
        """
        rows = self._load_rows(self.COUNTER_FILE, damaged)
        if not rows:
            return 1
        value = rows[0].get(self.COUNTER_KEY)
        # bool is a subclass of int, so true would otherwise pass as 1.
        is_whole_number = isinstance(value, int) and not isinstance(value, bool)
        if len(rows) != 1 or not is_whole_number or value < 1:
            raise ValidationError(
                f"El contador de turnos no es válido. Revisa {self.COUNTER_FILE}."
            )
        return value

    @staticmethod
    def _damaged_error(filenames: list[str]) -> CorruptedFileError:
        """Build one warning that names every damaged file."""
        if len(filenames) == 1:
            return CorruptedFileError(filenames[0])
        names = " y ".join(filenames)
        return CorruptedFileError(
            names,
            f"Los archivos {names} están dañados o no están en UTF-8. "
            "Se guardó una copia de cada uno y el sistema siguió con esas "
            "listas vacías.",
        )

    # ------------------------------------------------------------ creating

    def _next_number(self, care_type: CareType) -> str:
        """Return the number for a new ticket of this type and advance the counter.

        create_ticket calls it only after every check has passed, so a
        rejected ticket does not use up a number.
        """
        number = Ticket.format_number(care_type.prefix, self._counter)
        self._counter += 1
        return number

    def _queue_for(self, care_type: CareType) -> TicketQueue:
        """Return the queue for this care type.

        It asks the care type whether it is priority and never checks its
        class, so a new CareType subclass lands in the right queue without
        changing this method.
        """
        if care_type.is_priority:
            return self._priority_queue
        return self._normal_queue

    def create_ticket(
        self, patient: Patient, care_type: CareType, reason: str
    ) -> Ticket:
        """Create a Pendiente ticket, put it at the back of its queue and save.

        Checks, in this order: the reason, the care type against the
        patient (Adulto mayor needs 60 years or more) and RN-07. Raises
        ValidationError if any of them fails, and nothing changes.
        """
        clean_reason = Validator.reason(reason)
        care_type.validate_for(patient)
        active = self.active_ticket_of(patient.code)
        if active is not None:
            raise ValidationError(
                f"Este paciente ya tiene el turno {active.number} activo."
            )

        ticket = Ticket(self._next_number(care_type), patient, care_type, clean_reason)
        self._tickets[ticket.number] = ticket
        self._queue_for(care_type).enqueue(ticket)
        self._save()
        return ticket

    # ------------------------------------------------------------- queries

    def active_ticket_of(self, patient_code: str) -> Ticket | None:
        """Return the patient's Pendiente or En atención ticket, or None."""
        code = str(patient_code).strip().upper()
        for ticket in self._tickets.values():
            if ticket.is_active and ticket.patient.code == code:
                return ticket
        return None

    def get(self, number: str) -> Ticket:
        """Return the ticket with this number, or raise NotFoundError."""
        key = str(number).strip().upper()
        ticket = self._tickets.get(key)
        if ticket is None:
            raise NotFoundError(f"No existe el turno {key}.")
        return ticket

    def get_status(self, number: str) -> TicketStatus:
        """Return the status of a ticket (RF-18), or raise NotFoundError."""
        return self.get(number).status

    def peek_next(self) -> Ticket | None:
        """Return the ticket that will be called next without taking it out.

        The front of the priority queue goes first (RN-01). If that queue is
        empty, it is the front of the normal queue. None means nobody waits.
        """
        for queue in (self._priority_queue, self._normal_queue):
            if not queue.is_empty():
                return queue.peek()
        return None

    def pending_priority(self) -> list[Ticket]:
        """Copy of the priority queue in arrival order."""
        return self._priority_queue.list_all()

    def pending_normal(self) -> list[Ticket]:
        """Copy of the normal queue in arrival order."""
        return self._normal_queue.list_all()

    def priority_count(self) -> int:
        """Number of tickets waiting in the priority queue."""
        return self._priority_queue.count()

    def normal_count(self) -> int:
        """Number of tickets waiting in the normal queue."""
        return self._normal_queue.count()

    def queues_empty(self) -> bool:
        """True when nobody waits in either queue (RF-26)."""
        return self._priority_queue.is_empty() and self._normal_queue.is_empty()

    def list_tickets(self) -> list[Ticket]:
        """Every ticket in any status, sorted by sequence."""
        return sorted(self._tickets.values(), key=lambda ticket: ticket.sequence)

    @property
    def in_progress(self) -> Ticket | None:
        """Ticket En atención right now, or None if the office is free."""
        return self._in_progress

    def list_care_records(self) -> list[CareRecord]:
        """Care records from the most recent to the oldest (RF-35).

        The list is kept in the order the cares finished, so reversing it
        is enough. It is a new list, so the interface cannot change the
        manager's copy.
        """
        return list(reversed(self._care_records))

    # ------------------------------------------------ care and cancellation

    def call_next(self) -> Ticket:
        """Take the next ticket out of its queue, move it to En atención and save.

        RN-08 is checked first: while a ticket is En atención nobody else is
        called. Then the priority queue goes first (RN-01), and inside each
        queue the front is the oldest ticket (RN-02).
        Raises ValidationError if a ticket is already En atención and
        EmptyQueueError if both queues are empty.
        """
        if self._in_progress is not None:
            raise ValidationError(
                f"Finaliza la atención de {self._in_progress.number} "
                "antes de llamar al siguiente."
            )
        if self.queues_empty():
            raise EmptyQueueError()

        # The same order as peek_next, so the ticket the screen shows as
        # "Siguiente" is the one that gets called.
        if self._priority_queue.is_empty():
            queue = self._normal_queue
        else:
            queue = self._priority_queue
        ticket = queue.dequeue()
        ticket.start_care()
        self._in_progress = ticket
        self._save()
        return ticket

    def finish_care(self, username: str) -> CareRecord:
        """Move the ticket in care to Atendido, record who served it and save.

        The record goes at the end of the care list, so the list stays in
        the order the cares finished. Raises ValidationError if no ticket
        is En atención.
        """
        ticket = self._in_progress
        if ticket is None:
            raise ValidationError("No hay ningún turno en atención.")

        ticket.finish_care()
        record = CareRecord.from_ticket(ticket, username)
        self._care_records.append(record)
        self._in_progress = None
        self._save()
        return record

    def cancel_ticket(self, number) -> int:
        """Cancel a Pendiente ticket, take it out of its queue and save.

        Returns the position the ticket had in its queue, 0 being the front.
        CancelTicketAction keeps it so the undo can put the ticket back in
        the same place. Raises NotFoundError if the number does not exist
        and ValidationError if the ticket is not Pendiente (RN-05).
        """
        ticket = self.get(number)
        # Ticket.cancel() checks RN-05 and raises before changing anything.
        # Once it passes, the ticket was Pendiente, and every Pendiente
        # ticket is in its queue, so remove() finds it.
        ticket.cancel()
        position = self._queue_for(ticket.care_type).remove(ticket)
        self._save()
        return position

    # ------------------------------------------------------- undo helpers
    #
    # Only the undo actions of step C10 call these methods. The undo stack
    # reverts actions from the newest to the oldest, so when one of them
    # runs, everything done after its action has already been reverted.
    # The checks below raise NotUndoableError if that is not the case,
    # for example if tickets.json was reloaded in between.

    def remove_pending_ticket(self, number) -> None:
        """Delete a Pendiente ticket: out of its queue and out of the dictionary.

        It reverts "Registrar paciente" and "Generar turno". The counter does
        not go back, so the number is not given again while the program runs
        (section 3.5).
        """
        ticket = self.get(number)
        if ticket.status is not TicketStatus.PENDING:
            raise NotUndoableError(
                f"El turno {ticket.number} ya no está Pendiente, "
                "así que no se puede eliminar."
            )
        self._queue_for(ticket.care_type).remove(ticket)
        del self._tickets[ticket.number]
        self._save()

    def return_to_front(self, ticket: Ticket) -> None:
        """Put the ticket in care back to Pendiente, at the front of its queue.

        It reverts "Atender siguiente". The ticket was first in line when it
        was called, so the front is where it belongs. The office is free again.
        """
        if ticket is not self._in_progress:
            raise NotUndoableError(
                f"El turno {ticket.number} no es el que está en atención."
            )
        ticket.revert_to(TicketStatus.PENDING)
        self._queue_for(ticket.care_type).push_front(ticket)
        self._in_progress = None
        self._save()

    def restore_cancelled(self, ticket: Ticket, position: int) -> None:
        """Put a Cancelado ticket back to Pendiente in the position it had.

        It reverts "Cancelar turno". position is the number cancel_ticket
        returned. Raises ValidationError if that position no longer exists
        in the queue.
        """
        if ticket.status is not TicketStatus.CANCELLED:
            raise NotUndoableError(
                f"El turno {ticket.number} no está Cancelado."
            )
        active = self.active_ticket_of(ticket.patient.code)
        if active is not None:
            # Restoring would leave the patient with two active tickets (RN-07).
            raise NotUndoableError(
                f"El paciente ya tiene el turno {active.number} activo."
            )
        # insert_at goes before revert_to: if the position is wrong it
        # raises, and the ticket is still Cancelado.
        self._queue_for(ticket.care_type).insert_at(position, ticket)
        ticket.revert_to(TicketStatus.PENDING)
        self._save()

    def revert_finish(self, ticket: Ticket) -> None:
        """Put an Atendido ticket back in care and delete its care record.

        It reverts "Finalizar atención". RN-08 still applies, so it raises
        NotUndoableError if another ticket is En atención.
        """
        if ticket.status is not TicketStatus.SERVED:
            raise NotUndoableError(
                f"El turno {ticket.number} no está Atendido."
            )
        if self._in_progress is not None:
            raise NotUndoableError(
                f"Finaliza la atención de {self._in_progress.number} "
                "antes de deshacer."
            )
        index = self._record_index(ticket.number)
        del self._care_records[index]
        ticket.revert_to(TicketStatus.IN_PROGRESS)
        self._in_progress = ticket
        self._save()

    def _record_index(self, ticket_number: str) -> int:
        """Position of the ticket's care record, searching from the newest.

        Raises NotUndoableError if the record is missing, which only happens
        when care_records.json was edited by hand.
        """
        for index in range(len(self._care_records) - 1, -1, -1):
            if self._care_records[index].ticket_number == ticket_number:
                return index
        raise NotUndoableError(
            f"No se encontró el registro de atención del turno {ticket_number}."
        )

    # -------------------------------------------------------------- saving

    def _save(self) -> None:
        """Write tickets.json, care_records.json and ticket_counter.json."""
        self._repository.save(
            self.TICKETS_FILE, [ticket.to_dict() for ticket in self.list_tickets()]
        )
        self._repository.save(
            self.CARE_RECORDS_FILE,
            [record.to_dict() for record in self._care_records],
        )
        self._repository.save(
            self.COUNTER_FILE, [{self.COUNTER_KEY: self._counter}]
        )
