"""Fill data/ with a simulated week of the clinic and open the application.

These are the JSON files that go with the final delivery (step F6): 300
patients over five working days, so the application looks like a clinic
that is really in use.

The week ends at the moment the script runs. Each day goes from 7:00 to
17:00 (today, only until now). A morning receptionist and an afternoon one
take turns at noon, register patients with different ages, care types and
criteria, call and finish cares, give new tickets to patients who come back
and correct patient data. Every 30 patients the administrator steps in to
cancel tickets and undo actions. On every day but the last, the office
stays open until the queues are empty. In the last hour of the week nobody
is called, so the queues keep the patients still waiting, and nobody is
left in care.

Every operation goes through ClinicSystem, so the validations, permissions,
queues and the ticket counter all apply. A simulated clock (utils.dates.
set_clock) gives each action its time of the week; it is switched back to
the real clock before the window opens.

The action history lives only in memory (section 3.8). That is why the
script ends by opening the window with the same ClinicSystem: log in as
admin to see the whole week in the history. Closing the window loses the
history; the patients, tickets and care records stay in data/.

Like generate_demo_data.py, the script copies data/ to backups/ first and
then starts from an empty clinic, so running it again gives a new week
instead of piling patients on top. If something fails, data/ goes back to
the copy. Close the application before running it. From the project root,
in PyCharm's terminal:

    python tests/bulk_demo.py
    python tests/bulk_demo.py --sin-ventana    (only fill data/ and print the summary)
    python tests/bulk_demo.py --semilla 7      (other names and choices; 2026 by default)
"""

import argparse
import json
import random
import shutil
import sys
import time as clock_time
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models.patient import Patient  # noqa: E402
from models.ticket import Ticket  # noqa: E402
from services.clinic_system import ClinicSystem  # noqa: E402
from services.ticket_manager import TicketManager  # noqa: E402
from tests.generate_demo_data import (  # noqa: E402
    ADMIN,
    BACKUP_FOLDER,
    DATA_FILES,
    DATA_FOLDER,
    RECEPTION,
    DemoDataError,
    backup,
    check,
    check_utf8,
)
from utils.dates import DATE_FORMAT, set_clock  # noqa: E402
from utils.exceptions import ClinicError  # noqa: E402

TOTAL_PATIENTS = 300
WORK_DAYS = 5
OPENING = time(7, 0)
NOON = time(12, 0)
CLOSING = time(17, 0)
OVERTIME = timedelta(hours=3)        # the most a day can run past closing
MIN_DAY = timedelta(hours=1)         # a shorter "today" is left out of the week
DEFAULT_SEED = 2026

ADMIN_ROUND_EVERY = 30      # patients between visits of the administrator
SERVE_RATE = 0.85           # chance of serving someone after each arrival
RETURN_RATE = 0.08          # chance that a past patient comes back
UPDATE_RATE = 0.05          # chance of correcting a patient's data
# In the last hour of the week nobody is served, so the queues end with
# patients waiting. Without it the priority queue would usually end empty,
# because priority goes first.
LATE_PERIOD = timedelta(hours=1)

AFTERNOON_NAME = "Carmen Ávila Muñoz"
AFTERNOON_USER = "recepcion_tarde"
# The administrator gives the first password, then the receptionist changes
# it from Archivo > Cambiar mi contraseña (RF-43 and RF-44).
AFTERNOON_PASSWORDS = ("Tarde123", "Tarde456", "Tarde789")

