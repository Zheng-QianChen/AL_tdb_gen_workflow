"""Persistent, local project workbench. Mutations name the project explicitly."""

from contextlib import contextmanager, ExitStack
import shutil
from typing import Literal
import hashlib
import json
import os

import requests
from fastapi import APIRouter, Form as FormField, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from pymatgen.core import Structure
from config import STATIC_DIR, resolve_data_path, safe_name
from src import project_archive
from src import experiment_table
from src import project_models
from src.run_lock import RunBusyError
from src import project_catalog as cat
from src.parameter_fit_settings import FitParameter, ParameterFitRequest
from src.storage import atomic_write
from src.structure_sources import fetch_structures

router = APIRouter()


@contextmanager
def session():
    try:
        with cat.catalog() as db:
            yield db
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


class Form(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )


class Project(Form):
    title: str = Field(min_length=1, max_length=120)
    elements: list[str] = Field(min_length=1, max_length=118)


class Phase(Form):
    alias: str = Field(min_length=1, max_length=120)
    name: str = Field(default="", pattern=r"^(?:[A-Za-z][A-Za-z0-9_]{0,39})?$")
    system: list[str] = Field(min_length=1)


class SavedProject(Project):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")


class SinglePhaseModel(Form):
    title: str = Field(min_length=1, max_length=120)
    phase: str
    template: str | None = None


class Paper(Form):
    title: str = Field(min_length=1, max_length=400)
    citation: str = Field(min_length=1, max_length=1500)
    notes: str = Field(default="", max_length=120000)
    systems: list[list[str]] = Field(default_factory=list, max_length=250)


class Observation(Form):
    paper: str
    phase: str | None = None
    locator: str = Field(min_length=1, max_length=500)
    payload: dict


class Input(Form):
    name: str = Field(min_length=1, max_length=140)
    text: str = Field(min_length=1, max_length=20000000)
    paper: str | None = None


class Geometry(Form):
    ref: str = Field(min_length=1, max_length=200)
    cif: str = Field(min_length=1, max_length=4000000)
    shared: bool = False


class Link(Form):
    structure: str
    phase: str


class Query(Form):
    provider: Literal["mp", "oqmd"]
    elements: list[str]
    offset: int = Field(default=0, ge=0, le=100000)


class Fit(Form):
    inputs: list[str] = Field(min_length=1, max_length=10)
    observations: list[str] = Field(min_length=1, max_length=200)
    parameters: list[FitParameter] = Field(min_length=1, max_length=12)
    phases: list[str] = Field(min_length=1)
    components: list[str] = Field(min_length=2, max_length=8)


@router.get("/projects")
def workbench():
    return FileResponse(STATIC_DIR / "projects.html")


@router.get("/api/projects")
def list_projects():
    with session() as db:
        return [
            cat.project(db, r[0])
            for r in db.execute("SELECT id FROM projects ORDER BY rowid")
        ]


@router.post("/api/projects", status_code=201)
def create_project(data: Project):
    with session() as db:
        pid = cat.uid()
        db.execute(
            "INSERT INTO projects VALUES(?,?,?)",
            (pid, data.title, cat.pack(cat.symbols(data.elements))),
        )
        return cat.project(db, pid)


@router.get("/api/projects/{pid}")
def open_project(pid: str):
    with session() as db:
        from src.fit_adapter import ADAPTER_ENV

        return cat.snapshot(db, pid) | {
            "executors": {k: bool(os.getenv(v)) for k, v in ADAPTER_ENV.items()}
        }


@router.post("/api/projects/{pid}/models", status_code=201)
def create_model(pid: str, data: SinglePhaseModel):
    with ExitStack() as rollback:
        with session() as db:
            phase = cat.owned(db, "phases", pid, data.phase)
            result = save(db, "models", pid, {"title": data.title, "phase": data.phase})
            if data.template:
                source = cat.owned(db, "models", pid, data.template)
                config = project_models.config_path(source["id"])
                if source["phase"] != data.phase or not config.is_file():
                    raise ValueError("请选择同一相的已配置模型作为起点")
                mid = result["id"]
                rollback.callback(shutil.rmtree, resolve_data_path(project_models.root(mid)), ignore_errors=True)
                rollback.callback(project_models.config_path(mid).unlink, missing_ok=True)
                project_models.configure(mid, phase["name"] or phase["alias"],
                                         json.loads(config.read_text(encoding="utf-8")), json.loads(phase["system"]))
        rollback.pop_all()
        return result


