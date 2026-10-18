from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from config import RUN_DIR, safe_name

al_router = APIRouter()


class TaskSelection(BaseModel):
    user_id: str = "guest"
    configname: str = "input"

    def task_id(self):
        safe_name(self.user_id)
        safe_name(self.configname)
        return f"{self.user_id}_{self.configname}"


def get_manager(request):
    return request.app.state.manager


def selection_id(data):
    try:
        return data.task_id()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@al_router.post("/start")
async def start_al(request: Request, data: TaskSelection):
    task_id = selection_id(data)
    try:
        success, message = await get_manager(request).create_and_start_task(
            task_id, RUN_DIR / f"{data.configname}.json", restart=True)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"status": "success" if success else "error", "task_id": task_id, "message": message}


@al_router.post("/pause")
async def pause_al(request: Request, data: TaskSelection):
    runner = get_manager(request).tasks.get(selection_id(data))
    if runner is None:
        raise HTTPException(404, "Task not found")
    paused = await runner.toggle_pause()
    return {"status": "paused" if paused else "resumed", "paused": paused, "task_id": runner.task_id}


@al_router.post("/stop")
async def stop_al(request: Request, data: TaskSelection):
    task_id = selection_id(data)
    runner = get_manager(request).tasks.get(task_id)
    if runner is None:
        return {"status": "not_found", "task_id": task_id}
    runner.stop_event.set()
    runner.paused = False
    return {"status": "stopping", "task_id": task_id}


@al_router.get("/status")
async def get_status(request: Request, user_id: str = "guest", configname: str = "input"):
    task_id = selection_id(TaskSelection(user_id=user_id, configname=configname))
    runner = get_manager(request).tasks.get(task_id)
    if runner is None:
        return {"running": False, "status_text": "task not found", "task_id": task_id}
    status = ("FAILED" if runner.error else "COMPLETED" if runner.completed else
              "STOPPING" if runner.running and runner.stop_event.is_set() else
              "PAUSED" if runner.paused else "RUNNING" if runner.running else "ENDED")
    return {"task_id": task_id, "running": runner.running, "paused": runner.paused,
            "started": runner.started, "iter": runner.iter, "process": runner.process,
            "subscribers": len(runner.subscribers), "status_text": status,
            "task_status": status, "error": runner.error}


@al_router.websocket("/ws")
@al_router.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str = "", task: str = "default"):
    task_id = task_id or task
    await websocket.accept()
    manager = websocket.app.state.manager
    manager.subscribe(task_id, websocket)
    try:
        runner = manager.tasks.get(task_id)
        if runner:
            await websocket.send_json({"type": "snapshot", "iter": runner.iter, "process": runner.process,
                                       "running": runner.running, "paused": runner.paused})
        while True:
            data = await websocket.receive_json()
            runner = manager.tasks.get(task_id)
            if runner and data.get("action") == "pause":
                await runner.toggle_pause()
            elif runner and data.get("action") == "stop":
                runner.stop_event.set()
                runner.paused = False
    except WebSocketDisconnect:
        pass
    finally:
        manager.unsubscribe(task_id, websocket)
