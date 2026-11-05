"""Root window of the application.

App creates ClinicSystem, shows the warnings found while loading the JSON
files and switches between the login view and the main view. It also
catches any error that escapes a button, so the program never closes on
the user with a traceback (RNF-10, RNF-11).
"""

import time
import tkinter as tk
import traceback
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from types import TracebackType

from services.clinic_system import ClinicSystem
from ui.login_view import LoginView
from ui.main_view import MainView
from ui.widgets import confirm, show_error, show_warning
from utils.exceptions import ClinicError


class App(tk.Tk):
    """Main Tkinter window; switches between the login view and the main view."""

    WINDOW_TITLE = "Sistema de turnos de la clínica"
    WINDOW_SIZE = "1100x700"
    MIN_WIDTH = 900
    MIN_HEIGHT = 600
    THEME = "clam"

    START_ERROR_TITLE = "No se pudo iniciar"
    START_CLOSING_NOTE = (
        "La aplicación se va a cerrar sin modificar los archivos de datos."
    )
    UNEXPECTED_ERROR_MESSAGE = (
        "Ocurrió un error inesperado y la acción no se completó. "
        "El detalle quedó registrado en errors.log."
    )
    EXIT_QUESTION = "¿Seguro que quieres salir del sistema?"

    def __init__(
        self,
        data_folder: str = "data",
        log_path: str | Path = "errors.log",
        system: ClinicSystem | None = None,
    ) -> None:
        """Build the window and load the system.

        If ClinicSystem cannot start, for example because tickets.json has a
        ticket written twice by hand, the window shows the message and closes
        before the login appears. Nobody can work, so nothing gets saved
        over the file that has to be fixed (section 3.11).

        system receives a ClinicSystem that is already loaded, and then
        data_folder is not used. tests/bulk_demo.py passes one with a full
        action history, which lives only in memory (section 3.8) and would
        be lost if App created its own. main.py does not pass it.
        """
        super().__init__()
        self._log_path = Path(log_path)
        self._view: ttk.Frame | None = None
        self._system: ClinicSystem | None = None

        self.title(self.WINDOW_TITLE)
        self.geometry(self.WINDOW_SIZE)
        self.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self._configure_style()
        self.protocol("WM_DELETE_WINDOW", self.request_exit)

        if system is not None:
            self._system = system
        else:
            self._system = self._start_system(data_folder)
        if self._system is None:
            self.destroy()
            return

        self.show_login()
        if self._system.warnings:
            # update_idletasks puts the login on screen now. Without it, the
            # warning ran first and showed up with nothing behind it (E1,
            # CP-27). after_idle then opens it once mainloop starts.
            self.update_idletasks()
            self.after_idle(self._show_load_warnings)

    def _configure_style(self) -> None:
        """Use the clam theme of ttk and give the table rows some height."""
        style = ttk.Style(self)
        style.theme_use(self.THEME)
        style.configure("Treeview", rowheight=24)

    def _start_system(self, data_folder: str) -> ClinicSystem | None:
        """Create ClinicSystem, or show why it failed and return None."""
        try:
            return ClinicSystem(data_folder)
        except ClinicError as error:
            message = error.message
        except Exception:
            self._write_log(traceback.format_exc())
            message = self.UNEXPECTED_ERROR_MESSAGE
        # The empty window is hidden; the user sees only the message.
        self.withdraw()
        show_error(
            f"{message}\n\n{self.START_CLOSING_NOTE}",
            parent=self,
            title=self.START_ERROR_TITLE,
        )
        return None

    def _show_load_warnings(self) -> None:
        """Show the damaged files found while loading (RNF-12)."""
        show_warning("\n\n".join(self._system.warnings), parent=self)

    # ------------------------------------------------------------------ views

    def show_login(self) -> None:
        """Show the login form. MainView calls it after logging out.

        Salir in the login uses request_exit, so it asks the same question
        as the window's X.
        """
        self._show_view(LoginView, on_success=self.show_main, on_exit=self.request_exit)

    def show_main(self) -> None:
        """Show the main window. LoginView calls it after a correct login."""
        self._show_view(MainView, on_logout=self.show_login, on_exit=self.request_exit)

    def _show_view(
        self, view_class: type[ttk.Frame], **callbacks: Callable[[], None]
    ) -> None:
        """Destroy the current view and put a new one in the window.

        The menu bar goes away first. MainView adds its own, and Tk wants
        that menu to be a child of the window, not of MainView, so
        destroying the view does not remove it. Without this step the login
        would keep the menu, and every logout would leave an old menu behind.
        """
        if self._view is not None:
            self._view.destroy()
        menu_name = self.cget("menu")
        if menu_name:
            self.nametowidget(menu_name).destroy()
        self.configure(menu="")
        self._view = view_class(self, self._system, **callbacks)
        self._view.pack(fill="both", expand=True)

    # ------------------------------------------------------- exit and errors

    def request_exit(self) -> None:
        """Ask before closing (RF-05). Used by the X button and by the Salir option.

        Every operation already saved its JSON files, so closing loses
        nothing except the action history, which lives only in memory
        (section 3.8).
        """
        if confirm(self.EXIT_QUESTION, parent=self):
            self.destroy()

    def mainloop(self, n: int = 0) -> None:
        """Run the event loop, unless the system failed to start.

        Overridden because __init__ destroys the window in that case, and
        main.py should not have to check anything before calling mainloop().
        """
        if self._system is None:
            return
        super().mainloop(n)

    def report_callback_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        """Handle any error that escaped a button or an event.

        Tkinter calls this method instead of printing the traceback. A
        ClinicError that a tab forgot to catch still shows its own message.
        Anything else is a bug: the user sees a general message and the
        details go to errors.log (RNF-11). The program keeps running.
        """
        if isinstance(exc_value, ClinicError):
            show_error(exc_value.message, parent=self)
            return
        self._write_log(
            "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        )
        show_error(self.UNEXPECTED_ERROR_MESSAGE, parent=self)

    def _write_log(self, details: str) -> None:
        """Append the date and the traceback to errors.log, in UTF-8."""
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self._log_path, "a", encoding="utf-8") as file:
                file.write(f"[{stamp}]\n{details}\n")
        except OSError:
            # If the log cannot be written, the user still gets the message.
            # Raising here would hide the original error behind this one.
            pass
