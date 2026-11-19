"""Single-phase model workspaces over the existing per-configuration runner."""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED

from config import resolve_data_path, safe_name
from src.run_lock import RunBusyError, RunLease, is_running
from src.settings import TaskConfig
from src.storage import atomic_json, atomic_write


def root(mid):
    if not re.fullmatch(r"[0-9a-f]{32}", mid):
        raise ValueError("无效的模型标识")
    return f"workbench/models/{mid}"


def filename(mid):
    root(mid)
    return f"model_{mid}.json"


def config_path(mid):
    return resolve_data_path("run/" + filename(mid))


def paths(mid):
    base = root(mid)
    return {"record_path": base + "/record", "structure_out_file": base + "/structure.vasp",
            "generate_DFT_path": base + "/generated", "calced_DFT_path": base + "/calculated",
            "pkl_phase_path": base + "/checkpoints"}


def isolate(data, mid, phase):
    locations = paths(mid)
    data = dict(data, phase_name=phase, record_path=locations["record_path"],
                structure_out_file=locations["structure_out_file"])
    data["AL_set"] = dict(data["AL_set"], **{k: locations[k] for k in
                           ("generate_DFT_path", "calced_DFT_path", "pkl_phase_path")})
    return TaskConfig.model_validate(data).model_dump()


def map_inputs(data, translate):
    data["structure_file"] = translate(data["structure_file"])
    ref = data["tdb_model"]["Atom_ref"]
    ref["file"] = translate(ref["file"])
    data["AL_set"]["descriptor"] = {translate(k): v for k, v in data["AL_set"]["descriptor"].items()}
    return data


def configure(mid, phase, raw, system):
    data = isolate(raw, mid, phase)
    constituents = {s.upper() for site in data["tdb_model"]["comp"] for s in site}
    if constituents - {"VA", *(s.upper() for s in system)}:
        raise ValueError("亚点阵组元超出了该相的适用体系")
    def copy_input(name):
        src = resolve_data_path(name)
        if not src.is_file():
            raise ValueError(f"未找到模型输入文件：{name}")
        raw = src.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        # VASP readers also recognize extensionless names such as POSCAR.
        dest = f"{root(mid)}/inputs/{digest}/{safe_name(src.name)}"
        if not resolve_data_path(dest).exists():
            atomic_write(resolve_data_path(dest), raw, binary=True)
        return dest
    with RunLease(data):
        if (resolve_data_path(data["record_path"]) / "checkpoint.json").exists():
            raise ValueError("该模型已有计算检查点。请新建模型后修改配置。")
        map_inputs(data, copy_input)
        atomic_json(config_path(mid), data)
    return data


def describe(row):
    mid = row["id"]
    record = resolve_data_path(paths(mid)["record_path"])
    state = "待配置"
    if config_path(mid).is_file():
        state = "已配置"
        checkpoint = record / "checkpoint.json"
        if is_running(record):
            state = "运行中"
        elif checkpoint.is_file():
            try:
                data = json.loads(checkpoint.read_text(encoding="utf-8"))
                stage = {0:"选择端元",1:"等待结果",2:"训练",3:"已完成"}.get(data["process"],"已有检查点")
                state = f"第 {data['iter']} 轮 · {stage}"
            except (ValueError, OSError, KeyError, TypeError):
                state = "检查点待复核"
    return dict(row, config=filename(mid), configured=config_path(mid).is_file(), state=state,
                archived=resolve_data_path(root(mid)+"/history.zip").is_file())


def export_files(mid, blob):
    config = config_path(mid)
    if not config.is_file():
        return {}
    def pack_input(name):
        path = resolve_data_path(name)
        if path.parent.parent != resolve_data_path(root(mid) + "/inputs"):
            raise ValueError("模型输入没有归档到本模型")
        return {"digest": blob(path, path.parent.name), "name": path.name}
    # map_inputs also translates dictionary keys, so use filenames as portable tokens.
    inputs = {}
    def token(name):
        key = "/".join(Path(name).parts[-2:])
        inputs[key] = pack_input(name)
        return key
    folder = resolve_data_path(root(mid))
    def inventory():
        files = {}
        for path in folder.rglob("*"):
            relative = path.relative_to(folder)
            key = relative.as_posix()
            if relative.parts[0] == "inputs" or not path.is_file() or key in {
                "record/results.sqlite-shm", "record/results.sqlite-wal", "record/results.sqlite-journal"
            }:
                continue
            if not path.resolve().is_relative_to(folder):
                raise ValueError("模型包含指向目录外的文件")
            stat = path.stat()
            # SQLite's own backup transaction includes WAL changes. Closing its
            # final reader may checkpoint the main file, even for a stable run.
            files[key] = stat.st_ino if key == "record/results.sqlite" else (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        return files

    # A waiting worker holds its lease even when its files are stable. An
    # optimistic snapshot permits export then, and detects a concurrent write.
    before = inventory()
    original = config.read_bytes()
    data = map_inputs(json.loads(original), token)
    bundle = {"config": data, "inputs": inputs, "files": {}}
    for key in before:
        path = folder / key
        if key == "record/results.sqlite":
            with TemporaryDirectory() as tmp:
                copy = Path(tmp) / "results.sqlite"
                with closing(sqlite3.connect(path.as_uri()+"?mode=ro", uri=True)) as src, closing(sqlite3.connect(copy)) as dest:
                    src.backup(dest)
                bundle["files"][key] = blob(copy)
        else:
            bundle["files"][key] = blob(path)
    if before != inventory() or original != config.read_bytes():
        raise RunBusyError("模型文件正在更新")
    return bundle


def restore_files(mid, phase, system, bundle, make_dir, store_blob, cleanup):
    if not bundle:
        return
    folder = make_dir(root(mid))
    inputs = bundle["inputs"]
    def restore_input(key):
        asset = inputs[key]
        name = safe_name(asset["name"])
        digest = asset["digest"]
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("模型输入摘要无效")
        relative = f"{root(mid)}/inputs/{digest}/{name}"
        store_blob(digest, resolve_data_path(relative))
        return relative
    raw = bundle["config"]
    # Rebase all paths before TaskConfig validation on the destination machine.
    data = isolate(map_inputs(raw, restore_input), mid, phase)
    if {s.upper() for site in data["tdb_model"]["comp"] for s in site} - {"VA", *(s.upper() for s in system)}:
        raise ValueError("模型亚点阵组元与适用体系不符")
    # Preserve the original run evidence, including serialized checkpoints, as
    # an inert download. Starting the restored copy creates its own new run.
    files = dict(bundle["files"])
    previous = files.pop("history.zip", None)
    if previous and not files:
        store_blob(previous, folder / "history.zip")
    elif files:
        if previous:
            files["previous-run.zip"] = previous
        with ZipFile(folder / "history.zip", "w", ZIP_DEFLATED) as history:
            for name, digest in files.items():
                parts = name.split("/")
                if any(safe_name(part) != part for part in parts):
                    raise ValueError("历史结果的文件名无效")
                temp = folder / "restore.tmp"
                store_blob(digest, temp)
                history.write(temp, name)
                temp.unlink()
    path = config_path(mid)
    cleanup.callback(path.unlink, missing_ok=True)
    atomic_json(path, data)
