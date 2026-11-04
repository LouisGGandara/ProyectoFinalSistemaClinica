"""Login window (RF-01, RF-02).

The view only collects the two fields and shows what ClinicSystem answers.
ClinicSystem checks that the fields are filled in and that the credentials
match, so the rules live in one place and the view repeats none of them.
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from services.clinic_system import ClinicSystem
from ui.widgets import GAP, TITLE_FONT, bind_enter, show_error
from utils.exceptions import ClinicError, InvalidCredentialsError


class LoginView(ttk.Frame):
    """Login form with username, hidden password, Ingresar and Salir."""

    TITLE = "Sistema de atención y turnos"
    SUBTITLE = "Ingresa tu usuario y contraseña para continuar."
    USERNAME_LABEL = "Usuario"
    PASSWORD_LABEL = "Contraseña"
    LOGIN_TEXT = "Ingresar"
    EXIT_TEXT = "Salir"

    PASSWORD_MASK = "•"
    ENTRY_WIDTH = 36

    def __init__(
        self,
        parent: tk.Misc,
        system: ClinicSystem,
        on_success: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        """Build the form and put the cursor in the Usuario field.

        on_success is App.show_main. on_exit is App.request_exit, the same
        function the window's X uses, so Salir also asks before closing.
        """
        super().__init__(parent, padding=20)
        self._system = system
        self._on_success = on_success
        self._on_exit = on_exit
        self._username = tk.StringVar()
        self._password = tk.StringVar()

        self._build_form()
        # The window is not drawn yet; after_idle waits for it, otherwise
        # Windows may ignore the focus request.
        self.after_idle(self._username_entry.focus_set)

    def _build_form(self) -> None:
        """Lay out the form in a block centered in the window, as in the sketch."""
        form = ttk.Frame(self, padding=(48, 32))
        # place keeps the block in the middle when the window is resized.
        form.place(relx=0.5, rely=0.5, anchor="center")

        ttk.Label(form, text=self.TITLE, font=TITLE_FONT).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(form, text=self.SUBTITLE).grid(
            row=1, column=0, sticky="w", pady=(4, 16)
        )

        ttk.Label(form, text=self.USERNAME_LABEL).grid(row=2, column=0, sticky="w")
        self._username_entry = ttk.Entry(
            form, textvariable=self._username, width=self.ENTRY_WIDTH
        )
        self._username_entry.grid(row=3, column=0, sticky="ew", pady=(2, 12))

        ttk.Label(form, text=self.PASSWORD_LABEL).grid(row=4, column=0, sticky="w")
        # show replaces each character on screen; the variable keeps the real text (RNF-06).
        self._password_entry = ttk.Entry(
            form,
            textvariable=self._password,
            width=self.ENTRY_WIDTH,
            show=self.PASSWORD_MASK,
        )
        self._password_entry.grid(row=5, column=0, sticky="ew", pady=(2, 12))

        # Ingresar is created first so Tab reaches it before Salir. Both
        # are packed from the right, which keeps Ingresar on the right side.
        buttons = ttk.Frame(form)
        buttons.grid(row=6, column=0, sticky="e", pady=(8, 0))
        login_button = ttk.Button(
            buttons, text=self.LOGIN_TEXT, command=self._submit, default="active"
        )
        login_button.pack(side="right")
        exit_button = ttk.Button(buttons, text=self.EXIT_TEXT, command=self._on_exit)
        exit_button.pack(side="right", padx=(0, GAP))

        # Enter logs in from either field or from Ingresar. On Salir it asks
        # to exit, because that is the button the user has selected.
        # bind_enter binds each widget and not the whole window: a window
        # binding would outlive this view and keep trying to log in from
        # the main window.
        for widget in (self._username_entry, self._password_entry, login_button):
            bind_enter(widget, self._submit)
        bind_enter(exit_button, self._on_exit)

    def _submit(self) -> None:
        """Send the credentials to ClinicSystem and react to its answer.

        Wrong credentials (CP-02): the message never says which field
        failed (RNF-09), the password is erased and the cursor goes back to
        it, while the username stays so it does not have to be typed again.
        An empty field (CP-03): ClinicSystem names the field, and the cursor
        goes to the first empty one.
        A correct login (CP-01) hands over to App.show_main, which replaces
        this view with the main window.
        """
        try:
            self._system.login(self._username.get(), self._password.get())
        except InvalidCredentialsError as error:
            show_error(error.message, parent=self)
            self._password.set("")
            self._password_entry.focus_set()
            return
        except ClinicError as error:
            show_error(error.message, parent=self)
            self._focus_first_empty()
            return
        self._on_success()

    def _focus_first_empty(self) -> None:
        """Put the cursor in the first field left empty, checking Usuario first."""
        if not self._username.get().strip():
            self._username_entry.focus_set()
        else:
            self._password_entry.focus_set()
