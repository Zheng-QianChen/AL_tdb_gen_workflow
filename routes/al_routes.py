from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, HTTPException, Body
import asyncio, json
from config import logger, RUN_DIR
from src.main_process.al_worker import ALRunner
from pathlib import Path

al_router = APIRouter()

def get_manager(request: Request):
    """从 app state 中安全获取 manager"""
    if not hasattr(request.app.state, "manager"):
        raise HTTPException(status_code=500, detail="ALManager not initialized in app state")
    return request.app.state.manager

@al_router.post("/start")
async def start_al(request: Request, data: dict = Body(...)):
    """
    启动/重启特定任务
    请求体示例: {"user_id": "guest", "PHASE_NAME": "Alpha", ...}
    """
    manager = get_manager(request)
    
    # 构造或获取任务ID
    user_id = data.get("user_id", "guest")
    configname = data.get("configname", "input")
    # config_dir = data.get("config", {})
    task_id = f"{user_id}_{configname}"
    
    logger.info(f"接收到启动任务请求: {task_id}")
    
    # 如果任务已存在且在运行，先停止旧的
    if task_id in manager.tasks:
        old_runner = manager.tasks[task_id]
        await old_runner.stop()
        del manager.tasks[task_id] # 移除旧实例以便重新创建
    
    # 使用你 Manager 里的核心启动方法
    success, msg = await manager.create_and_start_task(task_id, f"{RUN_DIR}/{configname}.json")
    
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    
    return {"status": "success", "task_id": task_id, "message": msg}


@al_router.post("/pause")
async def pause_al(request: Request, task_id: str = Body(..., embed=True)):
    """暂停/继续特定任务"""
    manager = get_manager(request)
    if task_id not in manager.tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    runner = manager.tasks[task_id]
    paused = await runner.toggle_pause()
    return {"status": "paused" if paused else "resumed", "paused": paused, "task_id": task_id}

@al_router.post("/stop")
async def stop_al(request: Request, task_id: str = Body(..., embed=True)):
    """停止特定任务"""
    manager = get_manager(request)
    if task_id in manager.tasks:
        runner = manager.tasks[task_id]
        asyncio.create_task(runner.stop())
        return {"status": "stopping", "task_id": task_id}
    return {"status": "not_found", "message": "任务未运行"}

@al_router.get("/status")
async def get_status(request: Request, task_id: str = "guest_default"):
    """
    查询任务状态
    访问示例: /status?task_id=guest_Alpha
    """
    manager = get_manager(request)
    
    if task_id not in manager.tasks:
        return {
            "running": False,
            "status_text": "未启动",
            "task_id": task_id
        }
    
    runner = manager.tasks[task_id]
    
    async with runner.state_lock:
        status_text = "运行中"
        if not runner.running:
            status_text = "已结束"
        elif runner.paused:
            status_text = "已暂停"
            
        task_status = "运行中"
        if runner.main_task and runner.main_task.done():
            task_status = "已完成/已停止"
            
        return {
            "running": runner.running,
            "paused": runner.paused,
            "started": runner.started,
            "iter": runner.iter,
            "process": runner.process,
            "subscribers": len(runner.subscribers),
            "status_text": status_text,
            "task_status": task_status,
            "task_id": task_id
        }

# 注意：WebSocket 建议统一在 app.py 的端点处理，
# 或者在此处根据 task_id 订阅
@al_router.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str = "guest_default"):
    manager = websocket.app.state.manager
    await websocket.accept()
    
    manager.subscribe(task_id, websocket)
    logger.info(f"WS Client subscribed to {task_id}")
    
    try:
        while True:
            # 接收前端指令 (例如暂停/停止)
            data = await websocket.receive_json()
            if task_id in manager.tasks:
                runner = manager.tasks[task_id]
                action = data.get("action")
                if action == "pause": await runner.toggle_pause()
                if action == "stop": await runner.stop()
                
    except WebSocketDisconnect:
        manager.unsubscribe(task_id, websocket)
        logger.info(f"WS Client disconnected from {task_id}")