# Separated so a second first name matches the first one, and so only
# women can get the Embarazo criterion.
WOMEN_NAMES = (
    "Ana", "María", "Sofía", "Lucía", "Begoña", "Valentina", "Camila",
    "Ximena", "Renata", "Daniela", "Inés", "Mónica", "Verónica", "Paola",
    "Ángela", "Gabriela", "Elena", "Rocío", "Beatriz", "Natalia",
)
MEN_NAMES = (
    "José", "Luis", "Andrés", "Tomás", "Iván", "Martín", "Julián",
    "Sebastián", "Matías", "Óscar", "Rubén", "Raúl", "Héctor", "Jesús",
    "Nicolás", "Ramón", "Fernando", "Joaquín", "Emilio", "Germán",
)
SURNAMES = (
    "López", "Pérez", "Gómez", "Peña", "Muñoz", "Núñez", "Ordóñez", "Ibáñez",
    "Castañeda", "Hernández", "García", "Martínez", "Rodríguez", "Díaz",
    "Ramírez", "Morales", "Ruiz", "Álvarez", "Jiménez", "Sánchez",
    "Gutiérrez", "Ávila", "Méndez", "Cifuentes", "Orellana", "Barrios",
    "Echeverría", "Quiñónez", "Montúfar", "Peñate", "Cabrera", "Fuentes",
    "Estrada", "Velásquez", "Aguilar", "Juárez", "Monzón", "Girón", "Solís",
    "Toledo",
)
REASONS = (
    "Dolor de cabeza", "Fiebre alta desde ayer", "Control de presión arterial",
    "Dolor de garganta", "Tos persistente", "Revisión de resultados de laboratorio",
    "Dolor abdominal", "Mareos frecuentes", "Renovación de receta",
    "Control de diabetes", "Alergia en la piel", "Dolor lumbar",
    "Vacunación", "Control de niño sano", "Dolor de oído",
    "Infección urinaria", "Corte en la mano", "Esguince de tobillo",
    "Dolor en el pecho", "Dificultad para respirar", "Control prenatal",
    "Revisión de la vista", "Vómitos y diarrea", "Certificado médico",
    "Dolor de muelas",
)
URGENT_REASONS = ("Dolor en el pecho", "Dificultad para respirar", "Corte en la mano")
PHONE_FIRST_DIGITS = "234567"


class SimulatedClock:
    """The clock now_text reads while the week is simulated.

    It only moves forward, and never past its limit, so the dates keep the
    order of the operations and none ends up later than the real time.
    """

    def __init__(self, start: datetime) -> None:
        self._now = start
        self._limit = start

    def __call__(self) -> datetime:
        return self._now

    def jump_to(self, moment: datetime, limit: datetime) -> None:
        """Move to moment (or stay, if it is in the past) with a new limit."""
        self._now = max(self._now, moment)
        self._limit = max(limit, self._now)

    def advance(self, minutes: float) -> None:
        """Let some minutes go by, without crossing the limit."""
        self._now = min(self._now + timedelta(minutes=minutes), self._limit)


def work_days(end: datetime, count: int) -> list[tuple[datetime, datetime]]:
    """Opening and closing time of the last count weekdays up to end.

    Today closes at end if the clinic is still open; a today shorter than
    MIN_DAY is left out, and the week ends on the previous weekday.
    """
    days = []
    day: date = end.date()
    while len(days) < count:
        if day.weekday() < 5:  # Monday to Friday
            opening = datetime.combine(day, OPENING)
            closing = min(datetime.combine(day, CLOSING), end)
            if closing - opening >= MIN_DAY:
                days.append((opening, closing))
        day -= timedelta(days=1)
    return list(reversed(days))


def split_patients(total: int, days: list[tuple[datetime, datetime]]) -> list[int]:
    """Patients per day, in proportion to how long each day is open."""
    minutes = [(closing - opening).total_seconds() for opening, closing in days]
    shares = [total * part / sum(minutes) for part in minutes]
    counts = [int(share) for share in shares]
    # The patients lost by rounding down go to the days with the largest rest.
    by_rest = sorted(range(len(days)), key=lambda i: shares[i] - counts[i], reverse=True)
    for index in by_rest[: total - sum(counts)]:
        counts[index] += 1
    return counts


