"""User administration tab (step D8).

Only the administrator sees this tab (section 3.1). The form creates users
(RF-06), the table lists them with their role (RF-08) and Eliminar
seleccionado deletes the selected one after asking (RF-07). The rules of
RN-12, such as not deleting one's own account or the last administrator,
are checked by ClinicSystem; the tab shows its message. Cambiar contraseña
gives the selected user a new password (RF-43); the administrator's own
password is changed from Archivo > Cambiar mi contraseña instead.
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from models.permissions import Permission
from services.clinic_system import ClinicSystem
from ui.base_tab import BaseTab
from ui.password_dialog import PasswordDialog
from ui.widgets import (
    FRAME_PADDING,
    GAP,
    HINT_COLOR,
    SMALL_GAP,
    add_form_entry,
    add_table_frame,
    bind_enter,
    confirm,
    show_info,
)

ENTRY_WIDTH = 30


class UsersTab(BaseTab):
    """Creates and deletes users and shows what each one may do."""

    title = "Usuarios"
    required_permission = Permission.MANAGE_USERS

    FORM_TITLE = "Nuevo usuario"
    TABLE_TITLE = "Usuarios del sistema"
    PERMISSIONS_TITLE = "Permisos del usuario seleccionado"
    NAME_LABEL = "Nombre completo"
    USERNAME_LABEL = "Usuario"
    PASSWORD_LABEL = "Contraseña"
    ROLE_LABEL = "Rol"
    CREATE_TEXT = "Crear usuario"
    CLEAR_TEXT = "Limpiar"
    DELETE_TEXT = "Eliminar seleccionado"
    PASSWORD_TEXT = "Cambiar contraseña"

    FORM_HINT = (
        "Usuario: de 4 a 20 letras, números o guion bajo.\n"
        "Contraseña: al menos 6 caracteres."
    )
    OWN_ACCOUNT_HINT = (
        "Tu cuenta ({username}) no se puede eliminar, y su contraseña se "
        "cambia en Archivo > Cambiar mi contraseña."
    )
    NO_SELECTION_HINT = "Selecciona un usuario en la tabla para ver lo que puede hacer."
    PERMISSIONS_OF = "{username} ({role}) puede:"

    SELECT_USER_MESSAGE = "Selecciona un usuario en la tabla."
    CREATED_MESSAGE = "Se creó el usuario {username} con el rol {role}."
    DELETE_QUESTION = (
        "¿Eliminar al usuario {username} ({full_name})?\n\n"
        "Ya no podrá iniciar sesión, y esta acción no se puede deshacer."
    )
    DELETED_MESSAGE = "Se eliminó el usuario {username}."
    PASSWORD_TITLE = "Cambiar contraseña"
    PASSWORD_CHANGED_MESSAGE = (
        "Se cambió la contraseña de {username}. Desde ahora entra con la nueva."
    )

    PASSWORD_MASK = "•"

    # The username goes first: it is unique, so DataTable uses it as the row id.
    COLUMNS = (
        ("username", "Usuario", 120),
        ("full_name", "Nombre completo", 230),
        ("role", "Rol", 120),
    )

    def __init__(
        self,
        parent: tk.Misc,
        system: ClinicSystem,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent, system, on_change)
        self._full_name = tk.StringVar()
        self._username = tk.StringVar()
        self._password = tk.StringVar()
        self._role = tk.StringVar()
        self._permissions_caption = tk.StringVar(value=self.NO_SELECTION_HINT)
        # Users of the last refresh, by username, so the table selection
        # and the delete confirmation can show the full name and the role.
        self._users: dict = {}

        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self._build_left_side()
        self._build_table()

    def first_field(self) -> tk.Misc:
        return self._name_entry

    # --------------------------------------------------------------- layout

    def _build_left_side(self) -> None:
        """The form on top and the permissions of the selected user below it."""
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, GAP))
        left.rowconfigure(1, weight=1)
        self._build_form(left)
        self._build_permissions(left)

    def _build_form(self, parent: ttk.Frame) -> None:
        """Nombre completo, Usuario, Contraseña, Rol and the two buttons."""
        form = ttk.LabelFrame(parent, text=self.FORM_TITLE, padding=FRAME_PADDING)
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)

        self._name_entry = add_form_entry(
            form, 0, self.NAME_LABEL, self._full_name, ENTRY_WIDTH
        )
        username_entry = add_form_entry(
            form, 1, self.USERNAME_LABEL, self._username, ENTRY_WIDTH
        )
        # show hides the characters on screen, like in the login (RNF-06).
        password_entry = add_form_entry(
            form,
            2,
            self.PASSWORD_LABEL,
            self._password,
            ENTRY_WIDTH,
            show=self.PASSWORD_MASK,
        )

        ttk.Label(form, text=self.ROLE_LABEL).grid(
            row=3, column=0, sticky="w", pady=SMALL_GAP, padx=(0, GAP)
        )
        # readonly: only the roles that ClinicSystem knows can be chosen. It
        # starts empty so the administrator has to pick one on purpose.
        role_box = ttk.Combobox(
            form,
            textvariable=self._role,
            values=self._system.roles(),
            state="readonly",
            width=ENTRY_WIDTH - 3,
        )
        role_box.grid(row=3, column=1, sticky="ew", pady=SMALL_GAP)

        ttk.Label(
            form, text=self.FORM_HINT, wraplength=320, foreground=HINT_COLOR
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(GAP, 0))

        # Crear usuario is created first so Tab reaches it before Limpiar.
        buttons = ttk.Frame(form)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(GAP, 0))
        create_button = ttk.Button(
            buttons, text=self.CREATE_TEXT, command=self._create_user, default="active"
        )
        create_button.pack(side="right")
        ttk.Button(buttons, text=self.CLEAR_TEXT, command=self._clear_form).pack(
            side="right", padx=(0, GAP)
        )

        for widget in (
            self._name_entry,
            username_entry,
            password_entry,
            role_box,
            create_button,
        ):
            bind_enter(widget, self._create_user)

    def _build_permissions(self, parent: ttk.Frame) -> None:
        """List of what the selected user may do, refreshed on each selection."""
        box = ttk.LabelFrame(parent, text=self.PERMISSIONS_TITLE, padding=FRAME_PADDING)
        box.grid(row=1, column=0, sticky="nsew", pady=(GAP, 0))
        box.columnconfigure(0, weight=1)
        box.rowconfigure(1, weight=1)

        ttk.Label(
            box, textvariable=self._permissions_caption, wraplength=280, justify="left"
        ).grid(row=0, column=0, sticky="w", pady=(0, SMALL_GAP))
        # A plain Listbox is enough here: one column, read only. takefocus
        # is off so Tab does not stop in a list the user cannot change.
        self._permissions_list = tk.Listbox(
            box,
            height=len(Permission),
            activestyle="none",
            selectmode="browse",
            takefocus=False,
            exportselection=False,
            highlightthickness=0,
        )
        self._permissions_list.grid(row=1, column=0, sticky="nsew")

    def _build_table(self) -> None:
        """Right side: the users, the delete button and the note about one's own account."""
        frame, self._table = add_table_frame(
            self, self.COLUMNS, height=16, title=self.TABLE_TITLE
        )
        frame.grid(row=0, column=1, sticky="nsew")
        self._table.on_select(self._on_user_selected)

        bottom = ttk.Frame(frame)
        bottom.grid(row=1, column=0, sticky="ew", pady=(GAP, 0))
        bottom.columnconfigure(0, weight=1)
        username = self._system.current_user.username
        # The note takes its own row, so the two buttons do not squeeze it.
        ttk.Label(
            bottom,
            text=self.OWN_ACCOUNT_HINT.format(username=username),
            foreground=HINT_COLOR,
            wraplength=560,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, SMALL_GAP))
        self._password_button = ttk.Button(
            bottom, text=self.PASSWORD_TEXT, command=self._change_password
        )
        self._password_button.grid(row=1, column=1, sticky="e", padx=(GAP, 0))
        self._delete_button = ttk.Button(
            bottom, text=self.DELETE_TEXT, command=self._delete_user
        )
        self._delete_button.grid(row=1, column=2, sticky="e", padx=(GAP, 0))

    # -------------------------------------------------------------- refresh

    def refresh(self) -> None:
        """Reload the users. The form keeps what was typed, as in Registro."""
        users = self._system.list_users()
        self._users = {user.username: user for user in users}
        self._table.load((user.username, user.full_name, user.role) for user in users)
        self._on_user_selected()

    def _on_user_selected(self) -> None:
        """Update the permission list and the two buttons for the selected row.

        Eliminar seleccionado and Cambiar contraseña are disabled while
        one's own account is selected, so the administrator is not sent
        into something that will be refused. ClinicSystem still refuses
        both (RN-12, RF-44) if the call arrives some other way.
        """
        self._show_permissions()
        own = self._table.selected_id() == self._system.current_user.username
        for button in (self._delete_button, self._password_button):
            button.state(["disabled"] if own else ["!disabled"])

    def _show_permissions(self) -> None:
        """Fill the list with the permissions of the selected user.

        user.permissions() answers according to the class of the user:
        Administrator returns every permission and Receptionist only the
        reception ones (polymorphism). The list follows the order of the
        Permission enum, so both roles show their permissions in the same
        order and are easy to compare. Each value of the enum is already
        the Spanish text.
        """
        self._permissions_list.delete(0, "end")
        user = self._users.get(self._table.selected_id())
        if user is None:
            self._permissions_caption.set(self.NO_SELECTION_HINT)
            return
        self._permissions_caption.set(
            self.PERMISSIONS_OF.format(username=user.username, role=user.role)
        )
        allowed = user.permissions()
        for permission in Permission:
            if permission in allowed:
                self._permissions_list.insert("end", permission.value)

    # -------------------------------------------------------------- actions

    def _create_user(self) -> None:
        """Crear usuario (RF-06). ClinicSystem validates every field and the role."""
        self._run(
            self._system.create_user,
            self._full_name.get(),
            self._username.get(),
            self._password.get(),
            self._role.get(),
            on_success=self._after_create,
        )

    def _after_create(self, user) -> None:
        self._clear_form()
        show_info(
            self.CREATED_MESSAGE.format(username=user.username, role=user.role),
            parent=self,
        )

    def _delete_user(self) -> None:
        """Eliminar seleccionado (RF-07), after asking for confirmation (RNF-04).

        The confirmation names the user, because a deletion cannot be
        undone (section 3.6). If the selected row is one's own account or
        the last administrator, ClinicSystem refuses and _run shows why.
        """
        username = self._selected_or_warn(self._table, self.SELECT_USER_MESSAGE)
        if username is None:
            return
        user = self._users[username]
        question = self.DELETE_QUESTION.format(
            username=user.username, full_name=user.full_name
        )
        if not confirm(question, parent=self):
            return
        self._run(
            self._system.delete_user,
            username,
            on_success=lambda _result: show_info(
                self.DELETED_MESSAGE.format(username=username), parent=self
            ),
        )

    def _change_password(self) -> None:
        """Cambiar contraseña (RF-43): open the dialog for the selected user.

        The administrator does not type the user's current password, which
        they do not know; ClinicSystem only lets them do this for others.
        """
        username = self._selected_or_warn(self._table, self.SELECT_USER_MESSAGE)
        if username is None:
            return
        user = self._users[username]
        PasswordDialog(
            self,
            title=self.PASSWORD_TITLE,
            user_label=f"{user.username} ({user.full_name})",
            ask_current=False,
            on_submit=lambda dialog, _current, new, confirmation: self._run(
                self._system.change_password,
                username,
                new,
                confirmation,
                on_success=lambda _user: self._after_password_change(dialog, username),
                parent=dialog,
            ),
        )

    def _after_password_change(self, dialog: PasswordDialog, username: str) -> None:
        dialog.close()
        show_info(self.PASSWORD_CHANGED_MESSAGE.format(username=username), parent=self)

    def _clear_form(self) -> None:
        """Empty the four fields and put the cursor back in Nombre completo."""
        for variable in (self._full_name, self._username, self._password, self._role):
            variable.set("")
        self._name_entry.focus_set()