@router.get("/api/projects/{pid}/models/{mid}")
def model_detail(pid: str, mid: str):
    with session() as db:
        row = cat.owned(db, "models", pid, mid)
        phase = cat.owned(db, "phases", pid, row["phase"])
        return project_models.describe(row) | {"phaseLabel": phase["name"] or phase["alias"], "elements": json.loads(phase["system"]),
                                                "paths": project_models.paths(mid)}


@router.get("/api/projects/{pid}/models")
def list_models(pid: str):
    with session() as db:
        cat.project(db, pid)
        return cat.models(db, pid)


@router.put("/api/projects/{pid}/models/{mid}/config")
def configure_model(pid: str, mid: str, data: dict):
    with session() as db:
        row = cat.owned(db, "models", pid, mid)
        phase = cat.owned(db, "phases", pid, row["phase"])
        project_models.configure(mid, phase["name"] or phase["alias"], data, json.loads(phase["system"]))
        return {"success": True, "config": project_models.filename(mid)}


@router.get("/api/projects/{pid}/models/{mid}/history")
def model_history(pid: str, mid: str):
    with session() as db:
        cat.owned(db, "models", pid, mid)
        path = resolve_data_path(project_models.root(mid) + "/history.zip")
        if not path.is_file():
            raise HTTPException(404, "没有历史运行包")
        return FileResponse(path, filename="model-run.zip")


@router.patch("/api/projects/{pid}")
def extend_project(pid: str, data: Project):
    with session() as db:
        db.execute("BEGIN IMMEDIATE")
        before = cat.project(db, pid)
        elements = cat.symbols(data.elements)
        if not set(before["elements"]) <= set(elements):
            raise ValueError("请保留项目中已有的元素")
        db.execute(
            "UPDATE projects SET title=?,elements=? WHERE id=?",
            (data.title, cat.pack(elements), pid),
        )
        result = cat.project(db, pid)
        cat.revision(db, pid, pid, before, result)
        return result


def save(db, table, pid, fields, rid=None):
    cat.project(db, pid)
    if rid:
        before = cat.owned(db, table, pid, rid)
        db.execute(
            f"UPDATE {table} SET "
            + ",".join(k + "=?" for k in fields)
            + " WHERE project=? AND id=?",
            (*fields.values(), pid, rid),
        )
    else:
        rid = cat.uid()
        before = None
        db.execute(
            f"INSERT INTO {table}(id,project,"
            + ",".join(fields)
            + ") VALUES("
            + ",".join("?" for _ in range(2 + len(fields)))
            + ")",
            (rid, pid, *fields.values()),
        )
    cat.revision(db, pid, rid, before, cat.owned(db, table, pid, rid))
    return {"id": rid}


@router.post("/api/projects/{pid}/phases")
@router.put("/api/projects/{pid}/phases/{rid}")
def phase(pid: str, data: Phase, rid: str | None = None):
    with session() as db:
        system = cat.checked_system(db, pid, data.system)
        if rid:
            old = cat.owned(db, "phases", pid, rid)
            if set(json.loads(old["system"])) - set(system):
                raise ValueError("已有相记录的适用元素只能扩展；不同体系可另建候选")
        return save(
            db,
            "phases",
            pid,
            {
                "alias": data.alias,
                "name": data.name.upper(),
                "system": cat.pack(system),
            },
            rid,
        )


@router.post("/api/projects/{pid}/papers")
@router.put("/api/projects/{pid}/papers/{rid}")
def paper(pid: str, data: Paper, rid: str | None = None):
    with session() as db:
        fields = data.model_dump(exclude_unset=True)
        if "systems" in fields:
            fields["systems"] = cat.pack([cat.checked_system(db, pid, s) for s in data.systems])
        return save(db, "papers", pid, fields, rid)


@router.post("/api/projects/{pid}/papers/{rid}/pdf")
def add_pdf(pid: str, rid: str, file: UploadFile):
    with session() as db:
        cat.owned(db, "papers", pid, rid)
        raw = file.file.read(50 * 1024 * 1024 + 1)
        if len(raw) > 50 * 1024 * 1024 or not raw.startswith(b"%PDF-"):
            raise ValueError("请选择不超过 50 MiB 的 PDF")
        name = safe_name(file.filename or "paper.pdf")
        digest = hashlib.sha256(raw).hexdigest()
        atomic_write(
            resolve_data_path(f"workbench/papers/{pid}/{digest}.pdf"), raw, binary=True
        )
        db.execute(
            "INSERT OR IGNORE INTO attachments VALUES(?,?,?,?,?)",
            (cat.uid(), pid, rid, name, digest),
        )
        return {"sha256": digest}


