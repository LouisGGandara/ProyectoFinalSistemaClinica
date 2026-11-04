"""Tests for TicketManager.

Step C8: creating tickets, queues and loading.
Step C9: calling, finishing and cancelling (CP-13 to CP-18) and the four undo
helpers.

Every test works with a JsonRepository inside a tempfile.TemporaryDirectory,
so the real data folder is never touched.

Run from the project root with: python -m unittest discover tests
"""

import json
import tempfile
import unittest
from pathlib import Path

from models.care_type import CareType, NormalCare, PriorityCare
from models.patient import Patient
from models.ticket_status import TicketStatus
from persistence.json_repository import JsonRepository
from services.ticket_manager import TicketManager
from utils.exceptions import (
    CorruptedFileError,
    EmptyQueueError,
    NotFoundError,
    NotUndoableError,
    ValidationError,
)

CREATED = "2026-11-02 08:00:00"
SERVED = "2026-11-02 08:30:00"


def ticket_row(number, code, status="Pendiente", care_type="Normal",
               criterion=None, served_at=None):
    """Row of tickets.json as TicketManager writes it."""
    return {
        "number": number,
        "patient_code": code,
        "care_type": care_type,
        "criterion": criterion,
        "reason": "Control general",
        "created_at": CREATED,
        "status": status,
        "served_at": served_at,
    }


def record_row(number, code="PAC-0001", name="Ana López"):
    """Row of care_records.json."""
    return {
        "ticket_number": number,
        "patient_code": code,
        "patient_name": name,
        "care_type": "Normal",
        "registered_at": CREATED,
        "served_at": SERVED,
        "served_by": "admin",
    }


