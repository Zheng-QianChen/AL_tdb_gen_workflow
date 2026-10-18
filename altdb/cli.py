"""Script-friendly CLI: JSON on stdout, diagnostics on stderr."""
import argparse
import asyncio
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import signal
import sys


def parser():
    root = argparse.ArgumentParser(prog="python -m altdb", description="AL TDB workflow, terminal and first-principles task management")
    root.add_argument("--data-dir", help="Data root; defaults to AL_TDB_DATA_DIR or repository data/")
    root.add_argument("--json", action="store_true", help="Machine-readable JSON on stdout")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("validate", "status", "step"):
        commands.add_parser(name).add_argument("config")
    run = commands.add_parser("run", help="Advance to the next missing DFT batch, or completion")
    run.add_argument("config")
    run.add_argument("--watch", action="store_true", help="Wait for incoming results and keep advancing")
    run.add_argument("--max-steps", type=int)
    run.add_argument("--poll-interval", type=float, default=2)
    pipeline = commands.add_parser("pipeline", help="Run AL, prepare/submit/wait/collect FP, and repeat until complete")
    pipeline.add_argument("config")
    pipeline.add_argument("machine")
    gibbs = commands.add_parser("gibbs", help="Calculate homogeneous-phase G-x or G-T curves")
    gibbs.add_argument("request", help="Gibbs request JSON")
    gibbs.add_argument("--config", help="Use this workflow checkpoint and the request's reference TDB files")
    diagram = commands.add_parser("phase-diagram", help="Multi-phase equilibrium: binary, ternary, isopleth, property or point")
    diagram.add_argument("request", help="Phase diagram request JSON; exit code 6 means partial/unconfirmed results")
    diagram.add_argument("--config", help="Include a trained workflow phase alongside the request's competing-phase TDBs")
    diagram_tui = commands.add_parser("phase-diagram-tui", help="Standalone terminal interface for phase diagrams")
    diagram_tui.add_argument("request", nargs="?", default="", help="Optional initial request JSON path")
    reference = commands.add_parser("gibbs-reference", help="Prepare blank external single-point reference CSV and comparison request")
    reference.add_argument("result", help="Saved gibbs.json within the data directory")
    comparison = commands.add_parser("gibbs-compare", help="Compare imported Pandat/Thermo-Calc single-point results")
    comparison.add_argument("request", help="Comparison request JSON; exit code 5 means differences exceed tolerance")
    export = commands.add_parser("export")
    export.add_argument("config")
    export.add_argument("--mask", type=float, default=5)
    export.add_argument("--user", default="cli")
    imported = commands.add_parser("import-results", help="Validate and publish a complete calc.txt batch")
    imported.add_argument("config")
    imported.add_argument("source")
    demo = commands.add_parser("init-demo", help="Create inputs for a small synthetic example")
    demo.add_argument("--name")
    terminal = commands.add_parser("tui", help="Open the optional Textual terminal interface")
    terminal.add_argument("config")
    terminal.add_argument("--machine", help="FP environment JSON")
    fp = commands.add_parser("fp", help="Prepare, submit/recover, and collect first-principles tasks")
    actions = fp.add_subparsers(dest="fp_action", required=True)
    make = actions.add_parser("prepare")
    make.add_argument("config")
    make.add_argument("machine")
    submit = actions.add_parser("submit")
    submit.add_argument("config")
    submit.add_argument("machine")
    submit.add_argument("--dry-run", action="store_true", help="Local plan only; no SSH, upload or submission")
    submit.add_argument("--wait", action="store_true", help="Monitor until finished and retrieve outputs")
    submit.add_argument("--iteration", type=int)
    collect = actions.add_parser("collect")
    collect.add_argument("config")
    collect.add_argument("--iteration", type=int)
    return root


