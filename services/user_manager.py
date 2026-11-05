"""User management: loading, login, creation and deletion.

UserManager keeps every user in memory, indexed by username, and writes the
whole list to users.json after each change. The rules come from roadmap
section 3.10 and RN-12: the first run creates two users so someone can log
in, there is always at least one administrator, and nobody deletes their own
account.
"""

from models.permissions import Permission
from models.user import (
    ADMINISTRATOR_ROLE,
    RECEPTIONIST_ROLE,
    ROLES,
    User,
    user_from_dict,
)
from persistence.json_repository import JsonRepository
from utils.exceptions import (
    CorruptedFileError,
    DuplicateError,
    InvalidCredentialsError,
    NotFoundError,
    ValidationError,
)
from utils.validator import Validator


class UserManager:
    """Keeps the users in memory and saves them to users.json."""

    FILE = "users.json"

    # Users created when users.json is missing or empty (section 3.10):
    # full name, username, password and role.
    DEFAULT_USERS = (
        ("Administrador General", "admin", "Admin123", ADMINISTRATOR_ROLE),
        ("Recepcionista General", "recepcion", "Recep123", RECEPTIONIST_ROLE),
    )

    def __init__(self, repository: JsonRepository) -> None:
        self._repository = repository
        self._users: dict[str, User] = {}

    def load(self) -> None:
        """Read users.json and build the users.

        If the file did not exist or holds an empty list, the default users
        are created and saved. A damaged file is treated as empty, so the
        default users are created too and the clinic can still log in; the
        CorruptedFileError is raised afterwards so ClinicSystem can warn the
        user. The repository has already kept a copy of the damaged file.

        Raises ValidationError if a row is wrong or a username appears twice,
        which only happens when the file was edited by hand. In that case the
        users loaded before stay as they were.
        """
        corrupted = None
        try:
            rows = self._repository.load(self.FILE)
        except CorruptedFileError as error:
            rows = []
            corrupted = error

        users: dict[str, User] = {}
        for row in rows:
            user = user_from_dict(row)
            if user.username in users:
                raise ValidationError(
                    f"El usuario «{user.username}» está repetido en {self.FILE}."
                )
            users[user.username] = user
        self._users = users

        if not self._users:
            self._create_default_users()
        if corrupted is not None:
            raise corrupted

    def login(self, username: str, password: str) -> User:
        """Return the user whose username and password match.

        Empty fields raise ValidationError with the name of the field (CP-03).
        A wrong username and a wrong password raise the same
        InvalidCredentialsError, so the message gives no hint about which of
        the two failed (RNF-09).
        """
        username = Validator.required(username, "Usuario")
        Validator.required(password, "Contraseña")
        user = self._users.get(username)
        if user is None or not user.verify_password(password):
            raise InvalidCredentialsError()
        return user

    def create_user(
        self, full_name: str, username: str, password: str, role: str
    ) -> User:
        """Create a user of the given role, save it and return it.

        role is the Spanish name shown on screen ("Administrador" or
        "Recepcionista"). The username is compared without case, so "Admin"
        counts as a duplicate of "admin": two names that only differ in
        capital letters would be easy to confuse at the login screen.
        """
        user_class = ROLES.get(role)
        if user_class is None:
            raise ValidationError("Selecciona un rol válido.")
        username = Validator.username(username)
        if self._username_taken(username):
            raise DuplicateError("Ese nombre de usuario ya existe.")

        user = user_class.create(full_name, username, password)
        self._users[user.username] = user
        self._save()
        return user

    def delete_user(self, username: str, requested_by: User) -> None:
        """Delete a user and save, following RN-12.

        Nobody can delete their own account, and the last user with the
        MANAGE_USERS permission cannot be deleted, because then nobody could
        create users again. ClinicSystem checks that requested_by may manage
        users; this method only checks the rule about which account goes.
        """
        user = self._users.get(username)
        if user is None:
            raise NotFoundError(f"No existe el usuario «{username}».")
        if user.username == requested_by.username:
            raise ValidationError("No puedes eliminar tu propia cuenta.")
        # Asking for the permission, instead of the class, keeps the rule
        # right if another role with user management is added later.
        if (
            user.has_permission(Permission.MANAGE_USERS)
            and self._administrator_count() == 1
        ):
            raise ValidationError("Debe quedar al menos un administrador.")

        del self._users[user.username]
        self._save()

    def change_password(self, username: str, new_password: str) -> User:
        """Give a user a new password, save it and return the user.

        ClinicSystem decides who may ask for the change; this method only
        finds the user and saves. If the new password is not valid,
        User.change_password raises before anything is saved.
        """
        user = self._users.get(username)
        if user is None:
            raise NotFoundError(f"No existe el usuario «{username}».")
        user.change_password(new_password)
        self._save()
        return user

    def list_all(self) -> list[User]:
        """Return the users sorted by username."""
        return sorted(self._users.values(), key=lambda user: user.username.casefold())

    def _create_default_users(self) -> None:
        """Create the users of section 3.10 and save them."""
        for full_name, username, password, role in self.DEFAULT_USERS:
            user = ROLES[role].create(full_name, username, password)
            self._users[user.username] = user
        self._save()

    def _username_taken(self, username: str) -> bool:
        """Tell whether a user already has this name, ignoring case."""
        wanted = username.casefold()
        return any(name.casefold() == wanted for name in self._users)

    def _administrator_count(self) -> int:
        """Count the users who can manage users."""
        return sum(
            1 for user in self._users.values()
            if user.has_permission(Permission.MANAGE_USERS)
        )

    def _save(self) -> None:
        """Write every user to users.json."""
        self._repository.save(
            self.FILE, [user.to_dict() for user in self._users.values()]
        )
