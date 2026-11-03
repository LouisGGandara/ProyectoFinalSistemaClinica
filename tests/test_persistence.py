"""Tests for JsonRepository (step C6).

Every test works inside a tempfile.TemporaryDirectory, so the real data
folder is never touched.

Run from the project root with: python -m unittest discover tests
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from persistence.json_repository import JsonRepository
from utils.exceptions import ClinicError, CorruptedFileError, StorageError

PATIENTS = [
    {"code": "PAC-0001", "full_name": "José Peña", "age": 30},
    {"code": "PAC-0002", "full_name": "María Núñez", "age": 64},
]


class RepositoryTestCase(unittest.TestCase):
    """Creates a repository in a fresh temporary folder for each test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name) / "data"
        self.repo = JsonRepository(str(self.folder))

    def tearDown(self):
        self._tmp.cleanup()

    def corrupted_copies(self, stem: str) -> list[Path]:
        return sorted(self.folder.glob(f"{stem}.corrupted-*.json"))


class TestFolder(RepositoryTestCase):
    def test_init_creates_the_folder(self):
        self.assertTrue(self.folder.is_dir())

    def test_init_creates_nested_folders(self):
        nested = Path(self._tmp.name) / "a" / "b" / "data"
        JsonRepository(str(nested))
        self.assertTrue(nested.is_dir())

    def test_init_keeps_an_existing_folder(self):
        (self.folder / "users.json").write_text("[]", encoding="utf-8")
        JsonRepository(str(self.folder))
        self.assertTrue((self.folder / "users.json").is_file())

    def test_path_is_inside_the_folder(self):
        self.assertEqual(self.repo._path("users.json"), self.folder / "users.json")


class TestSaveAndLoad(RepositoryTestCase):
    def test_exists_is_false_before_saving(self):
        self.assertFalse(self.repo.exists("patients.json"))

    def test_saved_list_loads_back_equal(self):
        self.repo.save("patients.json", PATIENTS)
        self.assertTrue(self.repo.exists("patients.json"))
        self.assertEqual(self.repo.load("patients.json"), PATIENTS)

    def test_empty_list_round_trip(self):
        self.repo.save("tickets.json", [])
        self.assertEqual(self.repo.load("tickets.json"), [])

    def test_save_replaces_the_whole_content(self):
        self.repo.save("patients.json", PATIENTS)
        self.repo.save("patients.json", PATIENTS[:1])
        self.assertEqual(self.repo.load("patients.json"), PATIENTS[:1])

    def test_save_leaves_no_temporary_file(self):
        self.repo.save("patients.json", PATIENTS)
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_files_are_independent(self):
        self.repo.save("patients.json", PATIENTS)
        self.repo.save("users.json", [{"username": "admin"}])
        self.assertEqual(self.repo.load("patients.json"), PATIENTS)
        self.assertEqual(self.repo.load("users.json"), [{"username": "admin"}])


class TestEncoding(RepositoryTestCase):
    """Checks the real bytes on disk, not only that the program reads them back."""

    def test_file_bytes_are_utf8_without_escapes(self):
        self.repo.save("patients.json", [{"full_name": "José Peña"}])
        raw = (self.folder / "patients.json").read_bytes()

        self.assertIn("José Peña".encode("utf-8"), raw)
        # What ensure_ascii=True would write for é and ñ.
        self.assertNotIn(b"\\u00e9", raw)
        self.assertNotIn(b"\\u00f1", raw)
        # In cp1252 the é is the single byte 0xE9; in UTF-8 it is C3 A9.
        self.assertNotIn("José".encode("cp1252"), raw)

    def test_file_decodes_as_strict_utf8(self):
        self.repo.save("patients.json", PATIENTS)
        raw = (self.folder / "patients.json").read_bytes()
        text = raw.decode("utf-8")  # raises UnicodeDecodeError if not UTF-8
        self.assertEqual(json.loads(text), PATIENTS)

    def test_file_is_indented_with_four_spaces(self):
        self.repo.save("patients.json", [{"full_name": "José Peña"}])
        raw = (self.folder / "patients.json").read_bytes()
        self.assertIn(b'\n    {\n        "full_name": ', raw)

    def test_encoding_is_defined_once_as_utf8(self):
        self.assertEqual(JsonRepository.ENCODING, "utf-8")


class TestMissingFile(RepositoryTestCase):
    def test_missing_file_returns_empty_list(self):
        self.assertEqual(self.repo.load("care_records.json"), [])

    def test_missing_file_is_created_with_an_empty_list(self):
        self.repo.load("care_records.json")
        path = self.folder / "care_records.json"
        self.assertTrue(path.is_file())
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [])

    def test_missing_file_creates_no_corrupted_copy(self):
        self.repo.load("care_records.json")
        self.assertEqual(self.corrupted_copies("care_records"), [])


