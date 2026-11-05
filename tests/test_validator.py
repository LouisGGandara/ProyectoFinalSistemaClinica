"""Tests for step C1: custom exceptions, date helpers and Validator."""

import unittest
from datetime import datetime

from utils.dates import DATE_FORMAT, now_text, parse_date, set_clock
from utils.exceptions import (
    ClinicError,
    CorruptedFileError,
    DuplicateError,
    EmptyQueueError,
    EmptyStackError,
    InvalidCredentialsError,
    NotFoundError,
    NotUndoableError,
    PermissionDeniedError,
    StorageError,
    ValidationError,
)
from utils.validator import Validator


class TestExceptions(unittest.TestCase):
    ALL_ERRORS = (
        ValidationError,
        DuplicateError,
        InvalidCredentialsError,
        PermissionDeniedError,
        NotFoundError,
        EmptyQueueError,
        EmptyStackError,
        NotUndoableError,
        StorageError,
    )

    def test_every_error_inherits_from_clinic_error(self):
        for error_class in self.ALL_ERRORS + (CorruptedFileError,):
            with self.subTest(error_class=error_class.__name__):
                self.assertTrue(issubclass(error_class, ClinicError))

    def test_every_error_has_a_default_message(self):
        for error_class in self.ALL_ERRORS:
            with self.subTest(error_class=error_class.__name__):
                error = error_class()
                self.assertTrue(str(error))
                self.assertEqual(str(error), error.message)

    def test_messages_from_section_4_6(self):
        self.assertEqual(str(EmptyQueueError()), "No hay pacientes en espera.")
        self.assertEqual(
            str(EmptyStackError()), "No hay acciones que se puedan deshacer."
        )
        self.assertEqual(
            str(InvalidCredentialsError()), "Usuario o contraseña incorrectos."
        )
        self.assertEqual(
            str(PermissionDeniedError()),
            "Tu usuario no tiene permiso para esta acción.",
        )

    def test_custom_message_replaces_default(self):
        error = DuplicateError("Ya existe un paciente con el código PAC-0007.")
        self.assertEqual(str(error), "Ya existe un paciente con el código PAC-0007.")

    def test_one_except_catches_every_custom_error(self):
        with self.assertRaises(ClinicError):
            raise EmptyQueueError()

    def test_corrupted_file_error_keeps_filename(self):
        error = CorruptedFileError("tickets.json")
        self.assertEqual(error.filename, "tickets.json")
        self.assertIn("tickets.json", str(error))


class TestDates(unittest.TestCase):
    def test_now_text_follows_date_format(self):
        text = now_text()
        self.assertEqual(datetime.strptime(text, DATE_FORMAT).strftime(DATE_FORMAT), text)

    def test_parse_date_round_trip(self):
        self.assertEqual(
            parse_date("2026-11-01 18:30:05"), datetime(2026, 11, 1, 18, 30, 5)
        )

    def test_set_clock_changes_now_text_until_reset(self):
        set_clock(lambda: datetime(2026, 11, 2, 7, 15, 30))
        try:
            self.assertEqual(now_text(), "2026-11-02 07:15:30")
        finally:
            set_clock(None)
        self.assertNotEqual(now_text(), "2026-11-02 07:15:30")

    def test_parse_date_rejects_other_formats(self):
        for text in ("01/11/2026 18:30", "2026-11-01", "", "abc", None):
            with self.subTest(text=text):
                with self.assertRaises(ValidationError):
                    parse_date(text)


class TestRequired(unittest.TestCase):
    def test_strips_edges(self):
        self.assertEqual(Validator.required("  Ana  ", "Nombre"), "Ana")

    def test_empty_none_and_spaces_fail_with_field_label(self):
        for value in ("", "   ", None):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as context:
                    Validator.required(value, "Teléfono")
                self.assertEqual(str(context.exception), "Completa el campo Teléfono.")


