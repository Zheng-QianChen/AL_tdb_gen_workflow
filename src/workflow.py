"""Filesystem API used by automation and terminal interfaces."""
import json
import hashlib
from pathlib import Path
from config import RUN_DIR, resolve_data_path
from src.settings import TaskConfig
from src.run_lock import is_running

STAGES = {0: "selecting", 1: "waiting", 2: "training", 3: "completed"}


def input_hashes(data):
    sources = [data["structure_file"], data["tdb_model"]["Atom_ref"]["file"],
               *data["AL_set"]["descriptor"]]
    return {source: hashlib.sha256(resolve_data_path(source).read_bytes()).hexdigest()
            for source in sources}


def load_config(path):
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        candidate = RUN_DIR / (str(path) if str(path).endswith(".json") else str(path) + ".json")
    candidate = candidate.resolve()
    data = TaskConfig.model_validate_json(candidate.read_text(encoding="utf-8")).model_dump()
    return candidate, data


def read_checkpoint(data):
    path = resolve_data_path(data["record_path"]) / "checkpoint.json"
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("version") != 2 or state.get("config") != data:
        raise ValueError("Configuration differs from checkpoint; use a new run directory")
    if state.get("process") not in STAGES or state.get("iter", -1) < 0:
        raise ValueError("Invalid checkpoint manifest")
    if state.get("input_hashes") != input_hashes(data):
        raise ValueError("Input files changed since the checkpoint")
    name = f"model_{state['iter']:06d}_{state['process']}.pd"
    if state.get("checkpoint") != name or not (resolve_data_path(data["AL_set"]["pkl_phase_path"]) / name).is_file():
        raise ValueError("Checkpoint file is missing or invalid")
    return state


def status(path):
    path, data = load_config(path)
    state = read_checkpoint(data)
    record = resolve_data_path(data["record_path"])
    result = {"config": str(path), "phase": data["phase_name"],
              "status": "new" if state is None else STAGES[state["process"]],
              "iteration": 0 if state is None else state["iter"],
              "process": None if state is None else state["process"],
              "running": is_running(record), "record_path": str(record), "tasks": []}
    if state:
        iteration = state["iter"]
        generated = resolve_data_path(data["AL_set"]["generate_DFT_path"]) / str(iteration)
        manifest = generated / "tasks.json"
        result["tasks"] = json.loads(manifest.read_text(encoding="utf-8"))["tasks"] if manifest.exists() else []
        round_dir = resolve_data_path(data["AL_set"]["calced_DFT_path"]) / f"iter.{iteration:06d}"
        result["calc_file"] = str(round_dir / "calc.txt")
        result["results_ready"] = (round_dir / "calc.txt").is_file()
        for key, filename in (("fp", "manifest.json"), ("collection", "collection.json"), ("dispatch", "dispatch.json")):
            info = round_dir / "02.fp" / filename
            if info.exists():
                result[key] = json.loads(info.read_text(encoding="utf-8"))
    return result
