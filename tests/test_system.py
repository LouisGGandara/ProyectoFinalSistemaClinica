"""Integration tests for the ClinicSystem facade (step C12).

These tests go through ClinicSystem only, the same way the interface will.
Each one works in a data folder inside tempfile.TemporaryDirectory, so the
real data folder is never touched.

Run from the project root with: python -m unittest discover tests
"""

import json
import tempfile
import unittest
from pathlib import Path

from models.actions import (
    CALL_NEXT,
    LOGIN,
    LOGOUT,
    PATIENT_REGISTRATION,
    TICKET_CANCELLATION,
    UNDONE,
    USER_MANAGEMENT,
)
from models.permissions import Permission
from services.clinic_system import ClinicSystem
from utils.exceptions import (
    DuplicateError,
    EmptyQueueError,
    EmptyStackError,
    InvalidCredentialsError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)

ADMIN = ("admin", "Admin123")
RECEPTION = ("recepcion", "Recep123")


class SystemTestCase(unittest.TestCase):
    """Opens a ClinicSystem on a temporary data folder."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name) / "data"
        self.system = ClinicSystem(str(self.folder))

    def tearDown(self):
        self._tmp.cleanup()

    def reopen(self) -> ClinicSystem:
        """A new system on the same folder, as if the program was restarted."""
        return ClinicSystem(str(self.folder))

    def login_admin(self):
        return self.system.login(*ADMIN)

    def login_reception(self):
        return self.system.login(*RECEPTION)

    def register(self, code, name, age=30, care_type="Normal", criterion=None,
                 reason="Control general"):
        return self.system.register_patient(
            code, name, age, "55551234", reason, care_type, criterion
        )

    def numbers(self, tickets):
        return [ticket.number for ticket in tickets]


class TestStart(SystemTestCase):
    def test_first_start_creates_files_and_default_users(self):
        for name in ("users.json", "patients.json", "tickets.json",
                     "care_records.json", "ticket_counter.json"):
            self.assertTrue((self.folder / name).is_file(), name)
        self.assertEqual(self.system.warnings, [])
        self.assertIsNone(self.system.current_user)
        self.login_admin()
        names = [user.username for user in self.system.list_users()]
        self.assertEqual(names, ["admin", "recepcion"])

    def test_damaged_file_becomes_a_warning_and_the_system_starts(self):
        (self.folder / "care_records.json").write_text("{roto", encoding="utf-8")
        system = self.reopen()
        self.assertEqual(len(system.warnings), 1)
        self.assertIn("care_records.json", system.warnings[0])
        copies = list(self.folder.glob("care_records.corrupted-*.json"))
        self.assertEqual(len(copies), 1)
        system.login(*ADMIN)
        self.assertEqual(system.list_care_records(), [])

    def test_wrong_shape_becomes_a_warning_that_names_the_file(self):
        # Test E2-27: valid JSON such as [1, 2] used to end in a general
        # error that named no file.
        (self.folder / "patients.json").write_text("[1, 2]", encoding="utf-8")
        system = self.reopen()
        self.assertEqual(len(system.warnings), 1)
        self.assertIn("patients.json", system.warnings[0])

    def test_file_with_bom_starts_without_warnings(self):
        # Test E2-26: Notepad's "UTF-8 con BOM" is still UTF-8.
        self.login_admin()
        self.register("PAC-0001", "José Peña")
        for name in ("users.json", "patients.json"):
            path = self.folder / name
            path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        system = self.reopen()
        self.assertEqual(system.warnings, [])
        system.login(*ADMIN)
        self.assertEqual(system.list_patients()[0].full_name, "José Peña")

    def test_undone_ticket_number_is_not_reused_after_reopening(self):
        # Test E2-30 (RN-04): the counter survives closing the program.
        self.login_admin()
        self.register("PAC-0001", "Ana López")
        self.system.undo()
        system = self.reopen()
        system.login(*ADMIN)
        ticket = system.register_patient(
            "PAC-0001", "Pedro Gómez", 40, "55550000", "Control general", "Normal"
        )
        self.assertEqual(ticket.number, "N-002")

    def test_list_or_object_in_a_field_stops_with_a_clear_message(self):
        # Found while checking E2-27: a list or an object where the role or
        # the patient code goes used to raise TypeError.
        self.login_admin()
        self.register("PAC-0001", "Ana López")
        for filename, key in (("users.json", "role"), ("tickets.json", "patient_code")):
            for value in ([], {}):
                with self.subTest(filename=filename, value=value):
                    path = self.folder / filename
                    original = path.read_text(encoding="utf-8")
                    rows = json.loads(original)
                    rows[0][key] = value
                    path.write_text(json.dumps(rows), encoding="utf-8")
                    with self.assertRaises(ValidationError) as caught:
                        self.reopen()
                    # The message names a file to check, as in section 4.7.
                    self.assertIn(".json", str(caught.exception))
                    path.write_text(original, encoding="utf-8")

    def test_warnings_cannot_be_changed_from_outside(self):
        self.system.warnings.append("x")
        self.assertEqual(self.system.warnings, [])

    def test_repeated_ticket_number_stops_the_start_and_keeps_the_file(self):
        self.login_admin()
        self.register("PAC-0001", "Ana López")
        self.register("PAC-0002", "Luis Pérez")
        path = self.folder / "tickets.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        rows[1]["number"] = rows[0]["number"]
        edited = json.dumps(rows, indent=4, ensure_ascii=False)
        path.write_text(edited, encoding="utf-8")

        with self.assertRaises(ValidationError) as caught:
            self.reopen()
        self.assertIn("N-001", str(caught.exception))
        # Nothing was saved over the file the user has to fix.
        self.assertEqual(path.read_text(encoding="utf-8"), edited)

    def test_damaged_patients_explain_the_ticket_error(self):
        self.login_admin()
        self.register("PAC-0001", "Ana López")
        (self.folder / "patients.json").write_text("[", encoding="utf-8")
        with self.assertRaises(ValidationError) as caught:
            self.reopen()
        message = str(caught.exception)
        self.assertIn("patients.json está dañado", message)
        self.assertIn("PAC-0001", message)
        # The system stops, so the message must not say it went on.
        self.assertNotIn("siguió", message)


class TestSession(SystemTestCase):
    def test_login_opens_session_and_is_registered(self):
        user = self.login_admin()
        self.assertIs(self.system.current_user, user)
        last = self.system.last_action()
        self.assertEqual(last.action_type, LOGIN)
        self.assertEqual(last.username, "admin")
        self.assertFalse(last.is_undoable)

    def test_wrong_password_raises_and_leaves_no_session(self):
        with self.assertRaises(InvalidCredentialsError):
            self.system.login("admin", "clave")
        self.assertIsNone(self.system.current_user)

    def test_empty_fields_raise_validation_error(self):
        with self.assertRaises(ValidationError):
            self.system.login("", "")

    def test_second_login_without_logout_is_rejected(self):
        self.login_admin()
        with self.assertRaises(ValidationError):
            self.login_reception()
        self.assertEqual(self.system.current_user.username, "admin")

    def test_logout_closes_session_and_is_registered(self):
        self.login_admin()
        self.system.logout()
        self.assertIsNone(self.system.current_user)
        self.login_admin()
        types = [action.action_type for action in self.system.action_history()]
        self.assertEqual(types, [LOGIN, LOGOUT, LOGIN])

    def test_logout_without_session_does_nothing(self):
        self.system.logout()
        self.assertIsNone(self.system.current_user)

    def test_without_session_every_operation_is_denied(self):
        with self.assertRaises(PermissionDeniedError) as caught:
            self.register("PAC-0001", "Ana López")
        self.assertEqual(str(caught.exception), "Inicia sesión para continuar.")
        with self.assertRaises(PermissionDeniedError):
            self.system.pending_normal()
        self.assertFalse(self.system.has_permission(Permission.SEARCH))
        self.assertFalse(self.system.has_permission(None))


class TestPermissions(SystemTestCase):
    def test_admin_has_every_permission(self):
        self.login_admin()
        for permission in Permission:
            self.assertTrue(self.system.has_permission(permission), permission)

    def test_none_means_every_role(self):
        self.login_reception()
        self.assertTrue(self.system.has_permission(None))

    def test_receptionist_cannot_cancel_and_ticket_stays_pending(self):
        self.login_reception()
        ticket = self.register("PAC-0001", "Ana López")
        with self.assertRaises(PermissionDeniedError) as caught:
            self.system.cancel_ticket(ticket.number)
        self.assertEqual(
            str(caught.exception), "Tu usuario no tiene permiso para esta acción."
        )
        self.assertEqual(self.system.get_status(ticket.number), "Pendiente")
        self.assertEqual(self.numbers(self.system.pending_normal()), ["N-001"])

    def test_receptionist_is_denied_admin_functions(self):
        self.login_reception()
        denied = (
            self.system.undo,
            self.system.can_undo,
            self.system.last_action,
            self.system.action_history,
            self.system.list_users,
            lambda: self.system.create_user("Eva Ruiz", "evaruiz", "Clave123",
                                            "Recepcionista"),
            lambda: self.system.delete_user("admin"),
        )
        for operation in denied:
            with self.assertRaises(PermissionDeniedError):
                operation()

    def test_receptionist_does_the_daily_work(self):
        self.login_reception()
        self.assertEqual(self.system.next_code(), "PAC-0001")
        self.register("PAC-0001", "Ana López")
        self.system.call_next()
        self.system.finish_care()
        self.assertEqual(len(self.system.list_care_records()), 1)
        self.assertEqual(self.system.stats()["served"], 1)
        self.assertEqual(len(self.system.search("Nombre", "ana")), 1)


class TestPatients(SystemTestCase):
    def setUp(self):
        super().setUp()
        self.login_reception()

    def test_register_creates_patient_and_first_ticket(self):
        ticket = self.register("pac-0001", "Ana López")  # CP-05
        self.assertEqual(ticket.number, "N-001")
        self.assertEqual(ticket.patient.code, "PAC-0001")
        self.assertEqual(ticket.status.value, "Pendiente")
        self.assertEqual(self.numbers(self.system.pending_normal()), ["N-001"])
        self.assertEqual(self.system.next_code(), "PAC-0002")
        self.system.logout()
        self.login_admin()
        # Most recent first: admin login, receptionist logout, registration.
        action = self.system.action_history()[2]
        self.assertEqual(action.action_type, PATIENT_REGISTRATION)
        self.assertEqual(action.username, "recepcion")

    def test_duplicate_code_saves_nothing(self):  # CP-06
        self.register("PAC-0001", "Ana López")
        with self.assertRaises(DuplicateError) as caught:
            self.register("PAC-0001", "Otra Persona")
        self.assertEqual(
            str(caught.exception), "Ya existe un paciente con el código PAC-0001."
        )
        self.assertEqual(len(self.system.list_patients()), 1)
        self.assertEqual(self.numbers(self.system.pending_normal()), ["N-001"])

    def test_invalid_values_save_nothing(self):
        cases = (
            dict(age="abc"),  # CP-07
            dict(age=150),  # CP-08
            dict(care_type=""),  # CP-10
            dict(care_type="Prioritaria", criterion=None),
            dict(care_type="Prioritaria", criterion="Adulto mayor"),  # CP-11
            dict(reason="Mal"),
        )
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(ValidationError):
                    self.register("PAC-0001", "Ana López", **values)
                self.assertEqual(self.system.list_patients(), [])
                self.assertTrue(self.system.queues_empty())

    def test_bad_phone_saves_nothing(self):  # CP-09
        with self.assertRaises(ValidationError):
            self.system.register_patient(
                "PAC-0001", "Ana López", 30, "1234", "Control general", "Normal"
            )
        self.assertEqual(self.system.list_patients(), [])

    def test_senior_with_enough_age_goes_to_priority_queue(self):
        ticket = self.register("PAC-0001", "Rosa Méndez", age=67,
                               care_type="Prioritaria", criterion="Adulto mayor")
        self.assertEqual(ticket.number, "P-001")
        self.assertEqual(self.numbers(self.system.pending_priority()), ["P-001"])

    def test_rejected_registration_does_not_use_a_number(self):
        with self.assertRaises(ValidationError):
            self.register("PAC-0001", "Ana López", age="abc")
        self.assertEqual(self.register("PAC-0001", "Ana López").number, "N-001")

    def test_new_ticket_for_registered_patient(self):  # RF-17 and CP-12
        self.register("PAC-0001", "Ana López")
        with self.assertRaises(ValidationError) as caught:
            self.system.create_ticket("PAC-0001", "Dolor de espalda", "Normal")
        self.assertEqual(
            str(caught.exception), "Este paciente ya tiene el turno N-001 activo."
        )
        self.system.call_next()
        self.system.finish_care()
        ticket = self.system.create_ticket(
            "PAC-0001", "Dolor de espalda", "Prioritaria", "Urgencia"
        )
        self.assertEqual(ticket.number, "P-002")

    def test_new_ticket_for_unknown_patient(self):
        with self.assertRaises(NotFoundError):
            self.system.create_ticket("PAC-0099", "Dolor de espalda", "Normal")

    def test_update_patient(self):
        self.register("PAC-0001", "Ana López")
        self.system.update_patient("PAC-0001", "Ana María López", "31", "22223333")
        patient = self.system.list_patients()[0]
        self.assertEqual(
            (patient.full_name, patient.age, patient.phone),
            ("Ana María López", 31, "22223333"),
        )

    def test_invalid_update_changes_nothing(self):
        self.register("PAC-0001", "Ana López")
        with self.assertRaises(ValidationError):
            self.system.update_patient("PAC-0001", "Ana María López", "abc", "22223333")
        self.assertEqual(self.system.list_patients()[0].full_name, "Ana López")


class TestQueuesAndCare(SystemTestCase):
    def setUp(self):
        super().setUp()
        self.login_reception()

    def test_priority_first_then_arrival_order(self):  # CP-13
        self.register("PAC-0001", "Ana López")
        self.register("PAC-0002", "Luis Pérez")
        self.register("PAC-0003", "Eva Ruiz", care_type="Prioritaria",
                      criterion="Embarazo")
        self.assertEqual(self.system.peek_next().number, "P-003")
        served = []
        for _ in range(3):
            served.append(self.system.call_next().number)
            self.system.finish_care()
        self.assertEqual(served, ["P-003", "N-001", "N-002"])
        self.assertTrue(self.system.queues_empty())
        self.assertIsNone(self.system.peek_next())

    def test_empty_queues(self):  # CP-14
        with self.assertRaises(EmptyQueueError) as caught:
            self.system.call_next()
        self.assertEqual(str(caught.exception), "No hay pacientes en espera.")

    def test_one_care_at_a_time(self):  # CP-15
        self.register("PAC-0001", "Ana López")
        self.register("PAC-0002", "Luis Pérez")
        self.system.call_next()
        with self.assertRaises(ValidationError) as caught:
            self.system.call_next()
        self.assertEqual(
            str(caught.exception),
            "Finaliza la atención de N-001 antes de llamar al siguiente.",
        )

    def test_finish_records_user_and_date(self):  # CP-16
        self.register("PAC-0001", "Ana López")
        called = self.system.call_next()
        self.assertIs(self.system.in_progress(), called)
        self.assertEqual(self.system.get_status("n-001"), "En atención")
        record = self.system.finish_care()
        self.assertEqual(record.ticket_number, "N-001")
        self.assertEqual(record.served_by, "recepcion")
        self.assertRegex(record.served_at, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertIsNone(self.system.in_progress())
        self.assertEqual(self.system.get_status("N-001"), "Atendido")

    def test_finish_without_care_in_progress(self):
        with self.assertRaises(ValidationError):
            self.system.finish_care()

    def test_status_of_unknown_or_empty_number(self):
        with self.assertRaises(NotFoundError):
            self.system.get_status("N-999")
        with self.assertRaises(ValidationError):
            self.system.get_status("  ")


class TestCancelAndUndo(SystemTestCase):
    def setUp(self):
        super().setUp()
        self.login_admin()
        for code, name in (("PAC-0001", "Ana López"), ("PAC-0002", "Luis Pérez"),
                           ("PAC-0003", "Eva Ruiz")):
            self.register(code, name)

    def test_cancel_takes_ticket_out_of_its_queue(self):  # CP-17
        self.system.cancel_ticket("N-002")
        self.assertEqual(self.system.get_status("N-002"), "Cancelado")
        self.assertEqual(self.numbers(self.system.pending_normal()), ["N-001", "N-003"])
        self.assertEqual(self.system.stats()["normal_queue"], 2)
        self.assertEqual(self.system.last_action().action_type, TICKET_CANCELLATION)

    def test_cancel_served_ticket_is_rejected(self):  # CP-18
        self.system.call_next()
        self.system.finish_care()
        with self.assertRaises(ValidationError) as caught:
            self.system.cancel_ticket("N-001")
        self.assertEqual(
            str(caught.exception), "Solo se pueden cancelar turnos pendientes."
        )

    def test_cancel_needs_a_number(self):
        with self.assertRaises(ValidationError):
            self.system.cancel_ticket("")

    def test_undo_cancel_restores_position(self):  # CP-20
        self.system.cancel_ticket("N-002")
        undone = self.system.undo()
        self.assertEqual(undone.action_type, TICKET_CANCELLATION)
        self.assertTrue(undone.undone)
        self.assertEqual(
            self.numbers(self.system.pending_normal()), ["N-001", "N-002", "N-003"]
        )
        last = self.system.last_action()
        self.assertEqual(last.action_type, UNDONE)
        self.assertEqual(last.username, "admin")

    def test_undo_call_returns_ticket_to_front(self):  # CP-21
        self.system.call_next()
        self.system.undo()
        self.assertEqual(self.system.get_status("N-001"), "Pendiente")
        self.assertEqual(self.system.peek_next().number, "N-001")
        self.assertIsNone(self.system.in_progress())

    def test_nothing_to_undo(self):  # CP-22
        while self.system.can_undo():
            self.system.undo()
        with self.assertRaises(EmptyStackError) as caught:
            self.system.undo()
        self.assertEqual(
            str(caught.exception), "No hay acciones que se puedan deshacer."
        )
        self.assertEqual(self.system.list_patients(), [])

    def test_next_undo_names_the_action_without_undoing_it(self):
        self.system.cancel_ticket("N-002")
        self.system.logout()
        self.login_admin()
        # The logins on top are evidence, so the next undo is still the
        # cancellation, and asking for it changes nothing.
        upcoming = self.system.next_undo()
        self.assertEqual(upcoming.action_type, TICKET_CANCELLATION)
        self.assertEqual(self.system.get_status("N-002"), "Cancelado")
        self.assertIs(self.system.undo(), upcoming)

    def test_next_undo_with_nothing_left(self):
        while self.system.can_undo():
            self.system.undo()
        with self.assertRaises(EmptyStackError):
            self.system.next_undo()

    def test_receptionist_cannot_ask_for_next_undo(self):
        self.system.logout()
        self.login_reception()
        with self.assertRaises(PermissionDeniedError):
            self.system.next_undo()

    def test_undo_registration_and_update(self):
        self.system.update_patient("PAC-0003", "Eva María Ruiz", 40, "77778888")
        self.system.undo()
        patient = self.system.list_patients()[2]
        self.assertEqual((patient.full_name, patient.age), ("Eva Ruiz", 30))
        self.system.undo()
        self.assertEqual(len(self.system.list_patients()), 2)
        self.assertEqual(self.numbers(self.system.pending_normal()), ["N-001", "N-002"])

    def test_undo_finish_brings_care_back(self):
        self.system.call_next()
        self.system.finish_care()
        self.system.undo()
        self.assertEqual(self.system.get_status("N-001"), "En atención")
        self.assertEqual(self.system.list_care_records(), [])

    def test_undo_survives_logout_and_other_users(self):
        # Sections 3.7 and 3.8: the history lives while the program runs,
        # and logins on top of the cancellation do not block its undo.
        self.system.cancel_ticket("N-002")
        self.system.logout()
        self.login_reception()
        self.system.logout()
        self.login_admin()
        undone = self.system.undo()
        self.assertEqual(undone.action_type, TICKET_CANCELLATION)
        self.assertEqual(self.system.get_status("N-002"), "Pendiente")

    def test_undo_is_saved_to_disk(self):
        self.system.cancel_ticket("N-002")
        self.system.undo()
        system = self.reopen()
        system.login(*ADMIN)
        self.assertEqual(
            self.numbers(system.pending_normal()), ["N-001", "N-002", "N-003"]
        )

    def test_history_is_most_recent_first(self):
        self.system.call_next()
        types = [action.action_type for action in self.system.action_history()]
        self.assertEqual(types[0], CALL_NEXT)
        self.assertEqual(types[-1], LOGIN)


class TestQueries(SystemTestCase):
    def setUp(self):
        super().setUp()
        self.login_admin()

    def test_partial_name_search(self):  # CP-23
        self.register("PAC-0001", "María Gómez")
        self.register("PAC-0002", "Marco Díaz")
        self.register("PAC-0003", "Luis Pérez")
        found = self.system.search("Nombre", "mar")
        self.assertEqual(self.numbers(found), ["N-001", "N-002"])

    def test_search_without_results(self):  # CP-24
        self.register("PAC-0001", "María Gómez")
        self.assertEqual(self.system.search("Código de paciente", "PAC-9999"), [])

    def test_search_with_empty_text(self):
        with self.assertRaises(ValidationError):
            self.system.search("Nombre", " ")

    def test_stats(self):  # CP-25
        self.register("PAC-0001", "Ana López")
        self.register("PAC-0002", "Luis Pérez")
        self.register("PAC-0003", "Eva Ruiz", care_type="Prioritaria",
                      criterion="Discapacidad")
        self.system.call_next()
        self.system.finish_care()
        stats = self.system.stats()
        self.assertEqual(stats["registered_patients"], 3)
        self.assertEqual(stats["pending"], 2)
        self.assertEqual(stats["served"], 1)
        self.assertEqual(stats["normal"], 2)
        self.assertEqual(stats["priority"], 1)
        self.assertEqual(stats["normal_queue"], 2)
        self.assertEqual(stats["priority_queue"], 0)

    def test_lists_for_the_comboboxes(self):
        self.assertEqual(self.system.care_type_names(), ["Normal", "Prioritaria"])
        self.assertEqual(
            self.system.priority_criteria(),
            ["Adulto mayor", "Embarazo", "Discapacidad", "Urgencia"],
        )
        self.assertEqual(self.system.roles(), ["Administrador", "Recepcionista"])
        self.assertEqual(
            self.system.search_criteria(),
            ["Código de paciente", "Nombre", "Número de turno", "Estado",
             "Tipo de atención"],
        )
        self.assertEqual(
            self.system.search_suggestions("Tipo de atención"),
            ["Normal", "Prioritaria"],
        )
        self.assertEqual(self.system.search_suggestions("Nombre"), [])
        self.assertEqual(self.system.search_suggestions("Teléfono"), [])


class TestUsers(SystemTestCase):
    def setUp(self):
        super().setUp()
        self.login_admin()

    def test_create_and_delete_user_as_evidence(self):
        user = self.system.create_user("Eva Ruiz", "evaruiz", "Clave123",
                                       "Recepcionista")
        self.assertEqual(user.role, "Recepcionista")
        self.assertEqual(self.system.last_action().action_type, USER_MANAGEMENT)
        self.assertFalse(self.system.can_undo())
        self.system.delete_user("evaruiz")
        names = [u.username for u in self.system.list_users()]
        self.assertNotIn("evaruiz", names)

    def test_new_user_can_log_in_after_restart(self):
        self.system.create_user("Eva Ruiz", "evaruiz", "Clave123", "Administrador")
        system = self.reopen()
        self.assertEqual(system.login("evaruiz", "Clave123").role, "Administrador")

    def test_cannot_delete_own_account(self):
        with self.assertRaises(ValidationError):
            self.system.delete_user("admin")

    def test_duplicate_username(self):
        with self.assertRaises(DuplicateError):
            self.system.create_user("Otro Admin", "ADMIN", "Clave123",
                                    "Administrador")


class TestChangePassword(SystemTestCase):
    """The administrator changes others' passwords (RF-43); everyone changes their own (RF-44)."""

    def test_admin_changes_receptionist_password(self):
        self.login_admin()
        self.system.change_password("recepcion", "Nueva123", "Nueva123")
        action = self.system.last_action()
        self.assertEqual(action.action_type, USER_MANAGEMENT)
        self.assertEqual(
            action.description, "Se cambió la contraseña del usuario recepcion."
        )
        self.assertNotIn("Nueva123", action.description)
        self.assertNotIn("Nueva123", str(action.data))
        self.assertFalse(self.system.can_undo())
        self.system.logout()
        with self.assertRaises(InvalidCredentialsError):
            self.system.login(*RECEPTION)
        self.assertEqual(self.system.login("recepcion", "Nueva123").username,
                         "recepcion")

    def test_admin_cannot_change_own_password_from_users(self):
        self.login_admin()
        with self.assertRaises(ValidationError) as caught:
            self.system.change_password("admin", "Nueva123", "Nueva123")
        self.assertEqual(
            str(caught.exception),
            "Para cambiar tu propia contraseña usa Archivo > Cambiar mi contraseña.",
        )

    def test_receptionist_cannot_change_others(self):
        self.login_reception()
        with self.assertRaises(PermissionDeniedError):
            self.system.change_password("admin", "Nueva123", "Nueva123")
        self.system.logout()
        self.assertEqual(self.login_admin().username, "admin")

    def test_confirmation_must_match(self):
        self.login_admin()
        with self.assertRaises(ValidationError) as caught:
            self.system.change_password("recepcion", "Nueva123", "Nueva124")
        self.assertEqual(
            str(caught.exception),
            "La contraseña nueva y su confirmación no coinciden.",
        )

    def test_empty_fields_are_named(self):
        self.login_admin()
        cases = (
            (("recepcion", "", "Nueva123"), "Completa el campo Nueva contraseña."),
            (("recepcion", "Nueva123", "  "), "Completa el campo Confirmar contraseña."),
        )
        for args, message in cases:
            with self.assertRaises(ValidationError) as caught:
                self.system.change_password(*args)
            self.assertEqual(str(caught.exception), message)

    def test_unknown_user(self):
        self.login_admin()
        with self.assertRaises(NotFoundError):
            self.system.change_password("nadie", "Nueva123", "Nueva123")

    def test_receptionist_changes_own_password(self):
        self.login_reception()
        self.system.change_own_password("Recep123", "Nueva123", "Nueva123")
        self.system.logout()
        system = self.reopen()
        self.assertEqual(system.login("recepcion", "Nueva123").username, "recepcion")

    def test_own_change_is_evidence_in_the_history(self):
        self.login_reception()
        self.system.change_own_password("Recep123", "Nueva123", "Nueva123")
        self.system.logout()
        self.login_admin()
        changes = [a for a in self.system.action_history()
                   if a.action_type == USER_MANAGEMENT]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].description,
                         "Recepcionista General cambió su contraseña.")
        self.assertEqual(changes[0].username, "recepcion")
        self.assertFalse(changes[0].is_undoable)

    def test_wrong_current_password_changes_nothing(self):
        self.login_reception()
        with self.assertRaises(ValidationError) as caught:
            self.system.change_own_password("recep123", "Nueva123", "Nueva123")
        self.assertEqual(
            str(caught.exception), "La contraseña actual no es correcta."
        )
        self.system.logout()
        self.assertEqual(self.login_reception().username, "recepcion")

    def test_own_change_checks_the_fields_first(self):
        self.login_reception()
        cases = (
            (("", "Nueva123", "Nueva123"), "Completa el campo Contraseña actual."),
            (("Recep123", "Nueva123", "Otra1234"),
             "La contraseña nueva y su confirmación no coinciden."),
            (("Recep123", "123", "123"),
             "La contraseña debe tener al menos 6 caracteres."),
            (("Recep123", "Recep123", "Recep123"),
             "La contraseña nueva debe ser distinta de la actual."),
        )
        for args, message in cases:
            with self.assertRaises(ValidationError) as caught:
                self.system.change_own_password(*args)
            self.assertEqual(str(caught.exception), message)
        # A mismatch is reported even when the current password is wrong too.
        with self.assertRaises(ValidationError) as caught:
            self.system.change_own_password("mala", "Nueva123", "Otra1234")
        self.assertIn("no coinciden", str(caught.exception))

    def test_own_change_needs_a_session(self):
        with self.assertRaises(PermissionDeniedError) as caught:
            self.system.change_own_password("Admin123", "Nueva123", "Nueva123")
        self.assertEqual(str(caught.exception), "Inicia sesión para continuar.")

    def test_admin_changes_own_password(self):
        self.login_admin()
        self.system.change_own_password("Admin123", "Nueva123", "Nueva123")
        self.system.logout()
        with self.assertRaises(InvalidCredentialsError):
            self.login_admin()
        self.assertEqual(self.system.login("admin", "Nueva123").role, "Administrador")


