"""Project-owned literature, names and observations, with reusable structure objects."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from pymatgen.core import Element, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
from config import resolve_data_path
from src import project_models

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, title TEXT NOT NULL, elements TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS papers(id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects, title TEXT NOT NULL, citation TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '', systems TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS attachments(id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects, paper TEXT NOT NULL REFERENCES papers, name TEXT NOT NULL, digest TEXT NOT NULL, UNIQUE(project,paper,digest));
CREATE TABLE IF NOT EXISTS phases(id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects, alias TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', system TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS models(id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects, phase TEXT NOT NULL REFERENCES phases, title TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects, paper TEXT NOT NULL REFERENCES papers,
 phase TEXT REFERENCES phases, locator TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS structures(id TEXT PRIMARY KEY, owner TEXT REFERENCES projects, system TEXT NOT NULL, formula TEXT NOT NULL, sg TEXT NOT NULL, source TEXT NOT NULL, ref TEXT NOT NULL, geometry TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS inputs(id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects, paper TEXT REFERENCES papers, name TEXT NOT NULL, digest TEXT NOT NULL, UNIQUE(project,name,digest));
CREATE TABLE IF NOT EXISTS links(phase TEXT NOT NULL REFERENCES phases, structure TEXT NOT NULL REFERENCES structures, PRIMARY KEY(phase,structure));
CREATE TABLE IF NOT EXISTS revisions(id INTEGER PRIMARY KEY, project TEXT NOT NULL REFERENCES projects, entity TEXT NOT NULL, at TEXT NOT NULL, before TEXT NOT NULL, after TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fits(id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects, candidate TEXT NOT NULL, summary TEXT NOT NULL);
"""


