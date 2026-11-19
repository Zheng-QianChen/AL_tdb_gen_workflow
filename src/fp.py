"""Make/run/post first-principles tasks with DPDispatcher and dpdata."""
from collections import Counter
from datetime import datetime, timezone
import glob
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

import numpy as np
from filelock import FileLock, Timeout

from config import resolve_data_path
from src.fp_settings import load_machine, source_file
from src.run_lock import RunBusyError
from src.storage import atomic_json, atomic_write
from src.workflow import load_config, read_checkpoint


def digest(path):
    path = Path(path)
    value = hashlib.sha256()
    def add_file(file):
        with file.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(block)
    if path.is_dir():
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            if not child.resolve().is_relative_to(path.resolve()):
                raise ValueError("Dataset contains an escaping symlink")
            value.update(child.relative_to(path).as_posix().encode())
            add_file(child)
    else:
        add_file(path)
    return value.hexdigest()


def json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def task_path(base, relative):
    result = (base / relative).resolve()
    if not result.is_relative_to(base.resolve()):
        raise ValueError("Task path escapes its round directory")
    return result


def round_context(config, iteration=None, waiting=False):
    config_path, data = load_config(config)
    state = read_checkpoint(data)
    if state is None:
        raise ValueError("Initialize the run first: python -m altdb run CONFIG")
    iteration = state["iter"] if iteration is None else iteration
    if iteration < 0 or iteration > state["iter"]:
        raise ValueError("Iteration is outside this run")
    if waiting and (iteration != state["iter"] or state["process"] != 1):
        raise ValueError("This operation requires the current waiting-for-DFT stage")
    generated = resolve_data_path(data["AL_set"]["generate_DFT_path"]) / str(iteration)
    calculated = resolve_data_path(data["AL_set"]["calced_DFT_path"]) / f"iter.{iteration:06d}"
    fp = calculated / "02.fp"
    return config_path, data, state, generated, calculated, fp


def round_lock(fp):
    fp.mkdir(parents=True, exist_ok=True)
    return FileLock(str(fp / ".fp.lock"), timeout=0)


def requested_tasks(generated):
    path = generated / "tasks.json"
    if not path.is_file():
        raise ValueError("No task manifest for this round; generate this round using the current version")
    return json.loads(path.read_text(encoding="utf-8"))["tasks"]


def verify_inputs(fp, manifest):
    for task in manifest["tasks"]:
        folder = task_path(fp, task["task_id"])
        for name, expected in task["input_hashes"].items():
            path = task_path(folder, name)
            if not path.is_file() or digest(path) != expected:
                raise ValueError(f"Prepared input changed: {task['task_id']}/{name}")


def prepare(config, machine_file):
    from pymatgen.io.vasp.inputs import Incar, Poscar
    _, data, state, generated, _, fp = round_context(config, waiting=True)
    machine_path, settings = load_machine(machine_file)
    signature = json_hash(settings.model_dump())
    try:
        with round_lock(fp):
            inputs = {name: source_file(machine_path, value).read_bytes()
                      for name, value in settings.input_files.items()}
            incar = Incar.from_str(inputs["INCAR"].decode("utf-8"))
            if "KPOINTS" not in inputs and "KSPACING" not in incar:
                raise ValueError("Supply KPOINTS or specify KSPACING in INCAR")
            tasks, payloads = [], {}
            for task in requested_tasks(generated):
                source = task_path(generated, task["poscar"])
                if digest(source) != task["sha256"]:
                    raise ValueError(f"Generated POSCAR changed for {task['endmember']}")
                poscar = Poscar.from_file(source, check_for_potcar=False)
                if len(poscar.structure) != task["natoms"]:
                    raise ValueError("Generated atom count differs from task manifest")
                potcar = []
                for element in poscar.site_symbols:
                    value = settings.potcars.get(element.upper()) or settings.potcars.get(element)
                    if value is None:
                        raise ValueError(f"No POTCAR configured for {element}")
                    fragment = source_file(machine_path, value).read_bytes()
                    names = re.findall(r"TITEL\s*=\s*\S+\s+([A-Z][a-z]?)(?:_[^\s]+)?", fragment.decode("utf-8"))
                    if names != [element]:
                        raise ValueError(f"POTCAR TITEL must identify one {element} potential")
                    potcar.append(fragment.rstrip() + b"\n")
                files = {**inputs, "POSCAR": source.read_bytes(), "POTCAR": b"".join(potcar)}
                payloads[task["task_id"]] = files
                tasks.append({**task, "composition": dict(Counter(site.specie.symbol for site in poscar.structure)),
                              "input_hashes": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}})
            manifest = {"version": 1, "iteration": state["iter"], "config_hash": json_hash(data),
                        "machine_hash": signature, "result_format": settings.result_format,
                        "result_file": settings.result_file, "tasks": tasks}
            target = fp / "manifest.json"
            if target.exists():
                if json.loads(target.read_text(encoding="utf-8")) != manifest:
                    raise ValueError("Prepared round differs from current inputs/environment; keep the original files or use a new run")
                verify_inputs(fp, manifest)
            else:
                for task_id, files in payloads.items():
                    for name, content in files.items():
                        dest = task_path(fp, f"{task_id}/{name}")
                        if dest.exists() and dest.read_bytes() != content:
                            raise ValueError(f"Refusing to replace existing task input: {dest}")
                        atomic_write(dest, content, binary=True)
                atomic_json(target, manifest)
            return {"status": "prepared", "iteration": state["iter"], "task_count": len(tasks),
                    "directory": str(fp), "manifest": str(target)}
    except Timeout as exc:
        raise RunBusyError("Another FP operation owns this round") from exc


