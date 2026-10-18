from fastapi import APIRouter
from fastapi.responses import FileResponse
from config import STATIC_DIR

main_router = APIRouter()


@main_router.get("/")
@main_router.get("/index.html")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@main_router.get("/data_preparation.html")
@main_router.get("/data_preparation")
async def data_preparation():
    return FileResponse(STATIC_DIR / "data_preparation.html")


@main_router.get("/visualization.html")
@main_router.get("/visualization")
async def visualization():
    return FileResponse(STATIC_DIR / "visualization.html")


@main_router.get("/model_analysis.html")
@main_router.get("/model_analysis")
async def model_analysis():
    return FileResponse(STATIC_DIR / "model_analysis.html")


@main_router.get("/gibbs.html")
@main_router.get("/gibbs")
async def gibbs():
    return FileResponse(STATIC_DIR / "gibbs.html")


@main_router.get("/phase-diagram.html")
@main_router.get("/phase-diagram")
async def phase_diagram():
    return FileResponse(STATIC_DIR / "phase-diagram.html")
