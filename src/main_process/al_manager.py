"""Own shared computation resources and serialize task replacement."""
import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from config import RUN_DIR, resolve_data_path, safe_name
from src.settings import TaskConfig
from src.storage import atomic_json
from src.main_process.al_worker import ALRunner
from src.run_lock import RunLease


class ALManager:
    def __init__(self):
        self.tasks = {}
        self.subscribers = {}
        self.assessments = {}
        self.executor = ThreadPoolExecutor(max_workers=max(1, min(4, os.cpu_count() or 1)))
        self.lock = asyncio.Lock()

    async def create_and_start_task(self, task_id, config_dir, restart=False):
        safe_name(task_id)
        raw = config_dir if isinstance(config_dir, dict) else json.loads(Path(config_dir).read_text(encoding="utf-8"))
        data = TaskConfig.model_validate(raw).model_dump()
        path = RUN_DIR / f"{task_id}.json" if isinstance(config_dir, dict) else Path(config_dir)
        outputs = [resolve_data_path(data["record_path"]),
                   resolve_data_path(data["AL_set"]["generate_DFT_path"]),
                   resolve_data_path(data["AL_set"]["calced_DFT_path"]),
                   resolve_data_path(data["AL_set"]["pkl_phase_path"]),
                   resolve_data_path(data["structure_out_file"])]
        async with self.lock:
            if task_id in self.tasks:
                if not restart:
                    return False, "Task ID already exists"
                await self.tasks[task_id].stop()
            for key, other in self.tasks.items():
                if key == task_id or not other.running:
                    continue
                for left in outputs:
                    for right in other.output_paths:
                        if left.is_relative_to(right) or right.is_relative_to(left):
                            raise ValueError("Another running task owns an overlapping output directory")
            # Validation succeeds before a user configuration is replaced.
            lease = RunLease(data).acquire()
            try:
                atomic_json(path, data)
            except BaseException:
                lease.release()
                raise
            runner = ALRunner(task_id, path, executor=self.executor)
            runner.lease = lease
            runner.output_paths = outputs
            for websocket in self.subscribers.get(task_id, []):
                runner.subscribe(websocket)
            runner.running = runner.started = True
            self.tasks[task_id] = runner
            runner.main_task = asyncio.create_task(runner.main_loop())
        return True, "Task started"

    def subscribe(self, task_id, websocket):
        subscribers = self.subscribers.setdefault(task_id, [])
        if websocket not in subscribers:
            subscribers.append(websocket)
        if task_id in self.tasks:
            self.tasks[task_id].subscribe(websocket)

    def unsubscribe(self, task_id, websocket):
        if websocket in self.subscribers.get(task_id, []):
            self.subscribers[task_id].remove(websocket)
        if task_id in self.tasks:
            self.tasks[task_id].unsubscribe(websocket)

    async def close(self):
        await asyncio.gather(*(runner.stop() for runner in self.tasks.values()))
        await asyncio.to_thread(self.executor.shutdown, wait=True)