@router.get("/api/projects/{pid}/pdf/{rid}")
def pdf(pid: str, rid: str):
    with session() as db:
        row = cat.owned(db, "attachments", pid, rid)
        return FileResponse(
            resolve_data_path(f"workbench/papers/{pid}/{row['digest']}.pdf"),
            filename=row["name"],
            media_type="application/pdf",
            content_disposition_type="inline",
        )


@router.post("/api/projects/{pid}/observations")
@router.put("/api/projects/{pid}/observations/{rid}")
def observation(pid: str, data: Observation, rid: str | None = None):
    with session() as db:
        cat.owned(db, "papers", pid, data.paper)
        payload = dict(data.payload)
        payload.pop("archive_source", None)
        phase = None
        if data.phase or payload.get("kind") != "experiment":
            phase = cat.owned(db, "phases", pid, data.phase)
        if payload.get("system"):
            payload["system"] = cat.checked_system(db, pid, payload["system"])
        payload.pop("csv_source", None)
        if not isinstance(payload.get("kind"), str) or not payload["kind"].strip():
            raise ValueError("请选择数据类型")
        if payload.get("kind") in ("property", "phase_composition"):
            from src.parameter_fit_settings import FitObservation

            test = payload | {"id": "draft", "source": data.locator + " / source"}
            if payload["kind"] == "property":
                test["phase"] = phase["name"] or phase["alias"]
            FitObservation.model_validate(test)
            fractions = payload.get("composition", {})
            if (
                not fractions
                or abs(sum(fractions.values()) - 1) > 1e-8
                or min(fractions.values()) < 0
            ):
                raise ValueError("总成分应为非负且和为 1 的原子分数")
            cat.checked_system(db, pid, list(fractions))
            if payload["kind"] == "phase_composition":
                members = db.execute(
                    "SELECT id,name,alias FROM phases WHERE project=? ORDER BY id",
                    (pid,),
                ).fetchall()
                payload["_phase_ids"] = [
                    next(
                        (
                            m["id"]
                            for m in members
                            if target["phase"].upper()
                            in {m["name"].upper(), m["alias"].upper()}
                        ),
                        None,
                    )
                    for target in payload["phases"]
                ]
        elif not str(payload.get("value", "")).strip():
            raise ValueError("请填写摘录值或相图描述")
        if rid:
            before = json.loads(cat.owned(db, "observations", pid, rid)["payload"])
            for key in ("csv_source", "archive_source"):
                if key in before:
                    payload[key] = before[key]
            if payload["kind"] == "experiment":
                for key in ("quality_notes", "reported_phase"):
                    if key in before:
                        payload.setdefault(key, before[key])
        return save(
            db,
            "observations",
            pid,
            {
                "paper": data.paper,
                "phase": data.phase or None,
                "locator": data.locator,
                "payload": cat.pack(payload),
            },
            rid,
        )


@router.post("/api/projects/{pid}/experiment-table/{action}")
def import_experiments(
    pid: str,
    action: Literal["inspect", "preview", "commit"],
    file: UploadFile,
    mapping: str = FormField("{}"),
    confirmation: str = FormField(""),
):
    with session() as db:
        cat.project(db, pid)
        filename = safe_name(file.filename or "table.csv")
        if not filename.lower().endswith((".csv", ".tsv", ".txt")):
            raise ValueError("请选择 CSV、TSV 或制表符文本文件")
        raw = file.file.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("每个表格最大 4 MiB，请拆分导入")
        headers, rows = experiment_table.parse(raw)
        if action == "inspect":
            return {
                "headers": headers,
                "total": len(rows),
                "sample": [list(r.values()) for _, r in rows[:5]],
            }
        settings = experiment_table.Mapping.model_validate_json(mapping)
        digest = hashlib.sha256(raw).hexdigest()
        if action == "commit":
            db.execute("BEGIN IMMEDIATE")
        records, token = experiment_table.mapped_rows(
            db, pid, settings, filename, digest, headers, rows
        )
        duplicates = sum(r["duplicate"] for r in records)
        if action == "preview":
            return {
                "total": len(records),
                "duplicates": duplicates,
                "confirmation": token,
                "sample": [
                    {
                        "line": r["line"],
                        "phase": r["phase_label"],
                        "locator": r["locator"],
                        "value": r["payload"]["value"],
                        "quantity": r["payload"].get("quantity"),
                        "unit": r["payload"]["unit"],
                        "T_K": r["payload"].get("T_K"),
                    }
                    for r in records[:8]
                ],
            }
        if confirmation != token:
            raise ValueError("文件或列对应关系已改变，请重新预览")
        path = project_archive.table_path(pid, digest)
        if not path.exists():
            atomic_write(path, raw, binary=True)
        ids = []
        for row in records:
            if not row["duplicate"]:
                saved = save(
                    db,
                    "observations",
                    pid,
                    {
                        "paper": settings.paper,
                        "phase": row["phase"],
                        "locator": row["locator"],
                        "payload": cat.pack(row["payload"]),
                    },
                )
                ids.append(saved["id"])
        return {
            "added": len(ids),
            "duplicates": duplicates,
            "first": ids[0] if ids else None,
        }


