"""Independent Pandat cross-check of nine points in a synthetic CEF database.

Requires a user's licensed Pandat executable. No Pandat binaries or commercial
database are distributed. The parameters are synthetic, not an assessed alloy.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

from config import BASE_DATA_DIR
from examples.gibbs_demo import SYNTHETIC_TDB
from src.gibbs import run_curve
from src.gibbs_compare import model_declaration, run_comparison, write_csv
from src.storage import atomic_json, atomic_write


def save_comparison_figure(report, folder):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    figure = Figure(figsize=(10, 4.7), constrained_layout=True)
    FigureCanvasAgg(figure)
    left, right = figure.subplots(1, 2)
    colors = ("#1479af", "#c45822", "#218c62")
    for temperature, color in zip(sorted({r["T_K"] for r in report["rows"]}), colors):
        rows = sorted([r for r in report["rows"] if r["T_K"] == temperature], key=lambda r: r["X_NI"])
        x = [r["X_NI"] for r in rows]
        left.plot(x, [r["G_local_J_mol_atoms"]/1000 for r in rows], color=color, marker="x", label=f"Local {temperature:g} K")
        left.scatter(x, [r["G_reference_J_mol_atoms"]/1000 for r in rows], edgecolors=color,
                     facecolors="none", s=65, label=f"Pandat {temperature:g} K")
        right.plot(x, [r["delta_G_J_mol_atoms"] for r in rows], color=color, marker="o", label=f"{temperature:g} K")
    left.set_ylabel("G (kJ/mol-atoms)")
    right.set_ylabel("G(local) - G(Pandat) (J/mol-atoms)")
    right.axhline(0, color="#555555", linewidth=.7)
    for ax in (left, right):
        ax.set_xlabel("NI atomic fraction")
        ax.grid(alpha=.2)
        ax.legend(fontsize=8)
    figure.suptitle("Pandat 2022a Education cross-check | Synthetic two-sublattice CEF", fontsize=12)
    figure.savefig(folder / "comparison.png", dpi=170, bbox_inches="tight")
    figure.savefig(folder / "comparison.svg", bbox_inches="tight")
    return {"png": str(folder / "comparison.png"), "svg": str(folder / "comparison.svg")}


def batch_document(rows):
    document = ET.Element("pbfx", version="1.0")
    ET.SubElement(ET.SubElement(document, "Header"), "Application", name="Pandat", version="2022")
    for i, row in enumerate(rows):
        calculation = ET.SubElement(document, "calculation", name=f"synthetic_{i}", type="point")
        ET.SubElement(ET.SubElement(calculation, "databases"), "database", type="tdb", file_name="synthetic.tdb")
        units = ET.SubElement(calculation, "units")
        # Pandat 2022a point input uses atm; do not assume the display unit Pa
        # is supported for parsing the input pressure.
        for name, value in (("P", "atm"), ("T", "K"), ("n", "mole")):
            ET.SubElement(units, "unit", name=name, value=value)
        system = ET.SubElement(calculation, "system", name="Default_System")
        components = ET.SubElement(system, "components")
        for name in ("AL", "NI"):
            ET.SubElement(components, "component", name=name, status="Selected")
        phases = ET.SubElement(system, "phases")
        ET.SubElement(phases, "phase", name="*", status="suspend", type="")
        ET.SubElement(phases, "phase", name="SYNTHETIC_B2", status="restore", type="")
        space = ET.SubElement(ET.SubElement(ET.SubElement(system, "points"), "point"), "statespace")
        ET.SubElement(space, "T", value=format(row["T_K"], ".17g"))
        ET.SubElement(space, "P", value=format(row["P_Pa"] / 101325, ".17g"))
        for name in ("AL", "NI"):
            ET.SubElement(space, "n", component=name, value=format(row["X_" + name], ".17g"))
        ET.SubElement(ET.SubElement(system, "condition"), "individual_phase", value="true")
        ET.SubElement(system, "option")
        # Retain the unit attribute: omitting it crashes this older PBFX parser.
        output = ET.SubElement(calculation, "output", unit="")
        table = ET.SubElement(ET.SubElement(output, "tables"), "table", name=f"point_{i}.dat", source="default")
        for name in ("T", "P", "x(*)", "phase_name", "G(@*)", "x(*@*)"):
            ET.SubElement(table, "column", name=name)
    ET.indent(document, space="  ")
    return ET.tostring(document, encoding="unicode")


def read_pandat_point(path):
    # The .dat export has a header, a units row, and one data row.
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        units = next(reader)
        points = [row for row in reader if (row.get("T") or "").strip()]
    if units["T"] != "K" or units["P"] != "atm" or len(points) != 1:
        raise ValueError("Unexpected Pandat units or point count")
    point = points[0]
    if point["phase_name"] != "SYNTHETIC_B2":
        raise ValueError("Pandat returned a split or different phase")
    row = {"phase": point["phase_name"], "T_K": float(point["T"]),
           "P_Pa": float(point["P"]) * 101325, "G": float(point["G(@SYNTHETIC_B2)"])}
    for name in ("AL", "NI"):
        if units[f"x({name})"] != "mole/mole":
            raise ValueError("Expected atomic/molar fractions in Pandat output")
        row["X_" + name] = float(point[f"x({name})"])
        if abs(row["X_" + name] - float(point[f"x({name}@SYNTHETIC_B2)"])) > 1e-8:
            raise ValueError("Pandat phase composition differs from overall composition")
    return row


def benchmark(executable, version, timeout=60):
    if os.name != "nt":
        raise ValueError("This example supports the Windows Pandat 2022 console interface")
    executable = Path(executable).resolve(strict=True)
    folder = BASE_DATA_DIR / ("pandat_benchmark_" + uuid.uuid4().hex[:12])
    database = folder / "synthetic.tdb"
    atomic_write(database, SYNTHETIC_TDB)
    local = run_curve({"tdb_files": [str(database)], "phase": "SYNTHETIC_B2", "mode": "gx",
                       "temperatures": [600, 1000, 1400], "pressure": 101325,
                       "composition_start": {"AL": .9, "NI": .1},
                       "composition_end": {"AL": .1, "NI": .9}, "points": 3, "starts": 12})
    atomic_write(folder / "points.pbfx", batch_document(local["rows"]))
    # Keep the input handle open: this Pandat release crashes on stdin EOF.
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    with tempfile.TemporaryDirectory(prefix="altdb-pandat-") as temporary:
        work = Path(temporary)
        if not str(work).isascii():
            raise ValueError("Set TEMP to an ASCII-only path for this older Pandat release")
        shutil.copyfile(database, work / "synthetic.tdb")
        shutil.copyfile(folder / "points.pbfx", work / "points.pbfx")
        log_path = work / "console.log"
        count = len(local["rows"])
        with log_path.open("wb") as log:
            process = subprocess.Popen([str(executable), "points.pbfx", "2"], cwd=work,
                        stdin=subprocess.PIPE, stdout=log, stderr=log, startupinfo=startup,
                        creationflags=subprocess.CREATE_NEW_CONSOLE)
            start, ready_since, termination = time.monotonic(), None, "normal_exit"
            try:
                while process.poll() is None:
                    output = log_path.read_text(errors="replace")
                    complete = all((work / f"point_{i}.dat").is_file() for i in range(count)) and all(
                        f"Simulation [synthetic_{i}] done with Success." in output for i in range(count))
                    if complete:
                        ready_since = ready_since or time.monotonic()
                        if time.monotonic() - ready_since >= 3:
                            # Some builds retain their console input thread after
                            # all calculations finish. Stop only this owned process.
                            termination = "stopped_after_all_outputs_and_success_logs"
                            process.terminate()
                            break
                    if time.monotonic() - start > timeout:
                        termination = "timeout"
                        process.terminate()
                        break
                    time.sleep(.2)
            finally:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=10)
                process.stdin.close()
        shutil.copytree(work, folder / "raw")
        output = log_path.read_text(errors="replace")
        manifest = {"executable": str(executable), "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                    "software_version": version, "exit_code": process.returncode, "termination": termination,
                    "synthetic_parameters": True}
        atomic_json(folder / "execution.json", manifest)
        if termination == "timeout" or any(f"Simulation [synthetic_{i}] done with Success." not in output for i in range(count)):
            raise ValueError(f"Pandat did not finish every point; inspect {folder / 'raw' / 'console.log'}")
        references = [read_pandat_point(work / f"point_{i}.dat") for i in range(count)]
    reference_csv = folder / "reference.csv"
    write_csv(reference_csv, references)
    comparison_request = {"result": local["files"]["json"], "reference_csv": str(reference_csv),
                          "software": "pandat", "software_version": version,
                          "reference_model": model_declaration(local), "conditions_verified": True,
                          "energy_unit": "J/mol-atoms", "atol_J_mol_atoms": 1, "rtol": 0}
    atomic_json(folder / "compare.json", comparison_request)
    comparison = run_comparison(comparison_request)
    summary = {"synthetic_parameters": True, "benchmark_folder": str(folder), "execution": manifest,
               **{key: value for key, value in comparison.items() if key not in {"rows", "request", "notes"}}}
    summary["plots"] = save_comparison_figure(comparison, folder)
    atomic_json(folder / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, help="Path to licensed Pandat.exe")
    parser.add_argument("--version", required=True, help="Installed version/edition for provenance")
    args = parser.parse_args()
    print(json.dumps(benchmark(args.executable, args.version), ensure_ascii=False, indent=2))