def pack(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def uid():
    return uuid4().hex


def symbols(items):
    result = [str(v).strip().capitalize() for v in items]
    if (
        not result
        or len(set(result)) != len(result)
        or any(not Element.is_valid_symbol(el) for el in result)
    ):
        raise ValueError("请使用有效且不重复的元素符号")
    return sorted(result)


@contextmanager
def catalog():
    file = resolve_data_path("workbench/catalog.sqlite")
    file.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(file, timeout=20)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(SCHEMA)
        def requires_phase():
            return any(c["name"] == "phase" and c["notnull"]
                       for c in db.execute("PRAGMA table_info(observations)"))
        # Historical catalogs required one phase even for an unresolved multi-phase sample.
        # Recheck under the write lock so concurrent first requests only migrate once.
        if requires_phase():
            with db:
                db.execute("BEGIN IMMEDIATE")
                if requires_phase():
                    db.execute("ALTER TABLE observations RENAME TO observations_old")
                    ddl = next(q for q in SCHEMA.split(";") if "EXISTS observations(" in q)
                    db.execute(ddl)
                    db.execute("INSERT INTO observations SELECT * FROM observations_old ORDER BY rowid")
                    db.execute("DROP TABLE observations_old")
        if "notes" not in {r[1] for r in db.execute("PRAGMA table_info(papers)")}:
            with db:
                db.execute("BEGIN IMMEDIATE")
                if "notes" not in {r[1] for r in db.execute("PRAGMA table_info(papers)")}:
                    db.execute("ALTER TABLE papers ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
                    db.execute("ALTER TABLE papers ADD COLUMN systems TEXT NOT NULL DEFAULT '[]'")
        with db:
            yield db
    finally:
        db.close()


def project(db, pid):
    row = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if not row:
        raise KeyError("项目不存在")
    return dict(row) | {"elements": json.loads(row["elements"])}


def owned(db, table, pid, rid):
    row = db.execute(
        f"SELECT * FROM {table} WHERE project=? AND id=?", (pid, rid)
    ).fetchone()
    if not row:
        raise KeyError("条目不属于当前项目")
    return dict(row)


def checked_system(db, pid, items):
    system = symbols(items)
    if not set(system) <= set(project(db, pid)["elements"]):
        raise ValueError("体系包含当前项目以外的元素")
    return system


def revision(db, pid, entity, before, after):
    db.execute(
        "INSERT INTO revisions(project,entity,at,before,after) VALUES(?,?,?,?,?)",
        (
            pid,
            entity,
            datetime.now(timezone.utc).isoformat(),
            pack(before),
            pack(after),
        ),
    )


def observation_payload(db, pid, raw):
    payload = json.loads(raw)
    for target, rid in zip(payload.get("phases", []), payload.pop("_phase_ids", [])):
        if rid:
            phase = owned(db, "phases", pid, rid)
            target["phase"] = phase["name"] or phase["alias"]
    return payload


def models(db, pid):
    return [project_models.describe(r) for r in db.execute(
        "SELECT * FROM models WHERE project=? ORDER BY rowid", (pid,))]


def snapshot(db, pid):
    result = project(db, pid)
    result["models"] = models(db, pid)
    for table in (
        "phases",
        "papers",
        "attachments",
        "observations",
        "inputs",
        "fits",
        "revisions",
    ):
        result[table] = [
            dict(r)
            for r in db.execute(
                f"SELECT * FROM {table} WHERE project=? ORDER BY rowid", (pid,)
            )
        ]
    for row in result["observations"]:
        row["payload"] = observation_payload(db, pid, row["payload"])
    for row in result["phases"]:
        row["system"] = json.loads(row["system"])
    for row in result["papers"]:
        row["systems"] = json.loads(row["systems"])
    for row in result["fits"]:
        row["summary"] = json.loads(row["summary"])
    result["structures"] = []
    for r in db.execute(
        "SELECT id,owner,system,formula,sg,source,ref FROM structures WHERE owner IS NULL OR owner=? ORDER BY rowid",
        (pid,),
    ):
        parts = json.loads(r["system"])
        if set(parts) <= set(result["elements"]):
            result["structures"].append(dict(r) | {"system": parts})
    result["links"] = [
        dict(r)
        for r in db.execute(
            "SELECT phase,structure FROM links JOIN phases ON phases.id=links.phase WHERE project=?",
            (pid,),
        )
    ]
    return result


def save_geometry(db, pid, structure, source, ref, shared=True):
    parts = checked_system(
        db, pid, [el.symbol for el in structure.composition.elements]
    )
    geom = pack(structure.as_dict())
    owner = None if shared else pid
    identifier = hashlib.sha256(pack([owner, source, ref, geom]).encode()).hexdigest()
    symmetry = SpacegroupAnalyzer(structure, symprec=0.001)
    sg = f"{symmetry.get_space_group_symbol()} (#{symmetry.get_space_group_number()})"
    db.execute(
        "INSERT OR IGNORE INTO structures VALUES(?,?,?,?,?,?,?,?)",
        (
            identifier,
            owner,
            pack(parts),
            structure.composition.reduced_formula,
            sg,
            source,
            ref,
            geom,
        ),
    )
    return identifier


def attach(db, pid, phase_id, sid):
    phase = owned(db, "phases", pid, phase_id)
    row = db.execute(
        "SELECT system FROM structures WHERE id=? AND (owner IS NULL OR owner=?)",
        (sid, pid),
    ).fetchone()
    if not row or not set(json.loads(row["system"])) <= set(
        json.loads(phase["system"])
    ):
        raise ValueError("结构元素不属于该相的体系")
    db.execute("INSERT OR IGNORE INTO links VALUES(?,?)", (phase_id, sid))


def read_structure(db, pid, sid):
    row = db.execute(
        "SELECT * FROM structures WHERE id=? AND (owner IS NULL OR owner=?)", (sid, pid)
    ).fetchone()
    if not row:
        raise KeyError("结构不存在")
    checked_system(db, pid, json.loads(row["system"]))
    return row, Structure.from_dict(json.loads(row["geometry"]))


def cell_description(structure):
    occupied = SpacegroupAnalyzer(structure, symprec=0.001)
    skeleton = Structure(
        structure.lattice, ["H"] * len(structure), structure.frac_coords
    )
    bare = SpacegroupAnalyzer(skeleton, symprec=0.001)
    a, b = occupied.find_primitive(), bare.find_primitive()
    return {
        "带占位空间群": occupied.get_space_group_symbol(),
        "点集空间群": bare.get_space_group_symbol(),
        "输入晶胞位置数": len(structure),
        "化学原胞位置数": len(a),
        "骨架原胞位置数": len(b),
        "输入晶胞重复数": len(structure) // len(a),
        "原胞平移指数": len(a) // len(b),
    }
