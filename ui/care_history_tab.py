"""History of patients served (step D6).

One row per finished care, the most recent first (RF-35, RF-36). The
records are created by ClinicSystem.finish_care and removed only when that
action is undone, so the tab only reads them.
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from models.permissions import Permission
from services.clinic_system import ClinicSystem
from ui.base_tab import BaseTab
from ui.widgets import GAP, HEADING_FONT, SMALL_GAP, DataTable, count_text


class CareHistoryTab(BaseTab):
    """Shows the care records, newest first."""

    title = "Atendidos"
    required_permission = Permission.VIEW_CARE_HISTORY

    HEADING = "Historial de pacientes atendidos"
    COUNT_TEXT = "{count}. La más reciente aparece arriba."
    EMPTY_TEXT = (
        "Todavía no hay atenciones finalizadas. Aparecen aquí al usar "
        "Finalizar atención en Turnos y colas."
    )

    # The columns of RF-35. The ticket number goes first because DataTable
    # uses it as the row id, and a ticket is served at most once.
    COLUMNS = (
        ("number", "Turno", 60),
        ("code", "Código", 80),
        ("patient", "Paciente", 170),
        ("care_type", "Tipo de atención", 170),
        ("registered_at", "Fecha de registro", 145),
        ("served_at", "Fecha de atención", 145),
        ("served_by", "Atendido por", 100),
    )

    def __init__(
        self,
        parent: tk.Misc,
        system: ClinicSystem,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent, system, on_change)
        self._summary = tk.StringVar()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text=self.HEADING, font=HEADING_FONT).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(self, textvariable=self._summary).grid(
            row=1, column=0, sticky="w", pady=(SMALL_GAP, GAP)
        )
        self._table = DataTable(self, self.COLUMNS, height=16)
        self._table.grid(row=2, column=0, sticky="nsew")

    def refresh(self) -> None:
        """Reload the records. ClinicSystem already returns them newest first."""
        records = self._system.list_care_records()
        self._table.load(
            (
                record.ticket_number,
                record.patient_code,
                record.patient_name,
                record.care_type,
                record.registered_at,
                record.served_at,
                record.served_by,
            )
            for record in records
        )
        if records:
            count = count_text(
                len(records), "atención finalizada", "atenciones finalizadas"
            )
            self._summary.set(self.COUNT_TEXT.format(count=count))
        else:
            self._summary.set(self.EMPTY_TEXT)
