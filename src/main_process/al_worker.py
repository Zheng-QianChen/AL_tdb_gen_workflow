"""Resumable AL state machine.

A stop request waits for the current synchronous operation and its checkpoint.
Workers never close the manager's shared executor.
"""
import asyncio
import json
import logging
import random
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
from pymatgen.core import Element

from config import resolve_data_path
from src.class_def import Phase
from src.POSCAR_generate import replace_wyckoff
from src.settings import TaskConfig, parse_hyperparameters
from src.storage import atomic_json
from src.run_lock import RunLease
from src.workflow import input_hashes
from src.tdb_generator import tdb_generate_from_MLmodel

logger = logging.getLogger("al_tdb")


class ALRunner:
    def __init__(self, task_id, config_dir, executor=None):
        self.task_id = task_id
        self.input_json = Path(config_dir)
        self.executor = executor
        self.running = self.paused = self.started = False
        self.main_task = None
        self.subscribers = []
        self.phase = self.data = None
        self.iter = self.process = 0
        self.state_lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self.error = None
        self.completed = False
        self.lease = None
        self.initialized = False

    async def send_message(self, message):
        packet = message if isinstance(message, dict) else {"type": "message", "content": message}
        for websocket in self.subscribers[:]:
            try:
                await asyncio.wait_for(websocket.send_json(packet), timeout=1)
            except Exception:
                self.unsubscribe(websocket)

    def subscribe(self, websocket):
        if websocket not in self.subscribers:
            self.subscribers.append(websocket)

    def unsubscribe(self, websocket):
        if websocket in self.subscribers:
            self.subscribers.remove(websocket)

    async def toggle_pause(self):
        async with self.state_lock:
            self.paused = not self.paused
        await self.send_message({"type": "status", "status": "paused" if self.paused else "running"})
        return self.paused

    async def stop(self):
        self.stop_event.set()
        self.paused = False
        if self.main_task and self.main_task is not asyncio.current_task():
            await self.main_task
        self.release()
        self.running = self.started = False
        return True

    async def _run_sync(self, function, *args):
        # Do not cancel this future: Python threads cannot be safely killed.
        future = asyncio.get_running_loop().run_in_executor(self.executor, function, *args)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            await future
            raise

    def _parse_hyper_params(self, value):
        return parse_hyperparameters(value)

    def _build_eigen_table(self, descriptors):
        merged = None
        for filename, specification in descriptors.items():
            columns = [specification["index_name"], *specification["col_name"]]
            table = pd.read_csv(resolve_data_path(filename))[columns].copy()
            table = table.rename(columns={columns[0]: "symbol"})
            table["symbol"] = table["symbol"].str.upper()
            if table["symbol"].duplicated().any():
                raise ValueError(f"Duplicate descriptor symbols in {filename}")
            if merged is not None:
                overlap = (set(table.columns) & set(merged.columns)) - {"symbol"}
                if overlap:
                    raise ValueError(f"Duplicate descriptor columns: {sorted(overlap)}")
                merged = merged.merge(table, on="symbol", how="outer", validate="one_to_one")
            else:
                merged = table
        return merged

    def init_process(self, data):
        self.input_hashes = input_hashes(data)
        record = resolve_data_path(data["record_path"])
        settings = data["AL_set"]
        structure, placeholders = replace_wyckoff(
            resolve_data_path(data["structure_file"]),
            replacement_sequence=[Element.from_Z(i).symbol for i in range(1, 119)],
            convert_to_primatice=data["structure_convert_to_primitive"].upper() in {"Y", "YES"},
            output_file=resolve_data_path(data["structure_out_file"]))
        model = data["tdb_model"]
        try:
            holders = [placeholders[ord(letter) - ord("A")] for letter in model["site_holder"]]
        except IndexError as exc:
            raise ValueError("site_holder refers to a nonexistent Wyckoff group") from exc
        counts = structure.composition.get_el_amt_dict()
        if set(holders) != set(counts):
            raise ValueError("site_holder must cover all structure site groups")
        actual = np.array([counts[h] for h in holders], dtype=float)
        expected = np.array(model["occup_atoms_in_tdb"], dtype=float)
        if not np.allclose(actual / actual.sum(), expected / expected.sum()):
            raise ValueError("Sublattice site ratios disagree with the supplied structure")
        phase = Phase(0, data["phase_name"], structure, model, record)
        phase.tdb_model["site_holder"] = holders
        phase.random_seed = data["random_seed"]
        phase.X_table_init(
            settings["ML_model"], settings["ML_hyper_parameters"], settings["ML_style"],
            self._build_eigen_table(settings["descriptor"]), settings["eigen_weight"],
            settings["normalizer"], resolve_data_path(settings["generate_DFT_path"]),
            resolve_data_path(settings["calced_DFT_path"]), resolve_data_path(settings["pkl_phase_path"]),
            settings["pkl_show_control"], settings["quest"])
        initial = random.Random(data["random_seed"]).sample(phase.pool, min(data["init_random_n"], len(phase.pool)))
        for species in phase.tdb_model["sys_species"]:
            pure = ":".join([species] * len(model["comp"]))
            if pure in phase.pool:
                initial.append(pure)
        phase.upload(list(dict.fromkeys(initial)))
        record.mkdir(parents=True, exist_ok=True)
        if not (record / "iter.csv").exists():
            pd.DataFrame(columns=["training_data_amount", "RMSE(train)", "RMSE(test)",
                                  "fold_num_r2", "r2_score", "fold_num_rmse", "RMSE_score"]).to_csv(record / "iter.csv", index=False)
        return phase

    def _checkpoint(self):
        folder = resolve_data_path(self.data["AL_set"]["pkl_phase_path"])
        filename = folder / f"model_{self.iter:06d}_{self.process}.pd"
        self.phase.save(filename)
        record = resolve_data_path(self.data["record_path"])
        # The manifest is authoritative and only references an already complete file.
        atomic_json(record / "checkpoint.json", {
            "version": 2, "iter": self.iter, "process": self.process,
            "checkpoint": filename.name, "config": self.data, "input_hashes": self.input_hashes})
        with (record / "record.txt").open("a", encoding="utf-8") as stream:
            stream.write(f"{self.iter} {self.process}\n")

    def _restore(self):
        record = resolve_data_path(self.data["record_path"])
        manifest = record / "checkpoint.json"
        if manifest.exists():
            state = json.loads(manifest.read_text(encoding="utf-8"))
            if state.get("version") != 2 or state.get("config") != self.data:
                raise ValueError("Configuration differs from this checkpoint; use a new run directory")
            self.input_hashes = input_hashes(self.data)
            if state.get("input_hashes") != self.input_hashes:
                raise ValueError("Input files changed since the checkpoint; use a new run directory")
            self.iter, self.process = int(state["iter"]), int(state["process"])
            filename = f"model_{self.iter:06d}_{self.process}.pd"
            if state["checkpoint"] != filename or self.process not in {0, 1, 2, 3}:
                raise ValueError("Invalid checkpoint manifest")
            self.phase = Phase.load(resolve_data_path(self.data["AL_set"]["pkl_phase_path"]) / filename)
            return True
        if (record / "record.txt").exists():
            raise ValueError("Legacy run has no verified checkpoint manifest; use a new run directory")
        return False

    def read_last_line(self, file_path=""):
        path = Path(file_path) if file_path else resolve_data_path(self.data["record_path"]) / "record.txt"
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return 0, 0
        return tuple(map(int, lines[-1].split()))

    def output_tdb_file(self, user, mask, data_file=""):
        config_path = Path(data_file) if data_file else self.input_json
        data = TaskConfig.model_validate_json(config_path.read_text(encoding="utf-8")).model_dump()
        record = resolve_data_path(data["record_path"])
        state = json.loads((record / "checkpoint.json").read_text(encoding="utf-8"))
        if state.get("config") != data or state.get("version") != 2:
            raise ValueError("Configuration and checkpoint do not match")
        if state.get("input_hashes") != input_hashes(data):
            raise ValueError("Input files changed since the checkpoint")
        result = tdb_generate_from_MLmodel(
            resolve_data_path(data["AL_set"]["pkl_phase_path"]), iter=state["iter"],
            process=state["process"], user=user, mask=mask,
            file_path=record / "tdb_file" / f"export_{uuid.uuid4().hex[:12]}")
        return {"input_data": config_path, **result}

    def release(self):
        if self.lease is not None:
            self.lease.release()
            self.lease = None

    async def initialize(self):
        if self.initialized:
            return
        self.data = TaskConfig.model_validate_json(self.input_json.read_text(encoding="utf-8")).model_dump()
        if self.lease is None:
            self.lease = RunLease(self.data).acquire()
        if not await self._run_sync(self._restore):
            self.phase = await self._run_sync(self.init_process, self.data)
            self.iter, self.process = 0, 1
            await self._run_sync(self._checkpoint)
        self.initialized = True
        self.completed = self.process == 3

    async def advance_once(self):
        """Commit one stage, or return False without waiting for missing DFT data."""
        await self.initialize()
        if self.process == 3:
            self.completed = True
            return False
        if self.process == 1:
            result = resolve_data_path(self.data["AL_set"]["calced_DFT_path"]) / f"iter.{self.iter:06d}" / "calc.txt"
            if not result.exists():
                return False
            manifest = resolve_data_path(self.data["AL_set"]["generate_DFT_path"]) / str(self.iter) / "tasks.json"
            expected = ([task["endmember"] for task in json.loads(manifest.read_text(encoding="utf-8"))["tasks"]]
                        if manifest.exists() else None)
            await self._run_sync(self.phase.add_calced_points, result, expected)
            self.process = 2
        elif self.process == 2:
            await self._run_sync(self.phase.ML)
            self.iter += 1
            self.phase.iter = self.iter
            self.process = 0
        elif self.process == 0:
            await self._run_sync(self.phase.convex_analy)
            count = await self._run_sync(self.phase.generate_DFT_POSCAR)
            self.process = 1 if count else 3
        await self._run_sync(self._checkpoint)
        self.completed = self.process == 3
        await self.send_message({"type": "status", "iter": self.iter, "process": self.process,
                                "status": "completed" if self.completed else "running"})
        return True

    async def main_loop(self):
        self.running = self.started = True
        try:
            if self.stop_event.is_set():
                return
            await self.initialize()
            while not self.stop_event.is_set() and not self.completed:
                if self.paused:
                    await asyncio.sleep(.1)
                    continue
                if not await self.advance_once():
                    await asyncio.sleep(.2)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Task %s failed", self.task_id)
            self.error = str(exc)
            await self.send_message({"type": "error", "content": self.error})
        finally:
            self.running = self.started = False
            self.release()
            await self.send_message({"type": "status", "status": "failed" if self.error else ("completed" if self.completed else "stopped"),
                                     "iter": self.iter, "process": self.process})
