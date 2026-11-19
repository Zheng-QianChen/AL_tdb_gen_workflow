"""Inspect the committed tree that GitHub will serve as its source archive."""
import argparse
from pathlib import PurePosixPath
import re
import subprocess

from check_release_contents import PRIVATE_PARTS, PRIVATE_SUFFIXES, SECRETS

ROOTS = {"src", "altdb", "routes", "static", "docs", "examples", "tools", "tests", ".github"}
ROOT_FILES = {
    ".gitattributes", ".gitignore", "AGENTS.md", "LICENSE", "MANIFEST.in", "README.md",
    "Start-AL-TDB.cmd", "Start-AL-TDB.command", "Start-AL-TDB.sh", "app.py", "config.py",
    "constraints-test.txt", "environment.yml", "local_server.py", "main.py", "pyproject.toml",
    "pytest.ini", "setup.py", "requirements-cross-engine.txt", "requirements-dev.txt",
    "requirements-fp.txt", "requirements-terminal.txt", "requirements-thermo.txt", "requirements.txt",
}
FORBIDDEN = PRIVATE_SUFFIXES | {
    ".jsonl", ".parquet", ".h5", ".pkl", ".npz", ".tsv", ".exp", ".zip", ".whl", ".gz",
}
MACHINE_PATH = re.compile(rb"(?:[A-Z]:[/\\](?:Users|Documents and Settings)[/\\]|/home/[^/\s]+/\.ssh/)", re.I)


def check(revision):
    tree = subprocess.check_output(["git", "ls-tree", "-rz", revision])
    paths = []
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, kind, oid = header.split()
        path = PurePosixPath(name.decode())
        if (kind != b"blob" or mode not in {b"100644", b"100755"} or
                (path.parts[0] not in ROOTS and str(path) not in ROOT_FILES) or
                any(p.lower() in PRIVATE_PARTS for p in path.parts) or
                path.suffix.lower() in FORBIDDEN or path.name.lower().startswith((".env", "potcar")) or
                path.name in {"OUTCAR", "POSCAR", "CONTCAR", "WAVECAR", "CHGCAR", "vasprun.xml"}):
            raise ValueError(f"Unexpected tracked path: {path}")
        paths.append((oid, path))
    # Read blobs from the selected revision; untracked local datasets never enter this check.
    with subprocess.Popen(["git","cat-file","--batch"],stdin=subprocess.PIPE,stdout=subprocess.PIPE) as git:
        for oid, path in paths:
            git.stdin.write(oid+b"\n")
            git.stdin.flush()
            _, kind, size = git.stdout.readline().split()
            blob = git.stdout.read(int(size))
            if git.stdout.read(1) != b"\n" or kind != b"blob":
                raise RuntimeError("Invalid Git object stream")
            if SECRETS.search(blob) or MACHINE_PATH.search(blob) or blob.startswith((b"%PDF-", b"SQLite format 3\0")):
                git.stdin.close()
                raise ValueError(f"Review contents of {path}")
        git.stdin.close()
    if git.returncode:
        raise RuntimeError("Git could not read this revision")
    return len(paths)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("revision", nargs="?", default="HEAD")
    print(f"{check(parser.parse_args().revision)} public source files checked")
