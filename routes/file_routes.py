"""File endpoints restricted to the application data directory."""
import asyncio
import json
import uuid
from pathlib import Path
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from config import BASE_DATA_DIR, UPLOAD_DIR, RUN_DIR, resolve_data_path, safe_name
from src.settings import TaskConfig
from src.storage import atomic_json, atomic_write

file_router = APIRouter()


class FilePathRequest(BaseModel):
    file_path: str


def is_safe_path(base_dir, file_path):
    return Path(file_path).resolve().is_relative_to(Path(base_dir).resolve())


def data_path(value):
    try:
        return resolve_data_path(value)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc


@file_router.post("/save_input_json")
async def save_input_json(request: Request):
    body = await request.json()
    try:
        filename = safe_name(body.get("filename", "input.json"))
        data = TaskConfig.model_validate(body.get("data")).model_dump()
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    path = data_path(RUN_DIR / filename)
    if path.exists():
        backup = path.with_name(f"{path.stem}_{uuid.uuid4().hex[:8]}{path.suffix}")
        atomic_write(backup, path.read_bytes(), binary=True)
    atomic_json(path, data)
    return {"success": True, "message_key": "api.save_success", "file_path": str(path)}


@file_router.post("/upload_file")
async def upload_file(file: UploadFile = File(...)):
    created = None
    try:
        try:
            filename = safe_name(file.filename or f"upload_{uuid.uuid4().hex[:8]}")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        original = Path(filename)
        counter = 0
        while True:
            name = filename if counter == 0 else f"{original.stem}_{counter}{original.suffix}"
            path = data_path(UPLOAD_DIR / name)
            try:
                buffer = path.open("xb")
                created = path
                break
            except FileExistsError:
                counter += 1
        with buffer:
            while chunk := await file.read(1024 * 1024):
                buffer.write(chunk)
        relative = path.relative_to(BASE_DATA_DIR).as_posix()
        return {"success": True, "filename": path.name, "file_path": str(path),
                "relative_path": relative, "url": f"/get_data_file/{relative}"}
    except BaseException:
        if created is not None:
            created.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@file_router.post("/read-record")
async def read_record(request: FilePathRequest):
    path = data_path(request.file_path)
    if not path.is_file():
        raise HTTPException(404, "File not found")
    if path.stat().st_size > 10 * 1024 * 1024:
        raise HTTPException(413, "File is larger than 10 MB")
    try:
        content = await asyncio.to_thread(path.read_text, encoding="utf-8")
    except UnicodeError as exc:
        raise HTTPException(422, "Expected a UTF-8 text file") from exc
    return {"success": True, "content": content}


@file_router.get("/get_data_file/{file_path:path}")
async def get_data_file(file_path: str):
    path = data_path(file_path)
    if not path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(path)


@file_router.get("/get_config_status")
async def get_config_status(filename: str):
    try:
        filename = safe_name(filename)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    path = data_path(RUN_DIR / filename)
    if not path.is_file():
        raise HTTPException(404, "File not found")
    return json.loads(path.read_text(encoding="utf-8"))
