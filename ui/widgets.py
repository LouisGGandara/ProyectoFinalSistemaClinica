"""Reusable interface components: the DataTable and the message functions.

Every tab builds its tables with DataTable and shows its messages with
show_error, show_info, show_warning and confirm, so the window titles and
the table behaviour are written once. bind_enter and count_text live here
too, because several screens use them.

The fonts, the hint color and the spacing are also defined here. Every
screen takes them from these constants, so the margins match from one tab
to the next and a change of font is made in one line.
"""

import tkinter as tk
from collections.abc import Callable, Iterable, Sequence
from tkinter import messagebox, ttk

ERROR_TITLE = "Error"
INFO_TITLE = "Información"
WARNING_TITLE = "Aviso"
CONFIRM_TITLE = "Confirmar"

# Both Enter keys: the main one and the one on the numeric keypad.
ENTER_KEYS = ("<Return>", "<KP_Enter>")

# Segoe UI is the Windows interface font. On a system without it, Tk picks
# a similar one.
FONT_FAMILY = "Segoe UI"
TITLE_FONT = (FONT_FAMILY, 16, "bold")
HEADING_FONT = (FONT_FAMILY, 12, "bold")
STRONG_FONT = (FONT_FAMILY, 10, "bold")
NUMBER_FONT = (FONT_FAMILY, 14, "bold")
BIG_NUMBER_FONT = (FONT_FAMILY, 18, "bold")
# Gray for the help lines under a form or a button.
HINT_COLOR = "#555555"

# GAP separates two blocks of a screen (a form and its table, two
# buttons). FRAME_PADDING is the inner margin of every LabelFrame.
GAP = 10
SMALL_GAP = 4
FRAME_PADDING = 10


def count_text(count: int, singular: str, plural: str) -> str:
    """Number followed by the right form of the noun: "1 turno", "3 turnos".

    Writing "turno(s)" works for any count but reads like a form to fill
    in, so the screens pass both forms and this function picks one.
    """
    return f"{count} {singular if count == 1 else plural}"


def bind_enter(widget: tk.Misc, action: Callable[[], None]) -> None:
    """Run action when Enter is pressed on widget.

    It returns "break" so Tk skips its own handling of the key, which
    matters when action closes the window that holds the widget.
    """

    def handler(_event: tk.Event) -> str:
        action()
        return "break"

    for key in ENTER_KEYS:
        widget.bind(key, handler)


def show_error(
    message: str, parent: tk.Misc | None = None, title: str = ERROR_TITLE
) -> None:
    """Show an error message with an OK button."""
    messagebox.showerror(title, message, parent=parent)


def show_info(
    message: str, parent: tk.Misc | None = None, title: str = INFO_TITLE
) -> None:
    """Show an information message with an OK button."""
    messagebox.showinfo(title, message, parent=parent)


def show_warning(
    message: str, parent: tk.Misc | None = None, title: str = WARNING_TITLE
) -> None:
    """Show a warning, such as a damaged JSON file found at startup."""
    messagebox.showwarning(title, message, parent=parent)


def confirm(
    message: str, parent: tk.Misc | None = None, title: str = CONFIRM_TITLE
) -> bool:
    """Ask a yes or no question and return True if the user chose Sí (RNF-04)."""
    return messagebox.askyesno(title, message, parent=parent)


class DataTable(ttk.Frame):
    """Treeview with a vertical scrollbar, used by every table of the interface.

    Each column is a tuple (id, title, width). The first value of each row
    identifies it: a ticket number, a patient code or a username. That value
    is what selected_id() returns, so a tab can ask "which ticket did the
    user pick?" without reading the Treeview itself.
    """

    def __init__(
        self,
        parent: tk.Misc,
        columns: Sequence[tuple[str, str, int]],
        height: int = 10,
    ) -> None:
        super().__init__(parent)
        column_ids = [column_id for column_id, _title, _width in columns]
        self._tree = ttk.Treeview(
            self,
            columns=column_ids,
            show="headings",
            height=height,
            selectmode="browse",
        )
        for column_id, title, width in columns:
            self._tree.heading(column_id, text=title, anchor="w")
            self._tree.column(column_id, width=width, minwidth=40, anchor="w")

        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Treeview item id -> first value of the row. Kept apart because Tk
        # may hand back the values with a different type than they went in,
        # and two rows can share a first value (two actions in one second).
        self._row_ids: dict[str, str] = {}

    def load(self, rows: Iterable[Sequence[object]]) -> None:
        """Replace every row with the given ones, keeping the selection if it still exists.

        None is shown as an empty cell, for example a ticket that has no
        served_at date yet.
        """
        previous = self.selected_id()
        self.clear()
        for row in rows:
            values = ["" if value is None else str(value) for value in row]
            item = self._tree.insert("", "end", values=values)
            self._row_ids[item] = values[0]
            if values[0] == previous and not self._tree.selection():
                self._tree.selection_set(item)
                self._tree.see(item)

    def clear(self) -> None:
        """Remove every row."""
        self._tree.delete(*self._tree.get_children())
        self._row_ids.clear()

    def selected_id(self) -> str | None:
        """First value of the selected row, or None if no row is selected."""
        selection = self._tree.selection()
        if not selection:
            return None
        return self._row_ids.get(selection[0])

    def clear_selection(self) -> None:
        """Unselect the selected row, if there is one."""
        selection = self._tree.selection()
        if selection:
            self._tree.selection_remove(*selection)

    def on_select(self, callback: Callable[[], None]) -> None:
        """Call callback each time the selection of the table changes.

        Tk also sends this event when a row is unselected, so the callback
        should check selected_id() before acting.
        """
        self._tree.bind("<<TreeviewSelect>>", lambda _event: callback())
