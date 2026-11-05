"""Dialog that asks for a new password (RF-43, RF-44).

The same dialog serves two screens. From Archivo > Cambiar mi contraseña it
also asks for the current password, because whoever has the session open
must prove they know it. From the users tab the administrator sets a new
password for someone else, so that field is not shown.
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from ui.widgets import (
    GAP,
    HINT_COLOR,
    SMALL_GAP,
    STRONG_FONT,
    add_form_entry,
    bind_enter,
    center_dialog,
)

ENTRY_WIDTH = 28


class PasswordDialog(tk.Toplevel):
    """Modal dialog with the password fields and Cambiar contraseña.

    Like NewTicketDialog, it does not call ClinicSystem: on_submit receives
    the dialog and the three values (the current password is an empty text
    when the field is not shown). The caller closes the dialog with close()
    once the change worked, so an error leaves it open to correct a field.
    """

    USER_LABEL = "Usuario"
    CURRENT_LABEL = "Contraseña actual"
    NEW_LABEL = "Nueva contraseña"
    CONFIRM_LABEL = "Confirmar contraseña"
    HINT = "Al menos 6 caracteres. Distingue mayúsculas de minúsculas."
    SUBMIT_TEXT = "Cambiar contraseña"
    CLOSE_TEXT = "Cancelar"
    PASSWORD_MASK = "•"

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        user_label: str,
        ask_current: bool,
        on_submit: Callable[["PasswordDialog", str, str, str], None],
    ) -> None:
        super().__init__(parent)
        self._on_submit = on_submit
        self._current = tk.StringVar()
        self._new = tk.StringVar()
        self._confirmation = tk.StringVar()

        self.title(title)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)

        body = ttk.Frame(self, padding=2 * GAP)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text=self.USER_LABEL).grid(
            row=0, column=0, sticky="w", pady=SMALL_GAP, padx=(0, GAP)
        )
        ttk.Label(body, text=user_label, font=STRONG_FONT).grid(
            row=0, column=1, sticky="w", pady=SMALL_GAP
        )

        entries = []
        row = 1
        if ask_current:
            entries.append(
                add_form_entry(
                    body, row, self.CURRENT_LABEL, self._current, ENTRY_WIDTH,
                    show=self.PASSWORD_MASK,
                )
            )
            row += 1
        for label, variable in (
            (self.NEW_LABEL, self._new),
            (self.CONFIRM_LABEL, self._confirmation),
        ):
            entries.append(
                add_form_entry(
                    body, row, label, variable, ENTRY_WIDTH, show=self.PASSWORD_MASK
                )
            )
            row += 1

        ttk.Label(body, text=self.HINT, foreground=HINT_COLOR).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(SMALL_GAP, 0)
        )

        buttons = ttk.Frame(body)
        buttons.grid(row=row + 1, column=0, columnspan=2, sticky="e", pady=(GAP, 0))
        submit_button = ttk.Button(
            buttons, text=self.SUBMIT_TEXT, command=self._submit, default="active"
        )
        submit_button.pack(side="right")
        ttk.Button(buttons, text=self.CLOSE_TEXT, command=self.close).pack(
            side="right", padx=(0, GAP)
        )

        for widget in (*entries, submit_button):
            bind_enter(widget, self._submit)
        self.bind("<Escape>", lambda _event: self.close())

        center_dialog(self, parent.winfo_toplevel())
        self.wait_visibility()
        self.grab_set()
        entries[0].focus_set()

    def _submit(self) -> None:
        self._on_submit(
            self, self._current.get(), self._new.get(), self._confirmation.get()
        )

    def close(self) -> None:
        """Release the grab and destroy the dialog."""
        self.grab_release()
        self.destroy()
