"""Fill the data folder with the demo data of step F4.

The script runs one morning at the clinic through ClinicSystem, the same
facade the interface uses, so every rule applies: validations, permissions,
queues and the ticket counter. Nothing is written to the JSON files by hand.

Result: 10 patients, 4 of them priority (one per criterion), 3 tickets
served, 1 cancelled and 6 pending, 2 in the priority queue and 4 in the
normal one. Several names have accents and ñ, so opening patients.json in
Notepad shows that the files are readable UTF-8 (RNF-17).

Unlike console_demo.py, this script does write to data/. It works in this
order, so a failure never leaves data/ half written:

1. copy the current data/ to backups/data-YYYYMMDD-HHMMSS/,
2. run the morning in a temporary folder,
3. open that folder again with a new ClinicSystem and check every count,
4. only then copy the five JSON files into data/.

users.json is created again with the two default users of section 3.10
(admin / Admin123 and recepcion / Recep123), the ones the manual uses.

Close the application before running it: an open window would overwrite
data/ the next time it saves. From the project root:

    python tests/generate_demo_data.py
    python tests/generate_demo_data.py --rapido   (no pauses between steps)
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# Same reason as in console_demo.py: as a script, Python only looks for
# imports in tests/, so the project root has to be added by hand.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.clinic_system import ClinicSystem  # noqa: E402
from services.patient_manager import PatientManager  # noqa: E402
from services.ticket_manager import TicketManager  # noqa: E402
from services.user_manager import UserManager  # noqa: E402
from utils.exceptions import ClinicError  # noqa: E402

DATA_FOLDER = PROJECT_ROOT / "data"
BACKUP_FOLDER = PROJECT_ROOT / "backups"

# The names come from the managers, so a renamed file cannot be left behind.
DATA_FILES = (
    UserManager.FILE,
    PatientManager.FILE,
    TicketManager.TICKETS_FILE,
    TicketManager.CARE_RECORDS_FILE,
    TicketManager.COUNTER_FILE,
)

ADMIN = ("admin", "Admin123")
RECEPTION = ("recepcion", "Recep123")

# Seconds between steps. Without them every date would fall in the same
# second, and the tables of the demo would not look like a real morning.
PAUSE_SECONDS = 1

# code, full name, age, phone, reason, care type, criterion.
# The comment is the ticket each patient gets, given the order of run_morning.
PATIENTS = (
    ("PAC-0001", "Ana Lucía Pérez", 34, "55512340", "Dolor de garganta y fiebre", "Normal", None),  # N-001
    ("PAC-0002", "José Ramírez Peña", 45, "22334455", "Control de presión arterial", "Normal", None),  # N-002
    ("PAC-0003", "María Elena Gómez", 68, "77889900", "Mareos frecuentes", "Prioritaria", "Adulto mayor"),  # P-003
    ("PAC-0004", "Marco Antonio Díaz", 29, "44556677", "Revisión de resultados de laboratorio", "Normal", None),  # N-004
    ("PAC-0005", "Tomás Ibáñez Ruiz", 57, "33221100", "Dolor intenso en el pecho", "Prioritaria", "Urgencia"),  # P-005
    ("PAC-0006", "Iván Ordóñez", 52, "66778899", "Dolor lumbar", "Normal", None),  # N-006
    ("PAC-0007", "Begoña Núñez", 23, "55667788", "Alergia en la piel", "Normal", None),  # N-007
    ("PAC-0008", "Andrés Peñate Morales", 40, "23456789", "Renovación de receta", "Prioritaria", "Discapacidad"),  # P-008
    ("PAC-0009", "Lucía Fernández", 19, "34567890", "Tos persistente", "Normal", None),  # N-009
    ("PAC-0010", "Sofía Muñoz Castañeda", 31, "45678901", "Control prenatal", "Prioritaria", "Embarazo"),  # P-010
)

# What the data must look like at the end. verify() compares against it.
EXPECTED_STATS = {
    "registered_patients": 10,
    "pending": 6,
    "in_progress": 0,
    "served": 3,
    "cancelled": 1,
    "normal": 6,
    "priority": 4,
    "normal_queue": 4,
    "priority_queue": 2,
}
EXPECTED_PRIORITY_QUEUE = ["P-008", "P-010"]
EXPECTED_NORMAL_QUEUE = ["N-002", "N-004", "N-007", "N-009"]
EXPECTED_SERVED = ["P-005", "N-001", "P-003"]  # most recent first, as RF-36
EXPECTED_CANCELLED = "N-006"


class DemoDataError(Exception):
    """The generated data does not match what the demo needs."""


class Morning:
    """Runs the steps of the demo morning on one ClinicSystem."""

    def __init__(self, system: ClinicSystem, pause: float) -> None:
        self._system = system
        self._pause = pause

    def _wait(self) -> None:
        if self._pause:
            time.sleep(self._pause)

    def log_in(self, credentials: tuple[str, str]) -> None:
        """Close the open session, if any, and enter with other credentials."""
        self._system.logout()
        user = self._system.login(*credentials)
        print(f"   Sesión de {user.username} ({user.role})")

    def register(self, index: int) -> None:
        """Register PATIENTS[index]; ClinicSystem creates the first ticket."""
        ticket = self._system.register_patient(*PATIENTS[index])
        print(f"   Registrado {ticket.patient} con el turno {ticket.number} "
              f"({ticket.care_type.description()})")
        self._wait()

    def serve(self) -> None:
        """Call the next ticket and finish its care, as the reception does."""
        ticket = self._system.call_next()
        self._wait()
        self._system.finish_care()
        print(f"   Atendido {ticket.number}, {ticket.patient.full_name}")
        self._wait()

    def cancel(self, number: str) -> None:
        """Cancel a pending ticket. Needs a session of the administrator."""
        self._system.cancel_ticket(number)
        print(f"   Cancelado {number}")
        self._wait()


def run_morning(system: ClinicSystem, pause: float) -> None:
    """Register, serve and cancel in the order that gives the expected data.

    call_next always takes the priority queue first, so registrations and
    cares are mixed: if all ten patients came first, the three served
    tickets would all be priority.
    """
    morning = Morning(system, pause)
    morning.log_in(RECEPTION)
    for index in (0, 1, 2):
        morning.register(index)
    morning.serve()  # P-003 goes before N-001 and N-002 (RN-01)
    morning.serve()  # N-001, first normal to arrive (RN-02)
    for index in (3, 4, 5):
        morning.register(index)
    morning.serve()  # P-005, the urgency
    morning.register(6)

    # Only the administrator can cancel (section 3.1).
    morning.log_in(ADMIN)
    morning.cancel("N-006")

    morning.log_in(RECEPTION)
    for index in (7, 8, 9):
        morning.register(index)
    system.logout()


def check(condition: bool, message: str) -> None:
    if not condition:
        raise DemoDataError(message)


def verify(folder: Path) -> None:
    """Open the folder with a new ClinicSystem and check what the demo needs.

    Reading the files again, instead of asking the system that wrote them,
    tests the same path the application follows when it starts.
    """
    system = ClinicSystem(str(folder))
    check(not system.warnings, f"Avisos al cargar: {system.warnings}")
    system.login(*ADMIN)

    stats = system.stats()
    check(stats == EXPECTED_STATS,
          f"Estadísticas distintas a las esperadas: {stats}")
    priority = [ticket.number for ticket in system.pending_priority()]
    normal = [ticket.number for ticket in system.pending_normal()]
    check(priority == EXPECTED_PRIORITY_QUEUE, f"Cola prioritaria: {priority}")
    check(normal == EXPECTED_NORMAL_QUEUE, f"Cola normal: {normal}")
    served = [record.ticket_number for record in system.list_care_records()]
    check(served == EXPECTED_SERVED, f"Atendidos: {served}")
    check(system.get_status(EXPECTED_CANCELLED) == "Cancelado",
          f"{EXPECTED_CANCELLED} no quedó cancelado.")
    criteria = {
        ticket.care_type.criterion
        for ticket in system.search("Tipo de atención", "Prioritaria")
    }
    check(len(criteria) == 4, f"Criterios de los prioritarios: {criteria}")
    system.logout()
    check_utf8(folder)


def check_utf8(folder: Path) -> None:
    """Check that the five files are readable UTF-8 (RNF-17).

    No BOM, no \\uXXXX escapes, and the ñ of Peña stored as a real character.
    bulk_demo.py uses it too.
    """
    for name in DATA_FILES:
        raw = (folder / name).read_bytes()
        raw.decode("utf-8")  # raises UnicodeDecodeError if it is not UTF-8
        check(not raw.startswith(b"\xef\xbb\xbf"), f"{name} tiene BOM.")
        check(b"\\u" not in raw, f"{name} tiene secuencias \\uXXXX.")
    patients = (folder / PatientManager.FILE).read_bytes()
    check("Peña".encode("utf-8") in patients,
          "patients.json no tiene la ñ como carácter real.")


def backup(data_folder: Path, backup_root: Path) -> Path | None:
    """Copy the whole data folder to backups/data-YYYYMMDD-HHMMSS/.

    The copy includes the .corrupted files and anything else in the folder,
    so going back means copying it over data/. Returns None when there is
    no data folder yet. Two backups in the same second (this script with
    --rapido and then bulk_demo.py, say) get -2, -3 at the end of the name.
    """
    if not data_folder.is_dir():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = backup_root / f"data-{stamp}"
    copy_number = 1
    while destination.exists():
        copy_number += 1
        destination = backup_root / f"data-{stamp}-{copy_number}"
    shutil.copytree(data_folder, destination)
    return destination


def install(source: Path, data_folder: Path) -> None:
    """Copy the five JSON files into data/, each through a .tmp file.

    Same idea as JsonRepository.save: os.replace swaps the file in one
    step, so a failure in the middle of a copy leaves the old file whole.
    Other files in data/ (.gitkeep, old .corrupted copies) stay as they are.
    """
    data_folder.mkdir(exist_ok=True)
    for name in DATA_FILES:
        temporary = data_folder / f"{name}.tmp"
        shutil.copyfile(source / name, temporary)
        os.replace(temporary, data_folder / name)


def show_sample(data_folder: Path) -> None:
    """Print one line of patients.json, as it looks in Notepad."""
    text = (data_folder / PatientManager.FILE).read_text(encoding="utf-8")
    line = next(row for row in text.splitlines() if "Peña" in row)
    print(f"   Línea de patients.json: {line.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Genera los datos de demostración en data/ (paso F4)."
    )
    parser.add_argument(
        "--rapido",
        action="store_true",
        help="sin pausas entre pasos (todas las fechas quedan casi iguales)",
    )
    args = parser.parse_args()
    pause = 0 if args.rapido else PAUSE_SECONDS

    print("== 1. Respaldo ==")
    saved = backup(DATA_FOLDER, BACKUP_FOLDER)
    if saved is None:
        print("   No había carpeta data, no hay nada que respaldar")
    else:
        print(f"   Copia de data guardada en {saved.relative_to(PROJECT_ROOT)}")

    try:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "data"
            print("\n== 2. Mañana de demostración (carpeta temporal) ==")
            run_morning(ClinicSystem(str(work)), pause)

            print("\n== 3. Revisión ==")
            verify(work)
            print("   Conteos, colas, atendidos y UTF-8 correctos")

            print("\n== 4. Copia a data ==")
            install(work, DATA_FOLDER)
    except (ClinicError, DemoDataError, OSError, UnicodeDecodeError) as error:
        print(f"\nNo se generaron los datos: {error}")
        print("La carpeta data quedó sin cambios.")
        return 1

    for name in DATA_FILES:
        print(f"   data/{name}")
    show_sample(DATA_FOLDER)
    print("\nListo. Usuarios: admin / Admin123 y recepcion / Recep123.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
