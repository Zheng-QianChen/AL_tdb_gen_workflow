import os
import asyncio, uvicorn, signal, os
import logging
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# 1. import config and logger
from config import logger, ALLOWED_BASE_DIR, UPLOAD_DIR, STATIC_DIR, WORKING_DIR, RUN_DIR, BASE_DATA_DIR
# 2. import routes
from routes.main_routes import main_router
from routes.al_routes import al_router
from routes.file_routes import file_router
from routes.tdb_routes import tdb_router
# 3. import AL Manager
from src.main_process.al_manager import ALManager

os.mkdirs(ALLOWED_BASE_DIR, exist_ok=True)
os.mkdirs(STATIC_DIR, exist_ok=True)
os.mkdirs(UPLOAD_DIR, exist_ok=True)
os.mkdirs(RUN_DIR, exist_ok=True)
os.mkdirs(WORKING_DIR, exist_ok=True)
os.mkdirs(BASE_DATA_DIR, exist_ok=True)

# init logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AL_APP")

# init FastAPI app
app = FastAPI(title="AL TDB Generator Multi-Task System")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
manager = ALManager()
app.state.manager = manager

# ==========================================
# static files mounting
# ==========================================
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/working", StaticFiles(directory=str(WORKING_DIR)), name="working")

# ==========================================
# index and root route
# ==========================================

@app.get("/")
async def get_index():
    """root route serving index.html"""
    index_path = Path(STATIC_DIR) / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse(status_code=404, content={"message": "Index file not found. Please ensure static files are built."})

# init and include routers
app.include_router(main_router)
app.include_router(al_router)
app.include_router(file_router)
app.include_router(tdb_router)

# ==========================================
# Multi-task AL WebSocket and API
# ==========================================


@app.post("/api/start_task")
async def start_new_al_task(request: Request):
    """start a new AL task via API"""
    try:
        raw_data = await request.json()
        # construct unique task_id
        user_id = raw_data.get("user_id", "guest")
        phase_name = raw_data.get("PHASE_NAME", "default")
        task_id = f"{user_id}_{phase_name}"
        
        # manager will start a new AL task
        success, msg = await manager.create_and_start_task(task_id, raw_data)
        
        return {
            "status": "success" if success else "error",
            "task_id": task_id,
            "message": msg
        }
    except Exception as e:
        logger.error(f"Fail to starting this task: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.websocket("/ws")
async def al_websocket_endpoint(websocket: WebSocket, task: str= "default"):
    """
    Multi-task WebSocket channel
    Frontend connection example: ws://localhost:8089/ws?task=guest_BetaPhase
    """
    await websocket.accept()

    task_id = task

    # Use the subscription logic from the Manager
    manager.subscribe(task_id, websocket)
    logger.info(f"Client subscribed to task messages: {task_id}")
    
    try:
        # If Runner already exists, send an initial state snapshot
        if task_id in manager.tasks:
            runner = manager.tasks[task_id]
            await websocket.send_json({
                "type": "snapshot",
                "iter": runner.iter,
                "process": runner.process,
                "running": runner.running,
                "paused": runner.paused
            })

        # Keep connection alive and process incoming control commands
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            
            if task_id in manager.tasks:
                runner = manager.tasks[task_id]
                if action == "pause":
                    await runner.toggle_pause()
                elif action == "stop":
                    await runner.stop()
                    # Optional: can choose to break connection after stopping
                    
    except WebSocketDisconnect:
        manager.unsubscribe(task_id, websocket)
        logger.info(f"Client unsubscribed: {task_id}")
    except Exception as e:
        logger.error(f"WebSocket Exception: {e}")
        manager.unsubscribe(task_id, websocket)

# ==========================================
# Lifecycle Management
# ==========================================

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("System shutting down, stopping all active AL tasks...")
    # Stop all tasks managed by the Manager
    stop_tasks = [runner.stop() for runner in manager.tasks.values()]
    if stop_tasks:
        await asyncio.gather(*stop_tasks)
    # Shutdown the global thread pool
    manager.executor.shutdown(wait=True)
    logger.info("All resources released")

# ==========================================
# Entry Point
# ==========================================

if __name__ == "__main__":
    # Ensure the root directory for task execution exists
    os.makedirs("static/run", exist_ok=True)
    
    port = 8090
    print(f"\n--- AL system is running ---")
    print(f"Main interface URL: http://localhost:{port}")
    print(f"API documentation URL: http://localhost:{port}/docs\n")
    
    uvicorn.run(app, host="0.0.0.0", port=port)