class TicketManagerTestCase(unittest.TestCase):
    """Creates a repository, five patients and a loaded manager for each test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name) / "data"
        self.repo = JsonRepository(str(self.folder))
        self.patients = {
            "PAC-0001": Patient("PAC-0001", "Ana López", 30, "55551234"),
            "PAC-0002": Patient("PAC-0002", "José Peña", 45, "22223333"),
            "PAC-0003": Patient("PAC-0003", "María Gómez", 72, "44445555"),
            "PAC-0004": Patient("PAC-0004", "Marco Ruiz", 25, "66667777"),
            "PAC-0005": Patient("PAC-0005", "Lucía Pérez", 28, "77778888"),
        }
        self.manager = self.new_manager()

    def tearDown(self):
        self._tmp.cleanup()

    def new_manager(self) -> TicketManager:
        manager = TicketManager(self.repo)
        manager.load(dict(self.patients))
        return manager

    def patient(self, number: int) -> Patient:
        return self.patients[f"PAC-{number:04d}"]

    def create(self, number: int, care_type: CareType | None = None,
               reason: str = "Dolor de cabeza"):
        return self.manager.create_ticket(
            self.patient(number), care_type or NormalCare(), reason
        )

    def read_json(self, filename: str) -> list:
        with open(self.folder / filename, "r", encoding="utf-8") as file:
            return json.load(file)

    def write_json(self, filename: str, data) -> None:
        with open(self.folder / filename, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)


# -------------------------------------------------------------- creating


class CreateTicketTests(TicketManagerTestCase):
    def test_numbering_is_global_across_both_queues(self):
        first = self.create(1)
        second = self.create(2, PriorityCare("Embarazo"))
        third = self.create(4)
        self.assertEqual(
            [first.number, second.number, third.number],
            ["N-001", "P-002", "N-003"],
        )

    def test_new_ticket_is_pending_with_patient_and_reason(self):
        ticket = self.create(1, reason="  Dolor de cabeza  ")
        self.assertIs(ticket.status, TicketStatus.PENDING)
        self.assertIs(ticket.patient, self.patient(1))
        self.assertEqual(ticket.reason, "Dolor de cabeza")

    def test_each_ticket_goes_to_the_back_of_its_queue(self):
        n1 = self.create(1)
        p2 = self.create(2, PriorityCare("Urgencia"))
        n3 = self.create(4)
        p4 = self.create(3, PriorityCare("Adulto mayor"))
        self.assertEqual(self.manager.pending_normal(), [n1, n3])
        self.assertEqual(self.manager.pending_priority(), [p2, p4])
        self.assertEqual(self.manager.normal_count(), 2)
        self.assertEqual(self.manager.priority_count(), 2)

    def test_queue_choice_depends_only_on_is_priority(self):
        # A care type the manager has never seen. It goes to the priority
        # queue only because its is_priority says so.
        class HomeVisitCare(CareType):
            name = "Visita"
            prefix = "P"
            is_priority = True

        ticket = self.create(1, HomeVisitCare())
        self.assertEqual(self.manager.pending_priority(), [ticket])
        self.assertEqual(self.manager.pending_normal(), [])

    def test_rn07_rejects_second_active_ticket(self):
        first = self.create(1)
        with self.assertRaises(ValidationError) as context:
            self.create(1, PriorityCare("Urgencia"))
        self.assertEqual(
            context.exception.message,
            f"Este paciente ya tiene el turno {first.number} activo.",
        )
        self.assertEqual(self.manager.normal_count(), 1)
        self.assertEqual(self.manager.priority_count(), 0)

    def test_rejected_ticket_does_not_use_up_a_number(self):
        self.create(1)
        with self.assertRaises(ValidationError):
            self.create(1)
        with self.assertRaises(ValidationError):
            self.create(2, reason="mal")
        self.assertEqual(self.create(2).number, "N-002")

    def test_short_reason_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.create(1, reason="dolo")
        self.assertTrue(self.manager.queues_empty())
        self.assertEqual(self.manager.list_tickets(), [])

    def test_senior_criterion_requires_age(self):
        with self.assertRaises(ValidationError) as context:
            self.create(1, PriorityCare("Adulto mayor"))
        self.assertEqual(
            context.exception.message,
            "El criterio Adulto mayor requiere 60 años o más.",
        )
        self.assertTrue(self.manager.queues_empty())

    def test_create_saves_both_files(self):
        self.create(2, PriorityCare("Discapacidad"), reason="Revisión de presión")
        rows = self.read_json(TicketManager.TICKETS_FILE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["number"], "P-001")
        self.assertEqual(rows[0]["patient_code"], "PAC-0002")
        self.assertEqual(rows[0]["criterion"], "Discapacidad")
        self.assertEqual(self.read_json(TicketManager.CARE_RECORDS_FILE), [])
        raw = (self.folder / TicketManager.TICKETS_FILE).read_bytes()
        self.assertIn("Revisión".encode("utf-8"), raw)


# --------------------------------------------------------------- queries


class QueryTests(TicketManagerTestCase):
    def test_empty_manager(self):
        self.assertTrue(self.manager.queues_empty())
        self.assertIsNone(self.manager.peek_next())
        self.assertEqual(self.manager.priority_count(), 0)
        self.assertEqual(self.manager.normal_count(), 0)

    def test_peek_next_prefers_priority_and_does_not_remove(self):
        self.create(1)
        self.create(4)
        priority = self.create(3, PriorityCare("Adulto mayor"))
        self.assertIs(self.manager.peek_next(), priority)
        self.assertIs(self.manager.peek_next(), priority)
        self.assertEqual(self.manager.priority_count(), 1)

    def test_peek_next_falls_back_to_normal(self):
        first = self.create(1)
        self.create(4)
        self.assertIs(self.manager.peek_next(), first)
        self.assertFalse(self.manager.queues_empty())

    def test_pending_lists_are_copies(self):
        self.create(1)
        self.manager.pending_normal().clear()
        self.assertEqual(self.manager.normal_count(), 1)

    def test_get_and_get_status(self):
        ticket = self.create(1)
        self.assertIs(self.manager.get(" n-001 "), ticket)
        self.assertIs(self.manager.get_status("N-001"), TicketStatus.PENDING)

    def test_get_unknown_number(self):
        with self.assertRaises(NotFoundError) as context:
            self.manager.get("N-999")
        self.assertEqual(context.exception.message, "No existe el turno N-999.")
        with self.assertRaises(NotFoundError):
            self.manager.get_status("P-001")

    def test_active_ticket_of(self):
        self.assertIsNone(self.manager.active_ticket_of("PAC-0001"))
        ticket = self.create(1)
        self.assertIs(self.manager.active_ticket_of("pac-0001"), ticket)
        self.assertIsNone(self.manager.active_ticket_of("PAC-0002"))

    def test_list_tickets_sorted_by_sequence(self):
        n1 = self.create(1)
        p2 = self.create(2, PriorityCare("Urgencia"))
        n3 = self.create(4)
        self.assertEqual(self.manager.list_tickets(), [n1, p2, n3])


# --------------------------------------------------------------- loading


class LoadTests(TicketManagerTestCase):
    def test_missing_files_are_created_empty(self):
        self.assertEqual(self.read_json(TicketManager.TICKETS_FILE), [])
        self.assertEqual(self.read_json(TicketManager.CARE_RECORDS_FILE), [])

    def test_queues_keep_their_order_after_save_and_load(self):
        self.create(1)
        self.create(2, PriorityCare("Urgencia"))
        self.create(4)
        self.create(3, PriorityCare("Adulto mayor"))
        self.create(5)

        reloaded = self.new_manager()
        self.assertEqual(
            [t.number for t in reloaded.pending_normal()],
            ["N-001", "N-003", "N-005"],
        )
        self.assertEqual(
            [t.number for t in reloaded.pending_priority()],
            ["P-002", "P-004"],
        )
        self.assertEqual(reloaded.peek_next().number, "P-002")

    def test_counter_continues_after_load(self):
        self.create(1)
        self.create(2)
        reloaded = self.new_manager()
        ticket = reloaded.create_ticket(self.patient(4), NormalCare(), "Control general")
        self.assertEqual(ticket.number, "N-003")

    def test_counter_file_is_saved_with_the_next_sequence(self):
        self.create(1)
        self.create(2)
        self.assertEqual(
            self.read_json(TicketManager.COUNTER_FILE), [{"next_sequence": 3}]
        )

    def test_counter_file_keeps_numbers_when_tickets_file_is_damaged(self):
        # Pending tickets lost with a damaged tickets.json left no care
        # record behind, so only the counter file remembers their numbers.
        self.create(1)
        self.create(2)
        (self.folder / TicketManager.TICKETS_FILE).write_text(
            "{esto no es json", encoding="utf-8"
        )
        manager = TicketManager(self.repo)
        with self.assertRaises(CorruptedFileError):
            manager.load(dict(self.patients))
        ticket = manager.create_ticket(self.patient(1), NormalCare(), "Control general")
        self.assertEqual(ticket.number, "N-003")

    def test_missing_counter_file_uses_the_tickets(self):
        # A data folder from before this file existed still works.
        self.write_json(TicketManager.TICKETS_FILE, [ticket_row("N-004", "PAC-0001")])
        manager = self.new_manager()
        ticket = manager.create_ticket(self.patient(2), NormalCare(), "Control general")
        self.assertEqual(ticket.number, "N-005")

    def test_counter_lower_than_the_tickets_is_ignored(self):
        self.write_json(TicketManager.TICKETS_FILE, [ticket_row("N-004", "PAC-0001")])
        self.write_json(TicketManager.COUNTER_FILE, [{"next_sequence": 2}])
        manager = self.new_manager()
        ticket = manager.create_ticket(self.patient(2), NormalCare(), "Control general")
        self.assertEqual(ticket.number, "N-005")

    def test_invalid_counter_stops_the_load(self):
        for rows in (
            [{"next_sequence": "7"}],
            [{"next_sequence": 0}],
            [{"next_sequence": True}],
            [{"otro": 3}],
            [{"next_sequence": 3}, {"next_sequence": 4}],
        ):
            with self.subTest(rows=rows):
                self.write_json(TicketManager.COUNTER_FILE, rows)
                with self.assertRaises(ValidationError) as context:
                    self.new_manager()
                self.assertIn(TicketManager.COUNTER_FILE, context.exception.message)

    def test_repeated_number_does_not_create_the_counter_file(self):
        # A start that stops on a hand-edited tickets.json leaves the data
        # folder as it was (test E2-28). setUp already loaded once, which
        # created the file, so it is removed first.
        (self.folder / TicketManager.COUNTER_FILE).unlink()
        self.write_json(TicketManager.TICKETS_FILE, [
            ticket_row("N-001", "PAC-0001"), ticket_row("N-001", "PAC-0002"),
        ])
        with self.assertRaises(ValidationError):
            self.new_manager()
        self.assertFalse((self.folder / TicketManager.COUNTER_FILE).exists())

    def test_loaded_ticket_points_to_the_same_patient(self):
        self.create(1)
        reloaded = self.new_manager()
        self.assertIs(reloaded.get("N-001").patient, self.patient(1))

    def test_queues_follow_sequence_not_file_order(self):
        self.write_json(TicketManager.TICKETS_FILE, [
            ticket_row("N-007", "PAC-0004"),
            ticket_row("N-002", "PAC-0001"),
            ticket_row("N-005", "PAC-0002"),
        ])
        manager = self.new_manager()
        self.assertEqual(
            [t.number for t in manager.pending_normal()],
            ["N-002", "N-005", "N-007"],
        )

    def test_only_pending_tickets_go_back_to_the_queues(self):
        self.write_json(TicketManager.TICKETS_FILE, [
            ticket_row("N-001", "PAC-0001", "Atendido", served_at=SERVED),
            ticket_row("N-002", "PAC-0002", "En atención"),
            ticket_row("N-003", "PAC-0004", "Cancelado"),
            ticket_row("N-004", "PAC-0005"),
            ticket_row("P-005", "PAC-0003", care_type="Prioritaria",
                       criterion="Adulto mayor"),
        ])
        self.write_json(TicketManager.CARE_RECORDS_FILE, [record_row("N-001")])
        manager = self.new_manager()

        self.assertEqual([t.number for t in manager.pending_normal()], ["N-004"])
        self.assertEqual([t.number for t in manager.pending_priority()], ["P-005"])
        self.assertIs(manager._in_progress, manager.get("N-002"))
        self.assertIs(manager.active_ticket_of("PAC-0002"), manager.get("N-002"))
        self.assertIsNone(manager.active_ticket_of("PAC-0001"))
        self.assertEqual(len(manager.list_tickets()), 5)

    def test_load_twice_does_not_duplicate_queue_entries(self):
        self.create(1)
        self.manager.load(dict(self.patients))
        self.assertEqual(self.manager.normal_count(), 1)

    def test_repeated_number_is_rejected(self):
        self.write_json(TicketManager.TICKETS_FILE, [
            ticket_row("N-004", "PAC-0001"),
            ticket_row("N-004", "PAC-0002"),
        ])
        manager = TicketManager(self.repo)
        with self.assertRaises(ValidationError) as context:
            manager.load(dict(self.patients))
        self.assertEqual(
            context.exception.message,
            "El turno N-004 ya existe. Revisa tickets.json.",
        )
        self.assertEqual(manager.list_tickets(), [])
        self.assertTrue(manager.queues_empty())

    def test_same_sequence_with_other_prefix_is_rejected(self):
        self.write_json(TicketManager.TICKETS_FILE, [
            ticket_row("N-004", "PAC-0001"),
            ticket_row("P-004", "PAC-0002", care_type="Prioritaria",
                       criterion="Urgencia"),
        ])
        with self.assertRaises(ValidationError) as context:
            self.new_manager()
        self.assertIn("N-004 y P-004", context.exception.message)

    def test_two_tickets_in_progress_are_rejected(self):
        self.write_json(TicketManager.TICKETS_FILE, [
            ticket_row("N-001", "PAC-0001", "En atención"),
            ticket_row("N-002", "PAC-0002", "En atención"),
        ])
        with self.assertRaises(ValidationError):
            self.new_manager()

    def test_patient_with_two_active_tickets_is_rejected(self):
        self.write_json(TicketManager.TICKETS_FILE, [
            ticket_row("N-001", "PAC-0001"),
            ticket_row("N-002", "PAC-0001"),
        ])
        with self.assertRaises(ValidationError) as context:
            self.new_manager()
        self.assertIn("PAC-0001", context.exception.message)

    def test_unknown_patient_is_rejected(self):
        self.write_json(TicketManager.TICKETS_FILE, [
            ticket_row("N-001", "PAC-0099"),
        ])
        with self.assertRaises(ValidationError):
            self.new_manager()

    def test_damaged_tickets_file_keeps_care_records_and_their_numbers(self):
        (self.folder / TicketManager.TICKETS_FILE).write_text(
            "{esto no es json", encoding="utf-8"
        )
        self.write_json(TicketManager.CARE_RECORDS_FILE, [
            record_row("N-001"), record_row("P-006"),
        ])
        manager = TicketManager(self.repo)
        with self.assertRaises(CorruptedFileError) as context:
            manager.load(dict(self.patients))
        self.assertEqual(context.exception.filename, "tickets.json")
        self.assertEqual(len(list(self.folder.glob("tickets.corrupted-*.json"))), 1)

        # The served numbers live on in care_records.json, so the counter
        # skips them (RN-04).
        ticket = manager.create_ticket(self.patient(1), NormalCare(), "Control general")
        self.assertEqual(ticket.number, "N-007")
        self.assertEqual(len(self.read_json(TicketManager.CARE_RECORDS_FILE)), 2)

    def test_both_files_damaged_give_one_warning(self):
        for filename in (TicketManager.TICKETS_FILE, TicketManager.CARE_RECORDS_FILE):
            (self.folder / filename).write_bytes("José".encode("cp1252"))
        with self.assertRaises(CorruptedFileError) as context:
            self.new_manager()
        self.assertIn("tickets.json y care_records.json", context.exception.message)


# ----------------------------------------------------------- calling next


class CallNextTests(TicketManagerTestCase):
    def test_cp13_priority_first_then_normals_in_arrival_order(self):
        # CP-13: two normal patients arrive, then a priority one.
        self.create(1)
        self.create(4)
        self.create(3, PriorityCare("Adulto mayor"))

        order = []
        for _ in range(3):
            order.append(self.manager.call_next().number)
            self.manager.finish_care("admin")
        self.assertEqual(order, ["P-003", "N-001", "N-002"])
        self.assertTrue(self.manager.queues_empty())

    def test_called_ticket_leaves_its_queue_and_is_in_progress(self):
        first = self.create(1)
        self.create(4)
        called = self.manager.call_next()

        self.assertIs(called, first)
        self.assertIs(called.status, TicketStatus.IN_PROGRESS)
        self.assertIs(self.manager.in_progress, called)
        self.assertEqual(self.manager.normal_count(), 1)
        # Still active for RN-07: the patient cannot get another ticket yet.
        self.assertIs(self.manager.active_ticket_of("PAC-0001"), called)

    def test_called_ticket_is_the_one_peek_next_showed(self):
        self.create(1)
        self.create(3, PriorityCare("Adulto mayor"))
        expected = self.manager.peek_next()
        self.assertIs(self.manager.call_next(), expected)

    def test_cp14_both_queues_empty(self):
        with self.assertRaises(EmptyQueueError) as context:
            self.manager.call_next()
        self.assertEqual(context.exception.message, "No hay pacientes en espera.")
        self.assertIsNone(self.manager.in_progress)

    def test_cp15_rn08_one_ticket_in_care_at_a_time(self):
        self.create(1)
        self.create(4)
        self.manager.call_next()
        with self.assertRaises(ValidationError) as context:
            self.manager.call_next()
        self.assertEqual(
            context.exception.message,
            "Finaliza la atención de N-001 antes de llamar al siguiente.",
        )
        self.assertEqual(self.manager.normal_count(), 1)
        self.assertIs(self.manager.get_status("N-002"), TicketStatus.PENDING)

    def test_rn08_is_checked_before_the_empty_queues(self):
        # With one ticket in care and nobody waiting, the message has to
        # say to finish first, not that nobody is waiting.
        self.create(1)
        self.manager.call_next()
        with self.assertRaises(ValidationError):
            self.manager.call_next()

    def test_call_next_saves(self):
        self.create(1)
        self.create(2, PriorityCare("Urgencia"))
        self.manager.call_next()

        reloaded = self.new_manager()
        self.assertEqual(reloaded.in_progress.number, "P-002")
        self.assertEqual(reloaded.pending_priority(), [])
        self.assertEqual([t.number for t in reloaded.pending_normal()], ["N-001"])


# ---------------------------------------------------------- finishing care


class FinishCareTests(TicketManagerTestCase):
    def test_cp16_finish_creates_the_record(self):
        ticket = self.create(3, PriorityCare("Adulto mayor"))
        self.manager.call_next()
        record = self.manager.finish_care("recepcion")

        self.assertIs(ticket.status, TicketStatus.SERVED)
        self.assertIsNotNone(ticket.served_at)
        self.assertIsNone(self.manager.in_progress)
        self.assertEqual(record.ticket_number, "P-001")
        self.assertEqual(record.patient_code, "PAC-0003")
        self.assertEqual(record.patient_name, "María Gómez")
        self.assertEqual(record.care_type, "Prioritaria (Adulto mayor)")
        self.assertEqual(record.registered_at, ticket.created_at)
        self.assertEqual(record.served_at, ticket.served_at)
        self.assertEqual(record.served_by, "recepcion")
        self.assertEqual(self.manager.list_care_records(), [record])

    def test_patient_can_get_a_new_ticket_after_care(self):
        self.create(1)
        self.manager.call_next()
        self.manager.finish_care("admin")
        self.assertIsNone(self.manager.active_ticket_of("PAC-0001"))
        self.assertEqual(self.create(1).number, "N-002")

    def test_finish_without_ticket_in_care(self):
        self.create(1)
        with self.assertRaises(ValidationError) as context:
            self.manager.finish_care("admin")
        self.assertEqual(
            context.exception.message, "No hay ningún turno en atención."
        )
        self.assertEqual(self.manager.list_care_records(), [])
        self.assertIs(self.manager.get_status("N-001"), TicketStatus.PENDING)

    def test_care_records_newest_first(self):
        for number in (1, 2, 4):
            self.create(number)
        for _ in range(3):
            self.manager.call_next()
            self.manager.finish_care("admin")
        self.assertEqual(
            [r.ticket_number for r in self.manager.list_care_records()],
            ["N-003", "N-002", "N-001"],
        )

    def test_care_records_list_is_a_copy(self):
        self.create(1)
        self.manager.call_next()
        self.manager.finish_care("admin")
        self.manager.list_care_records().clear()
        self.assertEqual(len(self.manager.list_care_records()), 1)

    def test_finish_saves_ticket_and_record(self):
        self.create(1)
        self.manager.call_next()
        self.manager.finish_care("admin")

        rows = self.read_json(TicketManager.TICKETS_FILE)
        self.assertEqual(rows[0]["status"], "Atendido")
        self.assertIsNotNone(rows[0]["served_at"])
        records = self.read_json(TicketManager.CARE_RECORDS_FILE)
        self.assertEqual(records[0]["ticket_number"], "N-001")
        self.assertEqual(records[0]["served_by"], "admin")

        reloaded = self.new_manager()
        self.assertIsNone(reloaded.in_progress)
        self.assertEqual(
            [r.ticket_number for r in reloaded.list_care_records()], ["N-001"]
        )


# ------------------------------------------------------------- cancelling


class CancelTicketTests(TicketManagerTestCase):
    def test_cp17_cancel_pending_ticket(self):
        n1 = self.create(1)
        n2 = self.create(2)
        n3 = self.create(4)
        position = self.manager.cancel_ticket("N-002")

        self.assertEqual(position, 1)
        self.assertIs(n2.status, TicketStatus.CANCELLED)
        self.assertEqual(self.manager.pending_normal(), [n1, n3])
        self.assertEqual(self.manager.normal_count(), 2)

    def test_position_is_counted_in_the_ticket_queue(self):
        self.create(1)
        self.create(2)
        self.create(3, PriorityCare("Adulto mayor"))
        # P-003 is the third ticket overall but the first of its queue.
        self.assertEqual(self.manager.cancel_ticket("p-003"), 0)
        self.assertEqual(self.manager.pending_priority(), [])

    def test_cp18_rn05_served_ticket_cannot_be_cancelled(self):
        self.create(1)
        self.manager.call_next()
        self.manager.finish_care("admin")
        with self.assertRaises(ValidationError) as context:
            self.manager.cancel_ticket("N-001")
        self.assertEqual(
            context.exception.message,
            "Solo se pueden cancelar turnos pendientes.",
        )
        self.assertIs(self.manager.get_status("N-001"), TicketStatus.SERVED)

    def test_rn05_ticket_in_care_cannot_be_cancelled(self):
        self.create(1)
        self.manager.call_next()
        with self.assertRaises(ValidationError):
            self.manager.cancel_ticket("N-001")
        self.assertIs(self.manager.get_status("N-001"), TicketStatus.IN_PROGRESS)

    def test_rn05_ticket_cannot_be_cancelled_twice(self):
        self.create(1)
        self.manager.cancel_ticket("N-001")
        with self.assertRaises(ValidationError):
            self.manager.cancel_ticket("N-001")

    def test_cancel_unknown_number(self):
        with self.assertRaises(NotFoundError):
            self.manager.cancel_ticket("N-404")

    def test_patient_can_get_a_new_ticket_after_cancel(self):
        self.create(1)
        self.manager.cancel_ticket("N-001")
        self.assertEqual(self.create(1).number, "N-002")

    def test_cancel_saves(self):
        self.create(1)
        self.create(2)
        self.manager.cancel_ticket("N-001")

        reloaded = self.new_manager()
        self.assertIs(reloaded.get_status("N-001"), TicketStatus.CANCELLED)
        self.assertEqual([t.number for t in reloaded.pending_normal()], ["N-002"])


# ----------------------------------------------------------- undo helpers


class UndoHelperTests(TicketManagerTestCase):
    """Each helper must leave queues, statuses, care records and files as they were."""

    def snapshot(self) -> dict:
        manager = self.manager
        return {
            "normal": [t.number for t in manager.pending_normal()],
            "priority": [t.number for t in manager.pending_priority()],
            "statuses": {t.number: t.status for t in manager.list_tickets()},
            "in_progress": manager.in_progress and manager.in_progress.number,
            "records": [r.ticket_number for r in manager.list_care_records()],
            "tickets_file": self.read_json(TicketManager.TICKETS_FILE),
            "records_file": self.read_json(TicketManager.CARE_RECORDS_FILE),
        }

    # remove_pending_ticket

    def test_remove_pending_ticket_restores_everything(self):
        self.create(1)
        before = self.snapshot()
        self.create(2)
        self.manager.remove_pending_ticket("N-002")

        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(NotFoundError):
            self.manager.get("N-002")
        self.assertIsNone(self.manager.active_ticket_of("PAC-0002"))

    def test_removed_number_is_not_given_again(self):
        self.create(1)
        self.manager.remove_pending_ticket("N-001")
        self.assertEqual(self.create(1).number, "N-002")

    def test_removed_number_is_not_given_again_after_reopening(self):
        # Test E2-30: the number of a ticket removed by undo must not come
        # back when the program is opened again (RN-04).
        self.create(1)
        self.create(2)
        self.manager.remove_pending_ticket("N-002")
        self.manager.remove_pending_ticket("N-001")
        reloaded = self.new_manager()
        ticket = reloaded.create_ticket(self.patient(1), NormalCare(), "Control general")
        self.assertEqual(ticket.number, "N-003")

    def test_remove_pending_ticket_keeps_order_of_the_others(self):
        self.create(1)
        self.create(2)
        self.create(4)
        self.manager.remove_pending_ticket("N-002")
        self.assertEqual(
            [t.number for t in self.manager.pending_normal()], ["N-001", "N-003"]
        )

    def test_remove_rejects_ticket_that_is_not_pending(self):
        self.create(1)
        self.manager.call_next()
        with self.assertRaises(NotUndoableError):
            self.manager.remove_pending_ticket("N-001")
        self.assertIs(self.manager.in_progress, self.manager.get("N-001"))

    # return_to_front

    def test_return_to_front_restores_everything(self):
        self.create(1)
        self.create(2)
        self.create(3, PriorityCare("Adulto mayor"))
        before = self.snapshot()
        ticket = self.manager.call_next()
        self.manager.return_to_front(ticket)

        self.assertEqual(self.snapshot(), before)
        self.assertIs(self.manager.peek_next(), ticket)

    def test_return_to_front_goes_ahead_of_later_arrivals(self):
        # CP-21 at manager level: the ticket comes back first in its queue.
        first = self.create(1)
        second = self.create(2)
        self.manager.call_next()
        self.manager.return_to_front(first)
        self.assertEqual(self.manager.pending_normal(), [first, second])

    def test_return_to_front_rejects_ticket_not_in_care(self):
        ticket = self.create(1)
        with self.assertRaises(NotUndoableError):
            self.manager.return_to_front(ticket)
        self.assertEqual(self.manager.normal_count(), 1)

    # restore_cancelled

    def test_restore_cancelled_restores_everything_at_any_position(self):
        self.create(1)
        self.create(2)
        self.create(4)
        before = self.snapshot()
        for number in ("N-001", "N-002", "N-003"):
            with self.subTest(number=number):
                position = self.manager.cancel_ticket(number)
                self.manager.restore_cancelled(self.manager.get(number), position)
                self.assertEqual(self.snapshot(), before)

    def test_restore_cancelled_rejects_ticket_that_is_not_cancelled(self):
        ticket = self.create(1)
        with self.assertRaises(NotUndoableError):
            self.manager.restore_cancelled(ticket, 0)
        self.assertEqual(self.manager.normal_count(), 1)

    def test_restore_cancelled_with_wrong_position_changes_nothing(self):
        self.create(1)
        ticket = self.create(2)
        self.manager.cancel_ticket("N-002")
        with self.assertRaises(ValidationError):
            self.manager.restore_cancelled(ticket, 5)
        self.assertIs(ticket.status, TicketStatus.CANCELLED)
        self.assertEqual(self.manager.normal_count(), 1)

    def test_restore_cancelled_respects_rn07(self):
        old = self.create(1)
        self.manager.cancel_ticket("N-001")
        self.create(1)
        with self.assertRaises(NotUndoableError):
            self.manager.restore_cancelled(old, 0)
        self.assertIs(old.status, TicketStatus.CANCELLED)

    # revert_finish

    def test_revert_finish_restores_everything(self):
        self.create(1)
        self.create(2)
        self.manager.call_next()
        before = self.snapshot()
        ticket = self.manager.in_progress
        self.manager.finish_care("admin")
        self.manager.revert_finish(ticket)

        self.assertEqual(self.snapshot(), before)
        self.assertIsNone(ticket.served_at)
        self.assertEqual(self.manager.list_care_records(), [])

    def test_revert_finish_removes_only_its_own_record(self):
        for number in (1, 2):
            self.create(number)
        self.manager.call_next()
        self.manager.finish_care("admin")
        last = self.manager.call_next()
        self.manager.finish_care("admin")
        self.manager.revert_finish(last)
        self.assertEqual(
            [r.ticket_number for r in self.manager.list_care_records()], ["N-001"]
        )

    def test_revert_finish_respects_rn08(self):
        first = self.create(1)
        self.create(2)
        self.manager.call_next()
        self.manager.finish_care("admin")
        self.manager.call_next()
        with self.assertRaises(NotUndoableError):
            self.manager.revert_finish(first)
        self.assertIs(first.status, TicketStatus.SERVED)
        self.assertEqual(len(self.manager.list_care_records()), 1)

    def test_revert_finish_rejects_ticket_that_is_not_served(self):
        self.create(1)
        ticket = self.manager.call_next()
        with self.assertRaises(NotUndoableError):
            self.manager.revert_finish(ticket)
        self.assertIs(self.manager.in_progress, ticket)

    # all four, in the order the undo stack would use them

    def test_reverting_a_session_backwards_returns_to_the_start(self):
        self.create(1)
        self.create(2)
        start = self.snapshot()

        p3 = self.create(3, PriorityCare("Adulto mayor"))
        called = self.manager.call_next()
        self.manager.finish_care("admin")
        n1 = self.manager.get("N-001")
        position = self.manager.cancel_ticket("N-001")
        self.assertIs(called, p3)

        self.manager.restore_cancelled(n1, position)
        self.manager.revert_finish(p3)
        self.manager.return_to_front(p3)
        self.manager.remove_pending_ticket("P-003")

        self.assertEqual(self.snapshot(), start)
        reloaded = self.new_manager()
        self.assertEqual(
            [t.number for t in reloaded.pending_normal()], ["N-001", "N-002"]
        )
        self.assertEqual(reloaded.list_care_records(), [])


if __name__ == "__main__":
    unittest.main()
