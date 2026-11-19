"""Check a wheel, source tarball or desktop ZIP without extracting its files."""

import argparse
import io
import re
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

PRIVATE_PARTS = {
    "data",
    "research_library",
    "chats",
    ".git",
    ".test-data",
    "uploads",
    "working",
    "validation",
    "parameter_fits",
}
PRIVATE_SUFFIXES = {
    ".sqlite",
    ".sqlite3",
    ".db",
    ".pdf",
    ".bib",
    ".ris",
    ".cif",
    ".tdb",
    ".pem",
    ".key",
    ".log",
    ".xlsx",
    ".csv",
}
SECRETS = re.compile(
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?:ghp_|github_pat_)[a-zA-Z0-9_]{30,}|(?:AKIA|ASIA)[0-9A-Z]{16}"
)
EXAMPLES = {
    "__init__.py",
    "demo.py",
    "gibbs_demo.py",
    "parameter_fit_demo.py",
    "phase_diagram_demo.py",
    "vasp_slurm/INCAR",
}


def check_member(name, data):
    p = PurePosixPath(name.replace("\\", "/"))
    parts = {x.lower() for x in p.parts}
    if (
        p.is_absolute()
        or ".." in parts
        or parts & PRIVATE_PARTS
        or p.suffix.lower() in PRIVATE_SUFFIXES
        or p.name.lower().startswith((".env", "potcar"))
        or p.name in {"OUTCAR", "POSCAR", "vasprun.xml"}
    ):
        raise ValueError(f"Unexpected release file: {p}")
    if "examples" in p.parts:
        relative = "/".join(p.parts[p.parts.index("examples") + 1 :])
        if relative not in EXAMPLES:
            raise ValueError(f"Unexpected packaged example: {p}")
    if SECRETS.search(data):
        raise ValueError(f"Credential-like material in {p}")
    if p.suffix == ".whl":
        with zipfile.ZipFile(io.BytesIO(data)) as wheel:
            return check_zip(wheel)
    return 1


def check_zip(archive):
    return sum(
        check_member(entry.filename, archive.read(entry))
        for entry in archive.infolist()
        if not entry.is_dir()
    )


def audit(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return check_zip(archive)
    with tarfile.open(path, "r:gz") as archive:
        return sum(
            check_member(entry.name, archive.extractfile(entry).read())
            for entry in archive
            if entry.isfile()
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", type=Path, nargs="+")
    for path in parser.parse_args().files:
        print(f"{path.name}: {audit(path)} checked files")
