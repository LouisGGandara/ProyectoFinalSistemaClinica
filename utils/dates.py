"""Date and time helpers.

Every date in the system is stored and shown as text with DATE_FORMAT. Keeping
the format in one constant means the JSON files, the tables and the sorting
all use the same shape.
"""

from datetime import datetime

from utils.exceptions import ValidationError

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def now_text() -> str:
    """Return the current local date and time formatted with DATE_FORMAT."""
    return datetime.now().strftime(DATE_FORMAT)


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
