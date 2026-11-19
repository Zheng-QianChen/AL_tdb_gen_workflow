#!/usr/bin/env python3
"""Build one desktop ZIP with the platform entry points and a portable Python wheel."""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def package_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("Could not read project version from pyproject.toml")


def build_wheel(wheel_dir: Path) -> Path:
    wheel_dir.mkdir(parents=True, exist_ok=True)
    for old in wheel_dir.glob("*.whl"):
        old.unlink()
    cmd = [sys.executable, "-m", "pip", "wheel", "--no-deps", str(ROOT), "--wheel-dir", str(wheel_dir)]
    completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise SystemExit(
            "Failed to build project wheel.\n"
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    wheels = sorted(wheel_dir.glob("*.whl"))
    if not wheels:
        raise SystemExit("pip wheel produced no .whl files")
    return wheels[-1]


def copy_launcher_files(staging: Path) -> None:
    shutil.copy2(ROOT / "constraints-test.txt", staging / "constraints-test.txt")
    altdb = staging / "altdb"
    altdb.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "Start-AL-TDB.cmd", staging / "Start-AL-TDB.cmd")
    for name in ("Start-AL-TDB.sh", "Start-AL-TDB.command", "AGENTS.md"):
        (staging / name).write_bytes((ROOT / name).read_bytes().replace(b"\r\n", b"\n"))
    shutil.copy2(ROOT / "static" / "agent-guide.html", staging / "agent-guide.html")
    shutil.copy2(ROOT / "altdb" / "launcher.py", altdb / "launcher.py")
    # Minimal package marker so helpers can treat altdb/ as a package if desired.
    init_src = ROOT / "altdb" / "__init__.py"
    if init_src.is_file():
        shutil.copy2(init_src, altdb / "__init__.py")
    else:
        (altdb / "__init__.py").write_text('"""AL TDB package marker for the Windows bundle."""\n', encoding="utf-8")
    docs_src = ROOT / "docs" / "windows-server.md"
    if docs_src.is_file():
        docs = staging / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        shutil.copy2(docs_src, docs / "windows-server.md")


def write_readme(staging: Path, version: str, wheel_name: str) -> None:
    (staging / "README-WINDOWS.txt").write_text(
        "\n".join(
            [
                f"AL TDB Workflow Windows local server bundle {version}",
                "",
                "1. Extract this ZIP to a folder path that may contain spaces.",
                "2. Install Python 3.11 or 3.12 (or set AL_TDB_PYTHON to that python.exe).",
                "3. Double-click Start-AL-TDB.cmd.",
                "4. First start creates a private env under %USERPROFILE%\\.altdb\\runtime",
                f"   and installs {wheel_name} with the fp and thermo extras.",
                "5. Edge opens the project workbench at /projects when the local server is healthy.",
                "6. Stop: Ctrl+C in the starter console, or Start-AL-TDB.cmd --stop.",
                "",
                "Details: docs\\windows-server.md",
                "",
            ]
        ),
        encoding="utf-8",
    )


def make_zip(staging: Path, output_zip: Path) -> None:
    if output_zip.exists():
        output_zip.unlink()
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                name = path.relative_to(staging).as_posix()
                entry = zipfile.ZipInfo.from_file(path, name)
                entry.create_system = 3
                entry.external_attr = (0o100755 if name.endswith((".sh", ".command")) else 0o100644) << 16
                archive.writestr(entry, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wheel",
        type=Path,
        help="Existing project wheel; if omitted, build with pip wheel --no-deps",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "dist",
        help="Directory for the ZIP (default: dist/)",
    )
    args = parser.parse_args(argv)
    version = package_version()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="altdb-win-bundle-") as tmp:
        staging = Path(tmp) / f"AL-TDB-windows-{version}"
        staging.mkdir(parents=True)
        wheels_dir = staging / "wheels"
        wheels_dir.mkdir()
        if args.wheel:
            wheel = args.wheel.expanduser().resolve()
            if not wheel.is_file():
                raise SystemExit(f"Wheel not found: {wheel}")
            target = wheels_dir / wheel.name
            shutil.copy2(wheel, target)
        else:
            target = build_wheel(wheels_dir)
        copy_launcher_files(staging)
        write_readme(staging, version, target.name)
        (staging / "启动说明.txt").write_text(
            "解压整个 ZIP。预先安装 Python 3.11 或 3.12（含 venv）。首次启动需要联网下载依赖。\n"
            "Windows：双击 Start-AL-TDB.cmd。\nLinux：在解压目录执行 sh Start-AL-TDB.sh。\n"
            "macOS：双击 Start-AL-TDB.command，或在终端执行 sh Start-AL-TDB.sh。\n"
            "Linux 无桌面：sh Start-AL-TDB.sh --no-browser，按终端地址访问。\n"
            "停止服务：在启动窗口按 Ctrl+C，或用同一入口加 --stop。\n"
            "项目交接与 AI 工作流见 AGENTS.md 和 agent-guide.html。\n", encoding="utf-8")
        output_zip = args.output_dir / f"AL-TDB-desktop-{version}.zip"
        make_zip(staging, output_zip)

    print(output_zip)
    print(f"sha256={digest(output_zip)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
