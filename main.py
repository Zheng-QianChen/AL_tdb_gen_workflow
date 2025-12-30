import webview
import threading
import uvicorn
import sys
import os

# 1. 导入你的 FastAPI 实例
# 确保是从你原来的主逻辑文件导入，或者直接在这里定义
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from config import runner, logger, ALLOWED_BASE_DIR, UPLOAD_DIR, STATIC_DIR, WORKING_DIR
from routes.main_routes import main_router
from routes.al_routes import al_router
from routes.file_routes import file_router
from routes.tdb_routes import tdb_router

# --- 这里放置你原来的路由和挂载代码 ---
app = FastAPI()
app.include_router(main_router)
app.include_router(al_router)
app.include_router(file_router)
app.include_router(tdb_router)
@app.get("/")
async def get_home():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

# 3. 挂载静态资源
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

def start_fastapi():
    port = 8082
    # 注意：这里直接传入 app 对象，而不是字符串 "app"
    # 也不要和 import 的模块名搞混
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")

if __name__ == "__main__":
    # 1. 启动后端线程
    # 使用 daemon=True 确保主窗口关闭时，后端线程也会自动退出
    t = threading.Thread(target=start_fastapi, daemon=True)
    t.start()

    # 2. 启动前端窗口
    # 建议先等待一秒确保后端服务已启动，或者使用 webview 的检查机制
    try:
        webview.create_window('AL TDB Gen UI', 'http://127.0.0.1:8082')
        webview.start()
    except Exception as e:
        print(f"窗口启动失败: {e}")