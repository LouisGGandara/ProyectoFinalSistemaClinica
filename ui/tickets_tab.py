"""Tickets and queues tab (step D5).

The tab shows both queues in arrival order, the ticket that goes next and
the one in care, and has the buttons to call, finish and cancel. Which
queue goes first, the one-office rule and the permissions are decided by
ClinicSystem. The tab shows what the system returns and sends it the
ticket the user picked.
"""

import tkinter as tk
from collections.abc import Callable, Iterable
from tkinter import ttk

from models.permissions import Permission
from services.clinic_system import ClinicSystem
from ui.base_tab import BaseTab
from ui.widgets import (
    BIG_NUMBER_FONT,
    FRAME_PADDING,
    GAP,
    HINT_COLOR,
    STRONG_FONT,
    DataTable,
    bind_enter,
    confirm,
    show_error,
    show_info,
)
from utils.exceptions import ClinicError


class TicketSummary(ttk.LabelFrame):
    """Box that shows one ticket: number, patient, care type and reason.

    The tab has two of them, Siguiente and En atención. When there is no
    ticket to show, the box shows a short message in its place.
    """

    WIDTH = 260

    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent, text=title, padding=FRAME_PADDING)
        self._number = tk.StringVar()
        self._details = tk.StringVar()
        ttk.Label(
            self, textvariable=self._number, font=BIG_NUMBER_FONT
        ).pack(anchor="w")
        ttk.Label(
            self, textvariable=self._details, wraplength=self.WIDTH, justify="left"
        ).pack(anchor="w", pady=(2, 0))

    def show_ticket(self, ticket) -> None:
        """Fill the box with the data of a ticket."""
        self._number.set(ticket.number)
        self._details.set(
            f"{ticket.patient.full_name} ({ticket.patient.code})\n"
            f"{ticket.care_type.description()}\n"
            f"Motivo: {ticket.reason}"
        )

    def show_message(self, message: str) -> None:
        """Leave the number empty and show message instead of the details."""
        self._number.set("—")
        self._details.set(message)


