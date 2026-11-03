"""Tests for the actions and ActionHistory (step C10).

The context of the actions is a SimpleNamespace with the two managers, which
is all an action needs. Each operation in UndoScenario does what ClinicSystem
will do in step C12: run the manager method and register the action.

Every test works with a JsonRepository inside a tempfile.TemporaryDirectory,
so the real data folder is never touched.

Run from the project root with: python -m unittest discover tests
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from models.actions import (
    ACTION_TYPES,
    CALL_NEXT,
    LOGIN,
    LOGOUT,
    TICKET_CANCELLATION,
    UNDONE,
    Action,
    CallNextAction,
    CancelTicketAction,
    CreateTicketAction,
    FinishCareAction,
    LogOnlyAction,
    RegisterPatientAction,
    UndoableAction,
    UpdatePatientAction,
)
from models.care_type import NormalCare, PriorityCare
from models.patient import Patient
from models.ticket_status import TicketStatus
from persistence.json_repository import JsonRepository
from services.action_history import ActionHistory
from services.patient_manager import PatientManager
from services.ticket_manager import TicketManager
from utils.exceptions import (
    EmptyStackError,
    NotFoundError,
    NotUndoableError,
)

USER = "admin"


def snapshot(patient_manager: PatientManager, ticket_manager: TicketManager) -> dict:
    """Everything undo must restore, as plain values that compare with ==.

    The ticket counter is left out on purpose: undo never gives a number
    back (section 3.5).
    """
    in_progress = ticket_manager.in_progress
    return {
        "patients": [
            (p.code, p.full_name, p.age, p.phone)
            for p in patient_manager.list_all()
        ],
        "tickets": [
            (t.number, t.status, t.served_at)
            for t in ticket_manager.list_tickets()
        ],
        "priority_queue": [t.number for t in ticket_manager.pending_priority()],
        "normal_queue": [t.number for t in ticket_manager.pending_normal()],
        "in_progress": in_progress.number if in_progress else None,
        "care_records": [
            r.ticket_number for r in ticket_manager.list_care_records()
        ],
    }


class UndoScenario(unittest.TestCase):
    """Repository, managers, history and the operations as ClinicSystem will do them."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name) / "data"
        self.repo = JsonRepository(str(self.folder))
        self.patients = PatientManager(self.repo)
        self.patients.load()
        self.tickets = TicketManager(self.repo)
        self.tickets.load(self.patients.patients_by_code())
        self.context = SimpleNamespace(
            patient_manager=self.patients, ticket_manager=self.tickets
        )
        self.history = ActionHistory()

    def tearDown(self):
        self._tmp.cleanup()

    # ----------------------------------------------- operations with actions

    def register(self, code, name, age=30, care_type=None):
        patient = Patient(code, name, age, "55551234")
        self.patients.register(patient)
        ticket = self.tickets.create_ticket(
            patient, care_type or NormalCare(), "Control general"
        )
        self.history.register(RegisterPatientAction(USER, patient, ticket))
        return ticket

    def new_ticket(self, code, care_type=None):
        patient = self.patients.get(code)
        ticket = self.tickets.create_ticket(
            patient, care_type or NormalCare(), "Dolor de espalda"
        )
        self.history.register(CreateTicketAction(USER, ticket))
        return ticket

    def update(self, code, name, age, phone):
        previous = self.patients.update(code, name, age, phone)
        self.history.register(
            UpdatePatientAction(USER, self.patients.get(code), previous)
        )

    def call_next(self):
        ticket = self.tickets.call_next()
        self.history.register(CallNextAction(USER, ticket))
        return ticket

    def finish(self):
        ticket = self.tickets.in_progress
        record = self.tickets.finish_care(USER)
        self.history.register(FinishCareAction(USER, ticket, record))
        return record

    def cancel(self, number):
        ticket = self.tickets.get(number)
        position = self.tickets.cancel_ticket(number)
        self.history.register(CancelTicketAction(USER, ticket, position))
        return position

    def log(self, action_type=LOGIN):
        self.history.register(LogOnlyAction(action_type, "Evidencia", USER))

    def undo(self):
        return self.history.undo_last(self.context, USER)

    def state(self):
        return snapshot(self.patients, self.tickets)

    def reloaded_state(self):
        """State read back from the JSON files by brand-new managers."""
        patients = PatientManager(self.repo)
        patients.load()
        tickets = TicketManager(self.repo)
        tickets.load(patients.patients_by_code())
        return snapshot(patients, tickets)


