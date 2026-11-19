"""Exercise the native entry point of an extracted desktop release on the current OS."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
from zipfile import ZipFile


def verify(bundle, root, runtime):
    folder = root / "AL TDB release"
    with ZipFile(bundle) as archive:
        for entry in archive.infolist():
            path = Path(archive.extract(entry, folder))
            if path.name.endswith((".sh", ".command")):
                mode = entry.external_attr >> 16
                assert mode & 0o111 and b"\r" not in path.read_bytes()
                path.chmod(mode & 0o777)
    assert (folder / "AGENTS.md").is_file()
    entry = "Start-AL-TDB.command" if sys.platform == "darwin" else "Start-AL-TDB.sh"
    cmd = (
        [str(folder / entry)]
        if os.name != "nt"
        else ["cmd.exe", "/d", "/c", "Start-AL-TDB.cmd"]
    )
    env = {
        **os.environ,
        "AL_TDB_RUNTIME_DIR": str(runtime),
        "AL_TDB_DATA_DIR": str(root / "data"),
        "AL_TDB_PYTHON": sys.executable,
        "AL_TDB_PORT": "18273",
        "AL_TDB_ROOT": str(folder),
    }

    def get(url):
        with urllib.request.urlopen(url, timeout=5) as res:
            return res.read()

    with (root / "launch.log").open("w+", encoding="utf-8") as log:
        server = subprocess.Popen(
            cmd + ["--no-browser"],
            cwd=folder,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        state = runtime / "launcher-state.json"
        try:
            deadline = time.monotonic() + 900
            while not state.is_file():
                if server.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Launcher did not reach ready state")
                time.sleep(0.5)
            info = json.loads(state.read_bytes())
            url = f"http://127.0.0.1:{info['port']}"
            assert json.loads(get(url + "/launcher-instance"))["id"] == info["id"]
            assert json.loads(get(url + "/health"))["status"] == "ok"
            assert b"project-experiments.js" in get(url + "/projects")
            assert b"AGENTS.md" in get(url + "/static/agent-guide.html")
            subprocess.run(
                cmd + ["--no-browser"], cwd=folder, env=env, check=True, timeout=30
            )
            print(
                f"{sys.platform}: extracted package start, health, experiments, AI guide and reuse OK"
            )
        finally:
            if state.is_file():
                subprocess.run(
                    cmd + ["--stop"], cwd=folder, env=env, timeout=30, check=True
                )
            if server.poll() is None and not state.exists():
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.terminate()
            server.wait(timeout=30)
            log.seek(0)
            sys.stderr.write(log.read()[-2000:])
        assert server.returncode == 0 and not state.exists()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument(
        "--runtime", type=Path, help="Dedicated empty or prewarmed test runtime"
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="al-tdb-smoke-") as name:
        root = Path(name)
        runtime = args.runtime or root / "runtime"
        if (runtime / "launcher-state.json").exists():
            raise SystemExit("Choose an unused test runtime")
        verify(args.bundle.resolve(), root, runtime.resolve())
