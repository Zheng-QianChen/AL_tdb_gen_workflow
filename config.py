"""Application paths are independent of the shell's working directory."""
import logging
import os
from pathlib import Path

logger = logging.getLogger("al_tdb")
PROJECT_ROOT = Path(__file__).resolve().parent
STATIC_DIR = PROJECT_ROOT / "static"
if STATIC_DIR.is_dir():
    DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
else:
    # Wheel assets live with the package; mutable runs belong to the user.
    from altdb import __file__ as package_file
    STATIC_DIR = Path(package_file).resolve().parent / "web_assets"
    DEFAULT_DATA_DIR = Path.home() / ".altdb" / "data"
BASE_DATA_DIR = Path(os.environ.get("AL_TDB_DATA_DIR", DEFAULT_DATA_DIR)).resolve()
UPLOAD_DIR = BASE_DATA_DIR / "uploads"
RUN_DIR = BASE_DATA_DIR / "run"
WORKING_DIR = BASE_DATA_DIR / "Phase_data"
ALLOWED_BASE_DIR = BASE_DATA_DIR
HOST = os.environ.get("AL_TDB_HOST", "127.0.0.1")
PORT = int(os.environ.get("AL_TDB_PORT", "8003"))


def safe_name(value):
    value = str(value).strip()
    if not value or value in {".", ".."} or any(c in value for c in '/\\:\x00'):
        raise ValueError("Expected a filename or task name without path separators")
    if value.endswith((".", " ")):
        raise ValueError("Invalid filename suffix")
    stem = value.split(".")[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        raise ValueError("Reserved filename")
    return value


def resolve_data_path(value):
    """Accept data-relative paths and old data/... paths, but never escape data/."""
    text = str(value).replace("\\", "/")
    if text.startswith("/get_data_file/"):
        text = text[len("/get_data_file/"):]
    if text.startswith("data/"):
        text = text[5:]
    path = Path(text)
    target = (path if path.is_absolute() else BASE_DATA_DIR / path).resolve()
    if not target.is_relative_to(BASE_DATA_DIR):
        raise ValueError("Path must stay within the application data directory")
    return target
