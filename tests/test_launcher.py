"""Unit tests for the Windows local-server launcher (no live server required)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from altdb import launcher


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("AL_TDB_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("AL_TDB_ROOT", raising=False)
    monkeypatch.delenv("AL_TDB_PYTHON", raising=False)
    return tmp_path


def test_discover_source_tree_prefers_checkout_with_app(root, monkeypatch):
    source = root / "src-tree"
    source.mkdir()
    (source / "Start-AL-TDB.cmd").write_text("@echo off\n", encoding="utf-8")
    (source / "pyproject.toml").write_text('name = "al-tdb-workflow"\n', encoding="utf-8")
    (source / "app.py").write_text("app = None\n", encoding="utf-8")
    nested = source / "altdb"
    nested.mkdir()
    launcher_file = nested / "launcher.py"
    launcher_file.write_text("# placeholder\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "__file__", str(launcher_file))
    assert launcher.discover_root() == source.resolve()
    assert launcher.is_source_tree(source)


def test_install_spec_wheel_uses_digest(root):
    bundle = root / "bundle"
    wheels = bundle / "wheels"
    wheels.mkdir(parents=True)
    wheel = wheels / "al_tdb_workflow-0.3.0-py3-none-any.whl"
    wheel.write_bytes(b"fake-wheel")
    (bundle / "Start-AL-TDB.cmd").write_text("@echo off\n", encoding="utf-8")
    spec = launcher.install_spec(bundle)
    assert spec["mode"] == "wheel"
    assert spec["pip_args"] == [f"{wheel}[fp,thermo]"]
    assert wheel.name in spec["identity"]
    assert launcher.file_digest(wheel) in spec["identity"]


def test_resolve_base_python_missing(root):
    missing = root / "no-python.exe"
    with pytest.raises(launcher.LauncherError, match="AL_TDB_PYTHON"):
        launcher.resolve_base_python(str(missing))


def test_resolve_base_python_from_env(root, monkeypatch):
    fake = root / "python.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("AL_TDB_PYTHON", str(fake))
    assert launcher.resolve_base_python() == fake.resolve()


def test_choose_port_skips_foreign_http(monkeypatch):
    occupied = {8003}

    monkeypatch.setattr(launcher, "port_occupied", lambda host, port: port in occupied)
    assert launcher.choose_port("127.0.0.1", 8003) == 8004


def test_run_launch_reuses_matching_server(monkeypatch, root):
    (root / 'app.py').touch()
    (root / 'pyproject.toml').touch()
    opened = []

    monkeypatch.setattr(launcher, "discover_root", lambda: root)
    monkeypatch.setattr(launcher, "resolve_base_python", lambda explicit=None: Path(sys.executable))
    monkeypatch.setattr(launcher, 'read_state', lambda: {'port':8003,'data_dir':'','identity':launcher.install_spec(root)['identity']})
    monkeypatch.setattr(launcher, 'instance_matches', lambda state: True)
    monkeypatch.setattr(launcher, "open_jobs", lambda host, port: opened.append((host, port)))
    monkeypatch.setattr(launcher, "ensure_private_env", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not install")))

    monkeypatch.delenv('AL_TDB_DATA_DIR', raising=False)
    args = launcher.build_parser().parse_args([])
    assert launcher.run_launch(args) == 0
    assert opened == [("127.0.0.1", 8003)]


def test_refuse_non_loopback_host():
    args = launcher.build_parser().parse_args(["--host", "0.0.0.0"])
    with pytest.raises(launcher.LauncherError, match="loopback"):
        launcher.run_launch(args)


def test_stop_refuses_a_stale_pid(root, monkeypatch):
    runtime = Path(root / "runtime")
    runtime.mkdir(parents=True)
    state = {
        "pid": 1_000_000,
        "host": "127.0.0.1",
        "port": 8003,
    }
    (runtime / launcher.STATE_NAME).write_text(json.dumps(state), encoding="utf-8")
    assert launcher.stop_server() == 1
    assert not list(runtime.glob('*.stop'))


def test_main_stop_and_error_codes(monkeypatch):
    monkeypatch.setattr(launcher, "stop_server", lambda: 0)
    assert launcher.main(["--stop"]) == 0

    def boom(*_a, **_k):
        raise launcher.LauncherError("no python")

    monkeypatch.setattr(launcher, "run_launch", boom)
    assert launcher.main([]) == 2


def test_paths_with_spaces_roundtrip(root):
    spaced = root / "path with spaces" / "bundle"
    wheels = spaced / "wheels"
    wheels.mkdir(parents=True)
    wheel = wheels / "al_tdb_workflow-0.3.0-py3-none-any.whl"
    wheel.write_bytes(b"abc")
    (spaced / "Start-AL-TDB.cmd").write_text("@echo off\n", encoding="utf-8")
    spec = launcher.install_spec(spaced)
    assert "path with spaces" in spec["pip_args"][0]
    assert Path(spec["pip_args"][0].split("[", 1)[0]) == wheel
