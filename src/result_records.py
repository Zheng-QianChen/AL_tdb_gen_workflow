"""Per-run SQLite ledger for computation results.

The database at ``record_path/results.sqlite`` is authoritative for training.
``calc.txt`` remains a compatibility export only. Revisions are append-only;
training bindings pin exact id/revision/payload hashes so later edits cannot
silently rewrite already-trained data.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from config import resolve_data_path
from src.workflow import load_config

SCHEMA_VERSION = 1
DB_NAME = "results.sqlite"
ALLOWED_EDITS = frozenset({"energy_ev_cell", "note"})
KNOWN_SOURCE_KINDS = frozenset({
    "vasp", "manual", "synthetic", "external_dataset",
    "legacy_unverified", "manual_override",
})

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


class ResultConflictError(ValueError):
    """Optimistic concurrency failure: expected_revision does not match tip."""


def _utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_dumps(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _json_loads(text):
    return json.loads(text) if text is not None else None


def _payload_hash(payload):
    import hashlib
    return hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()


def _file_lock(path):
    path = str(Path(path).resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[path] = lock
        return lock


def _config_data(config):
    if isinstance(config, dict):
        return config
    _, data = load_config(config)
    return data


def database_path(config):
    data = _config_data(config)
    return resolve_data_path(data["record_path"]) / DB_NAME


def has_database(config):
    return database_path(config).is_file()


def _connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=60, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _ensure_schema(connection):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    row = connection.execute("SELECT value FROM meta WHERE key = ?", ("schema_version",)).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?)", ("schema_version", str(SCHEMA_VERSION)))
    elif int(row["value"]) != SCHEMA_VERSION:
        raise ValueError(f"Unsupported results.sqlite schema version: {row['value']}")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS batches (
            iteration INTEGER PRIMARY KEY,
            source_kind TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            actor TEXT,
            reason TEXT
        )""")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS results (
            id TEXT PRIMARY KEY,
            iteration INTEGER NOT NULL,
            endmember TEXT NOT NULL,
            revision INTEGER NOT NULL,
            energy_ev_cell REAL NOT NULL,
            source_kind TEXT NOT NULL,
            note TEXT NOT NULL,
            analysis_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            modified_at TEXT NOT NULL,
            UNIQUE(iteration, endmember)
        )""")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS revisions (
            record_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            actor TEXT,
            reason TEXT,
            timestamp TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            before_json TEXT,
            after_json TEXT,
            PRIMARY KEY(record_id, revision),
            FOREIGN KEY(record_id) REFERENCES results(id)
        )""")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS training_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            iteration INTEGER NOT NULL,
            checkpoint TEXT NOT NULL,
            bound_at TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            snapshot_hash TEXT NOT NULL,
            UNIQUE(iteration, checkpoint)
        )""")
    connection.execute(
        """CREATE TABLE IF NOT EXISTS calculation_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            iteration INTEGER NOT NULL,
            task_id TEXT NOT NULL,
            endmember TEXT NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            timestamp TEXT NOT NULL,
            analysis_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL
        )""")
    for table in ("revisions", "training_bindings", "calculation_attempts"):
        for action in ("UPDATE", "DELETE"):
            connection.execute(
                f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action} "
                f"BEFORE {action} ON {table} BEGIN "
                "SELECT RAISE(ABORT, 'Audit records are append-only'); END")


@contextmanager
def _locked_db(config, *, write=False):
    path = database_path(config)
    lock = _file_lock(path)
    with lock:
        connection = _connect(path)
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            else:
                connection.execute("BEGIN")
            _ensure_schema(connection)
            yield connection
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()


def _row_to_record(row):
    return {
        "id": row["id"],
        "iteration": int(row["iteration"]),
        "endmember": row["endmember"],
        "revision": int(row["revision"]),
        "energy_ev_cell": float(row["energy_ev_cell"]),
        "source_kind": row["source_kind"],
        "note": row["note"] or "",
        "analysis": _json_loads(row["analysis_json"]) or {},
        "evidence": _json_loads(row["evidence_json"]) or {},
        "modified_at": row["modified_at"],
        "payload_hash": row["payload_hash"],
    }


def _canonical_payload(record):
    return {
        "id": record["id"],
        "iteration": int(record["iteration"]),
        "endmember": record["endmember"],
        "revision": int(record["revision"]),
        "energy_ev_cell": float(record["energy_ev_cell"]),
        "source_kind": record["source_kind"],
        "note": record.get("note") or "",
        "analysis": record.get("analysis") or {},
        "evidence": record.get("evidence") or {},
        "modified_at": record["modified_at"],
    }


def _validate_energy(value):
    try:
        energy = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("energy_ev_cell must be a finite float") from exc
    if not math.isfinite(energy):
        raise ValueError("energy_ev_cell must be a finite float")
    return energy


def _validate_actor_reason(actor, reason):
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("actor is required")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason is required")
    return actor.strip(), reason.strip()


def _record_id(iteration, endmember):
    return f"{int(iteration)}:{endmember}"


def list_results(config, iteration=None):
    """Public listing API. Empty when the database does not exist yet."""
    if not has_database(config):
        return {"records": [], "total": 0}
    if iteration is not None:
        try:
            iteration = int(iteration)
        except (TypeError, ValueError) as exc:
            raise ValueError("iteration must be an integer") from exc
        if iteration < 0:
            raise ValueError("iteration must be nonnegative")
    with _locked_db(config) as connection:
        if iteration is None:
            rows = connection.execute(
                "SELECT * FROM results ORDER BY iteration, endmember").fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM results WHERE iteration = ? ORDER BY endmember",
                (iteration,)).fetchall()
    records = [_row_to_record(row) for row in rows]
    return {"records": records, "total": len(records)}


def result_detail(config, record_id):
    if not isinstance(record_id, str) or not record_id.strip():
        raise ValueError("record_id is required")
    if not has_database(config):
        raise KeyError(record_id)
    with _locked_db(config) as connection:
        row = connection.execute("SELECT * FROM results WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        current = _row_to_record(row)
        history_rows = connection.execute(
            "SELECT * FROM revisions WHERE record_id = ? ORDER BY revision",
            (record_id,)).fetchall()
    history = []
    original = None
    for item in history_rows:
        payload = _json_loads(item["payload_json"])
        entry = {
            "revision": int(item["revision"]),
            "actor": item["actor"],
            "reason": item["reason"],
            "timestamp": item["timestamp"],
            "payload": payload,
            "payload_hash": item["payload_hash"],
            "before": _json_loads(item["before_json"]),
            "after": _json_loads(item["after_json"]),
        }
        history.append(entry)
        if int(item["revision"]) == 0:
            original = payload
    if original is None and history:
        original = history[0]["payload"]
    return {"record": current, "history": history, "original": original}


def revise_result(config, record_id, changes, actor, reason, expected_revision):
    actor, reason = _validate_actor_reason(actor, reason)
    if not isinstance(record_id, str) or not record_id.strip():
        raise ValueError("record_id is required")
    if not isinstance(changes, dict) or not changes:
        raise ValueError("changes must be a non-empty mapping")
    unknown = set(changes) - ALLOWED_EDITS
    if unknown:
        raise ValueError(f"Only energy_ev_cell and note may be edited; rejected: {sorted(unknown)}")
    try:
        expected_revision = int(expected_revision)
    except (TypeError, ValueError) as exc:
        raise ValueError("expected_revision must be an integer") from exc
    if expected_revision < 0:
        raise ValueError("expected_revision must be nonnegative")
    if not has_database(config):
        raise KeyError(record_id)

    with _locked_db(config, write=True) as connection:
        row = connection.execute("SELECT * FROM results WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        current = _row_to_record(row)
        if int(current["revision"]) != expected_revision:
            raise ResultConflictError(
                f"Revision conflict for {record_id}: expected {expected_revision}, "
                f"current {current['revision']}")

        before = {key: current[key] for key in ALLOWED_EDITS}
        before["source_kind"] = current["source_kind"]
        updated = dict(current)
        if "note" in changes:
            note = changes["note"]
            if note is None:
                note = ""
            if not isinstance(note, str):
                raise ValueError("note must be a string")
            updated["note"] = note
        if "energy_ev_cell" in changes:
            energy = _validate_energy(changes["energy_ev_cell"])
            if energy != float(current["energy_ev_cell"]):
                evidence = dict(updated.get("evidence") or {})
                evidence.setdefault("original_source_kind",
                                    evidence.get("original_source_kind")
                                    or (current["source_kind"]
                                        if current["source_kind"] != "manual_override"
                                        else evidence.get("original_source_kind", "manual")))
                evidence.setdefault("original_energy_ev_cell",
                                    evidence.get("original_energy_ev_cell", current["energy_ev_cell"]))
                updated["evidence"] = evidence
                updated["source_kind"] = "manual_override"
            updated["energy_ev_cell"] = energy

        updated["revision"] = int(current["revision"]) + 1
        updated["modified_at"] = _utc_now()
        payload = _canonical_payload(updated)
        digest = _payload_hash(payload)
        after = {key: updated[key] for key in ALLOWED_EDITS}
        after["source_kind"] = updated["source_kind"]

        connection.execute(
            """UPDATE results SET revision = ?, energy_ev_cell = ?, source_kind = ?, note = ?,
               analysis_json = ?, evidence_json = ?, payload_hash = ?, modified_at = ?
               WHERE id = ?""",
            (updated["revision"], updated["energy_ev_cell"], updated["source_kind"], updated["note"],
             _json_dumps(updated["analysis"]), _json_dumps(updated["evidence"]), digest,
             updated["modified_at"], record_id))
        connection.execute(
            """INSERT INTO revisions(record_id, revision, actor, reason, timestamp,
               payload_json, payload_hash, before_json, after_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record_id, updated["revision"], actor, reason, updated["modified_at"],
             _json_dumps(payload), digest, _json_dumps(before), _json_dumps(after)))

    return result_detail(config, record_id)


