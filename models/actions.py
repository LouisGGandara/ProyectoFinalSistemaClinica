"""Actions saved in the action history.

Will also contain the action type constants (LOGIN, LOGOUT, PATIENT_REGISTRATION,
TICKET_CREATION, PATIENT_UPDATE, CALL_NEXT, CARE_FINISHED, TICKET_CANCELLATION,
USER_MANAGEMENT and UNDONE). Implemented in step C10.
"""

from abc import ABC


class Action(ABC):
    """Abstract action with type, description, user, data and timestamp."""

    pass


class LogOnlyAction(Action):
    """Action kept only as evidence; it cannot be undone."""

    pass


class UndoableAction(Action, ABC):
    """Action that can be reverted."""

    pass


class RegisterPatientAction(UndoableAction):
    """Undoes a patient registration and its first ticket."""

    pass


class CreateTicketAction(UndoableAction):
    """Undoes a ticket created for an existing patient."""

    pass


class UpdatePatientAction(UndoableAction):
    """Restores a patient's previous name, age and phone."""

    pass


class CallNextAction(UndoableAction):
    """Returns a called ticket to the front of its queue."""

    pass


class FinishCareAction(UndoableAction):
    """Returns a served ticket to En atención and removes its care record."""

    pass


class CancelTicketAction(UndoableAction):
    """Returns a cancelled ticket to its previous queue position."""

    pass