@router.get("/api/projects/{pid}/observations/{rid}/table")
def original_table(pid: str, rid: str):
    with session() as db:
        row = cat.owned(db, "observations", pid, rid)
        source = json.loads(row["payload"])["csv_source"]
        return FileResponse(
            project_archive.table_path(pid, source["sha256"]),
            filename=safe_name(source["file"]),
            media_type="application/octet-stream",
        )


@router.post("/api/projects/{pid}/inputs")
def add_input(pid: str, data: Input):
    with session() as db:
        cat.project(db, pid)
        if data.paper:
            cat.owned(db, "papers", pid, data.paper)
        name = safe_name(data.name)
        if not name.lower().endswith(".tdb"):
            raise ValueError("请选择 TDB 文件")
        raw = data.text.encode()
        digest = hashlib.sha256(raw).hexdigest()
        atomic_write(
            resolve_data_path(f"workbench/inputs/{pid}/{digest}.tdb"), raw, binary=True
        )
        db.execute(
            "INSERT OR IGNORE INTO inputs VALUES(?,?,?,?,?)",
            (cat.uid(), pid, data.paper, name, digest),
        )
        return {
            "id": db.execute(
                "SELECT id FROM inputs WHERE project=? AND name=? AND digest=?",
                (pid, name, digest),
            ).fetchone()[0]
        }


@router.get("/api/projects/{pid}/inputs/{rid}/phases")
def input_phases(pid: str, rid: str):
    from src.gibbs import read_databases
    with session() as db:
        source = cat.owned(db, "inputs", pid, rid)
        model, _ = read_databases([f"workbench/inputs/{pid}/{source['digest']}.tdb"])
        return {"phases": sorted(model.phases)}


@router.post("/api/projects/{pid}/structures")
def cif(pid: str, data: Geometry):
    with session() as db:
        cat.project(db, pid)
        structure = Structure.from_str(data.cif, fmt="cif")
        return {
            "id": cat.save_geometry(db, pid, structure, "CIF", data.ref, data.shared)
        }


@router.post("/api/projects/{pid}/structures/search")
def external(pid: str, data: Query):
    with session() as db:
        system = cat.checked_system(db, pid, data.elements)
    try:
        rows, count = fetch_structures(data.provider, system, data.offset)
    except (requests.RequestException, ConnectionError, KeyError, IndexError) as exc:
        raise HTTPException(
            502, f"{data.provider} 未返回可读取的结构，请稍后重试"
        ) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with session() as db:
        ids = [cat.save_geometry(db, pid, s, data.provider, ref) for ref, s in rows]
        return {"ids": ids, "next_offset": data.offset + count if count == 20 else None}


@router.post("/api/projects/{pid}/links")
def link(pid: str, data: Link):
    with session() as db:
        cat.attach(db, pid, data.phase, data.structure)
        return {"ok": True}


@router.get("/api/projects/{pid}/structures/{sid}")
def coordinates(pid: str, sid: str):
    with session() as db:
        row, s = cat.read_structure(db, pid, sid)
        return {
            "晶胞对照": cat.cell_description(s),
            "source": row["source"],
            "ref": row["ref"],
            "structure": s.as_dict(),
        }


@router.get("/api/projects/{pid}/compare")
def compare(pid: str, first: str, second: str):
    from pymatgen.analysis.structure_matcher import (
        StructureMatcher,
        FrameworkComparator,
    )

    with session() as db:
        _, a = cat.read_structure(db, pid, first)
        _, b = cat.read_structure(db, pid, second)
    options = dict(ltol=0.12, stol=0.15, angle_tol=3, scale=True)
    bare = StructureMatcher(comparator=FrameworkComparator(), **options)
    skeletons = [Structure(s.lattice, ["H"] * len(s), s.frac_coords) for s in (a, b)]
    decorated = StructureMatcher(**options)
    return {
        "忽略元素的点阵重合": bool(bare.fit(*skeletons)),
        "元素角色一一对应后同型": bool(decorated.fit_anonymous(a, b))
        if a.is_ordered and b.is_ordered
        else "部分占位待核",
        "第一份结构": cat.cell_description(a),
        "第二份结构": cat.cell_description(b),
    }


