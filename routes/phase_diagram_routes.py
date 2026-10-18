"""Phase diagram endpoints share the CLI's calculation and validation pipeline."""
from pathlib import Path

from fastapi import APIRouter, Request

from config import BASE_DATA_DIR
from routes.tdb_routes import compute
from src.phase_diagram_settings import DiagramSource, PhaseDiagramRequest

phase_diagram_router = APIRouter()


@phase_diagram_router.post("/phase-diagram/options")
async def options(request: Request, data: DiagramSource):
    from src.phase_diagram import diagram_options
    return await compute(request, diagram_options, data)


@phase_diagram_router.post("/phase-diagram/calculate")
async def calculate(request: Request, data: PhaseDiagramRequest):
    from src.phase_diagram import run_diagram
    result = await compute(request, run_diagram, data)
    result["urls"] = {key: "/get_data_file/" + Path(path).resolve().relative_to(BASE_DATA_DIR).as_posix()
                      for key, path in result["files"].items()}
    return result
