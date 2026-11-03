"""Clinic patient.

A patient is registered once and keeps the same code across all their
tickets (roadmap section 3.3). The reason for the visit and the care type
belong to each ticket, so they are not stored here.
"""

from models.person import Person
from utils.dates import now_text, parse_date
from utils.exceptions import ValidationError
from utils.validator import Validator


class Patient(Person):
    """Registered patient with code, age, phone and registration date.

    Age and phone go through property setters, so every change is validated
    in one place, whether it comes from the form, a JSON file or the undo.
    """

    def __init__(
        self,
        code: str,
        full_name: str,
        age: int | str,
        phone: str,
        registered_at: str | None = None,
    ) -> None:
        super().__init__(full_name)
        self._code = Validator.patient_code(code)
        # These two assignments call the setters below, so a new patient is
        # checked by the same rules as a later change.
        self.age = age
        self.phone = phone
        if registered_at is None:
            self._registered_at = now_text()
        else:
            # A date read from patients.json may have been edited by hand.
            parse_date(registered_at)
            self._registered_at = registered_at

    @property
    def code(self) -> str:
        """Patient code, such as PAC-0001. Read only: tickets refer to it."""
        return self._code

    @property
    def registered_at(self) -> str:
        """Registration date and time. Read only: it records a past event."""
        return self._registered_at

    @property
    def age(self) -> int:
        """Age in whole years, between 0 and 120."""
        return self._age

    @age.setter
    def age(self, value: int | str) -> None:
        # The validator raises before the assignment, so a bad value leaves
        # the previous age untouched.
        self._age = Validator.age(value)

    @property
    def phone(self) -> str:
        """Phone with 8 digits that starts with 2 to 7."""
        return self._phone

    @phone.setter
    def phone(self, value: str) -> None:
        self._phone = Validator.phone(value)

    def description(self) -> str:
        """Return the code, name and age, as in "PAC-0001, Ana López, 30 años"."""
        years = "año" if self._age == 1 else "años"
        return f"{self._code}, {self.full_name}, {self._age} {years}"

    def update_details(self, full_name: str, age: int | str, phone: str) -> dict:
        """Change name, age and phone together and return the previous values.

        All three values are validated before any of them changes, so a
        wrong age cannot leave the patient with a new name and the old age.
        The returned dict uses the parameter names as keys, so the undo can
        restore the patient with update_details(**previous).
        """
        new_name = Validator.full_name(full_name)
        new_age = Validator.age(age)
        new_phone = Validator.phone(phone)

        previous = {
            "full_name": self.full_name,
            "age": self._age,
            "phone": self._phone,
        }
        self.full_name = new_name
        self.age = new_age
        self.phone = new_phone
        return previous

    def to_dict(self) -> dict:
        """Return the data saved in patients.json."""
        return {
            "code": self._code,
            "full_name": self.full_name,
            "age": self._age,
            "phone": self._phone,
            "registered_at": self._registered_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Patient":
        """Build a patient from a row of patients.json.

        The values go through the same validation as a new patient. A missing
        key raises ValidationError, which only happens if the file was edited
        by hand.
        """
        try:
            return cls(
                data["code"],
                data["full_name"],
                data["age"],
                data["phone"],
                data["registered_at"],
            )
        except KeyError as error:
            raise ValidationError(
                f"Falta el dato «{error.args[0]}» de un paciente en patients.json."
            ) from error

    def __str__(self) -> str:
        return f"{self._code} - {self.full_name}"
