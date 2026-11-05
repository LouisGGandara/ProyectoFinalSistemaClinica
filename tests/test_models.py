"""Tests for the models package.

Part 1 (step C2): Permission, Person, User, Administrator and Receptionist.
Part 2 (step C3): Patient.
Part 3 (step C4): TicketStatus, CareType and its subclasses, Ticket and CareRecord.
"""

import json
import unittest

from models.care_record import CareRecord
from models.care_type import (
    CARE_TYPE_NAMES,
    CareType,
    NormalCare,
    PriorityCare,
    make_care_type,
)
from models.patient import Patient
from models.permissions import Permission
from models.person import Person
from models.user import (
    ADMINISTRATOR_ROLE,
    RECEPTIONIST_ROLE,
    Administrator,
    Receptionist,
    User,
    user_from_dict,
)
from models.ticket import Ticket
from models.ticket_status import TicketStatus
from utils.dates import parse_date
from utils.exceptions import NotUndoableError, ValidationError

ADMIN_ONLY = {
    Permission.CANCEL_TICKET,
    Permission.UNDO,
    Permission.VIEW_ACTION_LOG,
    Permission.MANAGE_USERS,
}


class TestPermission(unittest.TestCase):
    def test_has_the_twelve_permissions_of_step_c2(self):
        names = {permission.name for permission in Permission}
        self.assertEqual(
            names,
            {
                "REGISTER_PATIENT",
                "UPDATE_PATIENT",
                "CREATE_TICKET",
                "SEARCH",
                "VIEW_QUEUES",
                "SERVE",
                "VIEW_CARE_HISTORY",
                "VIEW_STATS",
                "CANCEL_TICKET",
                "UNDO",
                "VIEW_ACTION_LOG",
                "MANAGE_USERS",
            },
        )

    def test_values_are_spanish_labels(self):
        self.assertEqual(Permission.CANCEL_TICKET.value, "Cancelar turno")
        self.assertEqual(len({p.value for p in Permission}), len(Permission))


class TestPerson(unittest.TestCase):
    def test_person_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            Person("Ana López")

    def test_subclass_without_description_cannot_be_instantiated(self):
        class Incomplete(Person):
            pass

        with self.assertRaises(TypeError):
            Incomplete("Ana López")

    def test_full_name_setter_cleans_and_validates(self):
        class Visitor(Person):
            def description(self) -> str:
                return self.full_name

        visitor = Visitor("  Ana   López-Pérez ")
        self.assertEqual(visitor.full_name, "Ana López-Pérez")
        self.assertEqual(str(visitor), "Ana López-Pérez")
        with self.assertRaises(ValidationError):
            visitor.full_name = "Ana--López"
        # A rejected value leaves the previous name in place.
        self.assertEqual(visitor.full_name, "Ana López-Pérez")


class TestUser(unittest.TestCase):
    def setUp(self):
        self.admin = Administrator.create("Luis Gándara", "admin", "Admin123")
        self.receptionist = Receptionist.create("María Peña", "recepcion", "Recep123")

    def test_user_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            User("Ana López", "analopez", "hash", "salt")
        with self.assertRaises(TypeError):
            User.create("Ana López", "analopez", "Clave123")

    def test_create_returns_the_class_it_was_called_on(self):
        self.assertIsInstance(self.admin, Administrator)
        self.assertIsInstance(self.receptionist, Receptionist)
        self.assertIsInstance(self.admin, Person)

    def test_correct_password_is_verified(self):
        self.assertTrue(self.admin.verify_password("Admin123"))

    def test_wrong_password_is_rejected(self):
        self.assertFalse(self.admin.verify_password("admin123"))
        self.assertFalse(self.admin.verify_password(""))
        self.assertFalse(self.admin.verify_password("Recep123"))

    def test_password_with_accents_is_verified(self):
        user = Receptionist.create("José Ñuñez", "jose_n", "contraseña")
        self.assertTrue(user.verify_password("contraseña"))
        self.assertFalse(user.verify_password("contrasena"))

    def test_hash_is_not_the_password(self):
        data = self.admin.to_dict()
        self.assertNotEqual(data["password_hash"], "Admin123")
        self.assertNotIn("Admin123", data.values())
        self.assertNotIn("password", data)
        self.assertEqual(len(data["password_hash"]), 64)
        self.assertEqual(len(data["salt"]), 32)

    def test_same_password_gives_different_hashes(self):
        other = Administrator.create("Otro Admin", "admin2", "Admin123")
        self.assertNotEqual(self.admin.to_dict()["salt"], other.to_dict()["salt"])
        self.assertNotEqual(
            self.admin.to_dict()["password_hash"], other.to_dict()["password_hash"]
        )

    def test_password_hash_is_private(self):
        # hasattr with a string avoids name mangling inside this test class,
        # so it asks for the attribute exactly as outside code would.
        self.assertFalse(hasattr(self.admin, "__password_hash"))
        self.assertFalse(hasattr(self.admin, "password_hash"))
        # Python stored it under the mangled name of the User class.
        self.assertTrue(hasattr(self.admin, "_User__password_hash"))

    def test_username_is_read_only(self):
        with self.assertRaises(AttributeError):
            self.admin.username = "otro"
        self.assertEqual(self.admin.username, "admin")

    def test_create_validates_its_data(self):
        with self.assertRaises(ValidationError):
            Administrator.create("Ana López", "ana", "Clave123")  # username too short
        with self.assertRaises(ValidationError):
            Administrator.create("Ana López", "ana lopez", "Clave123")
        with self.assertRaises(ValidationError):
            Administrator.create("Ana López", "analopez", "12345")  # short password
        with self.assertRaises(ValidationError):
            Administrator.create("-Ana", "analopez", "Clave123")

    def test_roles(self):
        self.assertEqual(self.admin.role, ADMINISTRATOR_ROLE)
        self.assertEqual(self.admin.role, "Administrador")
        self.assertEqual(self.receptionist.role, RECEPTIONIST_ROLE)
        self.assertEqual(self.receptionist.role, "Recepcionista")


