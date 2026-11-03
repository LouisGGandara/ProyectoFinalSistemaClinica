"""Patient management.

PatientManager keeps every patient in memory, indexed by code, and writes
the whole list to patients.json after each change. The code is the key that
tickets and care records use to refer to a patient, so it cannot repeat
(RN-03).
"""

from models.patient import Patient
from persistence.json_repository import JsonRepository
from utils.exceptions import DuplicateError, NotFoundError, ValidationError


class PatientManager:
    """Keeps the patients in memory and saves them to patients.json."""

    FILE = "patients.json"

    CODE_PREFIX = "PAC-"
    # Four digits, as in the PAC-0000 format of section 3.9.
    CODE_MAX_NUMBER = 9999

    def __init__(self, repository: JsonRepository) -> None:
        self._repository = repository
        self._patients: dict[str, Patient] = {}

    def load(self) -> None:
        """Read patients.json and build the patients.

        The list is emptied before reading. If the file is damaged, the
        repository raises CorruptedFileError and the manager stays empty,
        which is what ClinicSystem expects (section 4.7).

        Raises ValidationError if a row is wrong or a code appears twice,
        which only happens when the file was edited by hand.
        """
        self._patients = {}
        rows = self._repository.load(self.FILE)

        patients: dict[str, Patient] = {}
        for row in rows:
            patient = Patient.from_dict(row)
            if patient.code in patients:
                raise ValidationError(
                    f"El código {patient.code} está repetido en {self.FILE}."
                )
            patients[patient.code] = patient
        self._patients = patients

    def register(self, patient: Patient) -> None:
        """Add a new patient and save, or raise DuplicateError if the code exists."""
        if patient.code in self._patients:
            raise DuplicateError(
                f"Ya existe un paciente con el código {patient.code}."
            )
        self._patients[patient.code] = patient
        self._save()

    def get(self, code: str) -> Patient:
        """Return the patient with this code, or raise NotFoundError."""
        key = self._key(code)
        patient = self._patients.get(key)
        if patient is None:
            raise NotFoundError(f"No existe un paciente con el código {key}.")
        return patient

    def exists(self, code: str) -> bool:
        """Tell whether a patient has this code."""
        return self._key(code) in self._patients

    def update(self, code: str, full_name: str, age: int | str, phone: str) -> dict:
        """Change name, age and phone, save, and return the previous values.

        Patient.update_details validates the three values before changing
        any, so an invalid one leaves both the patient and the file as they
        were. The returned dict is what the undo needs to restore them.
        """
        patient = self.get(code)
        previous = patient.update_details(full_name, age, phone)
        self._save()
        return previous

    def delete(self, code: str) -> None:
        """Remove a patient and save. Only the undo of a registration uses it."""
        patient = self.get(code)
        del self._patients[patient.code]
        self._save()

    def next_code(self) -> str:
        """Return the highest existing code plus one, as in PAC-0008.

        Codes left free in between are not reused, so the proposal always
        comes after the most recent patient.
        """
        highest = max(
            (int(code.removeprefix(self.CODE_PREFIX)) for code in self._patients),
            default=0,
        )
        if highest >= self.CODE_MAX_NUMBER:
            raise ValidationError(
                "Ya se usaron todos los códigos de paciente hasta PAC-9999."
            )
        return f"{self.CODE_PREFIX}{highest + 1:04d}"

    def list_all(self) -> list[Patient]:
        """Return the patients sorted by code."""
        # Every code has four digits, so sorting the text gives numeric order.
        return [self._patients[code] for code in sorted(self._patients)]

    def patients_by_code(self) -> dict:
        """Return a copy of the code-to-patient dict, for loading the tickets.

        It is a copy so TicketManager can read it without being able to add
        or remove patients behind this manager's back.
        """
        return dict(self._patients)

    def count(self) -> int:
        """Return the number of registered patients."""
        return len(self._patients)

    @staticmethod
    def _key(code: str) -> str:
        """Clean a code typed by the user so it matches the stored key."""
        return str(code).strip().upper()

    def _save(self) -> None:
        """Write every patient to patients.json, sorted by code."""
        self._repository.save(
            self.FILE, [patient.to_dict() for patient in self.list_all()]
        )
