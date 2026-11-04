"""Action history tab and the undo button (step D7).

The tab shows the last action, every action from the most recent down
(RF-28, RF-29) and the button that undoes the last undoable one (RF-30).
The two stacks live in ActionHistory, and the tab only reads what
ClinicSystem returns. Only the administrator sees this tab (section 3.1).
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from models.permissions import Permission
from services.clinic_system import ClinicSystem
from ui.base_tab import BaseTab
from ui.widgets import (
    FRAME_PADDING,
    GAP,
    HEADING_FONT,
    HINT_COLOR,
    SMALL_GAP,
    STRONG_FONT,
    DataTable,
    confirm,
    count_text,
    show_info,
)


class ActionsTab(BaseTab):
    """Shows the action history and undoes the last undoable action."""

    title = "Historial de acciones"
    required_permission = Permission.VIEW_ACTION_LOG

    HEADING = "Historial de acciones"
    LAST_TITLE = "Última acción"
    UNDO_TITLE = "Deshacer"
    UNDO_TEXT = "Deshacer última acción"
    NEXT_UNDO_LABEL = "Se deshará:"
    LAST_DETAILS = "Usuario: {username}    Fecha: {timestamp}"

    NO_ACTIONS_TEXT = "No hay acciones registradas."
    NOTHING_TO_UNDO_TEXT = "No hay acciones que se puedan deshacer."
    COUNT_TEXT = "{count}. La más reciente aparece arriba."
    UNDO_QUESTION = (
        "¿Deshacer esta acción?\n\n{action_type}: {description}\n\n"
        "Los datos vuelven a como estaban antes de esa acción, y no hay "
        "forma de rehacerla."
    )
    UNDONE_MESSAGE = "Se deshizo la acción.\n\n{action_type}: {description}"

    # Values of the last column. An undone action stays in the table with
    # its own value, so the administrator sees what was reverted (step D7).
    CAN_UNDO = "Sí"
    EVIDENCE_ONLY = "No (evidencia)"
    ALREADY_UNDONE = "Ya se deshizo"

    # The date goes first because DataTable uses the first value as the
    # row id. Two actions can share a second, but nothing here needs the
    # selection, and DataTable keeps the rows apart anyway.
    COLUMNS = (
        ("timestamp", "Fecha", 150),
        ("action_type", "Tipo", 175),
        ("description", "Descripción", 500),
        ("username", "Usuario", 75),
        ("undoable", "¿Deshacible?", 105),
    )

    def __init__(
        self,
        parent: tk.Misc,
        system: ClinicSystem,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent, system, on_change)
        self._last_type = tk.StringVar()
        self._last_description = tk.StringVar()
        self._last_details = tk.StringVar()
        self._next_undo = tk.StringVar()
        self._summary = tk.StringVar()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        ttk.Label(self, text=self.HEADING, font=HEADING_FONT).grid(
            row=0, column=0, sticky="w"
        )
        self._build_top()
        ttk.Label(self, textvariable=self._summary).grid(
            row=2, column=0, sticky="w", pady=(GAP, SMALL_GAP)
        )
        self._table = DataTable(self, self.COLUMNS, height=14)
        self._table.grid(row=3, column=0, sticky="nsew")

    def _build_top(self) -> None:
        """The Última acción box on the left and the Deshacer box on the right."""
        top = ttk.Frame(self)
        top.grid(row=1, column=0, sticky="ew", pady=(GAP, 0))
        top.columnconfigure(0, weight=3, uniform="box")
        top.columnconfigure(1, weight=2, uniform="box")

        last_box = ttk.LabelFrame(top, text=self.LAST_TITLE, padding=FRAME_PADDING)
        last_box.grid(row=0, column=0, sticky="nsew", padx=(0, GAP))
        ttk.Label(last_box, textvariable=self._last_type, font=STRONG_FONT).pack(
            anchor="w"
        )
        ttk.Label(
            last_box,
            textvariable=self._last_description,
            wraplength=480,
            justify="left",
        ).pack(anchor="w", pady=(SMALL_GAP, 0))
        ttk.Label(
            last_box, textvariable=self._last_details, foreground=HINT_COLOR
        ).pack(anchor="w", pady=(SMALL_GAP, 0))

        undo_box = ttk.LabelFrame(top, text=self.UNDO_TITLE, padding=FRAME_PADDING)
        undo_box.grid(row=0, column=1, sticky="nsew")
        self._undo_button = ttk.Button(
            undo_box, text=self.UNDO_TEXT, command=self._undo
        )
        self._undo_button.pack(anchor="w")
        # This label says what the button would revert, or why it is off.
        # With the button disabled, the message of CP-22 shows up here.
        ttk.Label(
            undo_box, textvariable=self._next_undo, wraplength=300, justify="left"
        ).pack(anchor="w", pady=(GAP, 0))

    # -------------------------------------------------------------- refresh

    def refresh(self) -> None:
        """Reload the last action, the table and the state of the button.

        MainView calls this after every change, so an action done in another
        tab, such as a cancellation, shows up here right away.
        """
        actions = self._system.action_history()
        self._table.load(self._row(action) for action in actions)

        if actions:
            self._show_last_action(self._system.last_action())
            count = count_text(len(actions), "acción registrada", "acciones registradas")
            self._summary.set(self.COUNT_TEXT.format(count=count))
        else:
            # The login is always registered, so this only happens if the
            # tab is ever shown without a session behind it (RF-31).
            self._last_type.set(self.NO_ACTIONS_TEXT)
            self._last_description.set("")
            self._last_details.set("")
            self._summary.set(self.NO_ACTIONS_TEXT)

        self._refresh_undo()

    def _row(self, action) -> tuple:
        """One table row, with the values in the order of COLUMNS."""
        return (
            action.timestamp,
            action.action_type,
            action.description,
            action.username,
            self._undo_state(action),
        )

    def _undo_state(self, action) -> str:
        """Text of the last column for one action.

        is_undoable is answered by each action class, so the tab does not
        ask which class it got. undone exists only on the undoable ones,
        which is why it is read after is_undoable.
        """
        if not action.is_undoable:
            return self.EVIDENCE_ONLY
        if action.undone:
            return self.ALREADY_UNDONE
        return self.CAN_UNDO

    def _show_last_action(self, action) -> None:
        self._last_type.set(action.action_type)
        self._last_description.set(action.description)
        self._last_details.set(
            self.LAST_DETAILS.format(
                username=action.username, timestamp=action.timestamp
            )
        )

    def _refresh_undo(self) -> None:
        """Enable the button only when can_undo() is true, as step D7 asks.

        The permission is checked first because can_undo() itself requires
        UNDO. Today only the administrator sees the tab and also has UNDO,
        but a role that may read the history without undoing it would still
        get a disabled button instead of an error.
        """
        if not self._system.has_permission(Permission.UNDO):
            self._undo_button.state(["disabled"])
            self._next_undo.set("")
            return
        if self._system.can_undo():
            self._undo_button.state(["!disabled"])
            action = self._system.next_undo()
            self._next_undo.set(
                f"{self.NEXT_UNDO_LABEL} {action.action_type}. {action.description}"
            )
        else:
            self._undo_button.state(["disabled"])
            self._next_undo.set(self.NOTHING_TO_UNDO_TEXT)

    # -------------------------------------------------------------- actions

    def _undo(self) -> None:
        """Deshacer última acción (RF-30), after asking for confirmation (RNF-04).

        The confirmation names the action, so the administrator knows what
        will change before saying yes. If the stack emptied in the meantime,
        next_undo raises EmptyStackError and _query shows its message (RF-31).
        """
        action = self._query(self._system.next_undo)
        if action is None:
            return
        question = self.UNDO_QUESTION.format(
            action_type=action.action_type, description=action.description
        )
        if not confirm(question, parent=self):
            return
        self._run(self._system.undo, on_success=self._after_undo)

    def _after_undo(self, action) -> None:
        show_info(
            self.UNDONE_MESSAGE.format(
                action_type=action.action_type, description=action.description
            ),
            parent=self,
        )
