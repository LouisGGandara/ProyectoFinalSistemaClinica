"""Input validation for every data format of roadmap section 3.9.

Each method receives the raw value (usually the text of an Entry), cleans it
and returns it ready to store, or raises ValidationError with the message of
section 4.6. The limits live in class constants, so changing a rule means
changing one line.
"""

import re
import unicodedata

from utils.exceptions import ValidationError


class Validator:
    """Static methods that clean a value and return it, or raise ValidationError."""

    # Patterns are matched with re.fullmatch, so they need no ^ or $ anchors.
    # [0-9] is used instead of \d because \d also accepts digits from other
    # alphabets, such as Arabic numerals.
    PATIENT_CODE_PATTERN = r"PAC-[0-9]{4}"
    LETTER = "A-Za-zÁÉÍÓÚÜÑáéíóúüñ"
    FULL_NAME_PATTERN = rf"[{LETTER}]+(?:[ -][{LETTER}]+)*"
    PHONE_PATTERN = r"[2-7][0-9]{7}"
    USERNAME_MIN_LENGTH = 4
    USERNAME_MAX_LENGTH = 20
    USERNAME_PATTERN = rf"[A-Za-z0-9_]{{{USERNAME_MIN_LENGTH},{USERNAME_MAX_LENGTH}}}"

    NAME_MIN_LENGTH = 3
    NAME_MAX_LENGTH = 80
    AGE_MIN = 0
    AGE_MAX = 120
    REASON_MIN_LENGTH = 5
    REASON_MAX_LENGTH = 200
    PASSWORD_MIN_LENGTH = 6

    @staticmethod
    def required(value, field_label: str) -> str:
        """Return the value as text without edge spaces, or fail if it is empty.

        field_label is the name the user sees on the form, such as "Teléfono".
        """
        text = "" if value is None else str(value).strip()
        if not text:
            raise ValidationError(f"Completa el campo {field_label}.")
        return text

    @staticmethod
    def patient_code(value) -> str:
        """Return the code in upper case if it follows PAC-0000."""
        code = Validator.required(value, "Código").upper()
        if not re.fullmatch(Validator.PATIENT_CODE_PATTERN, code):
            raise ValidationError("El código debe tener el formato PAC-0000.")
        return code

    @staticmethod
    def full_name(value) -> str:
        """Return the name with single spaces if it follows section 3.9.

        Letters with accents and ñ are accepted. A hyphen must join two words,
        as in López-Pérez.
        """
        text = Validator.required(value, "Nombre")
        # Text pasted from some programs writes "é" as "e" plus a separate
        # accent mark. NFC joins them so the pattern recognizes the letter.
        text = unicodedata.normalize("NFC", text)
        name = " ".join(text.split())
        if not Validator.NAME_MIN_LENGTH <= len(name) <= Validator.NAME_MAX_LENGTH:
            raise ValidationError(
                f"El nombre debe tener entre {Validator.NAME_MIN_LENGTH} "
                f"y {Validator.NAME_MAX_LENGTH} caracteres."
            )
        if not re.fullmatch(Validator.FULL_NAME_PATTERN, name):
            raise ValidationError(
                "El nombre solo puede tener letras, espacios y guiones entre palabras."
            )
        return name

    @staticmethod
    def age(value) -> int:
        """Return the age as an int between AGE_MIN and AGE_MAX.

        Accepts an int or the text of a form field.
        """
        message = (
            f"La edad debe ser un número entero entre "
            f"{Validator.AGE_MIN} y {Validator.AGE_MAX}."
        )
        # bool is a subclass of int in Python, so True would pass as 1.
        if isinstance(value, bool):
            raise ValidationError(message)
        if isinstance(value, int):
            number = value
        else:
            text = Validator.required(value, "Edad")
            try:
                number = int(text)
            except ValueError as error:
                raise ValidationError(message) from error
        if not Validator.AGE_MIN <= number <= Validator.AGE_MAX:
            raise ValidationError(message)
        return number

    @staticmethod
    def phone(value) -> str:
        """Return the phone if it has 8 digits and starts with 2 to 7."""
        phone = Validator.required(value, "Teléfono")
        if not re.fullmatch(Validator.PHONE_PATTERN, phone):
            raise ValidationError(
                "El teléfono debe tener 8 dígitos, por ejemplo 55551234."
            )
        return phone

    @staticmethod
    def reason(value) -> str:
        """Return the reason for the visit if its length is within the limits."""
        reason = Validator.required(value, "Motivo")
        if len(reason) < Validator.REASON_MIN_LENGTH:
            raise ValidationError(
                f"Describe el motivo con al menos "
                f"{Validator.REASON_MIN_LENGTH} caracteres."
            )
        if len(reason) > Validator.REASON_MAX_LENGTH:
            raise ValidationError(
                f"El motivo no puede pasar de "
                f"{Validator.REASON_MAX_LENGTH} caracteres."
            )
        return reason

    @staticmethod
    def username(value) -> str:
        """Return the username if it has 4 to 20 letters, digits or underscores.

        Whether the name is already taken is checked by UserManager.
        """
        username = Validator.required(value, "Usuario")
        if not re.fullmatch(Validator.USERNAME_PATTERN, username):
            raise ValidationError(
                f"El nombre de usuario debe tener entre "
                f"{Validator.USERNAME_MIN_LENGTH} y {Validator.USERNAME_MAX_LENGTH} "
                "caracteres: letras, números o guion bajo."
            )
        return username

    @staticmethod
    def password(value) -> str:
        """Return the password unchanged if it is long enough.

        Unlike the other fields, the password is not stripped: a space the
        user typed is part of the password.
        """
        Validator.required(value, "Contraseña")
        password = str(value)
        if len(password) < Validator.PASSWORD_MIN_LENGTH:
            raise ValidationError(
                f"La contraseña debe tener al menos "
                f"{Validator.PASSWORD_MIN_LENGTH} caracteres."
            )
        return password
