"""Read submission receipts and an explicitly scoped scheduler observation feed."""
import json
import os
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from config import RUN_DIR, resolve_data_path
from src import project_models


STATES = {
    "PENDING": "queued", "CONFIGURING": "queued", "REQUEUED": "queued",
    "RUNNING": "running", "COMPLETING": "finishing", "SUSPENDED": "suspended",
    "COMPLETED": "finished", "CANCELLED": "cancelled", "FAILED": "failed",
    "TIMEOUT": "failed", "OUT_OF_MEMORY": "failed", "NODE_FAIL": "failed",
    "PREEMPTED": "failed", "BOOT_FAIL": "failed", "DEADLINE": "failed",
}
TERMINAL = {"finished", "cancelled", "failed"}


def read_object(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Expected an object")
    return data


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return moment if moment.utcoffset() is not None else None
    except ValueError:
        return None


def project_scopes():
    scopes = {}
    for entry in os.environ.get("AL_TDB_HPC_PROJECTS", "").split(","):
        external, _, local = entry.strip().partition("=")
        if external:
            scopes[external] = "" if local == "@standalone" else local or external
    return scopes


def asset_receipts(scopes):
    path = os.environ.get("AL_TDB_HPC_CATALOG")
    if not path or not scopes:
        return [], "unconfigured"
    rows = []
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            for external, project in scopes.items():
                records = db.execute("""
                    SELECT platform,scheduler_id,status,updated_at FROM jobs
                    WHERE project=? AND platform<>'' AND scheduler_id<>''
                    ORDER BY updated_at
                """, (external,))
                for record in records:
                    state = {"done":"finished", "cancelled":"cancelled", "failed":"failed", "queued":"submitted",
                             "running":"submitted", "submitted":"submitted"}.get(record["status"], "unknown")
                    rows.append(dict(project=project, project_title=external, model=None, model_title="",
                                     config=None, phase="", iteration=None, tasks=None, queue="",
                                     scheduler_id=str(record["scheduler_id"]), platform=record["platform"],
                                     state=state, receipt_at=record["updated_at"], raw="", observed_at=None,
                                     stale=False))
        return rows, "ok"
    except (sqlite3.Error, OSError, ValueError):
        return [], "unavailable"


def observation_feed(now, scopes):
    path = os.environ.get("AL_TDB_HPC_OBSERVATIONS")
    source = {"status": "unconfigured", "observed_at": None}
    if not path or not scopes:
        return source, []
    try:
        feed = read_object(Path(path))
        ttl = int(os.environ.get("AL_TDB_HPC_STALE_SECONDS", "300"))
        at = timestamp(feed.get("observed_at"))
        if not at or ttl <= 0 or not isinstance(feed.get("jobs"), dict):
            raise ValueError("Invalid scheduler observation feed")
        def fresh(moment):
            return moment is not None and -30 <= (now - moment).total_seconds() <= ttl
        rows = []
        for job in feed["jobs"].values():
            if not isinstance(job, dict) or job.get("project") not in scopes:
                continue
            platform, sid = job.get("platform"), job.get("scheduler_id")
            if not platform or sid in (None, ""):
                continue
            observed = timestamp(job.get("observed_at", feed["observed_at"]))
            raw = str(job.get("raw", "")).upper().strip().split("+")[0]
            state = STATES.get(raw, "unknown")
            rows.append(dict(platform=str(platform), scheduler_id=str(sid), state=state,
                             raw=raw if raw in STATES else "", observed_at=observed.isoformat() if observed else None,
                             stale=state not in TERMINAL and not (fresh(at) and fresh(observed)),
                             project=scopes[job["project"]], project_title=job["project"],
                             model=None, model_title="", config=None, iteration=None,
                             phase="", queue=str(job.get("queue") or ""), tasks=None, receipt_at=None))
        return {"status": "ok" if fresh(at) else "stale", "observed_at": at.isoformat()}, rows
    except (OSError, ValueError, TypeError):
        return {"status": "unavailable", "observed_at": None}, []


def model_owners():
    path = resolve_data_path("workbench/catalog.sqlite")
    if not path.is_file():
        return {}
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='models'").fetchone():
            return {}
        rows = db.execute("""
            SELECT m.id AS model, m.title AS model_title, m.project, p.title AS project_title,
                   COALESCE(NULLIF(s.name,''),s.alias) AS phase
            FROM models m JOIN projects p ON p.id=m.project JOIN phases s ON s.id=m.phase
        """)
        return {project_models.filename(row["model"]): dict(row) for row in rows}


def local_receipts(owners):
    rows, seen = [], set()
    skipped = 0
    configs = sorted(RUN_DIR.glob("*.json"), key=lambda p: (p.name not in owners, p.name))
    for config in configs:
        try:
            data = read_object(resolve_data_path(config))
            calculated = data.get("AL_set", {}).get("calced_DFT_path")
            if not calculated:
                continue
            root = resolve_data_path(calculated)
            if root in seen:
                continue
            seen.add(root)
            owner = owners.get(config.name, dict(project="", project_title="独立运行配置",
                               model=None, model_title="", phase=str(data.get("phase_name", ""))))
            for file in root.glob("iter.*/02.fp/dispatch.json"):
                try:
                    iteration = int(file.parents[1].name.split(".")[1])
                    receipt = read_object(resolve_data_path(file))
                    jobs = receipt.get("jobs") or [{}]
                    if not isinstance(jobs, list) or not all(isinstance(job, dict) for job in jobs):
                        raise ValueError("Invalid job receipt")
                    for job in jobs:
                        state = job.get("state")
                        if state not in TERMINAL | {"superseded"}:
                            state = {"finished": "finished", "submitted": "submitted"}.get(receipt.get("status"), "unknown")
                        rows.append(dict(**owner, config=config.name, iteration=iteration,
                                         scheduler_id=str(job.get("id") or ""), platform=receipt.get("platform") or "",
                                         tasks=job.get("tasks", receipt.get("task_count")), queue=receipt.get("queue") or "",
                                         state=state, receipt_at=job.get("receipt_at") or receipt.get("recorded_at"),
                                         observed_at=None, raw="", stale=False))
                except (ValueError, OSError, IndexError):
                    skipped += 1
        except (ValueError, OSError, AttributeError):
            skipped += 1
    return rows, skipped


def snapshot():
    owners = model_owners()
    rows, skipped = local_receipts(owners)
    scopes = project_scopes()
    source, observations = observation_feed(datetime.now(timezone.utc), scopes)
    assets, source["catalog"] = asset_receipts(scopes)
    def identity(job):
        return job["project"], job["platform"], job["scheduler_id"]

    def newest(records, key):
        unique = {}
        for record in records:
            previous = unique.get(identity(record))
            last = timestamp(previous[key]) if previous else None
            when = timestamp(record[key])
            if not last or (when and when >= last):
                unique[identity(record)] = record
        return unique.values()

    receipts = defaultdict(list)
    for job in rows:
        if job["scheduler_id"]:
            receipts[identity(job)].append(job)
    titles = {o["project"]: o["project_title"] for o in owners.values()}
    for asset in newest(assets, "receipt_at"):
        matches = receipts[identity(asset)]
        if not matches:
            asset["project_title"] = titles.get(asset["project"], asset["project_title"])
            matches.append(asset)
            rows.append(asset)
        elif len(matches) == 1 and asset["state"] in TERMINAL:
            job = matches[0]
            recorded, updated = timestamp(job["receipt_at"]), timestamp(asset["receipt_at"])
            if job["state"] != "superseded" and (not recorded or (updated and updated >= recorded)):
                job.update(state=asset["state"], receipt_at=asset["receipt_at"])
    for obs in newest(observations, "observed_at"):
        matches = receipts.get(identity(obs), [])
        if len(matches) == 1:
            job = matches[0]
            recorded, observed = timestamp(job["receipt_at"]), timestamp(obs["observed_at"])
            if job["state"] in TERMINAL | {"superseded"}:
                continue
            if job["config"] and recorded and (not observed or observed < recorded):
                continue
            for field in ("state", "observed_at", "raw", "stale"):
                job[field] = obs[field]
            job["queue"] = job["queue"] or obs["queue"]
        else:
            obs["project_title"] = titles.get(obs["project"], obs["project_title"])
            rows.append(obs)
    return {"source": source, "jobs": rows, "skipped": skipped}
