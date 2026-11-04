"""System users and their roles.

User holds what every user shares: the username and the password check.
Administrator and Receptionist only decide their role, their permissions and
how they describe themselves (roadmap section 3.1). user_from_dict() turns a
row of users.json back into the right subclass.
"""

import hashlib
import hmac
import secrets
from abc import ABC, abstractmethod

from models.permissions import Permission
from models.person import Person
from utils.exceptions import ValidationError
from utils.validator import Validator

# Role names as they appear on screen and in users.json.
ADMINISTRATOR_ROLE = "Administrador"
RECEPTIONIST_ROLE = "Recepcionista"


class User(Person, ABC):
    """A person who can log in, with a username, a password hash and permissions.

    The password itself is never stored. User keeps a random salt and the
    SHA-256 hash of salt plus password, and checks a login by hashing the
    typed password the same way.
    """

    SALT_BYTES = 16

    def __init__(
        self, full_name: str, username: str, password_hash: str, salt: str
    ) -> None:
        super().__init__(full_name)
        self._username = Validator.username(username)
        # Double underscore: Python renames it to _User__password_hash, so
        # code outside this class cannot read or replace it by accident.
        self.__password_hash = password_hash
        self._salt = salt

    @property
    def username(self) -> str:
        """Login name. Read only, because other records refer to it."""
        return self._username

    @property
    @abstractmethod
    def role(self) -> str:
        """Spanish name of the role, such as "Administrador"."""

    @abstractmethod
    def permissions(self) -> set[Permission]:
        """Return the permissions of this role as a new set."""

    def has_permission(self, permission: Permission) -> bool:
        """Tell whether this user's role includes the permission."""
        return permission in self.permissions()

    def verify_password(self, password: str) -> bool:
        """Tell whether the password matches the stored hash."""
        typed_hash = self._compute_hash(password, self._salt)
        # compare_digest takes the same time whether the first or the last
        # character differs, so the timing gives no hint about the hash.
        return hmac.compare_digest(typed_hash, self.__password_hash)

    @staticmethod
    def _compute_hash(password: str, salt: str) -> str:
        """Return the SHA-256 hash of salt plus password, as hex text."""
        return hashlib.sha256(
            salt.encode("utf-8") + password.encode("utf-8")
        ).hexdigest()

    @classmethod
    def create(cls, full_name: str, username: str, password: str) -> "User":
        """Build a new user of this class from a plain password.

        Administrator.create(...) returns an Administrator and
        Receptionist.create(...) a Receptionist. The salt is new for every
        user, so two users with the same password get different hashes.
        """
        password = Validator.password(password)
        salt = secrets.token_hex(cls.SALT_BYTES)
        return cls(full_name, username, cls._compute_hash(password, salt), salt)

    def to_dict(self) -> dict:
        """Return the data saved in users.json."""
        return {
            "full_name": self.full_name,
            "username": self._username,
            "role": self.role,
            "password_hash": self.__password_hash,
            "salt": self._salt,
        }


class Administrator(User):
    """User with every permission."""

    @property
    def role(self) -> str:
        return ADMINISTRATOR_ROLE

    def permissions(self) -> set[Permission]:
        return set(Permission)

    def description(self) -> str:
        return (
            f"{self.full_name} ({self.username}), administrador "
            "con acceso a todas las funciones"
        )


class Receptionist(User):
    """User with the reception permissions.

    The receptionist does the daily work, from registering a patient to
    calling them in. Cancelling, undoing, reading the action log and managing
    users stay with the administrator.
    """

    @property
    def role(self) -> str:
        return RECEPTIONIST_ROLE

    def permissions(self) -> set[Permission]:
        return {
            Permission.REGISTER_PATIENT,
            Permission.UPDATE_PATIENT,
            Permission.CREATE_TICKET,
            Permission.SEARCH,
            Permission.VIEW_QUEUES,
            Permission.SERVE,
            Permission.VIEW_CARE_HISTORY,
            Permission.VIEW_STATS,
        }

    def description(self) -> str:
        return (
            f"{self.full_name} ({self.username}), recepcionista "
            "que registra pacientes y atiende turnos"
        )


# Which class to build for each role saved in users.json.
ROLES: dict[str, type[User]] = {
    ADMINISTRATOR_ROLE: Administrator,
    RECEPTIONIST_ROLE: Receptionist,
}


def user_from_dict(data: dict) -> User:
    """Build an Administrator or a Receptionist from a row of users.json.

    Raises ValidationError if the role is unknown or a field is missing,
    which can only happen when someone edits the file by hand.
    """
    role = data.get("role")
    # str() because a hand-edited file may hold a list or an object here,
    # and a dictionary lookup with those raises TypeError.
    user_class = ROLES.get(str(role))
    if user_class is None:
        raise ValidationError(f"El rol «{role}» no existe. Revisa users.json.")
    try:
        return user_class(
            data["full_name"], data["username"], data["password_hash"], data["salt"]
        )
    except KeyError as error:
        raise ValidationError(
            f"Falta el dato «{error.args[0]}» de un usuario en users.json."
        ) from error
