"""Console walkthrough of the logic before the interface exists (step C12).

It is the only file of the project that uses print. It runs a short day at
the clinic through ClinicSystem and prints the state after each step.

The data goes to a temporary folder that is deleted at the end, so the real
data folder is never touched. Run it from the project root with:

    python tests/console_demo.py
"""

import sys
import tempfile
from pathlib import Path

# When the file runs as a script, Python only looks for imports in tests/.
# Adding the project root lets "from services..." work as in the tests.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.clinic_system import ClinicSystem  # noqa: E402
from utils.exceptions import ClinicError  # noqa: E402

STATS_LABELS = {
    "registered_patients": "Pacientes registrados",
    "pending": "Turnos pendientes",
    "in_progress": "En atención",
    "served": "Atendidos",
    "cancelled": "Cancelados",
    "normal": "Turnos normales",
    "priority": "Turnos prioritarios",
    "normal_queue": "En cola normal",
    "priority_queue": "En cola prioritaria",
}


def title(text: str) -> None:
    print()
    print(f"== {text} ==")


def show_queues(system: ClinicSystem) -> None:
    priority = [t.number for t in system.pending_priority()]
    normal = [t.number for t in system.pending_normal()]
    following = system.peek_next()
    current = system.in_progress()
    print(f"   Cola prioritaria ({len(priority)}): {', '.join(priority) or 'vacía'}")
    print(f"   Cola normal ({len(normal)}): {', '.join(normal) or 'vacía'}")
    print(f"   Siguiente: {following or 'nadie'}")
    print(f"   En atención: {current or 'nadie'}")


def attempt(description: str, operation, *args) -> None:
    """Run an operation that should fail and print the message the user would see."""
    try:
        operation(*args)
    except ClinicError as error:
        print(f"   {description}: {error}")
    else:
        print(f"   {description}: no hubo error (revisar)")


def run(folder: str) -> None:
    system = ClinicSystem(folder)
    title("1. Inicio")
    print(f"   Carpeta de datos temporal: {folder}")
    print(f"   Avisos al cargar: {system.warnings or 'ninguno'}")

    title("2. Inicio de sesión")
    attempt("admin con clave equivocada", system.login, "admin", "clave")
    user = system.login("recepcion", "Recep123")
    print(f"   Sesión abierta: {user.description()}")

    title("3. Registro de pacientes (recepcionista)")
    for data in (
        ("PAC-0001", "Ana López", 30, "55551234", "Dolor de cabeza", "Normal"),
        ("PAC-0002", "José Peña", 45, "22334455", "Control de presión", "Normal"),
        ("PAC-0003", "María Gómez", 67, "77889900", "Mareos frecuentes",
         "Prioritaria", "Adulto mayor"),
    ):
        ticket = system.register_patient(*data)
        print(f"   Registrado {ticket.patient} con el turno {ticket.number} "
              f"({ticket.care_type.description()})")
    show_queues(system)

    title("4. Validaciones")
    attempt("Edad 'abc'", system.register_patient,
            "PAC-0004", "Luis Pérez", "abc", "55551234", "Fiebre alta", "Normal")
    attempt("Adulto mayor con 30 años", system.register_patient,
            "PAC-0004", "Luis Pérez", 30, "55551234", "Fiebre alta",
            "Prioritaria", "Adulto mayor")
    attempt("Código repetido", system.register_patient,
            "PAC-0001", "Luis Pérez", 30, "55551234", "Fiebre alta", "Normal")
    attempt("Turno nuevo para quien ya tiene uno", system.create_ticket,
            "PAC-0002", "Dolor de espalda", "Normal")
    attempt("Recepcionista cancela N-002", system.cancel_ticket, "N-002")

    title("5. Atención")
    called = system.call_next()
    print(f"   Se llamó a {called.number}: el prioritario pasa primero")
    attempt("Llamar a otro sin finalizar", system.call_next)
    record = system.finish_care()
    print(f"   Atención finalizada: {record}")
    show_queues(system)

    title("6. Cambio de usuario")
    system.logout()
    user = system.login("admin", "Admin123")
    print(f"   Sesión abierta: {user.description()}")
    ticket = system.register_patient(
        "PAC-0004", "Marco Díaz", 52, "44556677", "Revisión de resultados", "Normal"
    )
    print(f"   Registrado {ticket.patient} con el turno {ticket.number}")
    show_queues(system)

    title("7. Cancelar N-002, que está en medio de la cola normal")
    system.cancel_ticket("N-002")
    print(f"   Estado de N-002: {system.get_status('N-002')}")
    show_queues(system)

    title("8. Deshacer")
    undone = system.undo()
    print(f"   Se deshizo: {undone.description}")
    print(f"   Estado de N-002: {system.get_status('N-002')}")
    show_queues(system)

    title("9. Búsquedas")
    found = system.search("Nombre", "mar")
    print("   Nombre 'mar': " + ", ".join(f"{t.number} {t.patient.full_name}"
                                          for t in found))
    found = system.search("Código de paciente", "PAC-9999")
    print(f"   Código 'PAC-9999': {found or 'sin resultados'}")

    title("10. Estadísticas")
    for key, value in system.stats().items():
        print(f"   {STATS_LABELS[key]}: {value}")

    title("11. Historial de acciones (la más reciente arriba)")
    for action in system.action_history():
        mark = " [deshecha]" if getattr(action, "undone", False) else ""
        print(f"   {action.action_type} | {action.username} | "
              f"{action.description}{mark}")

    title("12. Reinicio: un sistema nuevo lee los mismos archivos")
    system.logout()
    reopened = ClinicSystem(folder)
    reopened.login("admin", "Admin123")
    show_queues(reopened)
    print(f"   Atendidos guardados: {len(reopened.list_care_records())}")
    print(f"   ¿Hay algo para deshacer? {'Sí' if reopened.can_undo() else 'No'}")
    patients = (Path(folder) / "patients.json").read_text(encoding="utf-8")
    line = next(row for row in patients.splitlines() if "Peña" in row)
    print(f"   Línea de patients.json: {line.strip()}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        run(str(Path(tmp) / "data"))


if __name__ == "__main__":
    main()