class SimulatedWeek:
    """Runs the week on one ClinicSystem and keeps what it needs to choose."""

    def __init__(
        self,
        system: ClinicSystem,
        rng: random.Random,
        clock: SimulatedClock,
        end: datetime,
    ) -> None:
        self._system = system
        self._rng = rng
        self._clock = clock
        self._days = work_days(end, WORK_DAYS)
        self._patients: list[Patient] = []
        self._women: set[str] = set()  # codes of the patients who are women
        self._used_names: set[str] = set()
        self._admin_rounds = 0
        self._afternoon: tuple[str, str] | None = None  # set once the user exists
        self._reception = RECEPTION
        self._slot_minutes = 1.0
        self.summary: dict = {}

    @property
    def days(self) -> list[tuple[datetime, datetime]]:
        """Opening and closing time of each simulated day."""
        return list(self._days)

    # ------------------------------------------------------------ time

    def _wait(self, share: float) -> None:
        """Let part of the current patient's time slot go by, with some noise."""
        self._clock.advance(self._slot_minutes * share * self._rng.uniform(0.5, 1.5))

    # -------------------------------------------------------- sessions

    def _log_in(self, credentials: tuple[str, str]) -> None:
        self._system.logout()
        self._wait(0.02)
        self._system.login(*credentials)

    def _back_to_reception(self) -> None:
        self._log_in(self._reception)

    def _start_day(self, opening: datetime, closing: datetime) -> None:
        """Open the clinic: the morning receptionist logs in."""
        self._clock.jump_to(opening + timedelta(minutes=self._rng.uniform(0, 5)), closing)
        self._reception = RECEPTION
        self._log_in(self._reception)

    def _afternoon_shift(self) -> None:
        """At noon the afternoon receptionist takes over.

        The first day the administrator creates the account and gives it a
        password, and the receptionist changes it (RF-43 and RF-44).
        """
        if self._afternoon is None:
            first, given, own = AFTERNOON_PASSWORDS
            self._log_in(ADMIN)
            self._system.create_user(AFTERNOON_NAME, AFTERNOON_USER, first, "Recepcionista")
            self._wait(0.05)
            self._system.change_password(AFTERNOON_USER, given, given)
            self._wait(0.05)
            self._log_in((AFTERNOON_USER, given))
            self._system.change_own_password(given, own, own)
            self._afternoon = (AFTERNOON_USER, own)
        else:
            self._log_in(self._afternoon)
        self._reception = self._afternoon

    def _close_day(self, closing: datetime) -> None:
        """Serve whoever is still waiting, then close the session."""
        self._clock.jump_to(self._clock(), closing + OVERTIME)
        self._slot_minutes = 10.0
        while not self._system.queues_empty():
            self.serve()
        self._wait(0.2)
        self._system.logout()

    def _end_week(self) -> None:
        """The administrator deletes the afternoon account and checks the week.

        Deleting the account leaves users.json with the two users of
        section 3.10. The counts and the history are kept for the summary
        while the administrator's session is open.
        """
        self._log_in(ADMIN)
        if self._afternoon is not None:
            self._system.delete_user(AFTERNOON_USER)
        self.summary = {
            "stats": self._system.stats(),
            "history": self._system.action_history(),
        }
        self._system.logout()

    # --------------------------------------------------- random values

    def _full_name(self, woman: bool) -> str:
        """A name that has not been used yet in this run."""
        names = WOMEN_NAMES if woman else MEN_NAMES
        while True:
            first, second = self._rng.sample(names, 2)
            surnames = self._rng.sample(SURNAMES, 2)
            shape = self._rng.random()
            if shape < 0.15:
                name = f"{first} {surnames[0]}-{surnames[1]}"
            elif shape < 0.30:
                name = f"{first} {second} {surnames[0]}"
            else:
                name = f"{first} {surnames[0]} {surnames[1]}"
            if name not in self._used_names:
                self._used_names.add(name)
                return name

    def _age(self) -> int:
        """Children, adults and seniors in a rough clinic proportion."""
        group = self._rng.random()
        if group < 0.15:
            return self._rng.randint(0, 12)
        if group < 0.75:
            return self._rng.randint(13, 59)
        return self._rng.randint(60, 95)

    def _phone(self) -> str:
        rest = "".join(self._rng.choice("0123456789") for _ in range(7))
        return self._rng.choice(PHONE_FIRST_DIGITS) + rest

    def _care_type(self, age: int, woman: bool) -> tuple[str, str | None]:
        """Normal or Prioritaria with a criterion the patient can have.

        Adulto mayor only from 60 (RN-09), so the choice never trips a
        validation, and Embarazo only for women between 15 and 45.
        """
        priority_rate = 0.6 if age >= 60 else 0.2
        if self._rng.random() >= priority_rate:
            return "Normal", None
        criteria = ["Discapacidad", "Urgencia"]
        if age >= 60:
            criteria += ["Adulto mayor"] * 4
        if woman and 15 <= age <= 45:
            criteria += ["Embarazo"] * 3
        return "Prioritaria", self._rng.choice(criteria)

    def _reason(self, criterion: str | None) -> str:
        if criterion == "Embarazo":
            return "Control prenatal"
        if criterion == "Urgencia":
            return self._rng.choice(URGENT_REASONS)
        return self._rng.choice(REASONS)

    # ------------------------------------------------------ operations

    def register(self) -> Ticket:
        """Register a new patient with the next free code."""
        age = self._age()
        woman = self._rng.random() < 0.55
        care_type, criterion = self._care_type(age, woman)
        ticket = self._system.register_patient(
            self._system.next_code(),
            self._full_name(woman),
            age,
            self._phone(),
            self._reason(criterion),
            care_type,
            criterion,
        )
        self._patients.append(ticket.patient)
        if woman:
            self._women.add(ticket.patient.code)
        return ticket

    def serve(self) -> None:
        """Call the next ticket and finish its care, if anybody is waiting."""
        if self._system.queues_empty():
            return
        self._wait(0.1)
        self._system.call_next()
        self._wait(0.5)
        self._system.finish_care()

    def _has_active_ticket(self, patient: Patient) -> bool:
        tickets = self._system.search("Código de paciente", patient.code)
        return any(ticket.is_active for ticket in tickets)

    def returning_patient(self) -> None:
        """Give a new ticket to a patient whose last ticket is over (RF-17)."""
        candidates = [p for p in self._patients if not self._has_active_ticket(p)]
        if not candidates:
            return
        self._wait(0.05)
        patient = self._rng.choice(candidates)
        care_type, criterion = self._care_type(patient.age, patient.code in self._women)
        self._system.create_ticket(
            patient.code, self._reason(criterion), care_type, criterion
        )

    def update_patient(self) -> None:
        """Correct a phone number or a birthday, as the reception would (RF-14)."""
        self._wait(0.05)
        patient = self._rng.choice(self._patients)
        age = patient.age
        phone = patient.phone
        if self._rng.random() < 0.5 and age < 120:
            age += 1
        else:
            phone = self._phone()
        self._system.update_patient(patient.code, patient.full_name, age, phone)

    def _cancel_random(self) -> bool:
        """Cancel one pending ticket chosen at random. False if nobody waits."""
        pending = self._system.pending_normal() + self._system.pending_priority()
        if not pending:
            return False
        self._wait(0.05)
        self._system.cancel_ticket(self._rng.choice(pending).number)
        return True

    def admin_round(self) -> None:
        """The administrator tries one kind of undo and cancels a ticket.

        The rounds take turns, so every undoable action of section 3.6
        is undone at least once. The undo reverts the administrator's own
        last step, because it is the top of the undo stack. A cancellation
        or a call needs somebody waiting; when nobody is, the administrator
        corrects a patient and undoes that instead.
        """
        self._log_in(ADMIN)
        turn = self._admin_rounds % 4
        if turn == 0:
            done = self._cancel_random()     # undo: back to its position
        elif turn == 2:
            done = not self._system.queues_empty()
            if done:
                self._wait(0.05)
                self._system.call_next()     # undo: back to the front
        elif turn == 3:
            # Registered by mistake. Its ticket number is not used again
            # (RN-04), and it does not count toward the total.
            self.register()
            self._patients.pop()
            done = True
        else:
            done = False
        if not done:
            self.update_patient()            # undo: the previous values
        self._wait(0.05)
        self._system.undo()
        self._cancel_random()
        self._admin_rounds += 1
        self._back_to_reception()

    def run(self, total: int, show_progress: bool = True) -> None:
        """Register total patients over the week, with every operation mixed in."""
        counts = split_patients(total, self._days)
        number = 0
        for day_index, ((opening, closing), count) in enumerate(zip(self._days, counts)):
            last_day = day_index == len(self._days) - 1
            self._start_day(opening, closing)
            slot = (closing - opening) / count
            self._slot_minutes = slot.total_seconds() / 60
            for index in range(count):
                number += 1
                # Each patient gets an equal slot of the day; the clock may
                # not leave it, so the day ends on time.
                slot_start = opening + slot * index
                arrival = slot_start + slot * self._rng.uniform(0, 0.2)
                self._clock.jump_to(arrival, slot_start + slot - timedelta(seconds=1))
                if self._clock().time() >= NOON and self._reception == RECEPTION:
                    self._afternoon_shift()
                self.register()
                late = last_day and arrival >= closing - LATE_PERIOD
                if not late and self._rng.random() < SERVE_RATE:
                    self.serve()
                if self._rng.random() < RETURN_RATE:
                    self.returning_patient()
                if self._rng.random() < UPDATE_RATE:
                    self.update_patient()
                if number % ADMIN_ROUND_EVERY == 0:
                    self.admin_round()
                if show_progress and number % 50 == 0:
                    print(f"   {number} pacientes registrados")
            if not last_day:
                self._close_day(closing)
        self._end_week()


