import asyncio
import json
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
from pycalphad import Database
from examples.demo import ENERGY, write_synthetic_results
from src.class_def import Phase
from src.main_process.al_manager import ALManager
from src.main_process.al_worker import ALRunner
from src.storage import atomic_write
from tests.test_tdb import BASE


async def until(predicate, seconds=30):
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(.02)


def test_complete_resume_and_export(demo):
    async def exercise():
        path, data = demo
        manager = ALManager()
        try:
            await manager.create_and_start_task("test", path)
            first = manager.tasks["test"]
            await until(lambda: first.phase is not None and first.process == 1 or first.error)
            assert first.error is None
            # Stop while waiting for DFT, restore with the same committed state.
            await first.stop()
            assert not first.running
            await manager.create_and_start_task("test", path, restart=True)
            runner = manager.tasks["test"]
            await until(lambda: runner.phase is not None or runner.error)
            assert runner.error is None
            assert runner.phase.pool == first.phase.pool
            async with asyncio.timeout(60):
                while runner.running:
                    if runner.phase is not None and runner.process == 1:
                        target = Path(runner.phase.calced_DFT_path) / f"iter.{runner.iter:06d}" / "calc.txt"
                        if not target.exists():
                            write_synthetic_results(runner)
                    await asyncio.sleep(.05)
                await runner.main_task
            assert runner.error is None
            assert runner.completed
            assert runner.iter >= 2
            values = runner.phase.calc_points["Energy"]
            for member, expected in ENERGY.items():
                assert values[member] == pytest.approx(expected, abs=1e-8)
            manifest = json.loads((runner.phase.record_path / "checkpoint.json").read_text())
            assert (runner.phase.pkl_phase_path / manifest["checkpoint"]).is_file()
            saved = Phase.load(runner.phase.pkl_phase_path / manifest["checkpoint"])
            np.testing.assert_allclose(saved.calc_points["Energy"], values)
            result = await runner._run_sync(runner.output_tdb_file, "test", 0)
            db = Database(BASE + (result["file_path"] / result["file_name_tdb"]).read_text())
            assert "DEMO_B2" in db.phases
            assert len(db._parameters.all()) == 4
            second_export = await runner._run_sync(runner.output_tdb_file, "test", 0)
            assert second_export["file_path"] != result["file_path"]
            assert (result["file_path"] / result["file_name_tdb"]).is_file()
            # Export reads a snapshot, and a completed run can be reopened safely.
            assert runner.completed
            await manager.create_and_start_task("test", path, restart=True)
            restored = manager.tasks["test"]
            await restored.main_task
            assert restored.completed and restored.error is None
        finally:
            await manager.close()
    asyncio.run(exercise())


def test_stop_waits_for_sync_job_and_keeps_shared_executor(tmp_path):
    async def exercise():
        pool = ThreadPoolExecutor(max_workers=2)
        entered, release = threading.Event(), threading.Event()
        runner = ALRunner("stop", tmp_path / "input.json", pool)
        def blocked():
            entered.set()
            assert release.wait(5)
            return 42
        async def work():
            runner.running = True
            await runner._run_sync(blocked)
            runner.running = False
        try:
            runner.main_task = asyncio.create_task(work())
            await until(entered.is_set)
            stop = asyncio.create_task(runner.stop())
            await asyncio.sleep(.05)
            assert not stop.done()
            release.set()
            await stop
            assert not runner.running
            assert await asyncio.get_running_loop().run_in_executor(pool, lambda: 7) == 7
        finally:
            release.set()
            pool.shutdown()
    asyncio.run(exercise())


def test_immediate_stop_does_not_initialize(demo, monkeypatch):
    async def exercise():
        manager = ALManager()
        try:
            monkeypatch.setattr(ALRunner, "init_process", lambda *_: pytest.fail("Stopped job initialized"))
            await manager.create_and_start_task("early", demo[0])
            runner = manager.tasks["early"]
            await runner.stop()
            assert runner.phase is None
        finally:
            await manager.close()
    asyncio.run(exercise())


def test_overlapping_task_outputs_rejected(demo):
    async def exercise():
        manager = ALManager()
        try:
            await manager.create_and_start_task("one", demo[0])
            with pytest.raises(ValueError, match="overlapping"):
                await manager.create_and_start_task("two", demo[0])
            await manager.tasks["one"].stop()
        finally:
            await manager.close()
    asyncio.run(exercise())


def test_checkpoint_and_config_must_match(phase):
    phase._checkpoint()
    reader = ALRunner("reader", phase.input_json)
    reader.data = {**phase.data, "init_random_n": 100}
    with pytest.raises(ValueError, match="Configuration differs"):
        reader._restore()


def test_bad_energy_file_does_not_mutate_state(phase):
    p = phase.phase
    path = p.record_path / "bad.txt"
    atomic_write(path, "AL:NI,-8,-8\nUNKNOWN,0,0\n")
    with pytest.raises(ValueError, match="Unknown endmember"):
        p.add_calced_points(path)
    assert p.calc_points.empty
    assert p.subl_energy["in_iter"].isna().all()


def test_changed_reference_file_cannot_resume(phase):
    from config import resolve_data_path
    phase._checkpoint()
    ref = resolve_data_path(phase.data["tdb_model"]["Atom_ref"]["file"])
    ref.write_text("symbol,energy\nAl,-4\nNi,-5\n")
    with pytest.raises(ValueError, match="Input files changed"):
        phase._restore()


def test_reimport_is_idempotent(phase):
    path = write_synthetic_results(phase)
    phase.phase.add_calced_points(path)
    before = phase.phase.calc_points.copy()
    phase.phase.add_calced_points(path)
    assert len(phase.phase.y_test) == 0
    assert len(phase.phase.calc_points) == len(before)
