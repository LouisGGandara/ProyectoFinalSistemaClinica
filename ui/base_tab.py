"""Abstract base class of every tab of the main window.

Implemented in step D1.
"""

from abc import ABC
from tkinter import ttk


class BaseTab(ttk.Frame, ABC):
    """Tab with a title, a required permission and a refresh method."""

    pass
