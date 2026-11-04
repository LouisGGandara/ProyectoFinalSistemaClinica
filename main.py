"""Entry point of the clinic ticket system.

Run it from PyCharm or with: python main.py
"""

from pathlib import Path

from ui.app import App

# The data folder and errors.log are found from this file, not from the
# folder the program was started in. That way the JSON files are always the
# ones inside the project, even if PyCharm's working directory changes.
BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
    """Create the window and start the event loop."""
    app = App(data_folder=str(BASE_DIR / "data"), log_path=BASE_DIR / "errors.log")
    app.mainloop()


if __name__ == "__main__":
    main()
