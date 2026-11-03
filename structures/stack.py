"""LIFO stack built on a list.

ActionHistory keeps two of these: one with every action, used to show the
history, and one with the actions that can be undone (section 3.7). The stack
does not know what it stores, so the same class serves both.
"""

from typing import Any

from utils.exceptions import EmptyStackError


class Stack:
    """Last-in, first-out stack used by the action history."""

    def __init__(self) -> None:
        # The end of the list is the top of the stack. append() and pop()
        # work there in O(1); using the start would shift every item.
        self._items: list[Any] = []

    def push(self, item: Any) -> None:
        """Put the item on top."""
        self._items.append(item)

    def pop(self) -> Any:
        """Remove and return the item on top.

        Raises EmptyStackError if the stack has no items.
        """
        self._check_not_empty()
        return self._items.pop()

    def peek(self) -> Any:
        """Return the item on top without removing it.

        Raises EmptyStackError if the stack has no items.
        """
        self._check_not_empty()
        return self._items[-1]

    def is_empty(self) -> bool:
        """True when the stack has no items."""
        return not self._items

    def count(self) -> int:
        """Number of items in the stack."""
        return len(self._items)

    def __len__(self) -> int:
        return self.count()

    def list_from_top(self) -> list[Any]:
        """Copy of the items, the most recent first.

        The history tab shows the actions in this order (RF-29).
        """
        return self._items[::-1]

    def _check_not_empty(self) -> None:
        if not self._items:
            raise EmptyStackError()

    def __repr__(self) -> str:
        return f"Stack({len(self._items)} items)"