class TestChangePassword(unittest.TestCase):
    """User.change_password (RF-43, RF-44)."""

    def setUp(self):
        self.user = Receptionist.create("María Peña", "recepcion", "Recep123")

    def test_new_password_works_and_old_one_does_not(self):
        self.user.change_password("Nueva123")
        self.assertTrue(self.user.verify_password("Nueva123"))
        self.assertFalse(self.user.verify_password("Recep123"))

    def test_salt_and_hash_change(self):
        before = self.user.to_dict()
        self.user.change_password("Nueva123")
        after = self.user.to_dict()
        self.assertNotEqual(before["salt"], after["salt"])
        self.assertNotEqual(before["password_hash"], after["password_hash"])
        self.assertNotIn("Nueva123", after.values())

    def test_short_password_keeps_the_old_one(self):
        with self.assertRaises(ValidationError) as caught:
            self.user.change_password("12345")
        self.assertEqual(
            str(caught.exception), "La contraseña debe tener al menos 6 caracteres."
        )
        self.assertTrue(self.user.verify_password("Recep123"))

    def test_same_password_is_rejected(self):
        before = self.user.to_dict()
        with self.assertRaises(ValidationError) as caught:
            self.user.change_password("Recep123")
        self.assertEqual(
            str(caught.exception),
            "La contraseña nueva debe ser distinta de la actual.",
        )
        self.assertEqual(self.user.to_dict(), before)

    def test_password_with_accents_and_spaces(self):
        self.user.change_password(" contraseña ")
        self.assertTrue(self.user.verify_password(" contraseña "))
        self.assertFalse(self.user.verify_password("contraseña"))


class TestPermissionsByRole(unittest.TestCase):
    def setUp(self):
        self.admin = Administrator.create("Luis Gándara", "admin", "Admin123")
        self.receptionist = Receptionist.create("María Peña", "recepcion", "Recep123")

    def test_administrator_has_every_permission(self):
        self.assertEqual(self.admin.permissions(), set(Permission))
        for permission in Permission:
            with self.subTest(permission=permission.name):
                self.assertTrue(self.admin.has_permission(permission))

    def test_receptionist_does_not_have_undo(self):
        self.assertFalse(self.receptionist.has_permission(Permission.UNDO))

    def test_receptionist_matches_section_3_1(self):
        for permission in Permission:
            with self.subTest(permission=permission.name):
                expected = permission not in ADMIN_ONLY
                self.assertEqual(
                    self.receptionist.has_permission(permission), expected
                )

    def test_changing_the_returned_set_grants_nothing(self):
        permissions = self.receptionist.permissions()
        permissions.add(Permission.UNDO)
        self.assertFalse(self.receptionist.has_permission(Permission.UNDO))

    def test_description_depends_on_the_role(self):
        users = [self.admin, self.receptionist]
        descriptions = [user.description() for user in users]
        self.assertIn("administrador", descriptions[0])
        self.assertIn("recepcionista", descriptions[1])
        self.assertIn("Luis Gándara (admin)", descriptions[0])
        self.assertIn("María Peña (recepcion)", descriptions[1])


