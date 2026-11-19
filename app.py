"""FastAPI application shared by the browser and optional desktop launcher."""
import logging
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse

from config import BASE_DATA_DIR, UPLOAD_DIR, RUN_DIR, WORKING_DIR, STATIC_DIR, HOST, PORT, safe_name
from src.main_process.al_manager import ALManager
from routes.main_routes import main_router
from routes.al_routes import al_router
from routes.file_routes import file_router
from routes.tdb_routes import tdb_router
from routes.phase_diagram_routes import phase_diagram_router
from routes.result_routes import result_router
from routes.job_routes import job_router
from routes.project_routes import router as project_router
from routes.parameter_fit_routes import parameter_fit_router


def create_app():
    for folder in (BASE_DATA_DIR, UPLOAD_DIR, RUN_DIR, WORKING_DIR):
        folder.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(application):
        application.state.manager = ALManager()
        try:
            yield
        finally:
            await application.state.manager.close()

    application = FastAPI(title="AL TDB Generator", lifespan=lifespan)
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    application.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
    application.mount("/working", StaticFiles(directory=WORKING_DIR), name="working")
    # A bookmarked model tool must resolve to the same configuration as its
    # workbench link, including after a user edits or omits query parameters.
    model_tools = {"/": "task", "/index": "task", "/jobs": "config", "/results": "config",
                   "/visualization": "task", "/model_analysis": "config", "/data_preparation": "run",
                   "/gibbs": "run"}

    @application.middleware("http")
    async def resolve_model_tool(request, call_next):
        mid = request.query_params.get("model")
        param = model_tools.get(request.url.path.removesuffix(".html"))
        if mid and param and request.method == "GET":
            from src import project_catalog, project_models
            from starlette.concurrency import run_in_threadpool
            def resolve():
                with project_catalog.catalog() as db:
                    project_catalog.owned(db, "models", request.query_params.get("project"), mid)
                return project_models.filename(mid)
            try:
                name = await run_in_threadpool(resolve)
            except (KeyError, ValueError):
                return JSONResponse({"detail": "项目中没有该模型"}, status_code=404)
            if request.query_params.get(param) != name:
                return RedirectResponse(str(request.url.include_query_params(**{param: name})))
        return await call_next(request)
    for router in (main_router, al_router, file_router, tdb_router, phase_diagram_router, result_router, job_router, project_router, parameter_fit_router):
        application.include_router(router)

    @application.get("/health")
    async def health():
        return {"status": "ok"}

    @application.post("/api/start_task")
    async def start_task(request: Request, data: dict):
        try:
            task_id = safe_name(f"{data.get('user_id', 'guest')}_{data.get('phase_name', data.get('PHASE_NAME', 'default'))}")
            success, message = await request.app.state.manager.create_and_start_task(task_id, data)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not success:
            raise HTTPException(status_code=409, detail=message)
        return {"status": "success", "task_id": task_id, "message": message}
    return application


app = create_app()


def serve():
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    serve()
