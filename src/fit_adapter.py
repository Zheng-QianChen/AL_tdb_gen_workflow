"""Run a server-configured local optimizer adapter against a frozen project request."""

import hashlib
import os
from pathlib import Path
import subprocess
from uuid import uuid4
from config import resolve_data_path
from src.storage import atomic_json

ADAPTER_ENV = {
    "pandat": "AL_TDB_PANDAT_FIT_ADAPTER",
    "thermocalc": "AL_TDB_TC_FIT_ADAPTER",
}


def configured_adapter(engine):
    value = os.environ.get(ADAPTER_ENV[engine])
    if not value:
        return None
    program = Path(value)
    if (
        not program.is_absolute()
        or not program.is_file()
        or (os.name == "nt" and program.suffix.lower() != ".exe")
    ):
        raise ValueError(
            f"请检查服务端配置 {ADAPTER_ENV[engine]} 是否指向可执行的适配程序"
        )
    return program


def run_adapter(engine, program, request):
    from src.gibbs import read_databases

    folder = resolve_data_path("parameter_fits") / ("external_" + uuid4().hex)
    folder.mkdir(parents=True)
    payload = request.model_dump()
    payload["tdb_files"] = [str(resolve_data_path(f)) for f in request.tdb_files]
    atomic_json(folder / "request.json", payload)
    dest = folder / "candidate.tdb"
    with (folder / "adapter.log").open("wb") as log:
        try:
            result = subprocess.run(
                [str(program), str(folder / "request.json"), str(dest)],
                cwd=folder,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=3600,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"{engine} 适配程序启动失败或运行超时") from exc
    if result.returncode or not dest.is_file():
        raise ValueError(f"{engine} 未生成候选 TDB，请查阅该运行的 adapter.log")
    db, _ = read_databases([str(dest)])
    if not set(request.phases) <= set(db.phases):
        raise ValueError("外部候选 TDB 缺少本次指定的相")
    summary = {
        "engine": engine,
        "status": "external_candidate",
        "candidate_sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
        "ready_for_production": False,
    }
    atomic_json(folder / "result.json", summary)
    return str(dest), summary