def check_dates(folder: Path, end: datetime) -> None:
    """Tickets numbered in the order they were created, none after end."""
    rows = json.loads((folder / TicketManager.TICKETS_FILE).read_text(encoding="utf-8"))
    rows.sort(key=lambda row: int(row["number"].split("-")[1]))
    created = [datetime.strptime(row["created_at"], DATE_FORMAT) for row in rows]
    check(created == sorted(created), "Hay turnos con fechas fuera de orden.")
    check(created[-1] <= end, "Hay turnos con fecha posterior a la hora real.")


def verify(folder: Path, stats: dict, end: datetime) -> None:
    """Open data/ with a new ClinicSystem and compare it with the week."""
    reopened = ClinicSystem(str(folder))
    check(not reopened.warnings, f"Avisos al cargar: {reopened.warnings}")
    reopened.login(*ADMIN)
    check(reopened.stats() == stats, "Los conteos cambiaron al volver a abrir.")
    check(reopened.in_progress() is None, "Quedó un paciente en atención.")
    check(len(reopened.action_history()) == 1, "El historial debía empezar vacío.")
    reopened.logout()
    check_dates(folder, end)
    check_utf8(folder)


def clear_data(data_folder: Path) -> None:
    """Remove the five JSON files, so ClinicSystem starts an empty clinic.

    Other files (.gitkeep, old .corrupted copies) stay as they are.
    """
    data_folder.mkdir(exist_ok=True)
    for name in DATA_FILES:
        (data_folder / name).unlink(missing_ok=True)