class TestPatientCode(unittest.TestCase):
    def test_valid_code(self):
        self.assertEqual(Validator.patient_code("PAC-0001"), "PAC-0001")

    def test_lowercase_is_returned_uppercase(self):
        self.assertEqual(Validator.patient_code(" pac-0042 "), "PAC-0042")

    def test_invalid_codes(self):
        for value in ("PAC-1", "PAC-00001", "PAC0001", "ABC-0001", "PAC-00A1",
                      "PAC-١٢٣٤"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as context:
                    Validator.patient_code(value)
                self.assertEqual(
                    str(context.exception), "El código debe tener el formato PAC-0000."
                )

    def test_empty_code(self):
        with self.assertRaises(ValidationError):
            Validator.patient_code("")


class TestFullName(unittest.TestCase):
    INVALID_MESSAGE = "El nombre solo puede tener letras, espacios y guiones entre palabras."

    def test_valid_names(self):
        for value in ("Ana López-Pérez", "José Peña", "Begoña Núñez", "Ana"):
            with self.subTest(value=value):
                self.assertEqual(Validator.full_name(value), value)

    def test_spaces_are_cleaned(self):
        self.assertEqual(Validator.full_name("  Ana    María   López "), "Ana María López")

    def test_decomposed_accents_are_accepted(self):
        decomposed = "José Peña"
        self.assertEqual(Validator.full_name(decomposed), "José Peña")

    def test_misplaced_hyphens(self):
        for value in ("-Ana", "Ana-", "Ana--López", "Ana - López", "Ana -López"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as context:
                    Validator.full_name(value)
                self.assertEqual(str(context.exception), self.INVALID_MESSAGE)

    def test_digits_and_symbols(self):
        for value in ("Ana 2", "Ana_López", "O'Brien", "Ana."):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    Validator.full_name(value)

    def test_length_limits(self):
        self.assertEqual(Validator.full_name("Ana"), "Ana")
        self.assertEqual(len(Validator.full_name("A" * 80)), 80)
        for value in ("Al", "A" * 81):
            with self.subTest(length=len(value)):
                with self.assertRaises(ValidationError):
                    Validator.full_name(value)

    def test_empty_name(self):
        with self.assertRaises(ValidationError) as context:
            Validator.full_name("   ")
        self.assertEqual(str(context.exception), "Completa el campo Nombre.")


class TestAge(unittest.TestCase):
    MESSAGE = "La edad debe ser un número entero entre 0 y 120."

    def test_valid_ages(self):
        self.assertEqual(Validator.age("30"), 30)
        self.assertEqual(Validator.age(" 45 "), 45)
        self.assertEqual(Validator.age(0), 0)
        self.assertEqual(Validator.age("120"), 120)

    def test_letters_decimals_and_out_of_range(self):
        for value in ("abc", "121", "-1", "30.5", "3 0", 121, -5, 30.0, True):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as context:
                    Validator.age(value)
                self.assertEqual(str(context.exception), self.MESSAGE)

    def test_text_that_int_accepts_but_is_not_plain_digits(self):
        # int() takes all of these (test E2-03). Only 0 to 9 count as digits.
        for value in ("1_0", "+30", "-0", "٣٠", "３０"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as context:
                    Validator.age(value)
                self.assertEqual(str(context.exception), self.MESSAGE)

    def test_letters_keep_the_original_value_error(self):
        with self.assertRaises(ValidationError) as context:
            Validator.age("abc")
        self.assertIsInstance(context.exception.__cause__, ValueError)

    def test_empty_age(self):
        with self.assertRaises(ValidationError) as context:
            Validator.age("")
        self.assertEqual(str(context.exception), "Completa el campo Edad.")


class TestPhone(unittest.TestCase):
    MESSAGE = "El teléfono debe tener 8 dígitos, por ejemplo 55551234."

    def test_valid_phones(self):
        for value in ("55551234", "22223333", "79998888", " 45671234 "):
            with self.subTest(value=value):
                self.assertEqual(Validator.phone(value), value.strip())

    def test_invalid_phones(self):
        for value in ("1234", "12345678", "85551234", "5555123", "555512345",
                      "5555-1234", "5555 1234", "5555abcd"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as context:
                    Validator.phone(value)
                self.assertEqual(str(context.exception), self.MESSAGE)


class TestReason(unittest.TestCase):
    def test_valid_reason(self):
        self.assertEqual(Validator.reason("  Dolor de cabeza "), "Dolor de cabeza")

    def test_length_limits(self):
        self.assertEqual(Validator.reason("Tos 1"), "Tos 1")
        self.assertEqual(len(Validator.reason("x" * 200)), 200)

    def test_too_short(self):
        with self.assertRaises(ValidationError) as context:
            Validator.reason("Tos")
        self.assertEqual(
            str(context.exception), "Describe el motivo con al menos 5 caracteres."
        )

    def test_too_long(self):
        with self.assertRaises(ValidationError):
            Validator.reason("x" * 201)


class TestUsername(unittest.TestCase):
    def test_valid_usernames(self):
        for value in ("admin", "recepcion", "user_01", "A" * 20):
            with self.subTest(value=value):
                self.assertEqual(Validator.username(value), value)

    def test_invalid_usernames(self):
        for value in ("abc", "A" * 21, "ana lopez", "josé", "ana-lopez", "ana.l"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    Validator.username(value)


class TestPassword(unittest.TestCase):
    def test_valid_password_is_returned_unchanged(self):
        self.assertEqual(Validator.password("Admin123"), "Admin123")
        self.assertEqual(Validator.password(" abc12 "), " abc12 ")

    def test_too_short(self):
        with self.assertRaises(ValidationError) as context:
            Validator.password("abc12")
        self.assertEqual(
            str(context.exception), "La contraseña debe tener al menos 6 caracteres."
        )

    def test_empty_or_only_spaces(self):
        for value in ("", "      ", None):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as context:
                    Validator.password(value)
                self.assertEqual(str(context.exception), "Completa el campo Contraseña.")


if __name__ == "__main__":
    unittest.main()
