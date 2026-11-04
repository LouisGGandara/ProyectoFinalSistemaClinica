"""Action history with two stacks and the undo operation (sections 3.7 and 3.8).

The history stack keeps every action, so the history tab can show them and
the last one. The undo stack keeps only the undoable ones. With a single
stack, a login registered after a cancellation would sit on top and block
the undo of the cancellation. With two, evidence never gets in the way.

Both stacks live in memory only. The actions hold references to the ticket
and patient objects of this run, so after closing the program there is
nothing left to revert (section 3.8).
"""

from models.actions import UNDONE, Action, LogOnlyAction, UndoableAction, UndoContext
from structures.stack import Stack
from utils.exceptions import EmptyStackError


class ActionHistory:
    """Records every action and undoes the last undoable one."""

    def __init__(self) -> None:
        self._history = Stack()
        self._undo_stack = Stack()

    def register(self, action: Action) -> None:
        """Push the action on the history and, if it can be undone, on the undo stack."""
        self._history.push(action)
        if action.is_undoable:
            self._undo_stack.push(action)

    def last_action(self) -> Action:
        """Return the most recent action of any kind (RF-28).

        Raises EmptyStackError if nothing has been registered yet.
        """
        if self._history.is_empty():
            raise EmptyStackError("No hay acciones registradas.")
        return self._history.peek()

    def list_all(self) -> list[Action]:
        """Every action, the most recent first (RF-29)."""
        return self._history.list_from_top()

    def has_actions(self) -> bool:
        """True if at least one action has been registered."""
        return not self._history.is_empty()

    def can_undo(self) -> bool:
        """True if there is an action left to undo."""
        return not self._undo_stack.is_empty()

    def next_undo(self) -> UndoableAction:
        """Return the action that undo_last would revert, without reverting it.

        It is the top of the undo stack. The history tab names it in the
        confirmation, so the user knows what is about to change before
        saying yes. Raises EmptyStackError when there is nothing to undo.
        """
        return self._undo_stack.peek()

    def undo_last(self, context: UndoContext, username: str) -> Action:
        """Undo the last undoable action and return it (RF-30).

        The action leaves the undo stack, but it stays in the history marked
        as undone, and an "Acción deshecha" entry is pushed as evidence.
        If the undo fails, the action goes back on the undo stack and the
        error is raised again, so nothing is lost and the user sees why.
        Raises EmptyStackError when there is nothing to undo (RF-31).
        """
        if self._undo_stack.is_empty():
            raise EmptyStackError()

        action: UndoableAction = self._undo_stack.pop()
        try:
            action.undo(context)
        except Exception:
            self._undo_stack.push(action)
            raise

        self.register(
            LogOnlyAction(
                UNDONE,
                f"Se deshizo: {action.description}",
                username,
                {
                    "undone_type": action.action_type,
                    "undone_timestamp": action.timestamp,
                    "original_user": action.username,
                    **action.data,
                },
            )
        )
        return action
