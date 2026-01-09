import os
import json
import asyncio
from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor
from src.main_process.al_worker import ALRunner
from fastapi import FastAPI, WebSocket

class ALManager:
    def __init__(self):
        # 存储所有运行中的任务 {task_id: ALRunner实例}
        self.tasks: Dict[str, ALRunner] = {}
        # 存储 WebSocket 订阅关系 {task_id: [WebSocket客户端列表]}
        self.subscribers: Dict[str, List[WebSocket]] = {}
        # 全局共享线程池，防止多任务并发时撑爆 CPU
        self.executor = ThreadPoolExecutor(max_workers=os.cpu_count())

    async def create_and_start_task(self, task_id: str, config_dir: str):
        """创建一个新的计算实例并运行"""
        if task_id in self.tasks:
            return False, "任务 ID 已存在"

        # 1. 预处理路径
        # task_config = self._prepare_task_config(task_id, raw_data)
        
        # 2. 实例化 Runner (此时 Runner 已经拿到了属于自己的 task_id 和路径)
        runner = ALRunner(task_id=task_id, config_dir=config_dir, executor=self.executor)
        self.tasks[task_id] = runner
        
        # 3. 启动异步循环 (把预处理好的 config 传进去)
        runner.running = True
        runner.started = True
        runner.main_task = asyncio.create_task(runner.main_loop())
        
        return True, "任务启动成功"

    def subscribe(self, task_id: str, websocket: WebSocket):
        """将 Web 端的连接绑定到特定任务"""
        if task_id not in self.subscribers:
            self.subscribers[task_id] = []
        self.subscribers[task_id].append(websocket)
        
        # 如果 Runner 已经存在，把这个 socket 也传给 Runner 方便它实时推送到这
        if task_id in self.tasks:
            self.tasks[task_id].subscribers.append(websocket)

    def unsubscribe(self, task_id: str, websocket: WebSocket):
        """断开连接"""
        if task_id in self.subscribers:
            if websocket in self.subscribers[task_id]:
                self.subscribers[task_id].remove(websocket)
        if task_id in self.tasks:
            if websocket in self.tasks[task_id].subscribers:
                self.tasks[task_id].subscribers.remove(websocket)