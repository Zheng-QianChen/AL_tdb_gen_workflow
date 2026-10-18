"""Optional Thermo-Calc Education console checks of saved multi-phase grid points.

Uses the official Education launcher arguments, unchanged parameters and normal
global equilibrium. No TC-Python license is required. Preserve all native logs;
this check compares G only, not complete phase compositions or topology.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from examples.engine_runtime import hidden_startupinfo
import tempfile
import time

from examples.cross_engine_thermocalc import java_command, audit_import
from src.storage import atomic_json


def parse_checks(raw, rows, output, imported, completed):
    """Accept either observed local or global convergence message, never exit 0 alone."""
    blocks = re.split(r"POLY(?:_[0-9]+)?:\s*REINITIATE_MODULE", raw, flags=re.I)[1:]
    if len(blocks) != len(rows):
        blocks = re.split(r"POLY(?:_[0-9]+)?:\s*SET_CONDITION", raw, flags=re.I)[1:]
    checks = []
    for i, row in enumerate(rows):
        block = blocks[i] if i < len(blocks) else ""
        values = re.findall(r"\bGM\s*=\s*([-+0-9.Ee]+)", block)
        energy = float(values[-1]) if values else None
        calculated = bool(re.search(r"\b\d+\s+ITS,\s+CPU TIME USED|Calculated solution in\s+[0-9.]+\s+s using\s+\d+\s+iterations", block, re.I))
        calculated = calculated and not bool(re.search(r"\bERROR\b|NO SUCH COMMAND|NOT CONVERGED", block, re.I))
        error = None if energy is None else energy-row["G_J_mol_atoms"]
        checks.append({"point_id": row["point_id"], "T_K": row["T_K"], "composition": row["composition"],
                       "project_G": row["G_J_mol_atoms"], "thermocalc_G": energy, "delta_G": error,
                       "converged_marker": calculated, "result_file": str(output / f"point_{i:03}.txt"),
                       "energy_agrees": bool(imported and completed and (output / f"point_{i:03}.txt").is_file()
                                             and calculated and error is not None and abs(error) < .1)})
    return checks


def run(result_file, indices, home, output):
    result = json.loads(result_file.read_text(encoding="utf-8"))
    if len(result["sources"]) != 1:
        raise ValueError("This verifier requires one original TDB file")
    source = Path(result["sources"][0]["path"])
    if hashlib.sha256(source.read_bytes()).hexdigest() != result["sources"][0]["sha256"]:
        raise ValueError("Source database has changed")
    rows = [result["rows"][index] for index in indices]
    if any(row["status"] != "accepted" or min(row["composition"].values()) <= 0 for row in rows):
        raise ValueError("Select accepted interior points")
    if result["request"]["phases"] is not None or result["request"]["suspended_phases"]:
        raise ValueError("Select an all-phase diagram for this independent check")
    lines = ["set-echo", "go data", "switch_database user model.tdb", "define_elements " + " ".join(result["components"]),
             "get_data", "go p-3"]
    for i, row in enumerate(rows):
        lines += ["reinitiate_module", f"set_condition T={row['T_K']:.16g} P={row['P_Pa']:.16g} N=1 " +
                  " ".join(f"X({c})={x:.16g}" for c, x in list(row["composition"].items())[:-1]),
                  "compute_equilibrium", "list_equilibrium", f"point_{i:03}.txt", "VXNSD",
                  "show_value GM NP(*) X(*,*)"]
    lines.append("exit")
    output.mkdir(parents=True, exist_ok=True)
    # TC 2026b rejects indented $ comment lines in the NIMS fixture. Remove only
    # full-line comments, preserving every non-comment statement and both hashes.
    source_lines = source.read_text(encoding="utf-8-sig").splitlines()
    comment_count = sum(line.lstrip().startswith("$") for line in source_lines)
    normalized = "\n".join(line for line in source_lines if not line.lstrip().startswith("$")) + "\n"
    macro_text = "\n".join(lines) + "\n"
    (output / "input.tcm").write_text(macro_text, encoding="ascii")
    with tempfile.TemporaryDirectory(prefix="tc_diagram_") as temporary:
        work = Path(temporary)
        (work / "model.tdb").write_text(normalized, encoding="utf-8")
        (output / "model.tdb").write_text(normalized, encoding="utf-8")
        macro = work / "check.tcm"
        macro.write_text(macro_text, encoding="ascii")
        si = hidden_startupinfo()
        env = dict(os.environ, TC26B_HOME=str(home), LSHOST="NO-NET", LSERVRC=str(home / "lservrc"))
        completed_at, timed_out, cleanup = None, False, False
        with (output / "raw.log").open("wb") as stream:
            process = subprocess.Popen(java_command(home, macro), cwd=work, env=env, stdin=subprocess.DEVNULL,
                                       stdout=stream, stderr=subprocess.STDOUT, startupinfo=si)
            started = time.monotonic()
            while process.poll() is None:
                raw = (output / "raw.log").read_text(encoding="utf-8", errors="replace")
                if "Thermo-Calc completed normally" in raw and completed_at is None:
                    completed_at = time.monotonic()
                if completed_at is not None and time.monotonic()-completed_at > 15:
                    process.kill(); cleanup = True; break
                if time.monotonic()-started > 180:
                    process.kill(); timed_out = True; break
                time.sleep(.5)
            process.wait()
        for file in work.glob("point_*.txt"):
            shutil.copyfile(file, output / file.name)
    raw = (output / "raw.log").read_text(encoding="utf-8", errors="replace").replace("\r", "")
    imports = audit_import(raw.split("POLY", 1)[0])
    checks = parse_checks(raw, rows, output, imports["accepted_for_comparison"],
                          not timed_out and "Thermo-Calc completed normally" in raw)
    summary = {"engine": "Thermo-Calc Education 2026b", "constraint": "all-phase global equilibrium",
               "scope": "G-only cross-check; phase compositions/fractions and topology not certified",
               "tdb_sha256": result["sources"][0]["sha256"], "import_audit": imports,
               "normalization": {"full_comment_lines_removed": comment_count,
                                 "imported_sha256": hashlib.sha256((output / "model.tdb").read_bytes()).hexdigest()},
               "returncode": process.returncode, "timed_out": timed_out,
               "stopped_after_normal_macro_completion": cleanup,
               "normal_macro_completion": "Thermo-Calc completed normally" in raw, "checks": checks}
    atomic_json(output / "comparison.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--points", type=int, nargs="+", required=True)
    parser.add_argument("--home", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.result, args.points, args.home, args.output), ensure_ascii=False, indent=2))
