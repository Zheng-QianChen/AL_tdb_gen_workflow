"""Local loopback server launcher for double-click and ZIP distributions.

Creates or reuses a private virtual environment, installs the project wheel
(or editable source) with the ``fp`` and ``thermo`` extras, starts the app on
127.0.0.1, waits until a matching health check succeeds, then opens the project workbench in the browser. Does not install into the system Python site-packages.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from contextlib import contextmanager
import signal
from uuid import uuid4, UUID
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_TITLE = "AL TDB Generator"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8003
OPEN_PATH = "/projects"
HEALTH_PATH = "/health"
OPENAPI_PATH = "/openapi.json"
STATE_NAME = "launcher-state.json"
MARKER_NAME = "install-marker.json"
VENV_NAME = "venv"
SUPPORTED_MIN = (3, 11)
SUPPORTED_MAX_MINOR_SERIES = 12  # document 3.11–3.12; allow patch within series


class LauncherError(Exception):
    """User-facing failure with an actionable message."""


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def runtime_root() -> Path:
    override = os.environ.get("AL_TDB_RUNTIME_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".altdb" / "runtime").resolve()


def state_path() -> Path:
    return runtime_root() / STATE_NAME


def private_env_dir() -> Path:
    return runtime_root() / VENV_NAME


def discover_root(start: Path | None = None) -> Path:
    """Locate the bundle or source tree that owns Start-AL-TDB.cmd."""
    env = os.environ.get("AL_TDB_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = (start or Path(__file__)).resolve()
    candidates = [here.parent.parent, *here.parents]
    for root in candidates:
        if (root / "Start-AL-TDB.cmd").is_file() or (root / "pyproject.toml").is_file():
            return root
        if any((root / "wheels").glob("*.whl")):
            return root
    return here.parent.parent


def is_source_tree(root: Path) -> bool:
    return (root / "pyproject.toml").is_file() and (root / "app.py").is_file()


def bundle_wheels(root: Path) -> list[Path]:
    wheels = sorted((root / "wheels").glob("*.whl")) if (root / "wheels").is_dir() else []
    return [path for path in wheels if path.is_file()]


def resolve_base_python(explicit: str | None = None) -> Path:
    raw = explicit or os.environ.get("AL_TDB_PYTHON") or sys.executable
    path = Path(raw).expanduser()
    if not path.is_file():
        raise LauncherError(
            f"Python interpreter not found: {path}\n"
            "Install Python 3.11 or 3.12, or set AL_TDB_PYTHON to that interpreter "
            "(for example the python.exe inside a conda/venv). This launcher never "
            "downloads Python."
        )
    # A POSIX venv's python is often a symlink; keep its environment identity.
    return path.absolute()


def python_version_tuple(python: Path) -> tuple[int, int, int]:
    probe = subprocess.run(
        [str(python), "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        raise LauncherError(
            f"Could not query interpreter version: {python}\n{probe.stderr.strip()}"
        )
    parts = probe.stdout.strip().split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


def assert_supported_python(python: Path) -> tuple[int, int, int]:
    version = python_version_tuple(python)
    if version < (*SUPPORTED_MIN, 0) or version[0] != 3 or version[1] > SUPPORTED_MAX_MINOR_SERIES:
        raise LauncherError(
            f"Unsupported Python {version[0]}.{version[1]}.{version[2]} at {python}\n"
            "Use Python 3.11 or 3.12 and set AL_TDB_PYTHON to that executable."
        )
    return version


def venv_python(env_dir: Path) -> Path:
    if os.name == "nt":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_spec(root: Path) -> dict:
    if is_source_tree(root):
        resolved = root.resolve()
        return {
            "mode": "source",
            "root": str(resolved),
            "pip_args": ["-e", f"{resolved}[fp,thermo]"],
            "identity": f"source:{resolved}",
        }
    wheels = bundle_wheels(root)
    if not wheels:
        raise LauncherError(
            f"No source tree or wheels/*.whl under {root}\n"
            "Extract the full launcher bundle, or start from the repository checkout."
        )
    wheel = wheels[-1]
    return {
        "mode": "wheel",
        "root": str(root.resolve()),
        "wheel": str(wheel),
        "pip_args": [f"{wheel}[fp,thermo]"],
        "identity": f"wheel:{wheel.name}:{file_digest(wheel)}",
    }


def read_marker(env_dir: Path) -> dict | None:
    path = env_dir / MARKER_NAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_marker(env_dir: Path, payload: dict) -> None:
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / MARKER_NAME).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def ensure_private_env(base_python: Path, root: Path) -> Path:
    assert_supported_python(base_python)
    spec = install_spec(root)
    env_dir = private_env_dir()
    py = venv_python(env_dir)
    marker = read_marker(env_dir)
    needs_create = not py.is_file()
    needs_install = needs_create or not marker or marker.get("identity") != spec["identity"]
    if needs_create:
        eprint(f"Creating private environment at {env_dir}")
        env_dir.parent.mkdir(parents=True, exist_ok=True)
        if env_dir.exists() and any(env_dir.iterdir()):
            raise LauncherError(f'Incomplete runtime at {env_dir}; select a fresh AL_TDB_RUNTIME_DIR')
        created = subprocess.run(
            [str(base_python), "-m", "venv", str(env_dir)],
            check=False,
            capture_output=True,
            text=True,
        )
        if created.returncode != 0 or not py.is_file():
            raise LauncherError(
                "Failed to create a private virtual environment.\n"
                f"Command: {base_python} -m venv {env_dir}\n"
                f"{created.stderr.strip() or created.stdout.strip()}\n"
                "Ensure the chosen Python includes the venv module."
            )
    if needs_install:
        eprint(
            "Installing al-tdb-workflow[fp,thermo] into the private environment "
            "(first start or changed package)..."
        )
        prep = subprocess.run(
            [str(py), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
            check=False,
            capture_output=True,
            text=True,
        )
        if prep.returncode != 0:
            raise LauncherError(
                "Failed to upgrade pip inside the private environment.\n"
                f"{prep.stderr.strip() or prep.stdout.strip()}"
            )
        install = subprocess.run(
            [str(py), "-m", "pip", "install", "-c", str(root / "constraints-test.txt"), *spec["pip_args"]],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(root) if spec["mode"] == "source" else None,
        )
        if install.returncode != 0:
            raise LauncherError(
                "Failed to install the package into the private environment.\n"
                "Check network access for dependencies, then run the launcher again.\n"
                f"{install.stderr.strip() or install.stdout.strip()}"
            )
        write_marker(
            env_dir,
            {
                "identity": spec["identity"],
                "mode": spec["mode"],
                "root": spec["root"],
                "python": str(base_python),
                "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        eprint("Private environment ready.")
    else:
        eprint(f"Reusing private environment at {env_dir}")
    return py


def base_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def fetch_json(url: str, timeout: float = 1.5) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return None
            raw = response.read()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def port_occupied(host: str, port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def choose_port(host: str, preferred: int) -> int:
    if not port_occupied(host, preferred):
        return preferred
    for port in range(preferred + 1, preferred + 20):
        if not port_occupied(host, port):
            return port
    raise LauncherError(
        f"No free loopback port near {preferred}.\n"
        "Stop the conflicting local process or set AL_TDB_PORT to a free port.\n"
        "If another program answered HTTP on that port but is not AL TDB, it was ignored."
    )


def write_state(payload: dict) -> None:
    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    state_path().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_state() -> dict | None:
    path = state_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def clear_state() -> None:
    path = state_path()
    if path.is_file():
        path.unlink()


def find_edge() -> Path | None:
    candidates: list[Path] = []
    if sys.platform == "darwin":
        for base in (Path("/Applications"), Path.home() / "Applications"):
            candidates.append(base / "Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
    if sys.platform.startswith("linux") and shutil.which("microsoft-edge"):
        candidates.append(Path(shutil.which("microsoft-edge")))
    for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(key)
        if not base:
            continue
        candidates.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    which = shutil.which("msedge")
    if which:
        candidates.append(Path(which))
    for path in candidates:
        if path.is_file():
            return path
    return None


def open_jobs(host: str, port: int) -> None:
    url = f"{base_url(host, port)}{OPEN_PATH}"
    edge = find_edge()
    if edge is not None:
        subprocess.Popen([str(edge), "--new-window", url], close_fds=True)
        eprint(f"Opened Edge: {url}")
        return
    if os.name == "nt":
        # Fall back to the file association without claiming a successful Edge launch.
        subprocess.Popen(["cmd", "/c", "start", "", url], close_fds=True)
        eprint(f"Edge not found; opened default browser: {url}")
        return
    import webbrowser
    if not webbrowser.open_new(url):
        eprint(f"Open the workbench in your browser: {url}")


def instance_matches(state):
    if not state or state.get('host') not in {'127.0.0.1', 'localhost'}:
        return False
    token = state.get('id')
    if not isinstance(token, str) or len(token) != 32:
        return False
    try:
        if UUID(hex=token).hex != token:
            return False
    except ValueError:
        return False
    url = base_url(state['host'], state['port'])
    return fetch_json(url + '/launcher-instance') == {'id': token}


def stop_server():
    state = read_state()
    if not instance_matches(state):
        eprint('No matching launcher instance to stop.')
        return 1
    (runtime_root() / (state['id'] + '.stop')).touch()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not instance_matches(state):
            return 0
        time.sleep(.25)
    eprint('Shutdown requested. The service is finishing its active handlers.')
    return 1


@contextmanager
def startup_lock():
    runtime_root().mkdir(parents=True, exist_ok=True)
    with (runtime_root() / 'starting.lock').open('a+b') as guard:
        guard.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LauncherError('Another launch is preparing the server. Wait for that window.') from exc
        yield


def run_launch(args):
    host = args.host
    if host not in {'127.0.0.1', 'localhost'}:
        raise LauncherError('Use a loopback address (127.0.0.1 or localhost)')
    root = discover_root()
    data_dir = str(Path(args.data_dir).resolve()) if args.data_dir else ''
    spec = install_spec(root)
    with startup_lock():
        state = read_state()
        if instance_matches(state):
            if (state.get('identity'), state.get('data_dir')) != (spec['identity'], data_dir):
                raise LauncherError('Another distribution or data directory owns this runtime. Choose another AL_TDB_RUNTIME_DIR.')
            if not args.no_browser:
                open_jobs(host, state['port'])
            return 0
        base = resolve_base_python(args.python)
        if is_source_tree(root) and os.environ.get('AL_TDB_PYTHON') and subprocess.run(
                [str(base), '-c', 'import dpdata, dpdispatcher, pycalphad, websockets; from app import app'],
                cwd=root, capture_output=True).returncode == 0:
            assert_supported_python(base)
            py = base
        else:
            py = ensure_private_env(base, root)
        port = choose_port(host, args.port)
        token = uuid4().hex
        stop = runtime_root() / (token + '.stop')
        env = {**os.environ, 'AL_TDB_HOST':host, 'AL_TDB_PORT':str(port),
               'AL_TDB_INSTANCE':token, 'AL_TDB_STOP_FILE':str(stop)}
        if data_dir:
            env['AL_TDB_DATA_DIR'] = data_dir
        flags = [] if is_source_tree(root) else ['-I']
        process = subprocess.Popen([str(py), *flags, '-m', 'altdb.local_service'], cwd=root, env=env)
        state = dict(id=token, host=host, port=port, identity=spec['identity'], data_dir=data_dir)
        try:
            deadline=time.monotonic()+120
            while not instance_matches(state):
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise LauncherError('Server startup failed; inspect this console.')
                time.sleep(.25)
            write_state(state)
        except BaseException:
            stop.touch()
            raise
    try:
        if not args.no_browser:
            open_jobs(host,port)
        eprint(f"Serving {base_url(host,port)}{OPEN_PATH}. Press Ctrl+C here or run the launcher with --stop.")
        return process.wait()
    except KeyboardInterrupt:
        stop.touch()
        return process.wait(timeout=30)
    finally:
        if process.poll() is not None and read_state() == state:
            clear_state()
        if process.poll() is not None:
            stop.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AL TDB local workbench launcher")
    parser.add_argument("--no-browser", action="store_true", help="Start without opening a browser")
    parser.add_argument("--python", help="Base interpreter (overrides AL_TDB_PYTHON)")
    parser.add_argument("--host", default=os.environ.get("AL_TDB_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("AL_TDB_PORT", DEFAULT_PORT)))
    parser.add_argument("--data-dir", default=os.environ.get("AL_TDB_DATA_DIR"))
    parser.add_argument("--stop", action="store_true", help="Stop the server started by this launcher")
    parser.add_argument(
        "--print-root",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.print_root:
            print(discover_root())
            return 0
        if args.stop:
            return stop_server()
        return run_launch(args)
    except LauncherError as exc:
        eprint(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
