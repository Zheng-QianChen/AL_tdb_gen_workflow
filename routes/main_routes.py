from fastapi import APIRouter
from fastapi.responses import FileResponse

main_router = APIRouter()

# 首页路由
@main_router.get("/")
@main_router.get("/index.html")
async def read_index():
    return FileResponse("static/index.html")

# 数据准备及模型设置页面路由
@main_router.get("/data_preparation.html")
async def read_data_preparation():
    return FileResponse("static/data_preparation.html")

# 可视化页面路由
@main_router.get("/visualization.html")
async def read_visualization():
    return FileResponse("static/visualization.html")

# 模型分析页面路由
@main_router.get("/model_analysis.html")
async def read_model_analysis():
    return FileResponse("static/model_analysis.html")
    