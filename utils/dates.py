"""Date and time helpers.

Every date in the system is stored and shown as text with DATE_FORMAT. Keeping
the format in one constant means the JSON files, the tables and the sorting
all use the same shape.
"""

from collections.abc import Callable
from datetime import datetime

from utils.exceptions import ValidationError

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# The clock that now_text reads. The application always uses the real time.
# Only tests/bulk_demo.py replaces it, to spread a simulated week over its
# real hours instead of putting every date in the same few seconds (step F6).
_clock: Callable[[], datetime] = datetime.now


def now_text() -> str:
    """Return the current local date and time formatted with DATE_FORMAT."""
    return _clock().strftime(DATE_FORMAT)


def set_clock(clock: Callable[[], datetime] | None) -> None:
    """Make now_text read another clock, or the real one again with None.

    Every class that stamps a date (Patient, Ticket, Action) calls now_text,
    so changing the clock here changes it for all of them at once.
    """
    global _clock
    _clock = datetime.now if clock is None else clock


def parse_date(text: str) -> datetime:
    """Turn a DATE_FORMAT string back into a datetime.

    Raises ValidationError if the text has another shape, which can happen
    when someone edits a JSON file by hand.
    """
    try:
        return datetime.strptime(text, DATE_FORMAT)
    except (TypeError, ValueError) as error:
        raise ValidationError(
            f"La fecha «{text}» no tiene el formato AAAA-MM-DD HH:MM:SS."
        ) from error