def fit_request(db, pid, data):
    parts = cat.checked_system(db, pid, data.components)
    permitted = {
        r["name"]
        for r in db.execute("SELECT name,system FROM phases WHERE project=?", (pid,))
        if r["name"] and set(json.loads(r["system"])) & set(parts)
    }
    if set(data.phases) - permitted:
        raise ValueError("请先确定参与拟合的本库相名")
    files = []
    for rid in data.inputs:
        r = cat.owned(db, "inputs", pid, rid)
        files.append(f"workbench/inputs/{pid}/{r['digest']}.tdb")
    obs = []
    for rid in data.observations:
        r = cat.owned(db, "observations", pid, rid)
        p = cat.owned(db, "papers", pid, r["paper"])
        phase = cat.owned(db, "phases", pid, r["phase"])
        item = cat.observation_payload(db, pid, r["payload"])
        item.pop("csv_source", None)
        item.pop("archive_source", None)
        if item["kind"] == "property":
            item["phase"] = phase["name"]
        obs.append(item | {"id": rid, "source": p["citation"] + " / " + r["locator"]})
    return ParameterFitRequest(
        tdb_files=files,
        components=parts,
        phases=data.phases,
        parameters=data.parameters,
        observations=obs,
    )


@router.post("/api/projects/{pid}/fit/{engine}")
def project_fit(pid: str, data: Fit, engine: Literal["native", "pandat", "thermocalc"]):
    with session() as db:
        req = fit_request(db, pid, data)
    try:
        if engine != "native":
            from src.fit_adapter import configured_adapter, run_adapter

            program = configured_adapter(engine)
            if program is None:
                return {
                    "mode": "external_request",
                    "engine": engine,
                    "request": req.model_dump(),
                    "project": pid,
                }
            candidate, summary = run_adapter(engine, program, req)
        else:
            from src.parameter_fit import run_fit

            result = run_fit(req)
            candidate = result["files"]["candidate"]
            summary = {
                k: result[k]
                for k in (
                    "status",
                    "optimizer_success",
                    "parameters",
                    "all_observations_within_requested_scales",
                    "candidate_sha256",
                    "ready_for_production",
                    "independent_validation_passed",
                )
            }
    except (OSError, ValueError, ImportError) as exc:
        raise HTTPException(422, str(exc)) from exc
    with session() as db:
        rid = cat.uid()
        db.execute(
            "INSERT INTO fits VALUES(?,?,?,?)", (rid, pid, candidate, cat.pack(summary))
        )
        return {"id": rid, "summary": summary}


@router.get("/api/projects/{pid}/fits/{rid}/candidate")
def download_fit(pid: str, rid: str):
    with session() as db:
        row = cat.owned(db, "fits", pid, rid)
        return FileResponse(
            resolve_data_path(row["candidate"]),
            filename="candidate.tdb",
            media_type="application/octet-stream",
        )

@router.post("/api/projects/{pid}/archive")
def archive_project(pid: str, view: project_archive.View):
    try:
        file = project_archive.export_project(pid, view)
    except KeyError as exc:
        raise HTTPException(404, "项目不存在") from exc
    except RunBusyError as exc:
        raise HTTPException(409, "模型文件在打包期间发生了变化，请稍后重试。") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(422, "项目打包失败，请检查归档大小和关联文件的完整性") from exc

    def blocks():
        with file:
            while chunk := file.read(1024 * 1024):
                yield chunk

    return StreamingResponse(blocks(), media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="workspace.zip"'})


@router.post("/api/workspace/import", status_code=201)
def import_workspace(file: UploadFile):
    try:
        return project_archive.import_project(file.file)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/api/workspace/settings")
def open_saved_project(data: SavedProject):
    with session() as db:
        db.execute("BEGIN IMMEDIATE")
        created = db.execute(
            "INSERT OR IGNORE INTO projects(id,title,elements) VALUES(?,?,?)",
            (data.id, data.title, cat.pack(cat.symbols(data.elements))),
        ).rowcount
        return {"id": data.id, "created": bool(created)}