class TestUserFromDict(unittest.TestCase):
    def test_round_trip_keeps_class_data_and_password(self):
        for original in (
            Administrator.create("Luis Gándara", "admin", "Admin123"),
            Receptionist.create("María Peña", "recepcion", "Recep123"),
        ):
            with self.subTest(role=original.role):
                copy = user_from_dict(original.to_dict())
                self.assertIs(type(copy), type(original))
                self.assertEqual(copy.to_dict(), original.to_dict())

        copy = user_from_dict(
            Administrator.create("Luis Gándara", "admin", "Admin123").to_dict()
        )
        self.assertTrue(copy.verify_password("Admin123"))

    def test_to_dict_keys(self):
        data = Receptionist.create("María Peña", "recepcion", "Recep123").to_dict()
        self.assertEqual(
            set(data), {"full_name", "username", "role", "password_hash", "salt"}
        )
        self.assertEqual(data["role"], "Recepcionista")

    def test_unknown_role_raises_validation_error(self):
        data = Administrator.create("Luis Gándara", "admin", "Admin123").to_dict()
        data["role"] = "Doctor"
        with self.assertRaises(ValidationError) as context:
            user_from_dict(data)
        self.assertIn("Doctor", str(context.exception))

    def test_missing_field_raises_validation_error(self):
        data = Administrator.create("Luis Gándara", "admin", "Admin123").to_dict()
        del data["salt"]
        with self.assertRaises(ValidationError) as context:
            user_from_dict(data)
        self.assertIn("salt", str(context.exception))


def make_patient(**changes) -> Patient:
    """Return Ana López (CP-05) with any field replaced by a keyword."""
    data = {
        "code": "PAC-0001",
        "full_name": "Ana López",
        "age": 30,
        "phone": "55551234",
        "registered_at": "2026-11-01 08:30:00",
    }
    data.update(changes)
    return Patient(**data)


