"""System users and their roles.

Will also contain the function user_from_dict(data), which builds the right subclass
from the role saved in users.json. Implemented in step C2.
"""

from abc import ABC

from models.person import Person


class User(Person, ABC):
    """A person who can log in, with a username, a password hash and permissions."""

    pass


class Administrator(User):
    """User with every permission."""

    pass


class Receptionist(User):
    """User with the reception permissions."""

    pass