class TicketsTab(BaseTab):
    """Shows both queues and calls, finishes and cancels tickets."""

    title = "Turnos y colas"
    required_permission = Permission.VIEW_QUEUES

    NEXT_TITLE = "Siguiente"
    IN_PROGRESS_TITLE = "En atención"
    PRIORITY_TITLE = "Cola prioritaria ({count} en espera)"
    NORMAL_TITLE = "Cola normal ({count} en espera)"
    STATUS_TITLE = "Consultar estado de un turno"
    NUMBER_LABEL = "Número de turno"
    CALL_TEXT = "Atender siguiente"
    FINISH_TEXT = "Finalizar atención"
    CANCEL_TEXT = "Cancelar turno"
    QUERY_TEXT = "Consultar"

    EMPTY_QUEUES_TEXT = "No hay pacientes en espera."
    NOBODY_IN_CARE_TEXT = "No hay ningún paciente en consulta."
    CANCEL_HINT = (
        "Cancelar turno usa la fila seleccionada en una cola. Si no hay "
        "ninguna, usa el número escrito en Consultar estado."
    )
    SELECT_TICKET_MESSAGE = (
        "Selecciona un turno en una de las colas o escribe su número en "
        "Consultar estado."
    )
    CANCEL_QUESTION = "¿Cancelar el turno {number}? Esta acción se puede deshacer."
    CALLED_MESSAGE = "Pasa a consulta: {number}, {name}."
    FINISHED_MESSAGE = (
        "Se finalizó la atención de {number}. Quedó en el historial de atendidos."
    )
    CANCELLED_MESSAGE = "Se canceló el turno {number}."
    STATUS_RESULT = "El turno {number} está {status}."

    # The same columns for both queues. The first one is the ticket number,
    # which is what DataTable.selected_id() returns.
    COLUMNS = (
        ("number", "Turno", 50),
        ("patient", "Paciente", 120),
        ("care_type", "Tipo de atención", 155),
        ("created_at", "Hora de llegada", 145),
    )

    def __init__(
        self,
        parent: tk.Misc,
        system: ClinicSystem,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent, system, on_change)
        self._number = tk.StringVar()
        self._status_result = tk.StringVar()
        # Number of the last ticket consulted, so refresh() can update its
        # status after a call, a finish or a cancellation.
        self._queried_number: str | None = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_top()
        self._build_queues()
        self._build_status_query()

    def first_field(self) -> tk.Misc:
        """Número de turno, the only field of the tab.

        The cursor does not go to Atender siguiente on purpose: an Enter
        pressed by mistake would call a patient.
        """
        return self._number_entry

    # --------------------------------------------------------------- layout

    def _build_top(self) -> None:
        """Top row of the sketch: Siguiente, En atención and the three buttons."""
        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew")

        self._next_box = TicketSummary(top, self.NEXT_TITLE)
        self._next_box.grid(row=0, column=0, sticky="nsew", padx=(0, GAP))
        self._in_progress_box = TicketSummary(top, self.IN_PROGRESS_TITLE)
        self._in_progress_box.grid(row=0, column=1, sticky="nsew", padx=(0, GAP))
        top.columnconfigure(0, weight=1, uniform="box")
        top.columnconfigure(1, weight=1, uniform="box")

        buttons = ttk.Frame(top)
        buttons.grid(row=0, column=2, sticky="n")
        call_button = ttk.Button(
            buttons, text=self.CALL_TEXT, command=self._call_next, width=20
        )
        call_button.pack(fill="x", pady=(GAP, GAP // 2))
        finish_button = ttk.Button(
            buttons, text=self.FINISH_TEXT, command=self._finish_care, width=20
        )
        finish_button.pack(fill="x", pady=(0, GAP // 2))
        cancel_button = ttk.Button(
            buttons, text=self.CANCEL_TEXT, command=self._cancel_ticket, width=20
        )
        cancel_button.pack(fill="x")

        # Atender siguiente and Finalizar atención stay enabled with empty
        # queues or nobody in care, so a click gets the message of CP-14 or
        # CP-15 instead of a button that does nothing.
        if not self._system.has_permission(Permission.SERVE):
            call_button.state(["disabled"])
            finish_button.state(["disabled"])
        # The receptionist sees Cancelar turno disabled (CP-19). ClinicSystem
        # refuses the cancellation anyway if something else calls it (RNF-08).
        if self._system.has_permission(Permission.CANCEL_TICKET):
            ttk.Label(
                buttons, text=self.CANCEL_HINT, wraplength=170, foreground=HINT_COLOR
            ).pack(anchor="w", pady=(GAP, 0))
        else:
            cancel_button.state(["disabled"])

    def _build_queues(self) -> None:
        """Middle of the sketch: the priority queue on the left, the normal one on the right."""
        queues = ttk.Frame(self)
        queues.grid(row=1, column=0, sticky="nsew", pady=GAP)
        queues.columnconfigure(0, weight=1, uniform="queue")
        queues.columnconfigure(1, weight=1, uniform="queue")
        queues.rowconfigure(0, weight=1)

        self._priority_frame, self._priority_table = self._add_queue(queues, 0)
        self._normal_frame, self._normal_table = self._add_queue(queues, 1)

        # Only one ticket may be selected across both tables, so Cancelar
        # turno never has to guess which one the user meant.
        self._priority_table.on_select(
            lambda: self._keep_single_selection(
                self._priority_table, self._normal_table
            )
        )
        self._normal_table.on_select(
            lambda: self._keep_single_selection(
                self._normal_table, self._priority_table
            )
        )

    def _add_queue(
        self, parent: ttk.Frame, column: int
    ) -> tuple[ttk.LabelFrame, DataTable]:
        """Create the frame and the table of one queue. refresh() sets the title."""
        frame = ttk.LabelFrame(parent, padding=FRAME_PADDING)
        padx = (0, GAP) if column == 0 else 0
        frame.grid(row=0, column=column, sticky="nsew", padx=padx)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        table = DataTable(frame, self.COLUMNS, height=10)
        table.grid(row=0, column=0, sticky="nsew")
        return frame, table

    def _build_status_query(self) -> None:
        """Bottom of the sketch: type a ticket number and see its status (RF-18)."""
        frame = ttk.LabelFrame(self, text=self.STATUS_TITLE, padding=FRAME_PADDING)
        frame.grid(row=2, column=0, sticky="ew")

        ttk.Label(frame, text=self.NUMBER_LABEL).pack(side="left", padx=(0, GAP))
        self._number_entry = ttk.Entry(frame, textvariable=self._number, width=12)
        self._number_entry.pack(side="left", padx=(0, GAP))
        query_button = ttk.Button(
            frame, text=self.QUERY_TEXT, command=self._query_status
        )
        query_button.pack(side="left", padx=(0, GAP))
        ttk.Label(
            frame, textvariable=self._status_result, font=STRONG_FONT
        ).pack(side="left")

        bind_enter(self._number_entry, self._query_status)
        bind_enter(query_button, self._query_status)

    # -------------------------------------------------------------- refresh

    def refresh(self) -> None:
        """Reload both queues, their counters and the two boxes.

        The counters are the length of each list, so they always match the
        rows on screen. The Siguiente box says the queues are empty when
        queues_empty() is true (RF-26).
        """
        priority = self._system.pending_priority()
        normal = self._system.pending_normal()
        self._priority_table.load(self._rows(priority))
        self._normal_table.load(self._rows(normal))
        self._priority_frame.configure(
            text=self.PRIORITY_TITLE.format(count=len(priority))
        )
        self._normal_frame.configure(text=self.NORMAL_TITLE.format(count=len(normal)))

        if self._system.queues_empty():
            self._next_box.show_message(self.EMPTY_QUEUES_TEXT)
        else:
            self._next_box.show_ticket(self._system.peek_next())

        in_progress = self._system.in_progress()
        if in_progress is None:
            self._in_progress_box.show_message(self.NOBODY_IN_CARE_TEXT)
        else:
            self._in_progress_box.show_ticket(in_progress)

        self._refresh_status_result()

    @staticmethod
    def _rows(tickets: Iterable) -> list[tuple]:
        """One row per ticket, with the values in the order of COLUMNS."""
        return [
            (
                ticket.number,
                ticket.patient.full_name,
                ticket.care_type.description(),
                ticket.created_at,
            )
            for ticket in tickets
        ]

    def _refresh_status_result(self) -> None:
        """Ask again for the status of the last ticket consulted.

        Without this, "El turno N-004 está Pendiente" would stay on screen
        after N-004 was called. No error message here: the user did not
        click anything. If the ticket no longer exists, which can happen
        after undoing its creation, the result is just cleared.
        """
        if self._queried_number is None:
            return
        try:
            status = self._system.get_status(self._queried_number)
        except ClinicError:
            self._queried_number = None
            self._status_result.set("")
            return
        self._status_result.set(
            self.STATUS_RESULT.format(number=self._queried_number, status=status)
        )

    # -------------------------------------------------------------- actions

    def _call_next(self) -> None:
        """Atender siguiente (RF-23). ClinicSystem applies RN-01, RN-02 and RN-08."""
        self._run(self._system.call_next, on_success=self._after_call)

    def _after_call(self, ticket) -> None:
        show_info(
            self.CALLED_MESSAGE.format(
                number=ticket.number, name=ticket.patient.full_name
            ),
            parent=self,
        )

    def _finish_care(self) -> None:
        """Finalizar atención (RF-24). The care record is created in the logic."""
        self._run(
            self._system.finish_care,
            on_success=lambda record: show_info(
                self.FINISHED_MESSAGE.format(number=record.ticket_number),
                parent=self,
            ),
        )

    def _cancel_ticket(self) -> None:
        """Cancelar turno (RF-19), after asking for confirmation (RNF-04).

        Whether the ticket is Pendiente (RN-05) and whether the user may
        cancel (RN-10) is checked by ClinicSystem, and _run shows its message.
        """
        number = self._ticket_to_cancel()
        if number is None:
            show_error(self.SELECT_TICKET_MESSAGE, parent=self)
            return
        if not confirm(self.CANCEL_QUESTION.format(number=number), parent=self):
            return
        self._run(
            self._system.cancel_ticket,
            number,
            on_success=lambda _result: show_info(
                self.CANCELLED_MESSAGE.format(number=number), parent=self
            ),
        )

    def _ticket_to_cancel(self) -> str | None:
        """Selected ticket of either queue, or else the number typed below.

        The tables only list Pendiente tickets. The typed number lets the
        user try to cancel any other ticket too, and get the message of
        RN-05 (CP-18). The upper case is only for the confirmation text;
        ClinicSystem cleans the number on its own.
        """
        selected = self._priority_table.selected_id() or self._normal_table.selected_id()
        if selected is not None:
            return selected
        typed = self._number.get().strip().upper()
        return typed or None

    def _query_status(self) -> None:
        """Show the status of the typed ticket number (RF-18)."""
        number = self._number.get().strip().upper()
        status = self._query(self._system.get_status, number)
        if status is None:
            self._queried_number = None
            self._status_result.set("")
            return
        self._queried_number = number
        self._status_result.set(
            self.STATUS_RESULT.format(number=number, status=status)
        )

    @staticmethod
    def _keep_single_selection(selected: DataTable, other: DataTable) -> None:
        """Unselect the other table when the user picks a row in this one."""
        if selected.selected_id() is not None:
            other.clear_selection()