class TestPatientCreation(unittest.TestCase):
    def test_patient_is_a_person(self):
        patient = make_patient()
        self.assertIsInstance(patient, Person)

    def test_constructor_cleans_the_values(self):
        patient = make_patient(
            code=" pac-0001 ", full_name="  Ana   López ", age="30", phone=" 55551234 "
        )
        self.assertEqual(patient.code, "PAC-0001")
        self.assertEqual(patient.full_name, "Ana López")
        self.assertEqual(patient.age, 30)
        self.assertIsInstance(patient.age, int)
        self.assertEqual(patient.phone, "55551234")

    def test_constructor_rejects_invalid_values(self):
        cases = {
            "code": "PAC-1",
            "full_name": "-Ana",
            "age": "abc",
            "phone": "1234",
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    make_patient(**{field: value})

    def test_registered_at_defaults_to_now(self):
        patient = Patient("PAC-0002", "Marco Díaz", 45, "22223333")
        # parse_date raises if the text does not follow DATE_FORMAT.
        parse_date(patient.registered_at)

    def test_registered_at_keeps_the_given_date(self):
        self.assertEqual(make_patient().registered_at, "2026-11-01 08:30:00")

    def test_registered_at_with_wrong_format_is_rejected(self):
        with self.assertRaises(ValidationError):
            make_patient(registered_at="01/11/2026")


class TestPatientEncapsulation(unittest.TestCase):
    def setUp(self):
        self.patient = make_patient()

    def test_code_is_read_only(self):
        with self.assertRaises(AttributeError):
            self.patient.code = "PAC-0002"
        self.assertEqual(self.patient.code, "PAC-0001")

    def test_registered_at_is_read_only(self):
        with self.assertRaises(AttributeError):
            self.patient.registered_at = "2020-01-01 00:00:00"

    def test_age_setter_accepts_valid_values(self):
        self.patient.age = "61"
        self.assertEqual(self.patient.age, 61)
        self.patient.age = 0
        self.assertEqual(self.patient.age, 0)
        self.patient.age = 120
        self.assertEqual(self.patient.age, 120)

    def test_invalid_age_keeps_the_previous_value(self):
        for value in ("abc", 121, -1, "", True, "30.5"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    self.patient.age = value
                self.assertEqual(self.patient.age, 30)

    def test_age_error_message_comes_from_section_4_6(self):
        with self.assertRaises(ValidationError) as context:
            self.patient.age = 150
        self.assertEqual(
            str(context.exception),
            "La edad debe ser un número entero entre 0 y 120.",
        )

    def test_phone_setter_accepts_a_valid_phone(self):
        self.patient.phone = "77778888"
        self.assertEqual(self.patient.phone, "77778888")

    def test_invalid_phone_keeps_the_previous_value(self):
        for value in ("1234", "12345678", "5555-1234", "5555123a", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    self.patient.phone = value
                self.assertEqual(self.patient.phone, "55551234")


class TestPatientText(unittest.TestCase):
    def test_description(self):
        self.assertEqual(make_patient().description(), "PAC-0001, Ana López, 30 años")

    def test_description_uses_singular_for_one_year(self):
        self.assertEqual(
            make_patient(age=1).description(), "PAC-0001, Ana López, 1 año"
        )

    def test_str_has_code_and_name(self):
        self.assertEqual(str(make_patient()), "PAC-0001 - Ana López")

    def test_description_depends_on_the_kind_of_person(self):
        people = [
            make_patient(),
            Receptionist.create("María Peña", "recepcion", "Recep123"),
        ]
        descriptions = [person.description() for person in people]
        self.assertTrue(descriptions[0].startswith("PAC-0001"))
        self.assertIn("recepcionista", descriptions[1])


class TestPatientUpdateDetails(unittest.TestCase):
    def setUp(self):
        self.patient = make_patient()

    def assert_unchanged(self):
        self.assertEqual(self.patient.full_name, "Ana López")
        self.assertEqual(self.patient.age, 30)
        self.assertEqual(self.patient.phone, "55551234")

    def test_applies_the_new_values(self):
        self.patient.update_details(" Ana   López-Pérez ", "31", "44445555")
        self.assertEqual(self.patient.full_name, "Ana López-Pérez")
        self.assertEqual(self.patient.age, 31)
        self.assertEqual(self.patient.phone, "44445555")

    def test_returns_the_previous_values(self):
        previous = self.patient.update_details("Ana López-Pérez", 31, "44445555")
        self.assertEqual(
            previous, {"full_name": "Ana López", "age": 30, "phone": "55551234"}
        )

    def test_invalid_age_changes_nothing(self):
        # The new name and phone are valid; only the age is wrong.
        with self.assertRaises(ValidationError):
            self.patient.update_details("Ana López-Pérez", "abc", "44445555")
        self.assert_unchanged()

    def test_invalid_phone_changes_nothing(self):
        with self.assertRaises(ValidationError):
            self.patient.update_details("Ana López-Pérez", 31, "1234")
        self.assert_unchanged()

    def test_invalid_name_changes_nothing(self):
        with self.assertRaises(ValidationError):
            self.patient.update_details("Ana--López", 31, "44445555")
        self.assert_unchanged()

    def test_previous_values_restore_the_patient(self):
        # This is what UpdatePatientAction will do on undo (step C10).
        previous = self.patient.update_details("Ana López-Pérez", 31, "44445555")
        self.patient.update_details(**previous)
        self.assert_unchanged()

    def test_code_and_date_do_not_change(self):
        self.patient.update_details("Ana López-Pérez", 31, "44445555")
        self.assertEqual(self.patient.code, "PAC-0001")
        self.assertEqual(self.patient.registered_at, "2026-11-01 08:30:00")


class TestPatientDict(unittest.TestCase):
    def test_to_dict_keys_and_values(self):
        self.assertEqual(
            make_patient().to_dict(),
            {
                "code": "PAC-0001",
                "full_name": "Ana López",
                "age": 30,
                "phone": "55551234",
                "registered_at": "2026-11-01 08:30:00",
            },
        )

    def test_round_trip_keeps_the_same_data(self):
        original = make_patient(full_name="José Peña", age=65)
        copy = Patient.from_dict(original.to_dict())
        self.assertIsInstance(copy, Patient)
        self.assertIsNot(copy, original)
        self.assertEqual(copy.to_dict(), original.to_dict())

    def test_round_trip_through_json_text(self):
        original = make_patient(full_name="José Peña")
        text = json.dumps(original.to_dict(), ensure_ascii=False)
        self.assertIn("José Peña", text)
        copy = Patient.from_dict(json.loads(text))
        self.assertEqual(copy.to_dict(), original.to_dict())

    def test_missing_field_raises_validation_error(self):
        data = make_patient().to_dict()
        del data["phone"]
        with self.assertRaises(ValidationError) as context:
            Patient.from_dict(data)
        self.assertIn("phone", str(context.exception))

    def test_invalid_value_in_file_raises_validation_error(self):
        data = make_patient().to_dict()
        data["age"] = 200
        with self.assertRaises(ValidationError):
            Patient.from_dict(data)



def make_ticket(**changes) -> Ticket:
    """Return ticket N-001 of Ana López (CP-05) with any field replaced."""
    data = {
        "number": "N-001",
        "patient": make_patient(),
        "care_type": NormalCare(),
        "reason": "Dolor de cabeza",
        "created_at": "2026-11-01 08:30:00",
    }
    data.update(changes)
    return Ticket(**data)


class TestTicketStatus(unittest.TestCase):
    def test_values_are_spanish_labels(self):
        self.assertEqual(TicketStatus.PENDING.value, "Pendiente")
        self.assertEqual(TicketStatus.IN_PROGRESS.value, "En atención")
        self.assertEqual(TicketStatus.SERVED.value, "Atendido")
        self.assertEqual(TicketStatus.CANCELLED.value, "Cancelado")
        self.assertEqual(len(TicketStatus), 4)

    def test_is_active(self):
        self.assertTrue(TicketStatus.PENDING.is_active)
        self.assertTrue(TicketStatus.IN_PROGRESS.is_active)
        self.assertFalse(TicketStatus.SERVED.is_active)
        self.assertFalse(TicketStatus.CANCELLED.is_active)

    def test_status_can_be_read_back_from_its_value(self):
        self.assertIs(TicketStatus("En atención"), TicketStatus.IN_PROGRESS)


class TestCareType(unittest.TestCase):
    def test_care_type_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            CareType()

    def test_normal_care(self):
        care = NormalCare()
        self.assertIsInstance(care, CareType)
        self.assertEqual(care.name, "Normal")
        self.assertEqual(care.prefix, "N")
        self.assertFalse(care.is_priority)
        self.assertEqual(care.description(), "Normal")
        self.assertEqual(care.to_dict(), {"care_type": "Normal", "criterion": None})

    def test_priority_care(self):
        care = PriorityCare("Embarazo")
        self.assertIsInstance(care, CareType)
        self.assertEqual(care.name, "Prioritaria")
        self.assertEqual(care.prefix, "P")
        self.assertTrue(care.is_priority)
        self.assertEqual(care.criterion, "Embarazo")
        self.assertEqual(care.description(), "Prioritaria (Embarazo)")
        self.assertEqual(
            care.to_dict(), {"care_type": "Prioritaria", "criterion": "Embarazo"}
        )

    def test_criteria_of_section_3_2(self):
        self.assertEqual(
            PriorityCare.CRITERIA,
            ("Adulto mayor", "Embarazo", "Discapacidad", "Urgencia"),
        )
        self.assertEqual(PriorityCare.SENIOR_AGE, 60)

    def test_unknown_or_empty_criterion_is_rejected(self):
        for value in ("Gripe", "", "   ", None):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    PriorityCare(value)

    def test_criterion_is_read_only(self):
        care = PriorityCare("Urgencia")
        with self.assertRaises(AttributeError):
            care.criterion = "Embarazo"

    def test_senior_criterion_rejects_a_patient_aged_30(self):
        with self.assertRaises(ValidationError) as context:
            PriorityCare("Adulto mayor").validate_for(make_patient(age=30))
        self.assertEqual(
            str(context.exception), "El criterio Adulto mayor requiere 60 años o más."
        )

    def test_senior_criterion_accepts_60_and_more(self):
        care = PriorityCare("Adulto mayor")
        care.validate_for(make_patient(age=60))
        care.validate_for(make_patient(age=85))
        with self.assertRaises(ValidationError):
            care.validate_for(make_patient(age=59))

    def test_other_criteria_accept_any_age(self):
        young = make_patient(age=20)
        for criterion in ("Embarazo", "Discapacidad", "Urgencia"):
            with self.subTest(criterion=criterion):
                PriorityCare(criterion).validate_for(young)

    def test_normal_care_accepts_everyone(self):
        NormalCare().validate_for(make_patient(age=0))
        NormalCare().validate_for(make_patient(age=120))

    def test_same_calls_answer_according_to_the_type(self):
        # The loop never asks which class each object is.
        care_types = [NormalCare(), PriorityCare("Discapacidad")]
        self.assertEqual([c.prefix for c in care_types], ["N", "P"])
        self.assertEqual([c.is_priority for c in care_types], [False, True])
        self.assertEqual(
            [c.description() for c in care_types],
            ["Normal", "Prioritaria (Discapacidad)"],
        )


class TestMakeCareType(unittest.TestCase):
    def test_builds_each_type(self):
        self.assertIsInstance(make_care_type("Normal"), NormalCare)
        care = make_care_type(" Prioritaria ", "Urgencia")
        self.assertIsInstance(care, PriorityCare)
        self.assertEqual(care.criterion, "Urgencia")

    def test_names_for_the_combobox(self):
        self.assertEqual(CARE_TYPE_NAMES, ("Normal", "Prioritaria"))
        for name in CARE_TYPE_NAMES:
            criterion = "Embarazo" if name == "Prioritaria" else None
            self.assertEqual(make_care_type(name, criterion).name, name)

    def test_missing_type_has_the_message_of_section_4_6(self):
        for value in ("", "  ", None):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as context:
                    make_care_type(value)
                self.assertEqual(
                    str(context.exception), "Selecciona el tipo de atención."
                )

    def test_priority_without_criterion_is_rejected(self):
        with self.assertRaises(ValidationError):
            make_care_type("Prioritaria")

    def test_unknown_type_is_rejected(self):
        with self.assertRaises(ValidationError):
            make_care_type("Especial")

    def test_normal_ignores_a_leftover_criterion(self):
        care = make_care_type("Normal", "Embarazo")
        self.assertIsInstance(care, NormalCare)
        self.assertIsNone(care.to_dict()["criterion"])


class TestTicketCreation(unittest.TestCase):
    def test_new_ticket_is_pending(self):
        ticket = make_ticket()
        self.assertIs(ticket.status, TicketStatus.PENDING)
        self.assertTrue(ticket.is_active)
        self.assertIsNone(ticket.served_at)

    def test_created_at_defaults_to_now(self):
        ticket = Ticket("N-001", make_patient(), NormalCare(), "Dolor de cabeza")
        parse_date(ticket.created_at)

    def test_format_number(self):
        self.assertEqual(Ticket.format_number("N", 1), "N-001")
        self.assertEqual(Ticket.format_number("P", 42), "P-042")
        self.assertEqual(Ticket.format_number("N", 1234), "N-1234")

    def test_sequence_is_the_numeric_part(self):
        self.assertEqual(make_ticket(number="N-004").sequence, 4)
        ticket = make_ticket(number="p-1234", care_type=PriorityCare("Urgencia"))
        self.assertEqual(ticket.number, "P-1234")
        self.assertEqual(ticket.sequence, 1234)

    def test_sorting_by_sequence_mixes_both_prefixes(self):
        tickets = [
            make_ticket(number="N-004"),
            make_ticket(number="P-003", care_type=PriorityCare("Urgencia")),
            make_ticket(number="N-001"),
        ]
        ordered = sorted(tickets, key=lambda t: t.sequence)
        self.assertEqual([t.number for t in ordered], ["N-001", "P-003", "N-004"])

    def test_number_must_match_the_care_type(self):
        with self.assertRaises(ValidationError):
            make_ticket(number="P-001")  # normal care with a P number
        with self.assertRaises(ValidationError):
            make_ticket(number="N-001", care_type=PriorityCare("Urgencia"))

    def test_badly_formed_numbers_are_rejected(self):
        for value in ("N-01", "N001", "N-abc", "", "X-001"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    make_ticket(number=value)

    def test_reason_is_validated(self):
        with self.assertRaises(ValidationError):
            make_ticket(reason="Tos")
        self.assertEqual(make_ticket(reason="  Control anual ").reason, "Control anual")

    def test_bad_created_at_is_rejected(self):
        with self.assertRaises(ValidationError):
            make_ticket(created_at="ayer")

    def test_served_ticket_needs_a_care_date(self):
        with self.assertRaises(ValidationError):
            make_ticket(status=TicketStatus.SERVED)
        ticket = make_ticket(
            status=TicketStatus.SERVED, served_at="2026-11-01 09:00:00"
        )
        self.assertEqual(ticket.served_at, "2026-11-01 09:00:00")

    def test_only_a_served_ticket_has_a_care_date(self):
        with self.assertRaises(ValidationError):
            make_ticket(served_at="2026-11-01 09:00:00")

    def test_status_must_be_a_ticket_status(self):
        with self.assertRaises(ValidationError):
            make_ticket(status="Pendiente")

    def test_str(self):
        self.assertEqual(str(make_ticket()), "N-001 - Ana López (Pendiente)")


class TestTicketEncapsulation(unittest.TestCase):
    def test_attributes_are_read_only(self):
        ticket = make_ticket()
        for name, value in {
            "number": "N-999",
            "patient": make_patient(code="PAC-0002"),
            "care_type": PriorityCare("Urgencia"),
            "reason": "Otro motivo",
            "created_at": "2020-01-01 00:00:00",
            "status": TicketStatus.SERVED,
            "served_at": "2026-11-01 09:00:00",
            "sequence": 9,
            "is_active": False,
        }.items():
            with self.subTest(attribute=name):
                with self.assertRaises(AttributeError):
                    setattr(ticket, name, value)
        self.assertIs(ticket.status, TicketStatus.PENDING)

    def test_ticket_points_to_the_same_patient(self):
        patient = make_patient()
        ticket = make_ticket(patient=patient)
        self.assertIs(ticket.patient, patient)
        patient.phone = "77778888"
        self.assertEqual(ticket.patient.phone, "77778888")


class TestTicketTransitions(unittest.TestCase):
    def setUp(self):
        self.ticket = make_ticket()

    def test_full_valid_path(self):
        self.ticket.start_care()
        self.assertIs(self.ticket.status, TicketStatus.IN_PROGRESS)
        self.assertTrue(self.ticket.is_active)
        self.assertIsNone(self.ticket.served_at)

        self.ticket.finish_care()
        self.assertIs(self.ticket.status, TicketStatus.SERVED)
        self.assertFalse(self.ticket.is_active)
        parse_date(self.ticket.served_at)

    def test_cancel_a_pending_ticket(self):
        self.ticket.cancel()
        self.assertIs(self.ticket.status, TicketStatus.CANCELLED)
        self.assertFalse(self.ticket.is_active)

    def test_cancelling_a_served_ticket_raises(self):
        self.ticket.start_care()
        self.ticket.finish_care()
        with self.assertRaises(ValidationError) as context:
            self.ticket.cancel()
        self.assertEqual(
            str(context.exception), "Solo se pueden cancelar turnos pendientes."
        )
        self.assertIs(self.ticket.status, TicketStatus.SERVED)

    def test_cancelling_a_ticket_in_progress_raises(self):
        self.ticket.start_care()
        with self.assertRaises(ValidationError):
            self.ticket.cancel()
        self.assertIs(self.ticket.status, TicketStatus.IN_PROGRESS)

    def test_finishing_a_pending_ticket_raises(self):
        with self.assertRaises(ValidationError):
            self.ticket.finish_care()
        self.assertIs(self.ticket.status, TicketStatus.PENDING)

    def test_starting_twice_raises(self):
        self.ticket.start_care()
        with self.assertRaises(ValidationError):
            self.ticket.start_care()

    def test_final_states_do_not_move(self):
        # RN-06: Atendido and Cancelado are final.
        served = make_ticket()
        served.start_care()
        served.finish_care()
        cancelled = make_ticket()
        cancelled.cancel()
        for ticket in (served, cancelled):
            for method in (ticket.start_care, ticket.finish_care, ticket.cancel):
                with self.subTest(status=ticket.status.value, method=method.__name__):
                    before = ticket.status
                    with self.assertRaises(ValidationError):
                        method()
                    self.assertIs(ticket.status, before)


class TestTicketRevert(unittest.TestCase):
    def test_undo_call_next(self):
        ticket = make_ticket()
        ticket.start_care()
        ticket.revert_to(TicketStatus.PENDING)
        self.assertIs(ticket.status, TicketStatus.PENDING)

    def test_undo_finish_care_erases_the_care_date(self):
        ticket = make_ticket()
        ticket.start_care()
        ticket.finish_care()
        ticket.revert_to(TicketStatus.IN_PROGRESS)
        self.assertIs(ticket.status, TicketStatus.IN_PROGRESS)
        self.assertIsNone(ticket.served_at)

    def test_undo_cancel(self):
        ticket = make_ticket()
        ticket.cancel()
        ticket.revert_to(TicketStatus.PENDING)
        self.assertIs(ticket.status, TicketStatus.PENDING)

    def test_reverted_ticket_can_move_forward_again(self):
        ticket = make_ticket()
        ticket.cancel()
        ticket.revert_to(TicketStatus.PENDING)
        ticket.start_care()
        self.assertIs(ticket.status, TicketStatus.IN_PROGRESS)

    def test_revert_only_goes_back_one_step(self):
        served = make_ticket()
        served.start_care()
        served.finish_care()
        with self.assertRaises(NotUndoableError):
            served.revert_to(TicketStatus.PENDING)
        self.assertIs(served.status, TicketStatus.SERVED)

        with self.assertRaises(NotUndoableError):
            make_ticket().revert_to(TicketStatus.PENDING)

        cancelled = make_ticket()
        cancelled.cancel()
        with self.assertRaises(NotUndoableError):
            cancelled.revert_to(TicketStatus.IN_PROGRESS)


class TestTicketDict(unittest.TestCase):
    def setUp(self):
        self.patient = make_patient(full_name="José Peña", age=65)
        self.patients_by_code = {self.patient.code: self.patient}

    def test_to_dict_has_the_keys_of_section_3_11(self):
        ticket = make_ticket(
            number="P-002",
            patient=self.patient,
            care_type=PriorityCare("Adulto mayor"),
        )
        self.assertEqual(
            ticket.to_dict(),
            {
                "number": "P-002",
                "patient_code": "PAC-0001",
                "care_type": "Prioritaria",
                "criterion": "Adulto mayor",
                "reason": "Dolor de cabeza",
                "created_at": "2026-11-01 08:30:00",
                "status": "Pendiente",
                "served_at": None,
            },
        )

    def test_round_trip_in_every_status(self):
        pending = make_ticket(patient=self.patient)
        in_progress = make_ticket(patient=self.patient)
        in_progress.start_care()
        served = make_ticket(patient=self.patient)
        served.start_care()
        served.finish_care()
        cancelled = make_ticket(
            number="P-004", patient=self.patient, care_type=PriorityCare("Urgencia")
        )
        cancelled.cancel()
        for original in (pending, in_progress, served, cancelled):
            with self.subTest(status=original.status.value):
                text = json.dumps(original.to_dict(), ensure_ascii=False)
                copy = Ticket.from_dict(json.loads(text), self.patients_by_code)
                self.assertEqual(copy.to_dict(), original.to_dict())
                self.assertIs(copy.status, original.status)
                self.assertIs(copy.patient, self.patient)
                self.assertEqual(type(copy.care_type), type(original.care_type))

    def test_patient_must_exist(self):
        data = make_ticket(patient=self.patient).to_dict()
        with self.assertRaises(ValidationError) as context:
            Ticket.from_dict(data, {})
        self.assertIn("PAC-0001", str(context.exception))

    def test_unknown_status_is_rejected(self):
        data = make_ticket(patient=self.patient).to_dict()
        data["status"] = "Perdido"
        with self.assertRaises(ValidationError) as context:
            Ticket.from_dict(data, self.patients_by_code)
        self.assertIn("Perdido", str(context.exception))

    def test_missing_field_is_rejected(self):
        data = make_ticket(patient=self.patient).to_dict()
        del data["reason"]
        with self.assertRaises(ValidationError) as context:
            Ticket.from_dict(data, self.patients_by_code)
        self.assertIn("reason", str(context.exception))

    def test_loading_does_not_check_the_senior_age(self):
        # The age may have been corrected after the ticket was created.
        data = make_ticket(
            number="P-001",
            patient=self.patient,
            care_type=PriorityCare("Adulto mayor"),
        ).to_dict()
        self.patient.age = 59
        ticket = Ticket.from_dict(data, self.patients_by_code)
        self.assertEqual(ticket.care_type.criterion, "Adulto mayor")


class TestCareRecord(unittest.TestCase):
    def setUp(self):
        self.ticket = make_ticket(
            number="P-003", care_type=PriorityCare("Embarazo")
        )
        self.ticket.start_care()
        self.ticket.finish_care()

    def test_from_ticket_copies_the_data(self):
        record = CareRecord.from_ticket(self.ticket, "recepcion")
        self.assertEqual(record.ticket_number, "P-003")
        self.assertEqual(record.patient_code, "PAC-0001")
        self.assertEqual(record.patient_name, "Ana López")
        self.assertEqual(record.care_type, "Prioritaria (Embarazo)")
        self.assertEqual(record.registered_at, self.ticket.created_at)
        self.assertEqual(record.served_at, self.ticket.served_at)
        self.assertEqual(record.served_by, "recepcion")

    def test_only_served_tickets_have_a_record(self):
        with self.assertRaises(ValidationError):
            CareRecord.from_ticket(make_ticket(), "recepcion")

    def test_attributes_are_read_only(self):
        record = CareRecord.from_ticket(self.ticket, "recepcion")
        with self.assertRaises(AttributeError):
            record.served_by = "admin"

    def test_record_keeps_the_name_of_that_day(self):
        record = CareRecord.from_ticket(self.ticket, "recepcion")
        self.ticket.patient.full_name = "Ana López-Pérez"
        self.assertEqual(record.patient_name, "Ana López")

    def test_round_trip(self):
        original = CareRecord.from_ticket(self.ticket, "recepcion")
        text = json.dumps(original.to_dict(), ensure_ascii=False)
        copy = CareRecord.from_dict(json.loads(text))
        self.assertEqual(copy.to_dict(), original.to_dict())
        self.assertEqual(
            set(copy.to_dict()),
            {
                "ticket_number",
                "patient_code",
                "patient_name",
                "care_type",
                "registered_at",
                "served_at",
                "served_by",
            },
        )

    def test_missing_field_is_rejected(self):
        data = CareRecord.from_ticket(self.ticket, "recepcion").to_dict()
        del data["served_by"]
        with self.assertRaises(ValidationError):
            CareRecord.from_dict(data)

    def test_bad_date_is_rejected(self):
        data = CareRecord.from_ticket(self.ticket, "recepcion").to_dict()
        data["served_at"] = "hoy"
        with self.assertRaises(ValidationError):
            CareRecord.from_dict(data)


if __name__ == "__main__":
    unittest.main()