class TestCorruptedFile(RepositoryTestCase):
    def write_raw(self, filename: str, content: bytes) -> Path:
        path = self.folder / filename
        path.write_bytes(content)
        return path

    def test_invalid_json_raises_corrupted_file_error(self):
        self.write_raw("tickets.json", b'[{"number": "N-001",')
        with self.assertRaises(CorruptedFileError) as context:
            self.repo.load("tickets.json")
        self.assertEqual(context.exception.filename, "tickets.json")
        self.assertIn("tickets.json", str(context.exception))
        self.assertIsInstance(context.exception, ClinicError)

    def test_invalid_json_leaves_an_identical_copy(self):
        content = b"esto no es JSON"
        self.write_raw("tickets.json", content)
        with self.assertRaises(CorruptedFileError):
            self.repo.load("tickets.json")
        copies = self.corrupted_copies("tickets")
        self.assertEqual(len(copies), 1)
        self.assertRegex(copies[0].name, r"^tickets\.corrupted-\d{8}-\d{6}\.json$")
        self.assertEqual(copies[0].read_bytes(), content)

    def test_original_damaged_file_is_kept(self):
        path = self.write_raw("tickets.json", b"{roto")
        with self.assertRaises(CorruptedFileError):
            self.repo.load("tickets.json")
        self.assertEqual(path.read_bytes(), b"{roto")

    def test_cp1252_file_is_treated_as_corrupted(self):
        content = '[{"full_name": "José"}]'.encode("cp1252")
        self.write_raw("patients.json", content)
        with self.assertRaises(CorruptedFileError):
            self.repo.load("patients.json")
        copies = self.corrupted_copies("patients")
        self.assertEqual(len(copies), 1)
        # The copy keeps the cp1252 bytes as they were.
        self.assertEqual(copies[0].read_bytes(), content)

    def test_json_that_is_not_a_list_is_treated_as_corrupted(self):
        self.write_raw("users.json", b'{"username": "admin"}')
        with self.assertRaises(CorruptedFileError):
            self.repo.load("users.json")
        self.assertEqual(len(self.corrupted_copies("users")), 1)

    def test_save_after_corruption_writes_a_clean_file(self):
        self.write_raw("tickets.json", b"{roto")
        with self.assertRaises(CorruptedFileError):
            self.repo.load("tickets.json")
        self.repo.save("tickets.json", [])
        self.assertEqual(self.repo.load("tickets.json"), [])
        self.assertEqual(len(self.corrupted_copies("tickets")), 1)

    def test_failed_backup_raises_storage_error(self):
        self.write_raw("tickets.json", b"{roto")
        with mock.patch(
            "persistence.json_repository.shutil.copy2", side_effect=OSError
        ):
            with self.assertRaises(StorageError):
                self.repo.load("tickets.json")


class TestSaveErrors(RepositoryTestCase):
    def test_failed_replace_keeps_the_original(self):
        self.repo.save("patients.json", PATIENTS)
        before = (self.folder / "patients.json").read_bytes()

        with mock.patch(
            "persistence.json_repository.os.replace", side_effect=OSError
        ):
            with self.assertRaises(StorageError) as context:
                self.repo.save("patients.json", [])

        self.assertIsInstance(context.exception, ClinicError)
        self.assertEqual((self.folder / "patients.json").read_bytes(), before)
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_failure_halfway_through_writing_keeps_the_original(self):
        """Simulates the program failing in the middle of json.dump."""
        self.repo.save("patients.json", PATIENTS)
        before = (self.folder / "patients.json").read_bytes()

        def broken_dump(data, file, **kwargs):
            file.write('[{"code": "PAC-')  # half a file
            raise OSError("disco lleno")

        with mock.patch(
            "persistence.json_repository.json.dump", side_effect=broken_dump
        ):
            with self.assertRaises(StorageError):
                self.repo.save("patients.json", [{"code": "PAC-0003"}])

        self.assertEqual((self.folder / "patients.json").read_bytes(), before)
        self.assertEqual(self.repo.load("patients.json"), PATIENTS)
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_storage_error_message_is_in_spanish(self):
        with mock.patch(
            "persistence.json_repository.os.replace", side_effect=OSError
        ):
            with self.assertRaises(StorageError) as context:
                self.repo.save("patients.json", [])
        self.assertIn("No se pudo guardar", str(context.exception))

    def test_unserializable_data_keeps_its_type_and_cleans_up(self):
        with self.assertRaises(TypeError):
            self.repo.save("patients.json", [{"when": object()}])
        self.assertFalse(self.repo.exists("patients.json"))
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_unreadable_path_raises_storage_error(self):
        # A folder with the name of the file: open() fails with an OSError
        # that is not FileNotFoundError (IsADirectoryError on Linux,
        # PermissionError on Windows).
        (self.folder / "users.json").mkdir()
        with self.assertRaises(StorageError):
            self.repo.load("users.json")


if __name__ == "__main__":
    unittest.main()
