"""Permissions that a user role can have (roadmap section 3.1).

Each role decides its permissions in User.permissions(). ClinicSystem checks
them before every restricted operation, and the interface uses the same check
to hide or disable buttons.
"""

from enum import Enum


class Permission(Enum):
    """List of the permissions of the system.

    The value is the Spanish label the interface can show, for example in a
    permission error or in the users tab.
    """

    REGISTER_PATIENT = "Registrar paciente"
    UPDATE_PATIENT = "Modificar paciente"
    CREATE_TICKET = "Generar turno"
    SEARCH = "Buscar información"
    VIEW_QUEUES = "Ver colas"
    SERVE = "Atender pacientes"
    VIEW_CARE_HISTORY = "Ver historial de atendidos"
    VIEW_STATS = "Ver estadísticas"
    CANCEL_TICKET = "Cancelar turno"
    UNDO = "Deshacer la última acción"
    VIEW_ACTION_LOG = "Ver historial de acciones"
    MANAGE_USERS = "Administrar usuarios"
