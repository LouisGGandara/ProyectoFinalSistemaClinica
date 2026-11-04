"""Abstract base class of every tab of the main window.

Each tab of MainView inherits from BaseTab. The base class holds what every
tab needs (the system, the change callback and the error handling of the
buttons), and each subclass writes only its own widgets and its refresh().
"""

import tkinter as tk
from abc import ABC, abstractmethod
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from models.permissions import Permission
from services.clinic_system import ClinicSystem
from ui.widgets import GAP, DataTable, show_error
from utils.exceptions import ClinicError, StorageError


class BaseTab(ttk.Frame, ABC):
    """Tab with a title, a required permission and its own refresh().

    Subclasses set the class attributes title and required_permission.
    MainView reads both before creating the tab: it builds only the tabs
    the user may see and uses title as the tab label. None in
    required_permission means every role sees the tab.
    """

    title: str = ""
    required_permission: Permission | None = None

    PADDING = GAP

    def __init__(
        self,
        parent: tk.Misc,
        system: ClinicSystem,
        on_change: Callable[[], None],
    ) -> None:
        """Keep the system and the function that refreshes every tab.

        on_change is MainView.notify_change. A tab calls it after an
        operation that changed data, so the other tabs show the change too.
        """
        super().__init__(parent, padding=self.PADDING)
        self._system = system
        self._on_change = on_change
        # True while _run is working, message boxes included. See _run.
        self._busy = False

    @abstractmethod
    def refresh(self) -> None:
        """Load the data of this tab again from the system.

        Each tab reads different data: the queues, the patients, the
        statistics. It should not clear the forms, because a validation
        error must leave what the user typed (CP-07).
        """

    def first_field(self) -> tk.Misc | None:
        """Widget that should get the cursor when the tab is opened.

        Each tab with a form returns its first field. Tabs that only show
        data keep this default and return None. MainView calls focus_first()
        every time the user switches tabs, so the cursor is ready to type.
        """
        return None

    def focus_first(self) -> None:
        """Put the cursor in first_field(), or on the tab itself if it has none.

        A tab without fields still takes the focus. Otherwise the cursor
        would stay in a field of the tab the user just left, which is now
        hidden, and whatever they typed would end up there.
        """
        field = self.first_field()
        (field or self).focus_set()

    def _run(
        self,
        operation: Callable[..., Any],
        *args: Any,
        on_success: Callable[[Any], None] | None = None,
        parent: tk.Misc | None = None,
    ) -> None:
        """Call a ClinicSystem operation and handle its errors in one place.

        If the operation raises ClinicError, the user sees its Spanish
        message and nothing else happens. If it works, every tab is
        refreshed and then on_success receives what the operation
        returned, for example the new ticket so the tab can show its number.

        parent is the window the error message appears over. It defaults to
        the tab; a dialog passes itself, so the message is not hidden
        behind it.

        A button handler then fits in one line:
            self._run(self._system.call_next, on_success=self._show_called)

        A second call that arrives while the first one is still running is
        ignored. Tk keeps handling keys while a message box is open, so a
        quick second Enter or Space used to repeat the operation, and its
        error message covered the success message of the first (test E2-12).
        """
        if self._busy:
            return
        self._busy = True
        try:
            self._run_once(operation, args, on_success, parent or self)
        finally:
            self._busy = False

    def _run_once(
        self,
        operation: Callable[..., Any],
        args: tuple[Any, ...],
        on_success: Callable[[Any], None] | None,
        message_parent: tk.Misc,
    ) -> None:
        """The body of _run, without the guard against a repeated call."""
        try:
            result = operation(*args)
        except StorageError as error:
            # The change is already in memory and only the file failed, so
            # the tabs are refreshed to show what the system now holds.
            show_error(error.message, parent=message_parent)
            self._on_change()
            return
        except ClinicError as error:
            show_error(error.message, parent=message_parent)
            return
        self._on_change()
        if on_success is not None:
            on_success(result)

    def _query(
        self,
        operation: Callable[..., Any],
        *args: Any,
        parent: tk.Misc | None = None,
    ) -> Any:
        """Call a ClinicSystem query and return its answer, or None after an error.

        Works like _run for operations that only read, such as get_status
        or search. Nothing changed, so the other tabs are not refreshed. Use
        it only with queries that never return None themselves, because
        None here means the user already saw an error message.
        """
        try:
            return operation(*args)
        except ClinicError as error:
            show_error(error.message, parent=parent or self)
            return None

    def _selected_or_warn(self, table: DataTable, message: str) -> str | None:
        """Id of the selected row of the table, or None after showing the message.

        Used before modifying, cancelling or creating a ticket, which all
        need a row picked first (section 4.6), for example:
            number = self._selected_or_warn(table, "Selecciona un turno en la tabla.")
        """
        selected = table.selected_id()
        if selected is None:
            show_error(message, parent=self)
        return selected