def prepared(config, machine_file=None, iteration=None):
    _, data, state, _, calculated, fp = round_context(config, iteration)
    manifest = json.loads((fp / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("config_hash") != json_hash(data):
        raise ValueError("Prepared tasks belong to a different configuration")
    settings = None
    if machine_file is not None:
        _, settings = load_machine(machine_file)
        if manifest["machine_hash"] != json_hash(settings.model_dump()):
            raise ValueError("Machine configuration changed since prepare")
    verify_inputs(fp, manifest)
    return data, state, calculated, fp, manifest, settings


def save_dispatch(fp, submission, machine_file, plan, status):
    path = fp / "dispatch.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    platform = Path(machine_file).stem
    now = datetime.now(timezone.utc).isoformat()
    jobs = {job["id"]: dict(job) for job in previous.get("jobs", [])}
    for job in submission.belonging_jobs:
        if not job.job_id:
            continue
        sid = str(job.job_id)
        for old in jobs.values():
            if old["id"] != sid and old.get("group") == job.job_hash and old.get("state") == "submitted":
                old["state"] = "superseded"
        state = getattr(job.job_state, "name", "")
        jobs[sid] = dict(id=sid, group=job.job_hash, tasks=len(job.job_task_list),
                         state=state if state in {"finished", "failed"} else "submitted",
                         receipt_at=jobs.get(sid, {}).get("receipt_at", now))
    report = dict(status=status, directory=str(fp), task_count=plan["task_count"],
                  submission_hash=submission.submission_hash, platform=previous.get("platform") or platform,
                  queue=plan["queue"], recorded_at=now, jobs=list(jobs.values()))
    if status == "interrupted_or_failed":
        report["message"] = "Repeat the same dispatch command to recover; remote jobs are not cancelled."
    atomic_json(path, report)
    return report


def dispatch(config, machine_file, *, wait=False, dry_run=False, iteration=None):
    _, _, _, fp, manifest, settings = prepared(config, machine_file, iteration)
    plan = {"status": "planned", "directory": str(fp), "task_count": len(manifest["tasks"]),
            "batch_type": settings.machine["batch_type"], "command": settings.command,
            "queue": settings.resources.get("queue_name"), "connects_to_cluster": not dry_run,
            "tasks": [task["task_id"] for task in manifest["tasks"]]}
    # DPDispatcher dry_run uploads to the machine. Our dry-run never constructs
    # a Machine and is a strictly local plan.
    if dry_run:
        return plan
    try:
        with round_lock(fp):
            from dpdispatcher import Machine, Resources, Submission, Task
            machine_data = {**settings.machine, "local_root": str(fp)}
            machine = Machine.load_from_dict(machine_data)
            resources = Resources.load_from_dict(settings.resources)
            tasks = [Task(command=settings.command, task_work_path=task["task_id"],
                          forward_files=list(task["input_hashes"]),
                          backward_files=settings.backward_files,
                          outlog="stdout.log", errlog="stderr.log") for task in manifest["tasks"]]
            submission = Submission(work_base=str(fp), machine=machine, resources=resources, task_list=tasks)
            try:
                submission.run_submission(exit_on_submit=not wait, clean=False,
                                          check_interval=settings.check_interval)
            except BaseException:
                save_dispatch(fp, submission, machine_file, plan, "interrupted_or_failed")
                raise
            state = "finished" if submission.check_all_finished() else "submitted"
            return save_dispatch(fp, submission, machine_file, plan, state)
    except Timeout as exc:
        raise RunBusyError("Another FP operation owns this round") from exc
    except ImportError as exc:
        raise ImportError("Install requirements-fp.txt to submit FP tasks") from exc


def load_labels(source, fmt, **kwargs):
    import dpdata
    # dpdata 1.1 uses glob(folder + '/set.*') without escaping folder.
    # Keep the process cwd unchanged (Web tasks can be running concurrently).
    if fmt == "deepmd/npy" and glob.has_magic(str(source)):
        with tempfile.TemporaryDirectory(prefix="altdb-labels-") as temp:
            copied = Path(temp) / "dataset"
            shutil.copytree(source, copied)
            return dpdata.LabeledSystem(str(copied), fmt=fmt, **kwargs)
    return dpdata.LabeledSystem(str(source), fmt=fmt, **kwargs)


def read_labels(folder, task, fmt, filename):
    from pymatgen.io.vasp.inputs import Incar
    source = task_path(folder, filename)
    if not source.exists():
        raise ValueError(f"Missing {filename}")
    source_hash = digest(source)
    expected_frames = None
    if fmt == "vasp/outcar":
        expected_frames = 0
        finished = ionic_converged = False
        with source.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                expected_frames += bool(re.search(r"free\s+energy\s+TOTEN\s*=", line))
                finished |= "General timing and accounting" in line
                ionic_converged |= "reached required accuracy" in line
        if not finished:
            raise ValueError("OUTCAR is incomplete (no final timing block)")
        incar = Incar.from_file(folder / "INCAR")
        if int(incar.get("NSW", 0)) > 0 and int(incar.get("IBRION", -1)) != -1:
            if not ionic_converged:
                raise ValueError("Ionic relaxation has not converged")
    raw = load_labels(source, fmt, convergence_check=False)
    if not len(raw):
        raise ValueError("No labeled frames")
    if expected_frames is not None and len(raw) != expected_frames:
        raise ValueError("OUTCAR contains incomplete frames; refusing an earlier valid frame")
    if fmt.startswith("vasp/"):
        final = load_labels(source, fmt, begin=len(raw)-1, convergence_check=True)
        if len(final) != 1:
            raise ValueError("Final VASP frame has not converged")
        if fmt == "vasp/xml":
            from pymatgen.io.vasp.outputs import Vasprun
            xml = Vasprun(source, parse_dos=False, parse_eigen=False, parse_projected_eigen=False, parse_potcar_file=False)
            if not xml.converged:
                raise ValueError("VASP XML reports unconverged calculation")
    else:
        final = raw.sub_system([-1])
    labels = final.data
    composition = {name: int(count) for name, count in zip(labels["atom_names"], labels["atom_numbs"]) if count}
    if composition != task["composition"] or sum(composition.values()) != task["natoms"]:
        raise ValueError("Output species/atom counts disagree with the assigned endmember")
    for name in ("energies", "coords", "cells", "forces", "virials"):
        if name in labels and not np.isfinite(labels[name]).all():
            raise ValueError(f"Nonfinite {name}")
    energy = float(labels["energies"][-1])
    if digest(source) != source_hash:
        raise ValueError("Result changed while being read; synchronize outputs and retry")
    return final, {"endmember": task["endmember"], "task_id": task["task_id"],
                   "energy_ev_cell": energy, "natoms": task["natoms"], "frame": len(raw)-1,
                   "frames_in_source": len(raw), "source": filename, "sha256": source_hash,
                   "format": fmt, "convergence": "checked" if fmt.startswith("vasp/") else "external_dataset"}


def _collect_source_kind(result_format):
    if result_format.startswith("vasp/"):
        return "vasp"
    return "external_dataset"


def collect(config, *, iteration=None):
    from src.result_analysis import analyze_task_directory
    from src.result_records import batch_exists, export_calc_txt, record_attempts, register_batch
    data, state, calculated, fp, manifest, _ = prepared(config, iteration=iteration)
    if manifest["iteration"] != state["iter"] or state["process"] != 1:
        raise ValueError("Collection is only allowed for the current waiting round")
    source_kind = _collect_source_kind(manifest["result_format"])
    try:
        with round_lock(fp):
            records, failures, datasets, ledger, attempts = [], [], [], [], []
            for task in manifest["tasks"]:
                folder = task_path(fp, task["task_id"])
                parsed = {"analysis": {}, "evidence": {}}
                attempt = {'task_id': task['task_id'], 'endmember': task['endmember'], 'status': 'invalid'}
                try:
                    parsed = analyze_task_directory(
                        folder, result_format=manifest['result_format'],
                        result_file=manifest['result_file'], metadata=task)
                    labels, record = read_labels(folder, task,
                                                 manifest["result_format"], manifest["result_file"])
                    if (parsed['evidence'].get('result') is not None
                            and parsed['evidence']['result'] != record['sha256']):
                        raise ValueError('Result changed during analysis; synchronize outputs and retry')
                    parsed['evidence']['collect'] = record
                    records.append(record)
                    datasets.append((labels, task["task_id"]))
                    ledger.append({
                        "endmember": record["endmember"],
                        "energy_ev_cell": record["energy_ev_cell"],
                        "source_kind": source_kind,
                        "note": "",
                        "analysis": parsed["analysis"],
                        "evidence": {**parsed["evidence"],
                                     "task_id": task["task_id"],
                                     "result_format": manifest["result_format"],
                                     "result_sha256": record["sha256"]},
                    })
                    attempt['status'] = 'valid'
                except (ValueError, OSError, KeyError, IndexError, AssertionError, RuntimeError) as exc:
                    failures.append({"task_id": task["task_id"], "endmember": task["endmember"], "error": str(exc)})
                    attempt['error'] = str(exc)
                attempts.append({**attempt, **parsed})
            record_attempts(config, manifest['iteration'], attempts)
            report = {"status": "ready" if not failures else "pending", "iteration": manifest["iteration"],
                      "valid": len(records), "invalid": len(failures), "records": records, "failures": failures,
                      "source_kind": source_kind}
            target = calculated / "calc.txt"
            old_report = fp / "collection.json"
            db_path = str(resolve_data_path(data["record_path"]) / "results.sqlite")
            if batch_exists(config, manifest["iteration"]):
                if failures:
                    raise ValueError("Results were already published; refusing to replace their provenance")
                # Recollection compares immutable initial evidence, preserving
                # any user revisions to the current records.
                register_batch(config, manifest['iteration'], ledger, source_kind=source_kind,
                               actor='fp.collect', reason='verify repeated collection')
                if old_report.exists() and json.loads(old_report.read_text(encoding="utf-8")).get("records") != records:
                    raise ValueError("Results were already published; refusing to replace their provenance")
                export_calc_txt(config, manifest["iteration"], target)
                report["calc_file"] = str(target)
                report["database"] = db_path
                return report
            if target.exists() and not batch_exists(config, manifest["iteration"]):
                raise ValueError("calc.txt exists without a results database; use an explicit import")
            if failures:
                atomic_json(old_report, report)
                return report
            for labels, task_id in datasets:
                labels.to("deepmd/npy", str(fp / "datasets" / task_id))
            _, latest = load_config(config)
            current = read_checkpoint(latest)
            if current["iter"] != manifest["iteration"] or current["process"] != 1:
                raise ValueError("Workflow advanced during collection")
            register_batch(config, manifest["iteration"], ledger, source_kind=source_kind,
                           actor="fp.collect", reason="collect complete batch",
                           evidence={"manifest_iteration": manifest["iteration"],
                                     "config_hash": manifest.get("config_hash"),
                                     "machine_hash": manifest.get("machine_hash")})
            export_calc_txt(config, manifest["iteration"], target)
            atomic_json(old_report, report)
            return {**report, "calc_file": str(target), "database": db_path}
    except Timeout as exc:
        raise RunBusyError("Another FP operation owns this round") from exc
    except ImportError as exc:
        raise ImportError("Install requirements-fp.txt to collect VASP results") from exc


def import_results(config, source, *, source_kind="manual", actor="import-results",
                   reason="explicit one-time import"):
    """Validate a complete calc.txt and register it in the authoritative results database."""
    from src.class_def import Phase
    from src.result_records import export_calc_txt, register_batch
    _, data, state, generated, calculated, fp = round_context(config, waiting=True)
    if source_kind not in {"manual", "synthetic", "legacy_unverified", "external_dataset"}:
        raise ValueError("import source_kind must be manual, synthetic, legacy_unverified, or external_dataset")
    with round_lock(fp):
        path = resolve_data_path(data["AL_set"]["pkl_phase_path"]) / state["checkpoint"]
        phase = Phase.load(path)
        expected = {task["endmember"] for task in requested_tasks(generated)}
        original = Path(source).read_bytes()
        validated = phase.add_calced_points(source, expected, source_kind=source_kind)
        if Path(source).read_bytes() != original:
            raise ValueError("Results changed during import; finish writing the source first")
        evidence_hash = hashlib.sha256(original).hexdigest()
        ledger = [{
            "endmember": member,
            "energy_ev_cell": float(row["DFT_2"]),
            "source_kind": source_kind,
            "note": "",
            "analysis": {},
            "evidence": {"import_sha256": evidence_hash},
        } for member, row in validated.iterrows()]
        target = calculated / "calc.txt"
        register_batch(config, state["iter"], ledger, source_kind=source_kind,
                       actor=actor, reason=reason,
                       evidence={"import_sha256": evidence_hash, "source": str(source)})
        export_calc_txt(config, state["iter"], target)
        atomic_json(fp / "manual_import.json", {
            "source_sha256": evidence_hash, "count": len(ledger), "source_kind": source_kind})
        return {"status": "ready", "count": len(ledger), "calc_file": str(target),
                "source_kind": source_kind,
                "database": str(resolve_data_path(data["record_path"]) / "results.sqlite")}
