"""Terminal UI runs the same CLI commands in isolated child processes."""
import asyncio
import json
from pathlib import Path
import sys

from textual.app import App, ComposeResult
from textual.containers import Grid, Vertical, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, RichLog, Static


async def invoke_cli(arguments):
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-X", "utf8", "-m", "altdb", "--json", *arguments,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    text = stdout.decode("utf-8", errors="replace").strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = {"status": "error", "error": text or stderr.decode("utf-8", errors="replace")}
    return process.returncode, result, stderr.decode("utf-8", errors="replace")


class GibbsDialog(ModalScreen):
    DEFAULT_CSS = """
    GibbsDialog { align: center middle; }
    #gibbs-dialog { width: 70; height: 13; padding: 1 2; border: solid $primary; background: $surface; }
    #gibbs-dialog Static { height: 3; }
    #gibbs-dialog Horizontal { height: 3; margin-top: 1; }
    #gibbs-dialog Button { margin-right: 2; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, diagram=False):
        super().__init__()
        self.diagram = diagram

    def compose(self):
        with Vertical(id="gibbs-dialog"):
            yield Static("Multi-phase equilibrium / phase diagrams.\nEnter a diagram request JSON including competing-phase TDB files."
                         if self.diagram else "Gibbs G-x / G-T curves for this workflow.\nEnter a request JSON with reference TDB files and curve conditions.")
            yield Input(placeholder="Path to gibbs-request.json", id="gibbs-request")
            with Horizontal():
                yield Button("Calculate", id="gibbs-confirm", variant="primary")
                yield Button("Cancel", id="gibbs-cancel")

    def action_cancel(self):
        self.dismiss(None)

    def on_button_pressed(self, event):
        event.stop()
        if event.button.id == "gibbs-cancel":
            self.dismiss(None)
        else:
            value = self.query_one("#gibbs-request", Input).value.strip()
            if value:
                self.dismiss(value)


class WorkflowApp(App):
    TITLE = "AL-TDB | Workflow & First Principles"
    CSS = """
    #summary { height: 5; padding: 1 2; background: $panel; }
    #machine { margin: 1 1 0 1; }
    #actions { grid-size: 4 2; grid-rows: 3; height: 9; padding: 1; grid-gutter: 1; }
    #actions Button { width: 100%; }
    #tasks { height: 1fr; min-height: 5; margin: 0 1; }
    #events { height: 8; border: solid $primary; margin: 1; }
    .compact #summary { height: 3; padding: 0 1; }
    .compact #machine { margin: 0 1; }
    .compact #actions { height: 6; padding: 0 1; grid-gutter: 0 1; }
    .compact #tasks { min-height: 3; }
    .compact #events { height: 4; margin: 0 1; }
    """
    BINDINGS = [("r", "run_round", "Run"), ("s", "step", "Step"), ("g", "gibbs", "Gibbs"), ("p", "phase_diagram", "Phase diagram"), ("f5", "refresh", "Refresh"),
                ("q", "request_quit", "Quit"), ("ctrl+c", "request_quit", "Quit")]

    def __init__(self, config, machine=None, command_runner=None):
        super().__init__()
        from src.workflow import load_config
        self.config = str(load_config(config)[0])
        self.machine = str(Path(machine).expanduser().resolve()) if machine else ""
        self.command_runner = command_runner or invoke_cli
        self.busy = False
        self.refreshing = False
        self.last_state = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Loading committed state…", id="summary", markup=False)
        yield Input(value=self.machine, placeholder="machine.json path (VASP + Slurm)", id="machine")
        with Grid(id="actions"):
            for label, name in [("Run to next batch", "run"), ("One step", "step"),
                                ("Prepare FP", "prepare"), ("Submit / Sync FP", "submit"),
                                ("Collect results", "collect"), ("Export TDB", "export"),
                                ("Gibbs curves", "gibbs"), ("Phase diagram", "phase-diagram")]:
                yield Button(label, id=name)
        yield DataTable(id="tasks")
        yield RichLog(id="events", markup=False, wrap=True)
        yield Footer()

    async def on_mount(self):
        self.query_one("#tasks", DataTable).add_columns("Task", "Endmember", "Atoms", "FP status")
        await self.refresh_state()
        self.set_interval(3, self.refresh_state)

    def on_resize(self, event):
        self.set_class(event.size.height < 36, "compact")

    async def refresh_state(self):
        if self.refreshing:
            return
        self.refreshing = True
        try:
            _, state, _ = await self.command_runner(["status", self.config])
            self.last_state = state
            dispatch = state.get("dispatch", {}).get("status", "not submitted")
            self.query_one("#summary", Static).update(
                f"{state.get('phase', 'AL-TDB')}  |  iteration {state.get('iteration', '-')}  |  "
                f"{state.get('status', 'unknown')}  |  {'active writer' if state.get('running') else 'idle'}\n"
                f"FP: {dispatch}  |  validated {state.get('collection', {}).get('valid', 0)}/{len(state.get('tasks', []))}\n"
                f"{state.get('error', self.config)}")
            table = self.query_one("#tasks", DataTable)
            table.clear()
            collection = state.get("collection", {})
            good = {row["task_id"] for row in collection.get("records", [])}
            bad = {row["task_id"] for row in collection.get("failures", [])}
            prepared = {row["task_id"] for row in state.get("fp", {}).get("tasks", [])}
            for row in state.get("tasks", []):
                task = row["task_id"]
                label = ("validated" if task in good else "missing / invalid" if task in bad
                         else "retrieved" if task in prepared and dispatch == "finished"
                         else "submitted" if task in prepared and dispatch == "submitted"
                         else "prepared" if task in prepared else "generated")
                table.add_row(task, row["endmember"], str(row["natoms"]), label)
        except (OSError, ValueError) as exc:
            self.query_one("#summary", Static).update(f"Unable to read workflow: {exc}")
        finally:
            self.refreshing = False

    def launch(self, arguments):
        if self.busy:
            self.notify("Wait for the current operation to finish", severity="warning")
            return
        self.busy = True
        self.run_worker(self.execute_command(arguments), group="operation")

    async def execute_command(self, arguments):
        log = self.query_one("#events", RichLog)
        log.write("altdb " + " ".join(arguments))
        try:
            code, result, diagnostics = await self.command_runner(arguments)
            fields = ("status", "iteration", "steps_committed", "task_count", "valid", "invalid")
            log.write(" | ".join(f"{key}: {result[key]}" for key in fields if key in result))
            for key in ("error", "message", "tdb", "report", "directory"):
                if key in result:
                    log.write(str(result[key]))
            for failure in result.get("failures", []):
                log.write(f"{failure['endmember']}: {failure['error']}")
            for kind, path in result.get("files", {}).items():
                log.write(f"{kind.upper()}: {path}")
            if code not in {0, 10} and diagnostics:
                log.write(diagnostics[-3000:])
        except (OSError, ValueError) as exc:
            log.write(f"Operation failed: {exc}")
        finally:
            self.busy = False
            await self.refresh_state()

    def action_run_round(self):
        self.launch(["run", self.config])

    def action_step(self):
        self.launch(["step", self.config])

    def action_gibbs(self):
        if self.busy:
            self.notify("Wait for the current operation to finish", severity="warning")
            return
        def chosen(path):
            if path:
                self.launch(["gibbs", path, "--config", self.config])
        self.push_screen(GibbsDialog(), chosen)

    def action_phase_diagram(self):
        if self.busy:
            self.notify("Wait for the current operation to finish", severity="warning")
            return
        def chosen(path):
            if path:
                self.launch(["phase-diagram", path, "--config", self.config])
        self.push_screen(GibbsDialog(diagram=True), chosen)

    async def action_refresh(self):
        await self.refresh_state()

    def action_request_quit(self):
        if self.busy:
            self.notify("Current operation is finishing; its checkpoint must be saved before quitting", severity="warning")
        else:
            self.exit()

    async def on_button_pressed(self, event: Button.Pressed):
        action = event.button.id
        if action == "run":
            self.action_run_round()
        elif action == "step":
            self.action_step()
        elif action == "refresh":
            await self.refresh_state()
        elif action == "quit":
            self.action_request_quit()
        elif action == "export":
            self.launch(["export", self.config])
        elif action == "gibbs":
            self.action_gibbs()
        elif action == "phase-diagram":
            self.action_phase_diagram()
        elif action == "collect":
            self.launch(["fp", "collect", self.config])
        else:
            machine = self.query_one("#machine", Input).value.strip()
            if not machine:
                self.notify("Provide the machine.json path first", severity="warning")
                return
            self.launch(["fp", action, self.config, machine])


class PhaseDiagramApp(App):
    """A TDB-only terminal workflow does not require an AL training checkpoint."""
    TITLE = "AL-TDB | Multi-phase equilibrium & phase diagrams"
    CSS = """
    #diagram-input { height: 3; margin: 1; }
    #diagram-actions { height: 3; margin: 0 1; }
    #diagram-status { height: 3; padding: 0 1; }
    #diagram-results { height: 1fr; margin: 0 1; }
    #diagram-log { height: 7; border: solid $primary; margin: 1; }
    """
    BINDINGS = [("r", "calculate", "Calculate"), ("q", "request_quit", "Quit")]

    def __init__(self, request="", command_runner=None):
        super().__init__()
        self.request_path = request
        self.command_runner = command_runner or invoke_cli
        self.busy = False

    def compose(self):
        yield Header()
        yield Input(value=self.request_path, placeholder="Path to phase-diagram-request.json", id="diagram-input")
        with Horizontal(id="diagram-actions"):
            yield Button("Calculate", id="diagram-run", variant="primary")
            yield Button("Quit", id="diagram-quit")
        yield Static("Select a request JSON. TDB files must be inside the application data directory.", id="diagram-status", markup=False)
        yield DataTable(id="diagram-results")
        yield RichLog(id="diagram-log", markup=False, wrap=True)
        yield Footer()

    def on_mount(self):
        self.query_one(DataTable).add_columns("Point", "T (K)", "Bulk composition", "Assemblage", "G (J/mol-atoms)", "Audit")

    def action_calculate(self):
        if self.busy:
            return
        path = self.query_one("#diagram-input", Input).value.strip()
        if not path:
            self.notify("Enter a request JSON path", severity="warning")
            return
        self.busy = True
        self.query_one("#diagram-run", Button).disabled = True
        self.query_one("#diagram-status", Static).update("Calculating multi-phase equilibria and tracing boundaries…")
        self.run_worker(self.calculate(path), group="diagram")

    async def calculate(self, path):
        log = self.query_one("#diagram-log", RichLog)
        try:
            code, result, diagnostics = await self.command_runner(["phase-diagram", path])
            self.query_one("#diagram-status", Static).update(
                f"{result.get('status', 'error')} | {result.get('summary', result.get('error', ''))}")
            table = self.query_one(DataTable)
            table.clear()
            if "json" in result.get("files", {}):
                saved = json.loads(Path(result["files"]["json"]).read_text(encoding="utf-8"))
                for row in saved["rows"]:
                    composition = ", ".join(f"{c}={x:.4g}" for c, x in row["composition"].items())
                    energy = f"{row['G_J_mol_atoms']:.8g}" if "G_J_mol_atoms" in row else "—"
                    table.add_row(str(row["point_id"]), f"{row['T_K']:g}", composition, row["assemblage"], energy,
                                  "refine" if row.get("needs_refinement") else row["status"])
            for kind, file in result.get("files", {}).items():
                log.write(f"{kind.upper()}: {file}")
            if code:
                log.write(result.get("error", "Partial result: inspect failed points and mapping diagnostics."))
                log.write(diagnostics[-2000:])
        except (OSError, ValueError) as exc:
            self.query_one("#diagram-status", Static).update(str(exc))
        finally:
            self.busy = False
            self.query_one("#diagram-run", Button).disabled = False

    def action_request_quit(self):
        if self.busy:
            self.notify("Wait for the calculation to finish", severity="warning")
        else:
            self.exit()

    def on_button_pressed(self, event):
        if event.button.id == "diagram-run":
            self.action_calculate()
        elif event.button.id == "diagram-quit":
            self.action_request_quit()
