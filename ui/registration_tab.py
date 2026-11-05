"""Patient registration tab and new ticket dialog (step D4).

RegistrationTab registers patients, which creates their first ticket, edits
the name, age and phone of a registered patient, and opens NewTicketDialog
for a patient who comes back. Every rule (code format, duplicates, age,
phone, priority criterion, one active ticket per patient) is checked by
ClinicSystem. The tab only collects the text, sends it and shows the answer.
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
    HINT_COLOR,
    SMALL_GAP,
    STRONG_FONT,
    add_form_entry,
    add_table_frame,
    bind_enter,
    center_dialog,
    show_info,
)

ENTRY_WIDTH = 34
AGE_WIDTH = 8
PRIORITY_NAME = "Prioritaria"


class CareTypeFields:
    """The care type and priority criterion Comboboxes, used by the tab and the dialog.

    The criterion only makes sense for Prioritaria, so its Combobox stays
    disabled while the type is empty or Normal. Both screens need that same
    behaviour, and keeping it here means it is written once.

    It is a helper and not a widget: it puts its labels and Comboboxes on
    the rows of the parent's grid, so they line up with the other fields of
    the form.
    """

    TYPE_LABEL = "Tipo de atención"
    CRITERION_LABEL = "Criterio de prioridad"

    def __init__(
        self,
        parent: tk.Misc,
        row: int,
        care_types: list[str],
        criteria: list[str],
    ) -> None:
        self._care_type = tk.StringVar()
        self._criterion = tk.StringVar()
        self._enabled = True

        ttk.Label(parent, text=self.TYPE_LABEL).grid(
            row=row, column=0, sticky="w", pady=SMALL_GAP, padx=(0, GAP)
        )
        # readonly lets the user pick from the list but not type, so the
        # only possible values are the ones ClinicSystem offers.
        self._type_box = ttk.Combobox(
            parent,
            textvariable=self._care_type,
            values=care_types,
            state="readonly",
            width=ENTRY_WIDTH - 3,
        )
        self._type_box.grid(row=row, column=1, sticky="ew", pady=SMALL_GAP)
        self._type_box.bind("<<ComboboxSelected>>", self._on_type_selected)

        ttk.Label(parent, text=self.CRITERION_LABEL).grid(
            row=row + 1, column=0, sticky="w", pady=SMALL_GAP, padx=(0, GAP)
        )
        self._criterion_box = ttk.Combobox(
            parent,
            textvariable=self._criterion,
            values=criteria,
            state="disabled",
            width=ENTRY_WIDTH - 3,
        )
        self._criterion_box.grid(row=row + 1, column=1, sticky="ew", pady=SMALL_GAP)

    @property
    def widgets(self) -> tuple[ttk.Combobox, ttk.Combobox]:
        """The two Comboboxes, for the caller that binds Enter on its fields."""
        return self._type_box, self._criterion_box

    def values(self) -> tuple[str, str | None]:
        """Chosen type and criterion. The criterion is None unless the type is Prioritaria.

        An empty type goes to ClinicSystem as it is, and its answer is
        "Selecciona el tipo de atención." (CP-10).
        """
        care_type = self._care_type.get()
        if care_type != PRIORITY_NAME:
            return care_type, None
        return care_type, self._criterion.get()

    def clear(self) -> None:
        """Leave both Comboboxes empty, with the criterion disabled again."""
        self._care_type.set("")
        self._criterion.set("")
        self._update_criterion_state()

    def set_enabled(self, enabled: bool) -> None:
        """Turn both Comboboxes on or off. The tab turns them off while editing a patient."""
        self._enabled = enabled
        self._type_box.configure(state="readonly" if enabled else "disabled")
        self._update_criterion_state()

    def _on_type_selected(self, _event: tk.Event) -> None:
        self._update_criterion_state()

    def _update_criterion_state(self) -> None:
        """Enable the criterion only for Prioritaria, and empty it otherwise.

        Emptying it means a criterion picked before switching to Normal does
        not stay on screen as if it still applied.
        """
        if self._enabled and self._care_type.get() == PRIORITY_NAME:
            self._criterion_box.configure(state="readonly")
        else:
            self._criterion.set("")
            self._criterion_box.configure(state="disabled")


class RegistrationTab(BaseTab):
    """Registers and updates patients and lists them.

    The form works in two modes. In register mode the main button says
    Registrar and sends every field. After Modificar seleccionado it says
    Guardar cambios, the code is locked and only the name, age and phone
    are sent, because the reason and the care type belong to the ticket
    and not to the patient (section 3.3).
    """

    title = "Registro"
    required_permission = Permission.REGISTER_PATIENT

    FORM_TITLE = "Datos del paciente"
    TABLE_TITLE = "Pacientes registrados"
    CODE_LABEL = "Código"
    NAME_LABEL = "Nombre completo"
    AGE_LABEL = "Edad"
    PHONE_LABEL = "Teléfono"
    REASON_LABEL = "Motivo de la consulta"
    REGISTER_TEXT = "Registrar"
    SAVE_TEXT = "Guardar cambios"
    CLEAR_TEXT = "Limpiar"
    CANCEL_EDIT_TEXT = "Cancelar"
    MODIFY_TEXT = "Modificar seleccionado"
    NEW_TICKET_TEXT = "Nuevo turno"
    EDIT_NOTE = "Modificando a {code}. El motivo y el tipo de atención no se editan aquí."

    SELECT_PATIENT_MESSAGE = "Selecciona un paciente en la tabla."
    REGISTERED_MESSAGE = (
        "Paciente {code} registrado.\nTurno generado: {number}, {care_type}."
    )
    UPDATED_MESSAGE = "Se guardaron los cambios de {code}."
    TICKET_CREATED_MESSAGE = (
        "Turno generado para {code}: {number}, {care_type}."
    )

    COLUMNS = (
        ("code", "Código", 80),
        ("full_name", "Nombre completo", 150),
        ("age", "Edad", 45),
        ("phone", "Teléfono", 80),
        ("registered_at", "Fecha de registro", 155),
    )

    def __init__(
        self,
        parent: tk.Misc,
        system: ClinicSystem,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent, system, on_change)
        self._code = tk.StringVar()
        self._full_name = tk.StringVar()
        self._age = tk.StringVar()
        self._phone = tk.StringVar()
        self._reason = tk.StringVar()
        self._edit_note = tk.StringVar()

        # Code that next_code() proposed last time, used by refresh() to
        # tell a proposal apart from a code the user typed.
        self._proposed_code = ""
        # Code of the patient being edited, or None in register mode.
        self._editing_code: str | None = None
        # Patients of the last refresh, so Modificar seleccionado can fill
        # the form without asking the system again.
        self._patients: dict = {}

        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self._build_form()
        self._build_table()

    def first_field(self) -> tk.Misc:
        """Nombre completo. Código already comes filled with the proposed code."""
        return self._name_entry

    # --------------------------------------------------------------- layout

    def _build_form(self) -> None:
        """Left side of the sketch: the fields, then Registrar and Limpiar."""
        form = ttk.LabelFrame(self, text=self.FORM_TITLE, padding=FRAME_PADDING)
        form.grid(row=0, column=0, sticky="nsw", padx=(0, GAP))
        form.columnconfigure(1, weight=1)

        self._code_entry = add_form_entry(
            form, 0, self.CODE_LABEL, self._code, ENTRY_WIDTH
        )
        self._name_entry = add_form_entry(
            form, 1, self.NAME_LABEL, self._full_name, ENTRY_WIDTH
        )
        self._age_entry = add_form_entry(
            form, 2, self.AGE_LABEL, self._age, width=AGE_WIDTH, fill=False
        )
        self._phone_entry = add_form_entry(
            form, 3, self.PHONE_LABEL, self._phone, ENTRY_WIDTH
        )
        self._reason_entry = add_form_entry(
            form, 4, self.REASON_LABEL, self._reason, ENTRY_WIDTH
        )
        self._care_fields = CareTypeFields(
            form,
            row=5,
            care_types=self._system.care_type_names(),
            criteria=self._system.priority_criteria(),
        )

        ttk.Label(
            form, textvariable=self._edit_note, wraplength=300, foreground=HINT_COLOR
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(GAP, 0))

        # Registrar is created before Limpiar so Tab reaches it first after
        # the last field. Packing from the right keeps it on the right side.
        buttons = ttk.Frame(form)
        buttons.grid(row=8, column=0, columnspan=2, sticky="e", pady=(GAP, 0))
        self._submit_button = ttk.Button(
            buttons, text=self.REGISTER_TEXT, command=self._submit, default="active"
        )
        self._submit_button.pack(side="right")
        self._clear_button = ttk.Button(
            buttons, text=self.CLEAR_TEXT, command=self._clear_or_cancel
        )
        self._clear_button.pack(side="right", padx=(0, GAP))

        entries = (
            self._code_entry,
            self._name_entry,
            self._age_entry,
            self._phone_entry,
            self._reason_entry,
            *self._care_fields.widgets,
            self._submit_button,
        )
        for widget in entries:
            bind_enter(widget, self._submit)

    def _build_table(self) -> None:
        """Right side of the sketch: the patient table and its two buttons."""
        frame, self._table = add_table_frame(
            self, self.COLUMNS, height=16, title=self.TABLE_TITLE
        )
        frame.grid(row=0, column=1, sticky="nsew")

        buttons = ttk.Frame(frame)
        buttons.grid(row=1, column=0, sticky="e", pady=(GAP, 0))
        modify_button = ttk.Button(
            buttons, text=self.MODIFY_TEXT, command=self._start_edit
        )
        modify_button.pack(side="left", padx=(0, GAP))
        new_ticket_button = ttk.Button(
            buttons, text=self.NEW_TICKET_TEXT, command=self._open_new_ticket
        )
        new_ticket_button.pack(side="left")

        # Both roles have these permissions today (section 3.1). The check
        # keeps the buttons right if a role loses one later, and ClinicSystem
        # refuses the operation anyway (RNF-08).
        if not self._system.has_permission(Permission.UPDATE_PATIENT):
            modify_button.state(["disabled"])
        if not self._system.has_permission(Permission.CREATE_TICKET):
            new_ticket_button.state(["disabled"])

    # -------------------------------------------------------------- refresh

    def refresh(self) -> None:
        """Reload the patient table and the proposed code.

        The form keeps what the user typed, so a validation error never
        erases it (CP-07). The code field is the one exception: it gets the
        new proposal when it still shows the old one or is empty. A code
        the user typed by hand stays, and so does the code of a patient
        being edited.
        """
        patients = self._system.list_patients()
        self._patients = {patient.code: patient for patient in patients}
        self._table.load(
            (p.code, p.full_name, p.age, p.phone, p.registered_at) for p in patients
        )

        new_code = self._system.next_code()
        if self._editing_code is None and self._code.get().strip() in (
            "",
            self._proposed_code,
        ):
            self._code.set(new_code)
        self._proposed_code = new_code

    # ------------------------------------------------------- register/save

    def _submit(self) -> None:
        """Registrar in register mode, Guardar cambios in edit mode."""
        if self._editing_code is None:
            self._register_patient()
        else:
            self._save_changes()

    def _register_patient(self) -> None:
        """Send the whole form to register_patient (RF-09, RF-16).

        _run shows any error and leaves the form as it is, so CP-06 to CP-11
        need no code here. On success refresh() runs first and proposes the
        next code, then _after_register shows the ticket number.
        """
        care_type, criterion = self._care_fields.values()
        self._run(
            self._system.register_patient,
            self._code.get(),
            self._full_name.get(),
            self._age.get(),
            self._phone.get(),
            self._reason.get(),
            care_type,
            criterion,
            on_success=self._after_register,
        )

    def _after_register(self, ticket) -> None:
        self._clear_form()
        show_info(
            self.REGISTERED_MESSAGE.format(
                code=ticket.patient.code,
                number=ticket.number,
                care_type=ticket.care_type.description(),
            ),
            parent=self,
        )

    def _save_changes(self) -> None:
        """Send the new name, age and phone of the patient being edited (RF-14)."""
        code = self._editing_code
        self._run(
            self._system.update_patient,
            code,
            self._full_name.get(),
            self._age.get(),
            self._phone.get(),
            on_success=lambda _result: self._after_save(code),
        )

    def _after_save(self, code: str) -> None:
        self._leave_edit_mode()
        show_info(self.UPDATED_MESSAGE.format(code=code), parent=self)

    # ----------------------------------------------------------- edit mode

    def _start_edit(self) -> None:
        """Copy the selected patient into the form and switch to Guardar cambios."""
        code = self._selected_or_warn(self._table, self.SELECT_PATIENT_MESSAGE)
        if code is None:
            return
        patient = self._patients[code]
        self._editing_code = code
        self._code.set(code)
        self._full_name.set(patient.full_name)
        self._age.set(str(patient.age))
        self._phone.set(patient.phone)
        self._reason.set("")
        self._care_fields.clear()

        # The code stays visible but cannot change, since it identifies the
        # patient. Motivo and the care type belong to each ticket (section
        # 3.3), so they are turned off while editing.
        self._code_entry.state(["readonly"])
        self._reason_entry.state(["disabled"])
        self._care_fields.set_enabled(False)
        self._submit_button.configure(text=self.SAVE_TEXT)
        self._clear_button.configure(text=self.CANCEL_EDIT_TEXT)
        self._edit_note.set(self.EDIT_NOTE.format(code=code))
        self._name_entry.focus_set()

    def _leave_edit_mode(self) -> None:
        """Back to register mode with an empty form and the proposed code."""
        self._editing_code = None
        self._code_entry.state(["!readonly"])
        self._reason_entry.state(["!disabled"])
        self._care_fields.set_enabled(True)
        self._submit_button.configure(text=self.REGISTER_TEXT)
        self._clear_button.configure(text=self.CLEAR_TEXT)
        self._edit_note.set("")
        self._clear_form()

    def _clear_or_cancel(self) -> None:
        """Limpiar empties the form; in edit mode the same button cancels the edit."""
        if self._editing_code is None:
            self._clear_form()
        else:
            self._leave_edit_mode()

    def _clear_form(self) -> None:
        """Empty every field and put the proposed code back in Código."""
        self._code.set(self._proposed_code)
        for variable in (self._full_name, self._age, self._phone, self._reason):
            variable.set("")
        self._care_fields.clear()
        self._name_entry.focus_set()

    # ---------------------------------------------------------- new ticket

    def _open_new_ticket(self) -> None:
        """Open NewTicketDialog for the selected patient (RF-17)."""
        code = self._selected_or_warn(self._table, self.SELECT_PATIENT_MESSAGE)
        if code is None:
            return
        patient = self._patients[code]
        NewTicketDialog(
            self,
            patient_label=f"{patient.code}, {patient.full_name}",
            care_types=self._system.care_type_names(),
            criteria=self._system.priority_criteria(),
            on_submit=lambda dialog, reason, care_type, criterion: self._create_ticket(
                dialog, code, reason, care_type, criterion
            ),
        )

    def _create_ticket(
        self,
        dialog: "NewTicketDialog",
        code: str,
        reason: str,
        care_type: str,
        criterion: str | None,
    ) -> None:
        """Ask ClinicSystem for the ticket. The dialog closes only if it worked.

        Errors, such as the active ticket of RN-07 (CP-12), appear over the
        dialog and leave it open, so the user can fix the reason or the type
        or close it.
        """
        self._run(
            self._system.create_ticket,
            code,
            reason,
            care_type,
            criterion,
            on_success=lambda ticket: self._after_ticket_created(dialog, ticket),
            parent=dialog,
        )

    def _after_ticket_created(self, dialog: "NewTicketDialog", ticket) -> None:
        dialog.close()
        show_info(
            self.TICKET_CREATED_MESSAGE.format(
                code=ticket.patient.code,
                number=ticket.number,
                care_type=ticket.care_type.description(),
            ),
            parent=self,
        )


class NewTicketDialog(tk.Toplevel):
    """Dialog that creates a new ticket for a registered patient.

    It asks for the reason, the care type and the criterion, because those
    change on every visit (section 3.3). It does not call ClinicSystem
    itself: on_submit receives the dialog and the three values, and the tab
    decides what to do with them. The tab then closes the dialog with
    close() when the ticket was created.

    The dialog is modal. While it is open, the main window does not respond.
    """

    WINDOW_TITLE = "Nuevo turno"
    PATIENT_LABEL = "Paciente"
    REASON_LABEL = "Motivo de la consulta"
    SUBMIT_TEXT = "Generar turno"
    CLOSE_TEXT = "Cerrar"

    def __init__(
        self,
        parent: tk.Misc,
        patient_label: str,
        care_types: list[str],
        criteria: list[str],
        on_submit: Callable[["NewTicketDialog", str, str, str | None], None],
    ) -> None:
        super().__init__(parent)
        self._on_submit = on_submit
        self._reason = tk.StringVar()

        self.title(self.WINDOW_TITLE)
        self.resizable(False, False)
        # transient keeps the dialog above the main window and out of the
        # taskbar; grab_set sends every click of the app to the dialog.
        self.transient(parent.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.close)

        body = ttk.Frame(self, padding=2 * GAP)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text=self.PATIENT_LABEL).grid(
            row=0, column=0, sticky="w", pady=SMALL_GAP, padx=(0, GAP)
        )
        ttk.Label(body, text=patient_label, font=STRONG_FONT).grid(
            row=0, column=1, sticky="w", pady=SMALL_GAP
        )
        ttk.Label(body, text=self.REASON_LABEL).grid(
            row=1, column=0, sticky="w", pady=SMALL_GAP, padx=(0, GAP)
        )
        reason_entry = ttk.Entry(body, textvariable=self._reason, width=ENTRY_WIDTH)
        reason_entry.grid(row=1, column=1, sticky="ew", pady=SMALL_GAP)
        self._care_fields = CareTypeFields(body, 2, care_types, criteria)

        # Same order as the tab: Generar turno first for Tab, on the right.
        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(GAP, 0))
        submit_button = ttk.Button(
            buttons, text=self.SUBMIT_TEXT, command=self._submit, default="active"
        )
        submit_button.pack(side="right")
        ttk.Button(buttons, text=self.CLOSE_TEXT, command=self.close).pack(
            side="right", padx=(0, GAP)
        )

        for widget in (reason_entry, *self._care_fields.widgets, submit_button):
            bind_enter(widget, self._submit)
        self.bind("<Escape>", lambda _event: self.close())

        center_dialog(self, parent.winfo_toplevel())
        # The grab only works once the window is visible.
        self.wait_visibility()
        self.grab_set()
        reason_entry.focus_set()

    def _submit(self) -> None:
        care_type, criterion = self._care_fields.values()
        self._on_submit(self, self._reason.get(), care_type, criterion)

    def close(self) -> None:
        """Release the grab and destroy the dialog."""
        self.grab_release()
        self.destroy()
