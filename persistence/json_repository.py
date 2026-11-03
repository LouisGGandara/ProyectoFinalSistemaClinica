"""Reading and writing of the JSON files in UTF-8 (roadmap section 3.11).

It follows the pattern from the JSON class: with open(...) in "r" or "w"
mode, json.load and json.dump with indent=4 and ensure_ascii=False. On top of
that it creates missing files, keeps a copy of damaged ones and saves through
a temporary file, so a failure halfway through never leaves a broken file.

The repository only moves lists of dictionaries. Turning objects into
dictionaries is the job of each model (to_dict and from_dict).
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from utils.exceptions import CorruptedFileError, StorageError


class JsonRepository:
    """Loads and saves lists of dictionaries in the data folder."""

    # Every open() in this class uses this value. On Windows, open() without
    # an encoding falls back to the system code page (usually cp1252), so the
    # files would change encoding depending on the machine that wrote them.
    ENCODING = "utf-8"

    # Date stamp added to the name of the copy of a damaged file.
    BACKUP_DATE_FORMAT = "%Y%m%d-%H%M%S"

    def __init__(self, folder: str = "data") -> None:
        """Keep the data folder and create it if it does not exist."""
        self._folder = Path(folder)
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise StorageError(
                f"No se pudo crear la carpeta de datos «{folder}»."
            ) from error

    def _path(self, filename: str) -> Path:
        """Full path of a file inside the data folder."""
        return self._folder / filename

    def exists(self, filename: str) -> bool:
        """Tell whether the file is already in the data folder."""
        return self._path(filename).is_file()

    def load(self, filename: str) -> list:
        """Read the file and return its list of dictionaries.

        A missing file is created with an empty list and [] is returned.
        A damaged file, or one that is not UTF-8, is copied as
        name.corrupted-YYYYMMDD-HHMMSS.json and CorruptedFileError is raised;
        the manager that called load then starts with an empty list.
        Any other read error becomes StorageError.
        """
        path = self._path(filename)
        try:
            with open(path, "r", encoding=self.ENCODING) as file:
                data = json.load(file)
        except FileNotFoundError:
            # Must come before OSError, because FileNotFoundError is one of
            # its subclasses and would otherwise end up as StorageError.
            self.save(filename, [])
            return []
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            self._backup_corrupted(path)
            raise CorruptedFileError(filename) from error
        except OSError as error:
            raise StorageError(
                f"No se pudo leer el archivo {filename}."
            ) from error

        # Valid JSON that is not a list (for example an object written by
        # hand) is just as unusable for the managers, so it takes the same path.
        if not isinstance(data, list):
            self._backup_corrupted(path)
            raise CorruptedFileError(filename)
        return data

    def save(self, filename: str, data: list) -> None:
        """Write the whole list to the file through a temporary file.

        The data goes first to name.tmp and then os.replace puts it in
        place of the original. If writing fails, the original stays as it
        was. Any OSError is raised again as StorageError.
        """
        path = self._path(filename)
        tmp_path = path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding=self.ENCODING) as file:
                json.dump(data, file, indent=4, ensure_ascii=False)
            os.replace(tmp_path, path)
        except OSError as error:
            self._discard(tmp_path)
            raise StorageError() from error
        except (TypeError, ValueError):
            # Data that json cannot write is a bug in the caller, not a
            # storage problem, so it keeps its own type. The temporary file
            # is removed so it does not stay half written in the folder.
            self._discard(tmp_path)
            raise

    def _backup_corrupted(self, path: Path) -> None:
        """Copy a damaged file next to it, byte for byte.

        The copy keeps the original bytes untouched, even when they are not
        UTF-8, so the file can still be repaired by hand later.
        """
        stamp = datetime.now().strftime(self.BACKUP_DATE_FORMAT)
        backup = path.with_name(f"{path.stem}.corrupted-{stamp}.json")
        try:
            shutil.copy2(path, backup)
        except OSError as error:
            # Without a copy, the next save would overwrite the only version
            # of the data, so the user has to hear about it.
            raise StorageError(
                f"El archivo {path.name} está dañado y no se pudo guardar "
                "una copia. Revisa la carpeta de datos antes de seguir."
            ) from error

    @staticmethod
    def _discard(path: Path) -> None:
        """Delete a leftover temporary file, if there is one."""
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # A temporary file that cannot be deleted does no harm: the
            # next save overwrites it.
            pass
