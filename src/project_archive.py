"""Portable, project-scoped archives. The host catalog and all paths stay local."""
import hashlib
import json
import re
import sqlite3
from contextlib import ExitStack
from pathlib import Path
import shutil
from tempfile import TemporaryFile
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config import WORKSPACE_ARCHIVE_BYTES, resolve_data_path, safe_name
from src import project_catalog as cat
from src import project_models


class FitSetup(BaseModel):
    components: str
    parameters: str
    inputs: list[str]
    observations: list[str]
    phases: list[str]


class View(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: str = Field(default="home", max_length=40)
    scope: str = Field(default="all", max_length=512)
    structureTab: str = Field(default="systems", max_length=40)
    picks: dict[str, str] = Field(default_factory=dict, max_length=40)
    engine: str = Field(default="native", max_length=40)
    fitSetup: FitSetup | None = None


FORMAT = "al-tdb-workspace"
MANIFEST = "workspace.json"
FIT_FILES = ("candidate.tdb", "request.json", "optimizer_result.json", "fit.json", "result.json", "adapter.log")
TABLES = {
    "papers": ("title", "citation", "notes", "systems"),
    "phases": ("alias", "name", "system"),
    "models": ("phase", "title"),
    "observations": ("paper", "phase", "locator", "payload"),
    "attachments": ("paper", "name", "digest"),
    "inputs": ("paper", "name", "digest"),
    "fits": ("summary",),
}
ASSETS = {"attachments": ("papers", ".pdf"), "inputs": ("inputs", ".tdb")}


def table_path(pid, digest):
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("实验表格文件摘要无效")
    return resolve_data_path(f"workbench/tables/{pid}/{digest}.csv")


def file_digest(path):
    with path.open("rb") as src:
        return hashlib.file_digest(src, "sha256").hexdigest()


def verify_candidate(path, digest, summary):
    expected = summary.get("candidate_sha256")
    if expected and digest != expected:
        # Earlier Windows runs hashed LF text before the writer translated it to CRLF.
        normalized = path.read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(normalized).hexdigest() != expected:
            raise ValueError("候选库与拟合摘要不一致")


def export_project(pid, view):
    out = TemporaryFile()
    written = set()
    try:
        with cat.catalog() as db, ZipFile(out, "w", ZIP_DEFLATED) as archive:
            db.execute("BEGIN")
            snap = cat.snapshot(db, pid)
            records = {}
            tables = set()
            def blob(path, expected=None):
                digest = file_digest(path)
                if expected and digest != expected:
                    raise ValueError("项目文件与记录的 SHA-256 不一致")
                if digest not in written:
                    archive.write(path, "blobs/" + digest)
                    written.add(digest)
                return digest

            for table, columns in TABLES.items():
                entries = []
                for row in db.execute(f"SELECT * FROM {table} WHERE project=? ORDER BY rowid", (pid,)):
                    item = {k: row[k] for k in ("id", *columns)}
                    if table == "models":
                        item["workspace"] = project_models.export_files(row["id"], blob)
                    if table == "observations":
                        source = json.loads(row["payload"]).get("csv_source")
                        if source and source["sha256"] not in tables:
                            digest = source["sha256"]
                            blob(table_path(pid, digest), digest)
                            tables.add(digest)
                    if table in ASSETS:
                        folder, ext = ASSETS[table]
                        blob(resolve_data_path(f"workbench/{folder}/{pid}/{row['digest']}{ext}"), row["digest"])
                    if table == "fits":
                        candidate = resolve_data_path(row["candidate"])
                        digest = blob(candidate)
                        verify_candidate(candidate, digest, json.loads(row["summary"]))
                        item["files"] = {"candidate.tdb": digest}
                        for name in FIT_FILES[1:]:
                            path = candidate.parent / name
                            if path.is_file():
                                item["files"][name] = blob(path)
                    entries.append(item)
                records[table] = entries
            records["structures"] = [dict(db.execute("SELECT * FROM structures WHERE id=?", (s["id"],)).fetchone())
                                     for s in snap["structures"]]
            records["links"] = snap["links"]
            records["revisions"] = [{k: r[k] for k in ("entity", "at", "before", "after")} for r in snap["revisions"]]
            version = 2 if records["models"] else 1
            if any(p["notes"] or json.loads(p["systems"]) for p in records["papers"]):
                version = 3
            if tables:
                version = 4
            if any(r["phase"] is None for r in records["observations"]):
                version = 5
            if version == 1:
                del records["models"]
            manifest = dict(format=FORMAT, version=version, mode="full", project=cat.project(db, pid),
                            view=view.model_dump(), records=records)
            archive.writestr(MANIFEST, cat.pack(manifest).encode())
            if sum(i.file_size for i in archive.infolist()) > WORKSPACE_ARCHIVE_BYTES:
                raise ValueError("工作台超过服务端设置的归档大小上限")
        out.seek(0)
        return out
    except BaseException:
        out.close()
        raise


def inspect_archive(archive):
    infos = archive.infolist()
    names = {i.filename for i in infos}
    if (len(names) != len(infos) or MANIFEST not in names or
        sum(i.file_size for i in infos) > WORKSPACE_ARCHIVE_BYTES or
        any(not re.fullmatch(r"blobs/[a-f0-9]{64}", n) for n in names - {MANIFEST})):
        raise ValueError("文件不是可读取的工作台包，或已超过归档大小上限")
    manifest = json.loads(archive.read(MANIFEST))
    if (manifest["format"], manifest["mode"]) != (FORMAT, "full") or manifest["version"] not in (1, 2, 3, 4, 5):
        raise ValueError("工作台包格式或版本不支持")
    records = manifest["records"]
    if manifest["version"] == 1:
        records.setdefault("models", [])
    if manifest["version"] < 3:
        for paper in records.get("papers", []):
            paper.setdefault("notes", "")
            paper.setdefault("systems", "[]")
    if set(records) != {*TABLES, "structures", "links", "revisions"} or not all(isinstance(v, list) for v in records.values()):
        raise ValueError("项目数据清单不完整")
    return manifest


def restore(archive, manifest, cleanup):
    p, records = manifest["project"], manifest["records"]
    settings = View.model_validate(manifest["view"]).model_dump()
    pid = cat.uid()
    mapping = {p["id"]: pid}
    for table in (*TABLES, "structures"):
        for r in records[table]:
            old = r["id"]
            if old in mapping or not re.fullmatch(r"[a-f0-9]{32}|[a-f0-9]{64}", old):
                raise ValueError("条目标识重复或无效")
            mapping[old] = cat.uid()

    def store_blob(digest, path):
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("文件摘要无效")
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with archive.open("blobs/" + digest) as src, path.open("xb") as dst:
            shutil.copyfileobj(src, dst)
        if file_digest(path) != digest:
            raise ValueError("工作台包中的文件校验失败")

    def target_dir(relative):
        path = resolve_data_path(relative)
        path.mkdir(parents=True, exist_ok=False)
        cleanup.callback(shutil.rmtree, path, ignore_errors=True)
        return path

    with cat.catalog() as db:
        db.execute("BEGIN IMMEDIATE")
        elements = cat.symbols(p["elements"])
        if not isinstance(p["title"], str) or not p["title"].strip():
            raise ValueError("项目缺少名称")
        db.execute("INSERT INTO projects VALUES(?,?,?)", (pid, p["title"][:115] + "（副本）", cat.pack(elements)))
        for r in records["structures"]:
            system = cat.checked_system(db, pid, json.loads(r["system"]))
            geom = json.loads(r["geometry"])
            validate_geometry(geom)
            # Shared structure identities are content derived, including source and geometry.
            owner = pid if r["owner"] is not None else None
            sid = hashlib.sha256(cat.pack([owner, r["source"], r["ref"], r["geometry"]]).encode()).hexdigest()
            if owner is None and sid != r["id"]:
                raise ValueError("共享结构标识与原始晶胞不一致")
            mapping[r["id"]] = sid
            db.execute("INSERT OR IGNORE INTO structures VALUES(?,?,?,?,?,?,?,?)",
                       (sid, owner, cat.pack(system), r["formula"], r["sg"], r["source"], r["ref"], r["geometry"]))

        def ref(key, table):
            value = mapping[key]
            cat.owned(db, table, pid, value)
            return value

        table_folder = None
        for table, columns in TABLES.items():
            if table in ASSETS and records[table]:
                folder, ext = ASSETS[table]
                dest = target_dir(f"workbench/{folder}/{pid}")
            if table == "fits" and records[table]:
                fit_root = target_dir(f"workbench/fits/{pid}")
            for r in records[table]:
                item = {k: r[k] for k in columns}
                if table == "papers":
                    item["systems"] = cat.pack([cat.checked_system(db, pid, s) for s in json.loads(item["systems"])])
                    if not isinstance(item["notes"], str) or len(item["notes"]) > 120000:
                        raise ValueError("文献笔记无效")
                rid = mapping[r["id"]]
                if "paper" in item and item["paper"] is not None:
                    item["paper"] = ref(item["paper"], "papers")
                if table == "phases":
                    item["system"] = cat.pack(cat.checked_system(db, pid, json.loads(item["system"])))
                elif table == "models":
                    item["phase"] = ref(item["phase"], "phases")
                    phase = cat.owned(db, "phases", pid, item["phase"])
                    project_models.restore_files(rid, phase["name"] or phase["alias"], json.loads(phase["system"]),
                                                r["workspace"], target_dir, store_blob, cleanup)
                elif table == "observations":
                    payload = json.loads(item["payload"])
                    if item["phase"] is not None or payload.get("kind") != "experiment":
                        item["phase"] = ref(item["phase"], "phases")
                    if payload.get("system"):
                        payload["system"] = cat.checked_system(db, pid, payload["system"])
                    if "csv_source" in payload:
                        source = payload["csv_source"]
                        safe_name(source["file"])
                        path = table_path(pid, source["sha256"])
                        if table_folder is None:
                            table_folder = target_dir(f"workbench/tables/{pid}")
                        store_blob(source["sha256"], path)
                    if "_phase_ids" in payload:
                        payload["_phase_ids"] = [ref(i, "phases") if i else None for i in payload["_phase_ids"]]
                    item["payload"] = cat.pack(payload)
                elif table in ASSETS:
                    safe_name(item["name"])
                    store_blob(item["digest"], dest / (item["digest"] + ext))
                elif table == "fits":
                    files = r["files"]
                    if "candidate.tdb" not in files or set(files) - set(FIT_FILES):
                        raise ValueError("拟合文件清单无效")
                    summary = json.loads(item["summary"])
                    relative = f"workbench/fits/{pid}/{rid}"
                    folder = fit_root / rid
                    for name, digest in files.items():
                        store_blob(digest, folder / name)
                    verify_candidate(folder / "candidate.tdb", files["candidate.tdb"], summary)
                    item["candidate"] = relative + "/candidate.tdb"
                fields = ["id", "project", *item]
                db.execute(f"INSERT INTO {table}({','.join(fields)}) VALUES({','.join('?' for _ in fields)})",
                           (rid, pid, *item.values()))
        for link in records["links"]:
            cat.attach(db, pid, mapping[link["phase"]], mapping[link["structure"]])
        for r in records["revisions"]:
            # Rebind entity references; preserve the original text, dates and field values.
            def revision_doc(raw):
                doc = json.loads(raw)
                if isinstance(doc, dict):
                    for key in ("id", "project", "paper", "phase"):
                        if doc.get(key) is not None:
                            doc[key] = mapping[doc[key]]
                    if isinstance(doc.get("payload"), str):
                        payload = json.loads(doc["payload"])
                        if "_phase_ids" in payload:
                            payload["_phase_ids"] = [mapping[i] if i else None for i in payload["_phase_ids"]]
                            doc["payload"] = cat.pack(payload)
                return cat.pack(doc)
            db.execute("INSERT INTO revisions(project,entity,at,before,after) VALUES(?,?,?,?,?)",
                       (pid, mapping[r["entity"]], r["at"], revision_doc(r["before"]), revision_doc(r["after"])))
        settings["picks"] = {k: mapping[v] for k, v in settings["picks"].items() if v in mapping}
        if settings["fitSetup"]:
            for key in ("inputs", "observations"):
                settings["fitSetup"][key] = [mapping[v] for v in settings["fitSetup"][key] if v in mapping]
    return {"id": pid, "view": settings}


def validate_geometry(geom):
    # Only plain JSON site properties from structures are accepted for later decoding.
    def check(value, depth=0):
        if isinstance(value, dict):
            if depth and ("@module" in value or "@class" in value):
                raise ValueError("不支持带自定义对象的晶胞属性")
            for child in value.values():
                check(child, depth+1)
        elif isinstance(value, list):
            for child in value:
                check(child, depth+1)
    check(geom)
    if not isinstance(geom, dict) or not geom.get("sites") or "matrix" not in geom.get("lattice", {}):
        raise ValueError("结构坐标缺失")


def import_project(stream):
    try:
        stream.seek(0, 2)
        if stream.tell() > WORKSPACE_ARCHIVE_BYTES:
            raise ValueError("工作台包超过归档大小上限")
        stream.seek(0)
        with ZipFile(stream) as archive, ExitStack() as cleanup:
            result = restore(archive, inspect_archive(archive), cleanup)
            cleanup.pop_all()
            return result
    except (BadZipFile, UnicodeError, KeyError, IndexError, AttributeError, TypeError, RecursionError,
            ValidationError, RuntimeError, sqlite3.IntegrityError) as exc:
        raise ValueError("工作台包损坏或数据关系无效") from exc