def restore(saved: Path | None, data_folder: Path) -> None:
    """Put back the five files of the backup after a failed run."""
    clear_data(data_folder)
    if saved is None:
        return
    for name in DATA_FILES:
        if (saved / name).exists():
            shutil.copyfile(saved / name, data_folder / name)


def print_summary(summary: dict, days: list[tuple[datetime, datetime]]) -> None:
    """Counts of the data and of each type of action in the history."""
    stats = summary["stats"]
    history = summary["history"]
    first, last = days[0][0], days[-1][1]
    print(f"   Semana simulada: {first:%Y-%m-%d %H:%M} a {last:%Y-%m-%d %H:%M}")
    print(f"   Pacientes: {stats['registered_patients']}")
    print(f"   Turnos: {stats['pending']} pendientes, {stats['in_progress']} en atención, "
          f"{stats['served']} atendidos, {stats['cancelled']} cancelados")
    print(f"   Normales {stats['normal']}, prioritarios {stats['priority']}; "
          f"en cola normal {stats['normal_queue']}, "
          f"en cola prioritaria {stats['priority_queue']}")
    print(f"   Historial de acciones: {len(history)}")
    for action_type, count in Counter(a.action_type for a in history).most_common():
        print(f"      {action_type}: {count}")
    undone = sum(1 for action in history if getattr(action, "undone", False))
    print(f"      (acciones marcadas como deshechas: {undone})")


