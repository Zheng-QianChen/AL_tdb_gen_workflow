import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from altdb.cli import main
from config import resolve_data_path
from examples.demo import ENERGY, REFERENCE
from src.run_lock import RunLease, is_running
from src.thermodynamics import EV_PER_ATOM_TO_KJ_PER_MOL


def cli(capsys, *args):
    code = main(["--json", *map(str, args)])
    output = capsys.readouterr()
    return code, json.loads(output.out)


def test_cli_roundtrip_resumes_and_exports(demo, tmp_path, capsys):
    path, data = demo
    assert cli(capsys, "validate", path)[0] == 0
    code, state = cli(capsys, "run", path)
    assert code == 10 and state["status"] == "waiting" and not state["running"]
    for _ in range(5):
        rows = []
        for task in state["tasks"]:
            member = task["endmember"]
            reference = sum(REFERENCE[e] for e in member.split(":")) / 2
            total = (reference + ENERGY[member] / EV_PER_ATOM_TO_KJ_PER_MOL) * task["natoms"]
            rows.append(f"{member},{total:.17g},{total:.17g}\n")
        source = tmp_path / "results.txt"
        source.write_text("".join(rows), encoding="utf-8")
        assert cli(capsys, "import-results", path, source)[0] == 0
        assert cli(capsys, "import-results", path, source)[0] == 0
        code, state = cli(capsys, "run", path)
        if code == 0:
            break
        assert code == 10
    assert state["status"] == "completed" and state["iteration"] >= 2
    assert cli(capsys, "run", path)[1]["status"] == "completed"
    code, exported = cli(capsys, "export", path)
    assert code == 0 and Path(exported["tdb"]).is_file()
    from src.class_def import Phase
    from src.workflow import read_checkpoint, load_config
    config = load_config(path)[1]
    checkpoint = read_checkpoint(config)
    phase = Phase.load(resolve_data_path(data["AL_set"]["pkl_phase_path"]) / checkpoint["checkpoint"])
    assert phase.calc_points["Energy"].to_dict() == pytest.approx(ENERGY)


def test_cli_step_and_partial_import(demo, tmp_path, capsys):
    path, _ = demo
    code, first = cli(capsys, "step", path)
    assert code == 0 and first["process"] == 1
    assert len(first["tasks"]) > 1
    partial = tmp_path / "partial.txt"
    partial.write_text(f"{first['tasks'][0]['endmember']},-8,-8\n")
    code, failed = cli(capsys, "import-results", path, partial)
    assert code == 2 and "exactly" in failed["error"]
    assert not Path(first["calc_file"]).exists()
    assert cli(capsys, "step", path)[1]["process"] == 1
    assert cli(capsys, "run", path, "--max-steps", "0")[0] == 2
    # Bypassing import-results must not allow a partial batch into training.
    published = Path(first["calc_file"])
    published.parent.mkdir(parents=True, exist_ok=True)
    published.write_text(partial.read_text())
    code, failed = cli(capsys, "step", path)
    assert code == 2 and "exactly" in failed["error"]
    assert cli(capsys, "status", path)[1]["process"] == 1


def test_real_child_cli_json_and_cross_process_lease(demo):
    path, data = demo
    # Exercise the real entry point, stdout encoding, and an OS-level lock.
    def child(*args):
        return subprocess.run([sys.executable, "-X", "utf8", "-m", "altdb", "--json", *map(str, args)],
                              cwd=Path(__file__).resolve().parents[1], capture_output=True,
                              encoding="utf-8", timeout=45, env=os.environ.copy())
    with RunLease(data):
        assert is_running(resolve_data_path(data["record_path"]))
        status = child("status", path)
        assert status.returncode == 0 and json.loads(status.stdout)["running"]
        busy = child("run", path)
        assert busy.returncode == 3 and json.loads(busy.stdout)["type"] == "RunBusyError"
    resumed = child("run", path)
    assert resumed.returncode == 10, resumed.stderr + resumed.stdout
    assert not json.loads(resumed.stdout)["running"]


@pytest.mark.parametrize("size", [(110, 40), (80, 24)])
def test_tui_buttons_and_busy_guard(demo, size):
    from altdb.tui import WorkflowApp
    from textual.widgets import DataTable

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        gibbs_started = asyncio.Event()
        calls = []
        state = {"phase": "DEMO_B2", "status": "waiting", "iteration": 0,
                 "tasks": [{"task_id": "task.000000", "endmember": "AL:NI", "natoms": 2}]}

        async def fake(arguments):
            calls.append(arguments)
            if arguments[0] == "run":
                entered.set()
                await release.wait()
            elif arguments[0] == "gibbs":
                gibbs_started.set()
            return (10 if arguments[0] == "run" else 0), state, ""

        app = WorkflowApp(demo[0], machine="machine.json", command_runner=fake)
        async with app.run_test(size=size) as pilot:
            assert app.query_one("#tasks", DataTable).row_count == 1
            await pilot.click("#run")
            await asyncio.wait_for(entered.wait(), 5)
            await pilot.click("#step")
            assert app.busy and not any(c[0] == "step" for c in calls)
            release.set()
            await app.workers.wait_for_complete()
            for button in ("prepare", "submit", "collect", "export"):
                await pilot.click("#" + button)
                await app.workers.wait_for_complete()
            assert [c[1] for c in calls if c[0] == "fp"] == ["prepare", "submit", "collect"]
            assert any(c[0] == "export" for c in calls)
            assert not app.busy
            await pilot.click("#gibbs")
            await pilot.pause()
            from textual.widgets import Input
            app.screen.query_one("#gibbs-request", Input).value = "curve.json"
            await pilot.pause()
            await pilot.click("#gibbs-confirm")
            # Dismissing a modal schedules its callback; it may not have
            # created the worker yet when click() returns.
            await asyncio.wait_for(gibbs_started.wait(), 5)
            await app.workers.wait_for_complete()
            assert ["gibbs", "curve.json", "--config", str(demo[0])] in calls
            # Textual ignores another click during its 0.2 s active animation;
            # our fake command can finish much faster than a real subprocess.
            await pilot.pause(.25)
            await pilot.click("#gibbs")
            await pilot.pause()
            before = len([c for c in calls if c[0] != "status"])
            await pilot.click("#gibbs-cancel")
            await pilot.pause()
            assert len([c for c in calls if c[0] != "status"]) == before
    asyncio.run(exercise())


def test_tui_real_status_subprocess(demo):
    from altdb.tui import invoke_cli
    code, state, diagnostics = asyncio.run(invoke_cli(["status", str(demo[0])]))
    assert code == 0, diagnostics
    assert state["status"] == "new" and state["config"] == str(demo[0])
