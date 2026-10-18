"""Cross-process ownership shared by Web, CLI and TUI."""
import hashlib
import json
import os
from pathlib import Path
from filelock import FileLock, Timeout
from config import BASE_DATA_DIR, resolve_data_path
from src.storage import atomic_json


class RunBusyError(ValueError):
    pass


def output_paths(data):
    return [resolve_data_path(data["record_path"]),
            resolve_data_path(data["structure_out_file"]),
            *(resolve_data_path(data["AL_set"][key]) for key in
              ("generate_DFT_path", "calced_DFT_path", "pkl_phase_path"))]


def lock_for(record):
    folder = BASE_DATA_DIR / ".locks"
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(str(Path(record).resolve()).casefold().encode()).hexdigest()
    return FileLock(str(folder / (digest + ".lock")), timeout=0)


def is_running(record):
    lock = lock_for(record)
    try:
        lock.acquire()
    except Timeout:
        return True
    else:
        lock.release()
        return False


class RunLease:
    def __init__(self, data):
        self.paths = output_paths(data)
        self.record = resolve_data_path(data["record_path"])
        self.lock = lock_for(self.record)

    def acquire(self):
        folder = BASE_DATA_DIR / ".locks"
        with FileLock(str(folder / "registry.lock"), timeout=5):
            registry = folder / "owners.json"
            entries = json.loads(registry.read_text(encoding="utf-8")) if registry.exists() else []
            active = [entry for entry in entries if is_running(entry["record"])]
            for entry in active:
                for left in self.paths:
                    for value in entry["outputs"]:
                        right = Path(value)
                        if left.is_relative_to(right) or right.is_relative_to(left):
                            raise RunBusyError(f"Output is owned by another process: {entry['record']}")
            try:
                self.lock.acquire()
            except Timeout as exc:
                raise RunBusyError(f"Run is already active: {self.record}") from exc
            try:
                atomic_json(registry, [*active, {"record": str(self.record),
                    "outputs": [str(p) for p in self.paths], "pid": os.getpid()}])
            except BaseException:
                self.lock.release()
                raise
        return self

    def release(self):
        self.lock.release()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.release()
