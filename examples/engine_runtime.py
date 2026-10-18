"""Explicit local engine configuration and portable subprocess startup."""
import os
from pathlib import Path
import subprocess


def configured_path(variable, *, directory=False):
    value = os.environ.get(variable)
    if not value:
        raise ValueError(f"Set {variable} to your licensed engine installation path")
    path = Path(value).expanduser().resolve()
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError(f"{variable} does not identify an existing {'directory' if directory else 'file'}")
    return path


def thermocalc_home():
    return configured_path("TC26B_HOME", directory=True)


def pandat_executable():
    return configured_path("PANDAT_EXE")


def hidden_startupinfo():
    if os.name != "nt":
        return None
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return startup
