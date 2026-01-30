from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, HTTPException, Body
import asyncio, json
from config import logger, RUN_DIR
from src.main_process.al_worker import ALRunner
from pathlib import Path

al_router = APIRouter()

def get_manager(request: Request):
    """Safely retrieve the manager from app state"""
    if not hasattr(request.app.state, "manager"):
        raise HTTPException(status_code=500, detail="ALManager not initialized in app state")
    return request.app.state.manager

@al_router.post("/start")
async def start_al(request: Request, data: dict = Body(...)):
    """
    Start/Restart a specific task
    Request body example: {"user_id": "guest", "PHASE_NAME": "Alpha", ...}
    """
    manager = get_manager(request)
    
    # Construct or retrieve task ID
    user_id = data.get("user_id", "guest")
    configname = data.get("configname", "input")
    # config_dir = data.get("config", {})
    task_id = f"{user_id}_{configname}"
    
    logger.info(f"Received request to start task: {task_id}")
    
    # If task exists and is running, stop the old one first
    if task_id in manager.tasks:
        old_runner = manager.tasks[task_id]
        await old_runner.stop()
        del manager.tasks[task_id] # Remove old instance for re-creation
    
    # Use the core startup method in your Manager
    success, msg = await manager.create_and_start_task(task_id, f"{RUN_DIR}/{configname}.json")
    
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    
    return {"status": "success",
            "task_id": task_id,
            "message": msg}


@al_router.post("/pause")
async def pause_al(request: Request, data: dict = Body(...)):
    """Pause/Resume a specific task"""
    manager = get_manager(request)
    user_id = data.get("user_id", "guest")
    configname = data.get("configname", "input")
    # config_dir = data.get("config", {})
    task_id = f"{user_id}_{configname}"

    if task_id not in manager.tasks:
        raise HTTPException(status_code=404, detail="Task does not exist")
    
    runner = manager.tasks[task_id]
    paused = await runner.toggle_pause()
    return {"status": "paused" if paused else "resumed", 
            "paused": paused, 
            "task_id": task_id}

@al_router.post("/stop")
async def stop_al(request: Request, data: dict = Body(...)):
    """Stop a specific task"""
    manager = get_manager(request)
    user_id = data.get("user_id", "guest")
    configname = data.get("configname", "input")
    # config_dir = data.get("config", {})
    task_id = f"{user_id}_{configname}"

    if task_id in manager.tasks:
        runner = manager.tasks[task_id]
        asyncio.create_task(runner.stop())
        return {"status": "stopping", "task_id": task_id}
    return {"status": "not_found", "message": "Task is not running"}

@al_router.get("/status")
async def get_status(request: Request,
                     user_id: str = "guest", 
                     configname: str = "input"
):
    """
    Query task status
    Access example: /status?task_id=guest_Alpha
    """
    manager = get_manager(request)
    task_id = f"{user_id}_{configname}"
    
    if task_id not in manager.tasks:
        return {
            "running": False,
            "status_text": "task not found",
            "task_id": task_id
        }
    
    runner = manager.tasks[task_id]
    
    async with runner.state_lock:
        status_text = "RUNNING"
        if not runner.running:
            status_text = "ENDED"
        elif runner.paused:
            status_text = "PAUSED"
            
        task_status = "RUNNING"
        if runner.main_task and runner.main_task.done():
            task_status = "Completed/Stopped"
            
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

# Note: It is recommended to handle WebSockets at the app.py endpoint
# Or subscribe here based on task_id
@al_router.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str = "guest_default"):
    manager = websocket.app.state.manager
    await websocket.accept()
    
    manager.subscribe(task_id, websocket)
    logger.info(f"WS Client subscribed to {task_id}")
    
    try:
        while True:
            # Receive frontend commands (e.g., pause/stop)
            data = await websocket.receive_json()
            if task_id in manager.tasks:
                runner = manager.tasks[task_id]
                action = data.get("action")
                if action == "pause": await runner.toggle_pause()
                if action == "stop": await runner.stop()
                
    except WebSocketDisconnect:
        manager.unsubscribe(task_id, websocket)
        logger.info(f"WS Client disconnected from {task_id}")