class TestFullWalkthrough(SystemTestCase):
    """Login, registration, care, cancellation, undo, search, stats and restart."""

    def test_a_day_at_the_clinic(self):
        self.login_reception()
        self.register("PAC-0001", "Ana López")
        self.register("PAC-0002", "José Peña")
        self.register("PAC-0003", "María Gómez", age=67,
                      care_type="Prioritaria", criterion="Adulto mayor")
        self.assertEqual(self.system.call_next().number, "P-003")
        self.system.finish_care()
        with self.assertRaises(PermissionDeniedError):
            self.system.cancel_ticket("N-002")
        self.system.logout()

        self.login_admin()
        self.register("PAC-0004", "Marco Díaz")
        self.system.cancel_ticket("N-002")
        self.assertEqual(self.numbers(self.system.pending_normal()), ["N-001", "N-004"])
        self.system.undo()
        self.assertEqual(
            self.numbers(self.system.pending_normal()), ["N-001", "N-002", "N-004"]
        )
        self.assertEqual(
            self.numbers(self.system.search("Nombre", "mar")), ["P-003", "N-004"]
        )
        stats = self.system.stats()
        self.assertEqual(
            (stats["registered_patients"], stats["pending"], stats["served"],
             stats["cancelled"], stats["priority"]),
            (4, 3, 1, 0, 1),
        )

        # Restart: queues, care records and accents come back from the files.
        system = self.reopen()
        system.login(*ADMIN)
        self.assertEqual(
            self.numbers(system.pending_normal()), ["N-001", "N-002", "N-004"]
        )
        self.assertEqual(len(system.list_care_records()), 1)
        self.assertFalse(system.can_undo())
        raw = (self.folder / "patients.json").read_bytes()
        self.assertIn("José Peña".encode("utf-8"), raw)
        self.assertNotIn(b"\\u00e9", raw)


if __name__ == "__main__":
    unittest.main()
