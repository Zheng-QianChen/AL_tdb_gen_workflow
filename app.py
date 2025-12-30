import fastapi
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import asyncio, uvicorn, signal, os
from concurrent.futures import ThreadPoolExecutor
import logging

# 导入路由和配置
from config import runner, logger, ALLOWED_BASE_DIR, UPLOAD_DIR, STATIC_DIR, WORKING_DIR
from routes.main_routes import main_router
from routes.al_routes import al_router
from routes.file_routes import file_router
from routes.tdb_routes import tdb_router

# 初始化FastAPI应用
app = FastAPI()

# 配置静态文件

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/working", StaticFiles(directory=str(WORKING_DIR)))

# 创建线程池
executor = ThreadPoolExecutor(max_workers=1)

# 注册路由
app.include_router(main_router)
app.include_router(al_router)
app.include_router(file_router)
app.include_router(tdb_router)

# 系统信号处理
def handle_shutdown():
    logger.info("收到系统退出信号，正在清理资源...")
    asyncio.create_task(runner.stop())

@app.on_event("shutdown")
def shutdown_event():
    handle_shutdown()

if __name__ == "__main__":
    port = 8082
    print(f"click http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)