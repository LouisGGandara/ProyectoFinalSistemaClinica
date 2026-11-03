"""Abstract base class for every person in the system.

Users and patients inherit from Person. Nobody in the system is only a
person, so the class cannot be instantiated: each subclass has to say how it
describes itself.
"""

from abc import ABC, abstractmethod

from utils.validator import Validator


class Person(ABC):
    """Common data of a person: the full name."""

    def __init__(self, full_name: str) -> None:
        # Goes through the setter, so the name is validated from the start.
        self.full_name = full_name

    @property
    def full_name(self) -> str:
        """Full name, with single spaces and no edge spaces."""
        return self._full_name

    @full_name.setter
    def full_name(self, value: str) -> None:
        self._full_name = Validator.full_name(value)

    @abstractmethod
    def description(self) -> str:
        """Return a short Spanish text that identifies the person."""

    def __str__(self) -> str:
        return self._full_name