def batch_exists(config, iteration):
    if not has_database(config):
        return False
    with _locked_db(config) as connection:
        row = connection.execute(
            "SELECT 1 FROM batches WHERE iteration = ?", (int(iteration),)).fetchone()
    return row is not None


def register_batch(config, iteration, records, *, source_kind, actor, reason, evidence=None):
    """Insert an immutable initial batch for one iteration.

    Idempotent when the existing batch payload matches; otherwise refuses replacement.
    """
    actor, reason = _validate_actor_reason(actor, reason)
    try:
        iteration = int(iteration)
    except (TypeError, ValueError) as exc:
        raise ValueError("iteration must be an integer") from exc
    if iteration < 0:
        raise ValueError("iteration must be nonnegative")
    if source_kind not in KNOWN_SOURCE_KINDS or source_kind == "manual_override":
        raise ValueError(f"Invalid registration source_kind: {source_kind}")
    if not isinstance(records, list) or not records:
        raise ValueError("records must be a non-empty list")

    prepared = []
    seen = set()
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            raise ValueError(f"record {index} must be a mapping")
        endmember = str(item.get("endmember", "")).strip().replace("_", ":").upper()
        if not endmember:
            raise ValueError(f"record {index} missing endmember")
        if endmember in seen:
            raise ValueError(f"Duplicate endmember in batch: {endmember}")
        seen.add(endmember)
        energy = _validate_energy(item.get("energy_ev_cell"))
        note = item.get("note") or ""
        if not isinstance(note, str):
            raise ValueError("note must be a string")
        kind = item.get("source_kind") or source_kind
        if kind not in KNOWN_SOURCE_KINDS or kind == "manual_override":
            raise ValueError(f"Invalid source_kind for {endmember}: {kind}")
        analysis = item.get("analysis") or {}
        item_evidence = item.get("evidence") or {}
        if not isinstance(analysis, dict) or not isinstance(item_evidence, dict):
            raise ValueError("analysis and evidence must be mappings")
        record_id = item.get("id") or _record_id(iteration, endmember)
        prepared.append({
            "id": str(record_id),
            "iteration": iteration,
            "endmember": endmember,
            "revision": 0,
            "energy_ev_cell": energy,
            "source_kind": kind,
            "note": note,
            "analysis": analysis,
            "evidence": item_evidence,
        })

    batch_evidence = evidence or {}
    if not isinstance(batch_evidence, dict):
        raise ValueError("evidence must be a mapping")
    stamp = _utc_now()

    with _locked_db(config, write=True) as connection:
        existing = connection.execute(
            "SELECT * FROM batches WHERE iteration = ?", (iteration,)).fetchone()
        if existing is not None:
            current = connection.execute(
                "SELECT v.payload_json FROM revisions v JOIN results r ON r.id=v.record_id "
                "WHERE r.iteration = ? AND v.revision=0 ORDER BY r.endmember",
                (iteration,)).fetchall()
            current_payloads = [_json_loads(row["payload_json"]) for row in current]
            # Compare without modified_at / hash drift for idempotency of content.
            def fingerprint(items):
                return [(r["id"], r["endmember"], r["energy_ev_cell"], r["source_kind"],
                         r["note"], r["analysis"], r["evidence"]) for r in items]
            if fingerprint(current_payloads) == fingerprint(
                    sorted(prepared, key=lambda item: item['endmember'])):
                return {"status": "unchanged", "iteration": iteration, "count": len(prepared)}
            raise ValueError("Results were already published; refusing to replace their provenance")

        connection.execute(
            """INSERT INTO batches(iteration, source_kind, evidence_json, registered_at, actor, reason)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (iteration, source_kind, _json_dumps(batch_evidence), stamp, actor, reason))
        for item in prepared:
            item["modified_at"] = stamp
            payload = _canonical_payload(item)
            digest = _payload_hash(payload)
            connection.execute(
                """INSERT INTO results(id, iteration, endmember, revision, energy_ev_cell, source_kind,
                   note, analysis_json, evidence_json, payload_hash, modified_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item["id"], iteration, item["endmember"], 0, item["energy_ev_cell"],
                 item["source_kind"], item["note"], _json_dumps(item["analysis"]),
                 _json_dumps(item["evidence"]), digest, stamp))
            connection.execute(
                """INSERT INTO revisions(record_id, revision, actor, reason, timestamp,
                   payload_json, payload_hash, before_json, after_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                (item["id"], 0, actor, reason, stamp, _json_dumps(payload), digest,
                 _json_dumps({"energy_ev_cell": item["energy_ev_cell"], "note": item["note"],
                              "source_kind": item["source_kind"]})))
    return {"status": "registered", "iteration": iteration, "count": len(prepared)}


def export_calc_txt(config, iteration, target=None, *, records=None):
    """Write compatibility calc.txt from the authoritative database tip."""
    records = list_results(config, iteration=iteration)["records"] if records is None else records
    if not records:
        raise ValueError("No database results to export for this iteration")
    lines = [f"{row['endmember']},{row['energy_ev_cell']:.17g},{row['energy_ev_cell']:.17g}\n"
             for row in records]
    text = "".join(lines)
    if target is not None:
        from src.storage import atomic_write
        atomic_write(target, text)
    return text


def records_for_training(config, iteration, expected=None, *, checkpoint=None):
    """Return tip records for training. Fail closed if the batch is missing/incomplete."""
    if not has_database(config):
        raise ValueError("No results database; import or collect results before training")
    if not batch_exists(config, iteration):
        raise ValueError(f"No registered result batch for iteration {iteration}")
    listing = list_results(config, iteration=iteration)
    records = listing["records"]
    binding = training_snapshot(config, iteration, checkpoint) if checkpoint else None
    if binding:
        # Recover an interrupted stage from its pinned revisions, even if users
        # have subsequently edited the live records.
        with _locked_db(config) as connection:
            records = []
            for item in binding['records']:
                row = connection.execute(
                    'SELECT payload_json,payload_hash FROM revisions WHERE record_id=? AND revision=?',
                    (item['id'], item['revision'])).fetchone()
                if row is None or row['payload_hash'] != item['payload_hash']:
                    raise ValueError('Archived training revision is missing or changed')
                records.append({**_json_loads(row['payload_json']), 'payload_hash': row['payload_hash']})
    if expected is not None:
        members = [row["endmember"] for row in records]
        if len(members) != len(set(members)):
            raise ValueError("Duplicate endmember results in the current batch")
        if set(members) != set(expected):
            raise ValueError("Results must cover exactly the requested endmembers for this round")
    for row in records:
        _validate_energy(row["energy_ev_cell"])
    return records


def bind_training_snapshot(config, iteration, checkpoint, *, records):
    """Pin the exact result id/revision/hash set consumed when training advances."""
    if not isinstance(checkpoint, str) or not checkpoint.strip():
        raise ValueError("checkpoint name is required")
    if not records or any(row['iteration'] != int(iteration) for row in records):
        raise ValueError("Supply the nonempty record set actually consumed by this iteration")
    records = sorted(records, key=lambda row: row['id'])
    if len({row['id'] for row in records}) != len(records):
        raise ValueError("Duplicate records in training snapshot")
    snapshot = [{
        "id": row["id"],
        "endmember": row["endmember"],
        "revision": row["revision"],
        "payload_hash": row["payload_hash"],
        "energy_ev_cell": row["energy_ev_cell"],
        "source_kind": row["source_kind"],
    } for row in records]
    digest = _payload_hash({"iteration": int(iteration), "checkpoint": checkpoint, "records": snapshot})
    stamp = _utc_now()
    with _locked_db(config, write=True) as connection:
        for row in records:
            revision = connection.execute(
                'SELECT payload_hash FROM revisions WHERE record_id=? AND revision=?',
                (row['id'], row['revision'])).fetchone()
            if (revision is None or revision['payload_hash'] != row['payload_hash']
                    or _payload_hash(_canonical_payload(row)) != row['payload_hash']):
                raise ValueError("Training record does not match its archived revision")
        existing = connection.execute(
            'SELECT * FROM training_bindings WHERE iteration=? AND checkpoint=?',
            (int(iteration), checkpoint)).fetchone()
        if existing is not None:
            if existing['snapshot_hash'] != digest:
                raise ResultConflictError("This checkpoint already pins a different result snapshot")
            stamp = existing['bound_at']
        else:
            connection.execute(
                """INSERT INTO training_bindings(iteration, checkpoint, bound_at, snapshot_json, snapshot_hash)
                   VALUES (?, ?, ?, ?, ?)""",
                (int(iteration), checkpoint, stamp, _json_dumps(snapshot), digest))
    return {"iteration": int(iteration), "checkpoint": checkpoint,
            "records": snapshot, "snapshot_hash": digest, "bound_at": stamp}


def record_attempts(config, iteration, attempts):
    """Append every collection attempt, including failed/incomplete calculations."""
    with _locked_db(config, write=True) as connection:
        for item in attempts:
            if item['status'] not in {'valid', 'invalid'}:
                raise ValueError('Invalid collection status')
            connection.execute(
                'INSERT INTO calculation_attempts(iteration,task_id,endmember,status,error,'
                'timestamp,analysis_json,evidence_json) VALUES (?,?,?,?,?,?,?,?)',
                (int(iteration), item['task_id'], item['endmember'], item['status'],
                 item.get('error'), _utc_now(), _json_dumps(item.get('analysis', {})),
                 _json_dumps(item.get('evidence', {}))))


def list_attempts(config, iteration=None):
    if not has_database(config):
        return {'attempts': [], 'total': 0}
    with _locked_db(config) as connection:
        query = 'SELECT * FROM calculation_attempts'
        args = ()
        if iteration is not None:
            query += ' WHERE iteration=?'
            args = (int(iteration),)
        rows = connection.execute(query + ' ORDER BY id DESC', args).fetchall()
    attempts = [{**{key: row[key] for key in ('id','iteration','task_id','endmember','status','error','timestamp')},
                 'analysis': _json_loads(row['analysis_json']),
                 'evidence': _json_loads(row['evidence_json'])} for row in rows]
    return {'attempts': attempts, 'total': len(attempts)}


def training_snapshot(config, iteration, checkpoint=None):
    if not has_database(config):
        return None
    with _locked_db(config) as connection:
        if checkpoint is None:
            row = connection.execute(
                """SELECT * FROM training_bindings WHERE iteration = ?
                   ORDER BY id DESC LIMIT 1""", (int(iteration),)).fetchone()
        else:
            row = connection.execute(
                """SELECT * FROM training_bindings WHERE iteration = ? AND checkpoint = ?""",
                (int(iteration), checkpoint)).fetchone()
    if row is None:
        return None
    return {
        "iteration": int(row["iteration"]),
        "checkpoint": row["checkpoint"],
        "bound_at": row["bound_at"],
        "snapshot_hash": row["snapshot_hash"],
        "records": _json_loads(row["snapshot_json"]),
    }


def iteration_ready(config, iteration, expected=None):
    """False while the batch is absent; raises if a present batch fails validation."""
    if not has_database(config) or not batch_exists(config, iteration):
        return False
    records_for_training(config, iteration, expected=expected)
    return True


def ingest_legacy_calc(config, iteration, source, *, actor, reason,
                       source_kind="legacy_unverified", expected=None):
    """One-time explicit ingest of a file-only calc.txt before any DB batch exists."""
    actor, reason = _validate_actor_reason(actor, reason)
    if source_kind not in {"legacy_unverified", "manual", "synthetic"}:
        raise ValueError("Legacy ingest source_kind must be legacy_unverified, manual, or synthetic")
    if batch_exists(config, iteration):
        raise ValueError("A database batch already exists; refusing legacy file ingest")
    path = Path(source)
    original = path.read_bytes()
    import hashlib
    evidence_hash = hashlib.sha256(original).hexdigest()
    text = original.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    records = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.strip().split(",")
        if len(parts) != 3:
            raise ValueError(f"calc.txt line {line_number}: expected endmember,DFT_1,DFT_2")
        member = parts[0].strip().replace("_", ":").upper()
        energy = _validate_energy(parts[2])
        # Prefer DFT_2; require both finite and equal-or-use DFT_2 as training value.
        _validate_energy(parts[1])
        records.append({
            "endmember": member,
            "energy_ev_cell": energy,
            "source_kind": source_kind,
            "note": "",
            "analysis": {},
            "evidence": {"legacy_calc_sha256": evidence_hash, "line": line_number},
        })
    if expected is not None and {row["endmember"] for row in records} != set(expected):
        raise ValueError("Results must cover exactly the requested endmembers for this round")
    if path.read_bytes() != original:
        raise ValueError("Results changed during import; finish writing the source first")
    return register_batch(
        config, iteration, records, source_kind=source_kind, actor=actor, reason=reason,
        evidence={"legacy_calc_sha256": evidence_hash, "source": str(path)})
