from fastapi import APIRouter
from fastapi.responses import FileResponse

main_router = APIRouter()

# Home page route
@main_router.get("/")
@main_router.get("/index.html")
async def read_index():
    return FileResponse("static/index.html")

# Data preparation and model settings page route
@main_router.get("/data_preparation.html")
async def read_data_preparation():
    return FileResponse("static/data_preparation.html")

# Visualization page route
@main_router.get("/visualization.html")
async def read_visualization():
    return FileResponse("static/visualization.html")

# Model analysis page route
@main_router.get("/model_analysis.html")
async def read_model_analysis():
    return FileResponse("static/model_analysis.html")
    