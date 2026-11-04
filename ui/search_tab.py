"""Search tab (step D6).

The user picks a criterion, types a text and gets every ticket that
matches, in any status (RF-32 to RF-34). The matching rules live in
services/search.py; the tab only sends the criterion and the text to
ClinicSystem and shows the tickets it returns.
"""

import tkinter as tk
from collections.abc import Callable, Iterable
from tkinter import ttk

from models.permissions import Permission
from services.clinic_system import ClinicSystem
from ui.base_tab import BaseTab
from ui.widgets import (
    FRAME_PADDING,
    GAP,
    HINT_COLOR,
    SMALL_GAP,
    DataTable,
    bind_enter,
    count_text,
    show_info,
)
from utils.exceptions import ClinicError


class SearchTab(BaseTab):
    """Searches tickets by the chosen criterion."""

    title = "Búsqueda"
    required_permission = Permission.SEARCH

    CRITERION_LABEL = "Buscar por"
    TEXT_LABEL = "Texto"
    SEARCH_TEXT = "Buscar"
    CLEAR_TEXT = "Limpiar"
    RESULTS_TITLE = "Resultados"

    FREE_TEXT_HINT = (
        "Escribe el texto y presiona Buscar o Enter. En Nombre basta una "
        "parte, con o sin tildes."
    )
    LIST_HINT = "Elige un valor de la lista o escríbelo."
    NO_RESULTS_MESSAGE = "No se encontraron turnos con {criterion} «{text}»."
    COUNT_TEXT = "{count} con {criterion} «{text}»."
    EMPTY_TEXT = "Todavía no has hecho ninguna búsqueda."
    NO_RESULTS_TEXT = "Sin resultados para {criterion} «{text}»."

    # The first column is the ticket number, which DataTable uses as the
    # row id. The patient code comes next so a returning patient is easy
    # to spot across several visits.
    COLUMNS = (
        ("number", "Turno", 60),
        ("code", "Código", 80),
        ("patient", "Paciente", 170),
        ("care_type", "Tipo de atención", 170),
        ("status", "Estado", 90),
        ("created_at", "Fecha de generación", 145),
    )

    def __init__(
        self,
        parent: tk.Misc,
        system: ClinicSystem,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(parent, system, on_change)
        criteria = self._system.search_criteria()
        self._criterion = tk.StringVar(value=criteria[0] if criteria else "")
        self._text = tk.StringVar()
        self._hint = tk.StringVar()
        self._summary = tk.StringVar(value=self.EMPTY_TEXT)
        # Criterion and text of the last search that worked. refresh()
        # repeats it, so a ticket called or cancelled in another tab shows
        # its new status here too.
        self._last_search: tuple[str, str] | None = None
        # Values offered under the text field for the current criterion.
        self._suggestions: list[str] = []

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_form(criteria)
        self._build_results()
        self._update_suggestions()

    def first_field(self) -> tk.Misc:
        """The text field. The criterion already has a value, so the user can type right away."""
        return self._text_box

    # --------------------------------------------------------------- layout

    def _build_form(self, criteria: list[str]) -> None:
        """Top of the sketch: criterion, text, Buscar and Limpiar."""
        form = ttk.Frame(self)
        form.grid(row=0, column=0, sticky="ew")

        ttk.Label(form, text=self.CRITERION_LABEL).grid(
            row=0, column=0, sticky="w", padx=(0, GAP)
        )
        # readonly: only the criteria ClinicSystem knows can be chosen.
        criterion_box = ttk.Combobox(
            form,
            textvariable=self._criterion,
            values=criteria,
            state="readonly",
            width=20,
        )
        criterion_box.grid(row=0, column=1, sticky="w", padx=(0, 2 * GAP))
        criterion_box.bind("<<ComboboxSelected>>", self._on_criterion_selected)

        ttk.Label(form, text=self.TEXT_LABEL).grid(
            row=0, column=2, sticky="w", padx=(0, GAP)
        )
        # The text field is a Combobox the user can still type in. For
        # Estado and Tipo de atención its list holds the valid words; for
        # the other criteria the list is empty and it works as an Entry.
        self._text_box = ttk.Combobox(form, textvariable=self._text, width=28)
        self._text_box.grid(row=0, column=3, sticky="ew", padx=(0, GAP))
        form.columnconfigure(3, weight=1)

        search_button = ttk.Button(
            form, text=self.SEARCH_TEXT, command=self._search, width=12
        )
        search_button.grid(row=0, column=4, padx=(0, GAP))
        ttk.Button(form, text=self.CLEAR_TEXT, command=self._clear, width=10).grid(
            row=0, column=5
        )

        ttk.Label(form, textvariable=self._hint, foreground=HINT_COLOR).grid(
            row=1, column=3, columnspan=3, sticky="w", pady=(SMALL_GAP, 0)
        )

        for widget in (criterion_box, self._text_box, search_button):
            bind_enter(widget, self._search)

    def _build_results(self) -> None:
        """Results table with a line that says what was searched and how many came back."""
        frame = ttk.LabelFrame(self, text=self.RESULTS_TITLE, padding=FRAME_PADDING)
        frame.grid(row=1, column=0, sticky="nsew", pady=(GAP, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        ttk.Label(frame, textvariable=self._summary).grid(
            row=0, column=0, sticky="w", pady=(0, SMALL_GAP)
        )
        self._table = DataTable(frame, self.COLUMNS, height=14)
        self._table.grid(row=1, column=0, sticky="nsew")

    # -------------------------------------------------------------- refresh

    def refresh(self) -> None:
        """Repeat the last search, if there was one.

        It runs after every change in any tab. The user did not click
        anything, so an error here clears the results quietly instead of
        opening a message.
        """
        if self._last_search is None:
            return
        criterion, text = self._last_search
        try:
            tickets = self._system.search(criterion, text)
        except ClinicError:
            self._clear()
            return
        self._show_results(criterion, text, tickets)

    @staticmethod
    def _rows(tickets: Iterable) -> list[tuple]:
        """One row per ticket, with the values in the order of COLUMNS."""
        return [
            (
                ticket.number,
                ticket.patient.code,
                ticket.patient.full_name,
                ticket.care_type.description(),
                ticket.status.value,
                ticket.created_at,
            )
            for ticket in tickets
        ]

    def _show_results(self, criterion: str, text: str, tickets: list) -> None:
        """Fill the table and the summary line."""
        self._table.load(self._rows(tickets))
        template = self.COUNT_TEXT if tickets else self.NO_RESULTS_TEXT
        count = count_text(len(tickets), "turno encontrado", "turnos encontrados")
        self._summary.set(
            template.format(count=count, criterion=criterion.lower(), text=text)
        )

    # -------------------------------------------------------------- actions

    def _search(self) -> None:
        """Buscar (RF-32). An empty text or criterion gets the system's message.

        _query shows the message of a ValidationError and returns None.
        A search with no matches returns [], which is a valid answer, so
        the two cases never mix.
        """
        criterion = self._criterion.get()
        text = self._text.get().strip()
        tickets = self._query(self._system.search, criterion, text)
        if tickets is None:
            return
        self._last_search = (criterion, text)
        self._show_results(criterion, text, tickets)
        if not tickets:
            show_info(
                self.NO_RESULTS_MESSAGE.format(criterion=criterion.lower(), text=text),
                parent=self,
            )

    def _clear(self) -> None:
        """Limpiar: empty the text and the table and forget the last search."""
        self._last_search = None
        self._text.set("")
        self._table.clear()
        self._summary.set(self.EMPTY_TEXT)

    def _on_criterion_selected(self, _event: tk.Event) -> None:
        """Change the list and the hint under the text field to fit the new criterion.

        The typed text is left alone, except when it was one of the old
        criterion's words: "Pendiente" means nothing as a patient name.
        """
        if self._text.get() in self._suggestions:
            self._text.set("")
        self._update_suggestions()
        self._text_box.focus_set()

    def _update_suggestions(self) -> None:
        """Load the values that ClinicSystem offers for the chosen criterion."""
        self._suggestions = self._system.search_suggestions(self._criterion.get())
        self._text_box.configure(values=self._suggestions)
        self._hint.set(self.LIST_HINT if self._suggestions else self.FREE_TEXT_HINT)
