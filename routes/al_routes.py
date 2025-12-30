from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio, json
from config import runner, logger
from lib.main_process.al_worker import ALRunner
from pathlib import Path

al_router = APIRouter()

@al_router.post("/start")
async def start_al():
    """启动AL循环"""
    logger.info("接收到启动AL循环请求")
    
    if runner.started and runner.main_task and not runner.main_task.done():
        # 如果已经在运行，先停止
        await runner.stop()
        await asyncio.sleep(0.5)  # 短暂等待确保停止
    
    # 重置状态并启动新的任务
    runner.reset_state()
    runner.running = True
    runner.started = True
    runner.main_task = asyncio.create_task(runner.main_loop())
    
    return {"status": "started", "running": True}

@al_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket端点，用于实时通信"""
    await websocket.accept()
    runner.subscribe(websocket)
    try:
        while True:
            # 保持连接，每30秒发送一次心跳防止超时
            await asyncio.sleep(30)
            await websocket.send_text(json.dumps({"type": "heartbeat", "message": "连接保持中"}))
    except WebSocketDisconnect:
        runner.unsubscribe(websocket)
        logger.info("WebSocket连接断开")
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
        runner.unsubscribe(websocket)

@al_router.post("/pause")
async def pause_al():
    """暂停/继续AL循环"""
    paused = await runner.toggle_pause()  # 确保这里使用await
    return {"status": "paused" if paused else "resumed", "paused": paused}

@al_router.post("/stop")
async def stop_al():
    """立即返回响应，通过WebSocket通知状态变化"""
    # 立即响应，不等待实际停止完成
    asyncio.create_task(runner.stop())  # 在后台执行实际停止操作
    return {
        "status": "stopping", 
        "message": "停止指令已受理，正在终止任务",
        "running": True  # 暂时返回True，实际状态通过WebSocket更新
    }


@al_router.post("/reset")
async def reset_al():
    """重新加载input.json配置并重启ALRunner"""
    global runner
    logger.info("接收到重新加载input.json的请求")
    
    try:
        
        # 读取input.json文件
        input_path = Path("./static/run/input.json")

        if not input_path.exists():
            logger.error("input.json文件不存在")
            return {
                "success": False,
                "message": "input.json文件不存在"
            }
        
        # 解析配置文件
        with open(input_path, 'r') as f:
            input_config = json.load(f)
        logger.info("成功读取input.json配置文件")
        
        # 先停止当前运行的任务
        if runner.running or (runner.main_task and not runner.main_task.done()):
            logger.info("停止当前运行的ALRunner实例")
            await runner.stop()
            await asyncio.sleep(0.5)  # 等待停止完成
        
        # 创建新的ALRunner实例，假设它能接收配置参数
        runner = ALRunner()
        
        # 如果ALRunner有初始化配置的方法，在这里调用
        if hasattr(runner, 'load_config'):
            runner.load_config(input_config)
            logger.info("已将新配置应用到ALRunner")
        
        # 如果之前是运行状态，重新启动
        if runner.started:
            runner.reset_state()
            runner.running = True
            runner.main_task = asyncio.create_task(runner.main_loop())
            logger.info("已使用新配置重启ALRunner")
            return {
                "success": True,
                "message": "input.json已重新加载并应用，ALRunner已重启"
            }
        else:
            logger.info("input.json已重新加载，ALRunner处于停止状态")
            return {
                "success": True,
                "message": "input.json已重新加载并应用"
            }
            
    except Exception as e:
        logger.error(f"重新加载input.json失败: {str(e)}")
        return {
            "success": False,
            "message": f"重新加载失败: {str(e)}"
        }



@al_router.get("/status")
async def get_status() -> dict[str, bool | int | str]:
    async with runner.state_lock:
        status_text = "未运行"
        if runner.running:
            status_text = "运行中" if not runner.paused else "已暂停"
        task_status = "未启动"
        if runner.main_task:
            if runner.main_task.done():
                task_status = "已结束"
            else:
                task_status = "运行中"
        
        return {
            "running": runner.running,
            "paused": runner.paused,
            "started": runner.started,
            "subscribers": len(runner.subscribers),
            "status_text": status_text,
            "task_status": task_status
        }
    