class TestActionClasses(unittest.TestCase):
    """The hierarchy itself: abstract classes, properties and undo() once."""

    def test_action_and_undoable_action_are_abstract(self):
        with self.assertRaises(TypeError):
            Action(LOGIN, "x", USER)
        with self.assertRaises(TypeError):
            UndoableAction(CALL_NEXT, "x", USER)

    def test_log_only_action_is_not_undoable(self):
        action = LogOnlyAction(LOGIN, "Ingresó admin.", USER, {"role": "Administrador"})
        self.assertFalse(action.is_undoable)
        self.assertEqual(action.action_type, "Inicio de sesión")
        self.assertEqual(action.description, "Ingresó admin.")
        self.assertEqual(action.username, USER)
        self.assertEqual(action.data, {"role": "Administrador"})
        self.assertRegex(action.timestamp, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_timestamp_can_be_given(self):
        action = LogOnlyAction(LOGOUT, "Salió.", USER, timestamp="2026-11-02 08:00:00")
        self.assertEqual(action.timestamp, "2026-11-02 08:00:00")

    def test_data_cannot_be_changed_from_outside(self):
        original = {"ticket_number": "N-001"}
        action = LogOnlyAction(LOGIN, "x", USER, original)
        original["ticket_number"] = "N-999"
        action.data["ticket_number"] = "N-999"
        self.assertEqual(action.data, {"ticket_number": "N-001"})

    def test_data_defaults_to_empty_dict(self):
        self.assertEqual(LogOnlyAction(LOGIN, "x", USER).data, {})

    def test_action_types_are_spanish_and_complete(self):
        self.assertEqual(len(ACTION_TYPES), 10)
        self.assertIn("Acción deshecha", ACTION_TYPES)
        self.assertIn("Cancelación de turno", ACTION_TYPES)
        self.assertEqual(TICKET_CANCELLATION, "Cancelación de turno")


class TestEachUndo(UndoScenario):
    """Each subclass reverts its own operation (section 3.6)."""

    def test_undo_registration_removes_patient_and_ticket(self):
        before = self.state()
        self.register("PAC-0001", "Ana López")
        self.undo()
        self.assertEqual(self.state(), before)
        self.assertFalse(self.patients.exists("PAC-0001"))
        with self.assertRaises(NotFoundError):
            self.tickets.get("N-001")
        self.assertEqual(self.reloaded_state(), before)

    def test_undone_ticket_number_is_not_reused(self):
        self.register("PAC-0001", "Ana López")
        self.undo()
        ticket = self.register("PAC-0001", "Ana López")
        self.assertEqual(ticket.number, "N-002")

    def test_undo_new_ticket_keeps_the_patient(self):
        first = self.register("PAC-0001", "Ana López")
        self.call_next()
        self.finish()
        before = self.state()
        self.new_ticket("PAC-0001", PriorityCare("Urgencia"))
        self.assertEqual(self.tickets.priority_count(), 1)
        self.undo()
        self.assertEqual(self.state(), before)
        self.assertTrue(self.patients.exists("PAC-0001"))
        self.assertEqual(self.tickets.get(first.number).status, TicketStatus.SERVED)

    def test_undo_update_restores_previous_values(self):
        self.register("PAC-0001", "Ana López")
        before = self.state()
        self.update("PAC-0001", "Ana María López", "31", "22223333")
        self.assertEqual(self.patients.get("PAC-0001").full_name, "Ana María López")
        self.undo()
        patient = self.patients.get("PAC-0001")
        self.assertEqual(
            (patient.full_name, patient.age, patient.phone),
            ("Ana López", 30, "55551234"),
        )
        self.assertEqual(self.reloaded_state(), before)

    def test_undo_call_next_returns_ticket_to_front(self):
        """CP-21: the ticket goes back to Pendiente at the front of its queue."""
        self.register("PAC-0001", "Ana López")
        self.register("PAC-0002", "José Peña")
        before = self.state()
        called = self.call_next()
        self.assertEqual(called.number, "N-001")
        self.undo()
        self.assertEqual(called.status, TicketStatus.PENDING)
        self.assertEqual(self.state()["normal_queue"], ["N-001", "N-002"])
        self.assertIsNone(self.tickets.in_progress)
        self.assertEqual(self.state(), before)

    def test_undo_finish_returns_to_in_progress_and_deletes_record(self):
        self.register("PAC-0001", "Ana López")
        ticket = self.call_next()
        before = self.state()
        self.finish()
        self.assertEqual(len(self.tickets.list_care_records()), 1)
        self.undo()
        self.assertEqual(ticket.status, TicketStatus.IN_PROGRESS)
        self.assertIsNone(ticket.served_at)
        self.assertIs(self.tickets.in_progress, ticket)
        self.assertEqual(self.tickets.list_care_records(), [])
        self.assertEqual(self.reloaded_state(), before)

    def test_undo_cancel_restores_same_position(self):
        """CP-20: cancel the second ticket of the normal queue and undo."""
        self.register("PAC-0001", "Ana López")
        self.register("PAC-0002", "José Peña")
        self.register("PAC-0003", "Marco Ruiz")
        before = self.state()
        position = self.cancel("N-002")
        self.assertEqual(position, 1)
        self.assertEqual(self.state()["normal_queue"], ["N-001", "N-003"])
        self.undo()
        self.assertEqual(self.state()["normal_queue"], ["N-001", "N-002", "N-003"])
        self.assertEqual(self.tickets.get_status("N-002"), TicketStatus.PENDING)
        self.assertEqual(self.reloaded_state(), before)

    def test_cancel_action_keeps_position_in_data(self):
        self.register("PAC-0001", "Ana López")
        self.register("PAC-0002", "José Peña")
        self.cancel("N-002")
        action = self.history.last_action()
        self.assertIsInstance(action, CancelTicketAction)
        self.assertEqual(action.position, 1)
        self.assertEqual(action.data["position"], 1)
        self.assertIn("posición 2", action.description)

    def test_same_action_cannot_be_undone_twice(self):
        self.register("PAC-0001", "Ana López")
        action = self.history.last_action()
        action.undo(self.context)
        self.assertTrue(action.undone)
        with self.assertRaises(NotUndoableError):
            action.undo(self.context)


class TestActionHistory(UndoScenario):
    """The two stacks, the evidence entries and the failures."""

    def test_empty_history(self):
        self.assertFalse(self.history.has_actions())
        self.assertFalse(self.history.can_undo())
        self.assertEqual(self.history.list_all(), [])
        with self.assertRaises(EmptyStackError) as caught:
            self.history.last_action()
        self.assertEqual(str(caught.exception), "No hay acciones registradas.")

    def test_undo_with_nothing_to_undo(self):
        """CP-22: the message of section 4.6."""
        with self.assertRaises(EmptyStackError) as caught:
            self.undo()
        self.assertEqual(
            str(caught.exception), "No hay acciones que se puedan deshacer."
        )

    def test_evidence_goes_only_to_the_history(self):
        self.log(LOGIN)
        self.log(LOGOUT)
        self.assertTrue(self.history.has_actions())
        self.assertFalse(self.history.can_undo())
        with self.assertRaises(EmptyStackError):
            self.undo()

    def test_list_all_starts_with_the_most_recent(self):
        self.log(LOGIN)
        self.register("PAC-0001", "Ana López")
        self.call_next()
        types = [action.action_type for action in self.history.list_all()]
        self.assertEqual(types, ["Atención", "Registro de paciente", "Inicio de sesión"])
        self.assertEqual(self.history.last_action().action_type, "Atención")

    def test_login_after_cancel_does_not_block_its_undo(self):
        """Section 3.7: the evidence on top of the history does not get in the way."""
        self.register("PAC-0001", "Ana López")
        self.register("PAC-0002", "José Peña")
        self.cancel("N-001")
        self.log(LOGOUT)
        self.log(LOGIN)
        self.assertEqual(self.history.last_action().action_type, LOGIN)

        undone = self.undo()
        self.assertIsInstance(undone, CancelTicketAction)
        self.assertEqual(self.state()["normal_queue"], ["N-001", "N-002"])

    def test_undo_leaves_evidence_and_marks_the_action(self):
        self.register("PAC-0001", "Ana López")
        self.call_next()
        undone = self.undo()

        self.assertIsInstance(undone, CallNextAction)
        self.assertTrue(undone.undone)
        last = self.history.last_action()
        self.assertIsInstance(last, LogOnlyAction)
        self.assertEqual(last.action_type, UNDONE)
        self.assertEqual(last.username, USER)
        self.assertIn(undone.description, last.description)
        self.assertEqual(last.data["undone_type"], CALL_NEXT)
        self.assertEqual(last.data["ticket_number"], "N-001")
        # The undone action stays in the history; it only left the undo stack.
        self.assertIn(undone, self.history.list_all())
        self.assertEqual(len(self.history.list_all()), 3)

    def test_failed_undo_puts_the_action_back(self):
        self.register("PAC-0001", "Ana López")
        self.call_next()
        # Someone finishes the care without registering the action, so the
        # ticket is no longer the one in care and CallNextAction must refuse.
        self.tickets.finish_care(USER)
        entries_before = len(self.history.list_all())

        with self.assertRaises(NotUndoableError):
            self.undo()
        self.assertTrue(self.history.can_undo())
        self.assertIsInstance(self.history.last_action(), CallNextAction)
        self.assertFalse(self.history.last_action().undone)
        self.assertEqual(len(self.history.list_all()), entries_before)
        self.assertEqual(self.tickets.get_status("N-001"), TicketStatus.SERVED)

    def test_failed_registration_undo_changes_nothing(self):
        self.register("PAC-0001", "Ana López")
        self.tickets.call_next()  # not registered on purpose
        before = self.state()
        with self.assertRaises(NotUndoableError):
            self.undo()
        self.assertEqual(self.state(), before)
        self.assertTrue(self.patients.exists("PAC-0001"))


class TestFullUndo(UndoScenario):
    """Step C10 is done when undoing everything in reverse gets back to the start."""

    def test_undo_everything_in_reverse_order(self):
        # A patient from before the session, so the initial state is not empty.
        self.register("PAC-0001", "Ana López")
        initial = self.state()

        # Each entry is the operation and whether it is undoable.
        operations = [
            (lambda: self.register("PAC-0002", "José Peña"), True),
            (lambda: self.register("PAC-0003", "María Gómez", 72,
                                   PriorityCare("Adulto mayor")), True),
            (lambda: self.register("PAC-0004", "Marco Ruiz"), True),
            (self.call_next, True),                      # P-003, priority first
            (self.finish, True),
            (lambda: self.cancel("N-002"), True),        # middle of the queue
            (lambda: self.update("PAC-0004", "Marco Antonio Ruiz", 26,
                                 "66667777"), True),
            (self.call_next, True),                      # N-001
            (lambda: self.log(LOGOUT), False),
            (lambda: self.log(LOGIN), False),
            (self.finish, True),
            (lambda: self.new_ticket("PAC-0003", PriorityCare("Urgencia")), True),
        ]
        # The state right before each undoable operation. Undoing that
        # operation must bring the data back to it.
        states_before = []
        for operation, undoable in operations:
            if undoable:
                states_before.append(self.state())
            operation()
        self.assertEqual(len(states_before), 10)

        for expected in reversed(states_before):
            self.undo()
            self.assertEqual(self.state(), expected)

        self.assertEqual(self.state(), initial)
        self.assertEqual(self.reloaded_state(), initial)
        # Only the first registration is left to undo.
        self.undo()
        self.assertFalse(self.history.can_undo())
        with self.assertRaises(EmptyStackError):
            self.undo()

        undone_entries = [
            a for a in self.history.list_all() if a.action_type == UNDONE
        ]
        self.assertEqual(len(undone_entries), 11)
        self.assertTrue(
            all(a.undone for a in self.history.list_all() if a.is_undoable)
        )

    def test_queue_order_survives_undo_and_new_calls(self):
        """After undoing a call, the next call takes the same ticket again."""
        self.register("PAC-0001", "Ana López")
        self.register("PAC-0002", "María Gómez", 72, PriorityCare("Adulto mayor"))
        first = self.call_next()
        self.undo()
        again = self.call_next()
        self.assertIs(first, again)
        self.assertEqual(again.number, "P-002")


if __name__ == "__main__":
    unittest.main()
