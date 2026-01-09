import os
import asyncio, uvicorn, signal, os
import logging
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# 1. 导入配置
from config import logger, ALLOWED_BASE_DIR, UPLOAD_DIR, STATIC_DIR, WORKING_DIR
# 2. 导入路由
from routes.main_routes import main_router
from routes.al_routes import al_router
from routes.file_routes import file_router
from routes.tdb_routes import tdb_router
# 3. 导入你更新后的 Manager
from src.main_process.al_manager import ALManager

# 初始化日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AL_APP")

# 初始化应用
app = FastAPI(title="AL TDB Generator Multi-Task System")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
manager = ALManager()
app.state.manager = manager  # 必须这一步，路由里的 get_manager 才能生效

# 实例化全局管理器
manager = ALManager()

# ==========================================
# 静态文件配置
# ==========================================
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/working", StaticFiles(directory=str(WORKING_DIR)), name="working")

# ==========================================
# 首页与核心路由
# ==========================================

@app.get("/")
async def get_index():
    """解决 404 问题：访问根域名直接返回原本的页面"""
    index_path = Path(STATIC_DIR) / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse(status_code=404, content={"message": "首页 index.html 未在 static 目录找到"})

# 注册原有功能模块路由
app.include_router(main_router)
app.include_router(al_router)
app.include_router(file_router)
app.include_router(tdb_router)

# ==========================================
# 多任务控制接口 (基于你最新的 Manager 逻辑)
# ==========================================


@app.post("/api/start_task")
async def start_new_al_task(request: Request):
    """启动一个新的 AL 循环任务"""
    try:
        raw_data = await request.json()
        # 构造唯一 Task ID (建议由前端传入或根据参数生成)
        user_id = raw_data.get("user_id", "guest")
        phase_name = raw_data.get("PHASE_NAME", "default")
        task_id = f"{user_id}_{phase_name}"
        
        # 调用你定义的 Manager 启动逻辑
        success, msg = await manager.create_and_start_task(task_id, raw_data)
        
        return {
            "status": "success" if success else "error",
            "task_id": task_id,
            "message": msg
        }
    except Exception as e:
        logger.error(f"启动任务接口失败: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.websocket("/ws")
async def al_websocket_endpoint(websocket: WebSocket, task: str= "default"):
    """
    多任务 WebSocket 通道
    前端连接示例: ws://localhost:8089/ws?task=guest_BetaPhase
    """
    await websocket.accept()

    task_id = task

    # 使用你 Manager 中的订阅逻辑
    manager.subscribe(task_id, websocket)
    logger.info(f"客户端已订阅任务消息: {task_id}")
    
    try:
        # 如果 Runner 已经存在，发送一个初始状态快照
        if task_id in manager.tasks:
            runner = manager.tasks[task_id]
            await websocket.send_json({
                "type": "snapshot",
                "iter": runner.iter,
                "process": runner.process,
                "running": runner.running,
                "paused": runner.paused
            })

        # 保持连接，处理前端发来的控制指令
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            
            if task_id in manager.tasks:
                runner = manager.tasks[task_id]
                if action == "pause":
                    await runner.toggle_pause()
                elif action == "stop":
                    await runner.stop()
                    # 停止后可以根据需要选择是否 break 连接
                    
    except WebSocketDisconnect:
        manager.unsubscribe(task_id, websocket)
        logger.info(f"客户端取消订阅: {task_id}")
    except Exception as e:
        logger.error(f"WS 异常: {e}")
        manager.unsubscribe(task_id, websocket)

# ==========================================
# 生命周期管理
# ==========================================

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("系统正在关闭，正在停止所有运行中的 AL 任务...")
    # 停止 Manager 管理的所有任务
    stop_tasks = [runner.stop() for runner in manager.tasks.values()]
    if stop_tasks:
        await asyncio.gather(*stop_tasks)
    # 关闭全局线程池
    manager.executor.shutdown(wait=True)
    logger.info("所有资源已释放")

# ==========================================
# 启动入口
# ==========================================

if __name__ == "__main__":
    # 确保任务运行根目录存在
    os.makedirs("static/run", exist_ok=True)
    
    port = 8092
    print(f"\n--- AL 多任务系统已启动 ---")
    print(f"主界面地址: http://localhost:{port}")
    print(f"API 文档地址: http://localhost:{port}/docs\n")
    
    uvicorn.run(app, host="0.0.0.0", port=port)