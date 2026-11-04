"""Statistics tab (step D7).

One label per value of ClinicSystem.stats() (RF-37, RF-38). The tab keeps
no counts: refresh() asks the system again, and MainView calls refresh()
after every change, so the numbers stay current without a button (RF-39).
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
    NUMBER_FONT,
    SMALL_GAP,
)


class StatsTab(BaseTab):
    """Shows the clinic counts, grouped by what they count."""

    title = "Estadísticas"
    required_permission = Permission.VIEW_STATS

    HEADING = "Estadísticas de la clínica"
    NOTE = (
        "Normales y prioritarios cuentan todos los turnos de ese tipo, en "
        "cualquier estado. Las colas cuentan solo a quienes esperan ahora."
    )

    # Each group is (title, ((key of stats(), label), ...)). The keys are
    # the ones ClinicStats.compute() returns, in the order of RF-37 and RF-38.
    GROUPS = (
        ("Pacientes", (("registered_patients", "Pacientes registrados"),)),
        (
            "Turnos por estado",
            (
                ("pending", "Pendientes"),
                ("in_progress", "En atención"),
                ("served", "Atendidos"),
                ("cancelled", "Cancelados"),
            ),
        ),
        (
            "Turnos por tipo de atención",
            (("normal", "Normales"), ("priority", "Prioritarios")),
        ),
        (
            "Colas",
            (
                ("priority_queue", "En la cola prioritaria"),
                ("normal_queue", "En la cola normal"),
            ),
        ),
    )

    def __init__(
        self,
        parent: tk.Misc,
        system: ClinicSystem,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent, system, on_change)
        # One StringVar per key, so refresh() only sets the numbers.
        self._values: dict[str, tk.StringVar] = {}

        ttk.Label(self, text=self.HEADING, font=HEADING_FONT).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(self, text=self.NOTE, foreground=HINT_COLOR).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(SMALL_GAP, GAP)
        )
        # Two groups per row: Pacientes and Turnos por estado on top,
        # the care types and the queues below.
        for index, (group_title, items) in enumerate(self.GROUPS):
            box = self._build_group(group_title, items)
            box.grid(
                row=2 + index // 2,
                column=index % 2,
                sticky="nsew",
                padx=(0, GAP) if index % 2 == 0 else 0,
                pady=(0, GAP),
            )
        self.columnconfigure(0, weight=1, uniform="group")
        self.columnconfigure(1, weight=1, uniform="group")

    def _build_group(
        self, group_title: str, items: tuple[tuple[str, str], ...]
    ) -> ttk.LabelFrame:
        """A box with one row per value: the label on the left, the number on the right."""
        box = ttk.LabelFrame(self, text=group_title, padding=FRAME_PADDING)
        box.columnconfigure(0, weight=1)
        for row, (key, label) in enumerate(items):
            value = tk.StringVar(value="0")
            self._values[key] = value
            ttk.Label(box, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Label(box, textvariable=value, font=NUMBER_FONT).grid(
                row=row, column=1, sticky="e", pady=2
            )
        return box

    def refresh(self) -> None:
        """Ask stats() again and show each number in its label."""
        counts = self._system.stats()
        for key, value in self._values.items():
            value.set(str(counts.get(key, 0)))