async def run_workflow(args):
    from src.main_process.al_worker import ALRunner
    from src.workflow import load_config, read_checkpoint, status
    path, data = load_config(args.config)
    had_checkpoint = read_checkpoint(data) is not None
    runner = ALRunner("cli", path)
    previous = {}
    interrupted = False

    def request_stop(signum, frame):
        nonlocal interrupted
        interrupted = True
        runner.stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, request_stop)
    try:
        await runner.initialize()
        steps = 0
        if args.command == "step" and not had_checkpoint:
            report = status(path)
            if interrupted:
                report["status"] = "interrupted"
            return (130 if interrupted else 0), report
        while not runner.completed and not runner.stop_event.is_set():
            advanced = await runner.advance_once()
            steps += int(advanced)
            if args.command == "step":
                break
            if args.max_steps is not None and steps >= args.max_steps:
                break
            if not advanced:
                if not args.watch:
                    break
                await asyncio.sleep(args.poll_interval)
        report = status(path)
        report["steps_committed"] = steps
        if interrupted:
            report["status"] = "interrupted"
            return 130, report
        return (10 if args.command == "run" and report["status"] == "waiting" and not report.get("results_ready") else 0), report
    finally:
        runner.release()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def execute(args):
    from src.workflow import load_config, read_checkpoint, status
    if args.command == "phase-diagram":
        from src.phase_diagram import run_diagram
        data = json.loads(Path(args.request).read_text(encoding="utf-8-sig"))
        if args.config:
            data["config"] = args.config
        def progress(state):
            print(f"{state['stage']}: {state['completed']}/{state['total']}", file=sys.stderr, flush=True)
        result = run_diagram(data, progress)
        compact = {key: value for key, value in result.items() if key not in {"rows", "boundaries"}}
        compact["boundaries"] = {key: value for key, value in result["boundaries"].items() if key not in {"lines", "invariants"}}
        return (0 if result["status"] == "calculated" else 6), compact
    if args.command == "gibbs-reference":
        from src.gibbs_compare import prepare_reference
        return 0, prepare_reference(args.result)
    if args.command == "gibbs-compare":
        from src.gibbs_compare import run_comparison
        data = json.loads(Path(args.request).read_text(encoding="utf-8-sig"))
        result = run_comparison(data)
        return (0 if result["status"] == "within_tolerance" else 5), {k: v for k, v in result.items() if k != "rows"}
    if args.command == "gibbs":
        from src.gibbs import run_curve
        data = json.loads(Path(args.request).read_text(encoding="utf-8"))
        if args.config:
            data["config"] = args.config
        result = run_curve(data)
        return 0, {key: value for key, value in result.items() if key != "rows"}
    if args.command == "init-demo":
        from examples.demo import prepare_demo
        from config import safe_name
        if args.name:
            safe_name(args.name)
        path, data = prepare_demo(args.name)
        return 0, {"status": "created", "config": str(path), "phase": data["phase_name"], "synthetic": True}
    if args.command == "validate":
        from src.workflow import input_hashes
        path, data = load_config(args.config)
        hashes = input_hashes(data)
        read_checkpoint(data)
        return 0, {"status": "valid", "config": str(path), "input_hashes": hashes}
    if args.command == "status":
        return 0, status(args.config)
    if args.command == "pipeline":
        from src.fp import prepare, dispatch, collect
        run_args = argparse.Namespace(command="run", config=args.config, watch=False,
                                      max_steps=None, poll_interval=2)
        while True:
            code, state = asyncio.run(run_workflow(run_args))
            state["running"] = False
            if code != 10:
                return code, state
            print(f"Preparing FP iteration {state['iteration']}", file=sys.stderr)
            prepare(args.config, args.machine)
            dispatch(args.config, args.machine, wait=True)
            collected = collect(args.config)
            if collected["status"] != "ready":
                return 4, collected
    if args.command in {"run", "step"}:
        if args.command == "run" and (args.poll_interval <= 0 or (args.max_steps is not None and args.max_steps < 1)):
            raise ValueError("poll-interval and max-steps must be positive")
        code, result = asyncio.run(run_workflow(args))
        result["running"] = False
        return code, result
    if args.command == "export":
        from src.main_process.al_worker import ALRunner
        path, _ = load_config(args.config)
        result = ALRunner("cli", path).output_tdb_file(args.user, args.mask)
        return 0, {"status": "exported", "tdb": str(result["file_path"] / result["file_name_tdb"]),
                   "report": str(result["file_path"] / result["file_name_csv"])}
    if args.command == "import-results":
        from src.fp import import_results
        return 0, import_results(args.config, args.source)
    if args.command == "fp":
        from src.fp import prepare, dispatch, collect
        if args.fp_action == "prepare":
            return 0, prepare(args.config, args.machine)
        if args.fp_action == "submit":
            return 0, dispatch(args.config, args.machine, wait=args.wait,
                               dry_run=args.dry_run, iteration=args.iteration)
        result = collect(args.config, iteration=args.iteration)
        return (4 if result["status"] == "pending" else 0), result
    raise ValueError("Unsupported command")


def main(argv=None):
    args = parser().parse_args(argv)
    if args.json and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.data_dir:
        os.environ["AL_TDB_DATA_DIR"] = str(Path(args.data_dir).expanduser().resolve())
    if args.command in {"tui", "phase-diagram-tui"}:
        try:
            from altdb.tui import WorkflowApp, PhaseDiagramApp
            if args.command == "phase-diagram-tui":
                PhaseDiagramApp(args.request).run()
            else:
                WorkflowApp(args.config, machine=args.machine).run()
            return 0
        except ImportError as exc:
            print(f"Install requirements-terminal.txt: {exc}", file=sys.stderr)
            return 2
        except (ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
    try:
        # Existing numerical modules print progress. Keep stdout a single JSON
        # document so pipes, cron and scheduler scripts can reliably consume it.
        with redirect_stdout(sys.stderr):
            code, result = execute(args)
    except KeyboardInterrupt:
        code, result = 130, {"status": "interrupted", "message": "Re-run to recover; remote jobs are not cancelled"}
    except Exception as exc:
        from src.run_lock import RunBusyError
        from filelock import Timeout
        code = 3 if isinstance(exc, (RunBusyError, Timeout)) else 2 if isinstance(exc, (ValueError, OSError, ImportError)) else 1
        result = {"status": "error", "error": str(exc), "type": type(exc).__name__}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, default=str))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False, default=str))
    return code
