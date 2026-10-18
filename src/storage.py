"""Atomic writes for configuration, model checkpoints and checkpoint pointers."""
import json
import os
import tempfile
from pathlib import Path


def atomic_write(path, data, binary=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb" if binary else "w", **({} if binary else {"encoding": "utf-8"})) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path, value):
    atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))
