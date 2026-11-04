"""Main window: Archivo and Ver menus, the tabs and a status bar (step D3).

MainView builds only the tabs the user may see. The Historial de acciones
and Usuarios tabs are never created for a receptionist, so there is nothing
to hide afterwards (RF-03, CP-04). ClinicSystem still checks the permission
of every operation, in case some other code calls it (RNF-08).
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from services.clinic_system import ClinicSystem
from ui.actions_tab import ActionsTab
from ui.base_tab import BaseTab
from ui.care_history_tab import CareHistoryTab
from ui.registration_tab import RegistrationTab
from ui.search_tab import SearchTab
from ui.stats_tab import StatsTab
from ui.tickets_tab import TicketsTab
from ui.users_tab import UsersTab
from ui.widgets import GAP, SMALL_GAP, confirm


class MainView(ttk.Frame):
    """Shows the tabs that the current user is allowed to see."""

    # Order of the tabs in the notebook and in the Ver menu, as in the sketch.
    TAB_CLASSES: tuple[type[BaseTab], ...] = (
        RegistrationTab,
        TicketsTab,
        SearchTab,
        CareHistoryTab,
        ActionsTab,
        StatsTab,
        UsersTab,
    )

    FILE_MENU = "Archivo"
    VIEW_MENU = "Ver"
    LOGOUT_TEXT = "Cerrar sesión"
    EXIT_TEXT = "Salir"
    LOGOUT_QUESTION = (
        "¿Cerrar la sesión de {name}? Volverás a la pantalla de inicio de sesión."
    )
    STATUS_TEXT = "Usuario: {name} ({username})    Rol: {role}"

    def __init__(
        self,
        parent: tk.Misc,
        system: ClinicSystem,
        on_logout: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        """Build the status bar, the tabs and the menus, then load every tab.

        on_logout is App.show_login, called after system.logout().
        on_exit is App.request_exit, which asks before closing.
        """
        super().__init__(parent)
        self._system = system
        self._on_logout = on_logout
        self._on_exit = on_exit
        self._tabs: list[BaseTab] = []

        # The status bar is packed first so it keeps its row at the bottom
        # when the window gets smaller; the notebook takes what is left.
        self._build_status_bar()
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="both", expand=True, padx=GAP, pady=(GAP, 0))
        self._build_tabs()
        self._build_menu()
        self.notify_change()

        # Each time a tab is shown, its first field gets the cursor. The
        # first tab is selected while it is being added, before this
        # binding exists, so after_idle does that one by hand once the
        # window is drawn.
        self._notebook.bind("<<NotebookTabChanged>>", self._focus_current_tab)
        self.after_idle(self._focus_current_tab)

    def _build_tabs(self) -> None:
        """Create one tab for each class whose permission the user has.

        has_permission(None) is True, which covers a tab open to every role.
        """
        for tab_class in self.TAB_CLASSES:
            if not self._system.has_permission(tab_class.required_permission):
                continue
            tab = tab_class(self._notebook, self._system, self.notify_change)
            self._notebook.add(tab, text=tab_class.title)
            self._tabs.append(tab)

    def _build_menu(self) -> None:
        """Put the Archivo and Ver menus on the window.

        The menu bar belongs to the window, not to this frame, because Tk
        attaches menus to a toplevel. App removes it before showing the
        login, so it does not stay behind after logging out.
        """
        window = self.winfo_toplevel()
        menu_bar = tk.Menu(window, tearoff=False)

        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label=self.LOGOUT_TEXT, command=self._logout)
        file_menu.add_separator()
        file_menu.add_command(label=self.EXIT_TEXT, command=self._on_exit)
        menu_bar.add_cascade(label=self.FILE_MENU, menu=file_menu)

        # Ver lists only the tabs that were created, so the receptionist
        # gets no option for Historial de acciones or Usuarios.
        view_menu = tk.Menu(menu_bar, tearoff=False)
        for tab in self._tabs:
            view_menu.add_command(
                label=tab.title,
                command=lambda selected=tab: self._notebook.select(selected),
            )
        menu_bar.add_cascade(label=self.VIEW_MENU, menu=view_menu)

        window.configure(menu=menu_bar)

    def _build_status_bar(self) -> None:
        """Show the name, username and role of whoever logged in."""
        user = self._system.current_user
        text = self.STATUS_TEXT.format(
            name=user.full_name, username=user.username, role=user.role
        )
        status_bar = ttk.Frame(self, padding=(GAP, SMALL_GAP))
        status_bar.pack(side="bottom", fill="x")
        ttk.Separator(self).pack(side="bottom", fill="x")
        ttk.Label(status_bar, text=text).pack(side="left")

    def _focus_current_tab(self, _event: tk.Event | None = None) -> None:
        """Ask the visible tab to put the cursor in its first field.

        Each tab answers first_field() in its own way: Registro returns
        Nombre completo, Búsqueda returns the text field, and Estadísticas,
        which has no fields, returns None and takes the focus itself.
        """
        selected = self._notebook.select()
        if not selected:
            return
        tab = self._notebook.nametowidget(selected)
        if isinstance(tab, BaseTab):
            tab.focus_first()

    def notify_change(self) -> None:
        """Reload every tab. Each tab receives this method as on_change.

        After any operation that changes data, the tab that ran it calls
        this method through BaseTab._run, so a patient registered in
        Registro also shows up in Turnos y colas and in Estadísticas. Every
        tab answers refresh() in its own way (polymorphism), so this method
        does not need to know which tabs exist.
        """
        for tab in self._tabs:
            tab.refresh()

    def _logout(self) -> None:
        """Ask first, close the session and go back to the login (RF-04)."""
        name = self._system.current_user.full_name
        if not confirm(self.LOGOUT_QUESTION.format(name=name), parent=self):
            return
        self._system.logout()
        self._on_logout()