def open_window(system: ClinicSystem) -> None:
    """Open the application with this system, so its history stays visible."""
    # Imported here so --sin-ventana works where Tkinter is not installed.
    from ui.app import App

    app = App(log_path=PROJECT_ROOT / "errors.log", system=system)
    app.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Llena data/ con una semana simulada de la clínica y abre la aplicación."
    )
    parser.add_argument("--sin-ventana", action="store_true",
                        help="solo llena data/ y muestra el resumen")
    parser.add_argument("--semilla", type=int, default=DEFAULT_SEED,
                        help=f"cambia los nombres y las decisiones (por defecto {DEFAULT_SEED})")
    args = parser.parse_args()

    print("== 1. Respaldo ==")
    saved = backup(DATA_FOLDER, BACKUP_FOLDER)
    if saved is not None:
        print(f"   Copia de data guardada en {saved.relative_to(PROJECT_ROOT)}")

    end = datetime.now().replace(microsecond=0)
    print(f"\n== 2. Semana en la clínica (semilla {args.semilla}) ==")
    started = clock_time.perf_counter()
    try:
        clear_data(DATA_FOLDER)
        system = ClinicSystem(str(DATA_FOLDER))
        week_days = work_days(end, WORK_DAYS)
        clock = SimulatedClock(week_days[0][0])
        set_clock(clock)
        try:
            week = SimulatedWeek(system, random.Random(args.semilla), clock, end)
            week.run(TOTAL_PATIENTS)
        finally:
            set_clock(None)
        print(f"   Listo en {clock_time.perf_counter() - started:.1f} s")

        print("\n== 3. Revisión ==")
        verify(DATA_FOLDER, week.summary["stats"], end)
        print("   Conteos, fechas y UTF-8 correctos")
    except (ClinicError, DemoDataError, OSError, UnicodeDecodeError) as error:
        restore(saved, DATA_FOLDER)
        print(f"\nNo se generaron los datos: {error}")
        # The message for the user hides the cause; here it helps to know
        # which file failed and why (for example, a Windows lock).
        if error.__cause__ is not None:
            print(f"   Detalle técnico: {error.__cause__!r}")
        print("La carpeta data volvió a como estaba antes de correr el script.")
        return 1

    print("\n== 4. Resumen ==")
    print_summary(week.summary, week.days)

    if args.sin_ventana:
        print("\nEl historial de acciones se pierde al terminar el script (sección 3.8).")
        return 0
    print("\n== 5. Aplicación ==")
    print("   Entra como admin / Admin123 y abre Historial de acciones.")
    print("   Al cerrar la ventana, el historial se pierde; los datos quedan en data.")
    open_window(system)
    return 0


if __name__ == "__main__":
    sys.exit(main())
