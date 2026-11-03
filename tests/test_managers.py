"""Tests for UserManager and PatientManager (step C7), and for the search
criteria and ClinicStats (step C11).

Every test works with a JsonRepository inside a tempfile.TemporaryDirectory,
so the real data folder is never touched.

Run from the project root with: python -m unittest discover tests
"""

import json
import tempfile
import unittest
from pathlib import Path

from models.care_type import NormalCare, PriorityCare
from models.patient import Patient
from models.user import (
    ADMINISTRATOR_ROLE,
    RECEPTIONIST_ROLE,
    Administrator,
    Receptionist,
)
from persistence.json_repository import JsonRepository
from services.patient_manager import PatientManager
from services.search import (
    CRITERIA,
    ByCareType,
    ByPatientCode,
    ByPatientName,
    ByStatus,
    ByTicketNumber,
    SearchCriterion,
    search,
)
from services.stats import ClinicStats
from services.ticket_manager import TicketManager
from services.user_manager import UserManager
from utils.exceptions import (
    CorruptedFileError,
    DuplicateError,
    InvalidCredentialsError,
    NotFoundError,
    ValidationError,
)


class ManagerTestCase(unittest.TestCase):
    """Creates a repository in a fresh temporary folder for each test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name) / "data"
        self.repo = JsonRepository(str(self.folder))

    def tearDown(self):
        self._tmp.cleanup()

    def read_json(self, filename: str) -> list:
        with open(self.folder / filename, "r", encoding="utf-8") as file:
            return json.load(file)

    def write_raw(self, filename: str, text: str) -> None:
        (self.folder / filename).write_text(text, encoding="utf-8")


# ----------------------------------------------------------------- users


class UserManagerTestCase(ManagerTestCase):
    def setUp(self):
        super().setUp()
        self.manager = UserManager(self.repo)
        self.manager.load()
        self.admin = self.manager.login("admin", "Admin123")

    def reloaded(self) -> UserManager:
        """A second manager that reads the same folder, as after a restart."""
        manager = UserManager(JsonRepository(str(self.folder)))
        manager.load()
        return manager


class TestDefaultUsers(ManagerTestCase):
    def test_missing_file_creates_admin_and_receptionist(self):
        manager = UserManager(self.repo)
        manager.load()
        users = {user.username: user for user in manager.list_all()}
        self.assertEqual(set(users), {"admin", "recepcion"})
        self.assertIsInstance(users["admin"], Administrator)
        self.assertIsInstance(users["recepcion"], Receptionist)

    def test_default_users_are_saved_to_the_file(self):
        UserManager(self.repo).load()
        rows = self.read_json("users.json")
        self.assertEqual(
            {row["username"]: row["role"] for row in rows},
            {"admin": ADMINISTRATOR_ROLE, "recepcion": RECEPTIONIST_ROLE},
        )

    def test_file_never_holds_the_plain_passwords(self):
        UserManager(self.repo).load()
        text = (self.folder / "users.json").read_text(encoding="utf-8")
        self.assertNotIn("Admin123", text)
        self.assertNotIn("Recep123", text)

    def test_empty_list_creates_default_users(self):
        self.write_raw("users.json", "[]")
        manager = UserManager(self.repo)
        manager.load()
        self.assertEqual(len(manager.list_all()), 2)

    def test_existing_users_get_no_defaults(self):
        user = Administrator.create("Ana López", "analopez", "secreto1")
        self.repo.save("users.json", [user.to_dict()])
        manager = UserManager(self.repo)
        manager.load()
        self.assertEqual([u.username for u in manager.list_all()], ["analopez"])

    def test_damaged_file_creates_defaults_and_warns(self):
        self.write_raw("users.json", "{esto no es json")
        manager = UserManager(self.repo)
        with self.assertRaises(CorruptedFileError):
            manager.load()
        # The clinic can still log in, and the damaged file was kept.
        self.assertIsInstance(manager.login("admin", "Admin123"), Administrator)
        self.assertEqual(len(list(self.folder.glob("users.corrupted-*.json"))), 1)

    def test_repeated_username_in_file_is_rejected(self):
        row = Administrator.create("Ana López", "analopez", "secreto1").to_dict()
        self.repo.save("users.json", [row, row])
        with self.assertRaises(ValidationError) as context:
            UserManager(self.repo).load()
        self.assertIn("analopez", str(context.exception))


class TestLogin(UserManagerTestCase):
    def test_correct_credentials_return_the_user(self):
        self.assertIsInstance(self.admin, Administrator)
        self.assertIsInstance(
            self.manager.login("recepcion", "Recep123"), Receptionist
        )

    def test_wrong_password_is_rejected(self):
        with self.assertRaises(InvalidCredentialsError):
            self.manager.login("admin", "clave")

    def test_unknown_user_gets_the_same_message(self):
        with self.assertRaises(InvalidCredentialsError) as wrong_password:
            self.manager.login("admin", "clave")
        with self.assertRaises(InvalidCredentialsError) as unknown_user:
            self.manager.login("nadie", "Admin123")
        self.assertEqual(str(wrong_password.exception), str(unknown_user.exception))
        self.assertEqual(
            str(unknown_user.exception), "Usuario o contraseña incorrectos."
        )

    def test_username_is_case_sensitive(self):
        with self.assertRaises(InvalidCredentialsError):
            self.manager.login("ADMIN", "Admin123")

    def test_empty_username_asks_for_the_field(self):
        with self.assertRaises(ValidationError) as context:
            self.manager.login("", "Admin123")
        self.assertEqual(str(context.exception), "Completa el campo Usuario.")

    def test_empty_password_asks_for_the_field(self):
        with self.assertRaises(ValidationError) as context:
            self.manager.login("admin", "   ")
        self.assertEqual(str(context.exception), "Completa el campo Contraseña.")

    def test_spaces_around_the_username_are_ignored(self):
        self.assertEqual(self.manager.login("  admin ", "Admin123").username, "admin")


class TestCreateUser(UserManagerTestCase):
    def test_new_user_can_log_in_after_a_restart(self):
        created = self.manager.create_user(
            "María Núñez", "mnunez", "clave123", RECEPTIONIST_ROLE
        )
        self.assertIsInstance(created, Receptionist)
        user = self.reloaded().login("mnunez", "clave123")
        self.assertEqual(user.full_name, "María Núñez")

    def test_role_decides_the_class(self):
        user = self.manager.create_user(
            "Luis Pérez", "lperez", "clave123", ADMINISTRATOR_ROLE
        )
        self.assertIsInstance(user, Administrator)

    def test_duplicate_username_is_rejected(self):
        with self.assertRaises(DuplicateError) as context:
            self.manager.create_user("Otro Admin", "admin", "clave123", ADMINISTRATOR_ROLE)
        self.assertEqual(str(context.exception), "Ese nombre de usuario ya existe.")

    def test_duplicate_ignores_case(self):
        with self.assertRaises(DuplicateError):
            self.manager.create_user("Otro Admin", "Admin", "clave123", ADMINISTRATOR_ROLE)

    def test_unknown_role_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.manager.create_user("Luis Pérez", "lperez", "clave123", "Doctor")

    def test_invalid_data_adds_nothing(self):
        with self.assertRaises(ValidationError):
            self.manager.create_user("Luis Pérez", "lperez", "123", RECEPTIONIST_ROLE)
        with self.assertRaises(ValidationError):
            self.manager.create_user("Luis Pérez", "lp", "clave123", RECEPTIONIST_ROLE)
        self.assertEqual(len(self.manager.list_all()), 2)
        self.assertEqual(len(self.read_json("users.json")), 2)

    def test_list_all_is_sorted_by_username(self):
        self.manager.create_user("Beto Ruiz", "beto", "clave123", RECEPTIONIST_ROLE)
        self.assertEqual(
            [user.username for user in self.manager.list_all()],
            ["admin", "beto", "recepcion"],
        )


class TestDeleteUser(UserManagerTestCase):
    def test_delete_removes_the_user_from_memory_and_file(self):
        self.manager.delete_user("recepcion", self.admin)
        self.assertEqual([u.username for u in self.manager.list_all()], ["admin"])
        self.assertEqual([u.username for u in self.reloaded().list_all()], ["admin"])

    def test_nobody_deletes_their_own_account(self):
        with self.assertRaises(ValidationError) as context:
            self.manager.delete_user("admin", self.admin)
        self.assertEqual(str(context.exception), "No puedes eliminar tu propia cuenta.")
        self.assertEqual(len(self.manager.list_all()), 2)

    def test_last_administrator_cannot_be_deleted(self):
        # Only a call that skips ClinicSystem's permission check can get
        # here, but the manager still has to protect the rule on its own.
        receptionist = self.manager.login("recepcion", "Recep123")
        with self.assertRaises(ValidationError) as context:
            self.manager.delete_user("admin", receptionist)
        self.assertEqual(
            str(context.exception), "Debe quedar al menos un administrador."
        )
        self.assertEqual(len(self.manager.list_all()), 2)

    def test_an_administrator_can_go_if_another_remains(self):
        self.manager.create_user("Luis Pérez", "lperez", "clave123", ADMINISTRATOR_ROLE)
        self.manager.delete_user("lperez", self.admin)
        self.assertEqual(
            [user.username for user in self.manager.list_all()],
            ["admin", "recepcion"],
        )

    def test_unknown_user_is_not_found(self):
        with self.assertRaises(NotFoundError):
            self.manager.delete_user("nadie", self.admin)


# -------------------------------------------------------------- patients


class PatientManagerTestCase(ManagerTestCase):
    def setUp(self):
        super().setUp()
        self.manager = PatientManager(self.repo)
        self.manager.load()

    def register(self, code: str, name: str = "Ana López", age: int = 30) -> Patient:
        patient = Patient(code, name, age, "55551234")
        self.manager.register(patient)
        return patient

    def reloaded(self) -> PatientManager:
        manager = PatientManager(JsonRepository(str(self.folder)))
        manager.load()
        return manager


class TestPatientLoad(PatientManagerTestCase):
    def test_missing_file_starts_empty_and_creates_it(self):
        self.assertEqual(self.manager.count(), 0)
        self.assertEqual(self.read_json("patients.json"), [])

    def test_saved_patients_come_back_the_same(self):
        original = self.register("PAC-0001", "José Peña", 64)
        loaded = self.reloaded().get("PAC-0001")
        self.assertEqual(loaded.to_dict(), original.to_dict())

    def test_names_are_saved_as_real_utf8(self):
        self.register("PAC-0001", "José Peña")
        raw = (self.folder / "patients.json").read_bytes()
        self.assertIn("José Peña".encode("utf-8"), raw)
        self.assertNotIn(b"\\u00e9", raw)

    def test_repeated_code_in_file_is_rejected(self):
        row = Patient("PAC-0001", "Ana López", 30, "55551234").to_dict()
        self.repo.save("patients.json", [row, row])
        with self.assertRaises(ValidationError) as context:
            PatientManager(self.repo).load()
        self.assertIn("PAC-0001", str(context.exception))

    def test_damaged_file_leaves_the_manager_empty(self):
        self.register("PAC-0001")
        self.write_raw("patients.json", "[{roto")
        with self.assertRaises(CorruptedFileError):
            self.manager.load()
        self.assertEqual(self.manager.count(), 0)


class TestRegister(PatientManagerTestCase):
    def test_register_adds_and_saves(self):
        self.register("PAC-0001")
        self.assertTrue(self.manager.exists("PAC-0001"))
        self.assertEqual(self.manager.count(), 1)
        self.assertEqual(self.read_json("patients.json")[0]["code"], "PAC-0001")

    def test_duplicate_code_is_rejected(self):
        self.register("PAC-0001", "Ana López")
        with self.assertRaises(DuplicateError) as context:
            self.register("PAC-0001", "Marco Díaz")
        self.assertEqual(
            str(context.exception), "Ya existe un paciente con el código PAC-0001."
        )
        # The first patient stays, in memory and in the file.
        self.assertEqual(self.manager.get("PAC-0001").full_name, "Ana López")
        self.assertEqual(len(self.read_json("patients.json")), 1)

    def test_duplicate_code_typed_in_lower_case_is_rejected(self):
        self.register("PAC-0001")
        with self.assertRaises(DuplicateError):
            self.register("pac-0001")


class TestQueries(PatientManagerTestCase):
    def test_get_returns_the_patient(self):
        patient = self.register("PAC-0001")
        self.assertIs(self.manager.get("PAC-0001"), patient)

    def test_get_accepts_lower_case_and_spaces(self):
        patient = self.register("PAC-0001")
        self.assertIs(self.manager.get("  pac-0001 "), patient)
        self.assertTrue(self.manager.exists("pac-0001"))

    def test_unknown_code_is_not_found(self):
        with self.assertRaises(NotFoundError) as context:
            self.manager.get("PAC-9999")
        self.assertEqual(
            str(context.exception), "No existe un paciente con el código PAC-9999."
        )
        self.assertFalse(self.manager.exists("PAC-9999"))

    def test_list_all_is_sorted_by_code(self):
        self.register("PAC-0003")
        self.register("PAC-0001")
        self.register("PAC-0002")
        self.assertEqual(
            [patient.code for patient in self.manager.list_all()],
            ["PAC-0001", "PAC-0002", "PAC-0003"],
        )

    def test_patients_by_code_is_a_copy(self):
        patient = self.register("PAC-0001")
        copy = self.manager.patients_by_code()
        self.assertIs(copy["PAC-0001"], patient)
        copy.clear()
        self.assertEqual(self.manager.count(), 1)


class TestNextCode(PatientManagerTestCase):
    def test_first_code_is_one(self):
        self.assertEqual(self.manager.next_code(), "PAC-0001")

    def test_next_code_follows_the_highest(self):
        self.register("PAC-0001")
        self.register("PAC-0007")
        self.register("PAC-0003")
        self.assertEqual(self.manager.next_code(), "PAC-0008")

    def test_next_code_after_a_restart(self):
        self.register("PAC-0012")
        self.assertEqual(self.reloaded().next_code(), "PAC-0013")

    def test_no_code_left_after_9999(self):
        self.register("PAC-9999")
        with self.assertRaises(ValidationError):
            self.manager.next_code()


class TestUpdateAndDelete(PatientManagerTestCase):
    def test_update_returns_previous_values_and_saves(self):
        self.register("PAC-0001", "Ana López", 30)
        previous = self.manager.update("PAC-0001", "Ana López-Pérez", "31", "22223333")
        self.assertEqual(
            previous, {"full_name": "Ana López", "age": 30, "phone": "55551234"}
        )
        saved = self.reloaded().get("PAC-0001")
        self.assertEqual(
            (saved.full_name, saved.age, saved.phone),
            ("Ana López-Pérez", 31, "22223333"),
        )

    def test_previous_values_restore_the_patient(self):
        self.register("PAC-0001", "Ana López", 30)
        previous = self.manager.update("PAC-0001", "Ana Ruiz", 40, "22223333")
        self.manager.update("PAC-0001", **previous)
        self.assertEqual(
            self.reloaded().get("PAC-0001").to_dict(),
            self.manager.get("PAC-0001").to_dict(),
        )
        self.assertEqual(self.manager.get("PAC-0001").full_name, "Ana López")

    def test_invalid_update_changes_nothing(self):
        self.register("PAC-0001", "Ana López", 30)
        before = self.read_json("patients.json")
        with self.assertRaises(ValidationError):
            self.manager.update("PAC-0001", "Ana Ruiz", "abc", "22223333")
        patient = self.manager.get("PAC-0001")
        self.assertEqual((patient.full_name, patient.age), ("Ana López", 30))
        self.assertEqual(self.read_json("patients.json"), before)

    def test_update_unknown_code_is_not_found(self):
        with self.assertRaises(NotFoundError):
            self.manager.update("PAC-0001", "Ana López", 30, "55551234")

    def test_delete_removes_and_saves(self):
        self.register("PAC-0001")
        self.register("PAC-0002")
        self.manager.delete("PAC-0002")
        self.assertFalse(self.manager.exists("PAC-0002"))
        self.assertEqual(self.reloaded().count(), 1)
        # The deleted code is free again, because it was the highest.
        self.assertEqual(self.manager.next_code(), "PAC-0002")

    def test_delete_unknown_code_is_not_found(self):
        with self.assertRaises(NotFoundError):
            self.manager.delete("PAC-0001")


# ------------------------------------------------------ search and stats


class ClinicDataTestCase(ManagerTestCase):
    """A patient manager and a ticket manager sharing one temporary folder."""

    def setUp(self):
        super().setUp()
        self.patients = PatientManager(self.repo)
        self.patients.load()
        self.tickets = TicketManager(self.repo)
        self.tickets.load(self.patients.patients_by_code())

    def add(self, code, name, age=30, care_type=None, reason="Dolor de cabeza"):
        """Register a patient and give them a ticket, as register_patient will."""
        patient = Patient(code, name, age, "55551234")
        self.patients.register(patient)
        return self.tickets.create_ticket(patient, care_type or NormalCare(), reason)

    def found(self, criterion_name, text):
        """Numbers of the tickets search() returns."""
        results = search(self.tickets.list_tickets(), criterion_name, text)
        return [ticket.number for ticket in results]


class TestSearchCriteria(ClinicDataTestCase):
    def test_search_criterion_is_abstract(self):
        with self.assertRaises(TypeError):
            SearchCriterion()

    def test_criteria_has_the_five_names_in_combobox_order(self):
        self.assertEqual(
            list(CRITERIA),
            [
                "Código de paciente",
                "Nombre",
                "Número de turno",
                "Estado",
                "Tipo de atención",
            ],
        )

    def test_each_entry_is_a_criterion_under_its_own_name(self):
        classes = (ByPatientCode, ByPatientName, ByTicketNumber, ByStatus, ByCareType)
        for (name, criterion), cls in zip(CRITERIA.items(), classes):
            with self.subTest(name=name):
                self.assertIsInstance(criterion, cls)
                self.assertIsInstance(criterion, SearchCriterion)
                self.assertEqual(criterion.name, name)

    def test_normalize_drops_case_accents_and_extra_spaces(self):
        self.assertEqual(
            SearchCriterion._normalize("  MARÍA   José  Peña "), "maria jose pena"
        )

    def test_same_ticket_answers_differently_per_criterion(self):
        ticket = self.add("PAC-0001", "María López")
        self.assertTrue(CRITERIA["Nombre"].matches(ticket, "lópez"))
        self.assertFalse(CRITERIA["Código de paciente"].matches(ticket, "lópez"))
        self.assertTrue(CRITERIA["Número de turno"].matches(ticket, "n-001"))
        self.assertTrue(CRITERIA["Estado"].matches(ticket, "pendiente"))
        self.assertTrue(CRITERIA["Tipo de atención"].matches(ticket, "normal"))


class TestSearch(ClinicDataTestCase):
    def setUp(self):
        super().setUp()
        self.add("PAC-0001", "María López")
        self.add("PAC-0002", "Marco Díaz", 70, PriorityCare("Adulto mayor"))
        self.add("PAC-0003", "Ana Ruiz")

    def test_cp23_partial_name_finds_maria_and_marco(self):
        self.assertEqual(self.found("Nombre", "mar"), ["N-001", "P-002"])

    def test_name_ignores_case_and_accents(self):
        self.assertEqual(self.found("Nombre", "MARIA"), ["N-001"])
        self.assertEqual(self.found("Nombre", "díaz"), ["P-002"])
        self.assertEqual(self.found("Nombre", "  maría   lópez "), ["N-001"])

    def test_cp24_unknown_code_returns_no_results(self):
        self.assertEqual(self.found("Código de paciente", "PAC-9999"), [])

    def test_code_is_exact_and_ignores_case(self):
        self.assertEqual(self.found("Código de paciente", "pac-0002"), ["P-002"])
        self.assertEqual(self.found("Código de paciente", "PAC-000"), [])

    def test_ticket_number_is_exact(self):
        self.assertEqual(self.found("Número de turno", "p-002"), ["P-002"])
        self.assertEqual(self.found("Número de turno", "002"), [])

    def test_status_follows_the_ticket(self):
        self.tickets.call_next()
        self.tickets.cancel_ticket("N-003")
        self.assertEqual(self.found("Estado", "Pendiente"), ["N-001"])
        self.assertEqual(self.found("Estado", "en atencion"), ["P-002"])
        self.assertEqual(self.found("Estado", "CANCELADO"), ["N-003"])
        self.assertEqual(self.found("Estado", "Atendido"), [])

    def test_care_type(self):
        self.assertEqual(self.found("Tipo de atención", "prioritaria"), ["P-002"])
        self.assertEqual(self.found("Tipo de atención", "Normal"), ["N-001", "N-003"])

    def test_empty_text_is_rejected(self):
        for text in ("", "   ", None):
            with self.subTest(text=text):
                with self.assertRaises(ValidationError) as context:
                    search(self.tickets.list_tickets(), "Nombre", text)
                self.assertEqual(
                    str(context.exception), "Escribe el texto que quieres buscar."
                )

    def test_missing_or_unknown_criterion_is_rejected(self):
        with self.assertRaises(ValidationError) as context:
            search(self.tickets.list_tickets(), "", "mar")
        self.assertEqual(
            str(context.exception), "Selecciona un criterio de búsqueda."
        )
        with self.assertRaises(ValidationError):
            search(self.tickets.list_tickets(), "Teléfono", "5555")

    def test_search_does_not_change_the_tickets(self):
        before = [ticket.to_dict() for ticket in self.tickets.list_tickets()]
        self.found("Nombre", "mar")
        after = [ticket.to_dict() for ticket in self.tickets.list_tickets()]
        self.assertEqual(after, before)
        self.assertEqual(self.tickets.normal_count(), 2)


class TestClinicStats(ClinicDataTestCase):
    def setUp(self):
        super().setUp()
        self.stats = ClinicStats(self.patients, self.tickets)

    def test_empty_clinic_counts_zero(self):
        self.assertEqual(
            self.stats.compute(),
            {
                "registered_patients": 0,
                "pending": 0,
                "in_progress": 0,
                "served": 0,
                "cancelled": 0,
                "normal": 0,
                "priority": 0,
                "normal_queue": 0,
                "priority_queue": 0,
            },
        )

    def test_cp25_two_normal_one_priority_one_served(self):
        self.add("PAC-0001", "Ana López")
        self.add("PAC-0002", "Marco Díaz")
        self.add("PAC-0003", "Rosa Peña", 30, PriorityCare("Embarazo"))
        served = self.tickets.call_next()
        self.tickets.finish_care("admin")

        self.assertEqual(served.number, "P-003")
        result = self.stats.compute()
        self.assertEqual(result["registered_patients"], 3)
        self.assertEqual(result["pending"], 2)
        self.assertEqual(result["in_progress"], 0)
        self.assertEqual(result["served"], 1)
        self.assertEqual(result["cancelled"], 0)
        self.assertEqual(result["normal"], 2)
        self.assertEqual(result["priority"], 1)
        self.assertEqual(result["normal_queue"], 2)
        self.assertEqual(result["priority_queue"], 0)

    def test_counts_follow_every_change(self):
        self.add("PAC-0001", "Ana López")
        self.add("PAC-0002", "Marco Díaz")
        self.assertEqual(self.stats.compute()["normal_queue"], 2)

        self.tickets.call_next()
        result = self.stats.compute()
        self.assertEqual((result["pending"], result["in_progress"]), (1, 1))

        self.tickets.cancel_ticket("N-002")
        result = self.stats.compute()
        self.assertEqual((result["pending"], result["cancelled"]), (0, 1))
        self.assertEqual(result["normal_queue"], 0)
        # A cancelled ticket still counts as a normal ticket.
        self.assertEqual(result["normal"], 2)

    def test_undo_helpers_are_reflected(self):
        self.add("PAC-0001", "Ana López")
        self.tickets.call_next()
        self.tickets.finish_care("admin")
        self.assertEqual(self.stats.compute()["served"], 1)

        ticket = self.tickets.get("N-001")
        self.tickets.revert_finish(ticket)
        result = self.stats.compute()
        self.assertEqual((result["served"], result["in_progress"]), (0, 1))

    def test_patient_without_ticket_still_counts_as_registered(self):
        self.patients.register(Patient("PAC-0001", "Ana López", 30, "55551234"))
        result = self.stats.compute()
        self.assertEqual(result["registered_patients"], 1)
        self.assertEqual(result["pending"], 0)

    def test_status_counts_add_up_to_the_ticket_total(self):
        self.add("PAC-0001", "Ana López")
        self.add("PAC-0002", "Marco Díaz", 70, PriorityCare("Adulto mayor"))
        self.add("PAC-0003", "Rosa Peña")
        self.tickets.call_next()
        self.tickets.cancel_ticket("N-003")
        result = self.stats.compute()
        by_status = sum(
            result[key] for key in ("pending", "in_progress", "served", "cancelled")
        )
        self.assertEqual(by_status, result["normal"] + result["priority"])
        self.assertEqual(
            result["pending"], result["normal_queue"] + result["priority_queue"]
        )


if __name__ == "__main__":
    unittest.main()
