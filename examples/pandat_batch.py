"""Local Windows Pandat batch harness used by validation examples."""
import csv
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

from src.storage import atomic_json, atomic_write


def batch_document(rows, phase, components, groups, database="model.tdb", disordered_phase=None, all_site_columns=False):
    document = ET.Element("pbfx", version="1.0")
    ET.SubElement(ET.SubElement(document, "Header"), "Application", name="Pandat", version="2022")
    for i, row in enumerate(rows):
        calculation = ET.SubElement(document, "calculation", name=f"point_{i}", type="point")
        ET.SubElement(ET.SubElement(calculation, "databases"), "database", type="tdb", file_name=database)
        units = ET.SubElement(calculation, "units")
        for name, value in (("P", "atm"), ("T", "K"), ("n", "mole")):
            ET.SubElement(units, "unit", name=name, value=value)
        system = ET.SubElement(calculation, "system", name="Default_System")
        comps = ET.SubElement(system, "components")
        for name in components:
            ET.SubElement(comps, "component", name=name, status="Selected")
        phases = ET.SubElement(system, "phases")
        ET.SubElement(phases, "phase", name="*", status="suspend", type="")
        ET.SubElement(phases, "phase", name=phase, status="restore", type="")
        point = ET.SubElement(ET.SubElement(system, "points"), "point")
        space = ET.SubElement(point, "statespace")
        ET.SubElement(space, "T", value=format(row["T_K"], ".17g"))
        ET.SubElement(space, "P", value=format(row["P_Pa"] / 101325, ".17g"))
        for name in components:
            ET.SubElement(space, "n", component=name, value=format(row["X_"+name], ".17g"))
        ET.SubElement(ET.SubElement(system, "condition"), "individual_phase", value="true")
        ET.SubElement(system, "option")
        output = ET.SubElement(calculation, "output", unit="")
        table = ET.SubElement(ET.SubElement(output, "tables"), "table", name=f"point_{i}.dat", source="default")
        for name in ("T", "P", "x(*)", "phase_name", "G(@*)", "x(*@*)"):
            ET.SubElement(table, "column", name=name)
        if disordered_phase or all_site_columns:
            # Pandat reports the reference phase name once order vanishes.
            # Explicit ordered-phase columns make its 2022 exporter fail.
            ET.SubElement(table, "column", name="y(*@*)")
        else:
            for site, group in enumerate(groups, start=1):
                for name in group:
                    ET.SubElement(table, "column", name=f"y({name}#{site}@{phase})")
    ET.indent(document, space="  ")
    return ET.tostring(document, encoding="unicode")


def run_batch(executable, folder, rows, phase, components, groups, timeout=60, disordered_phase=None, all_site_columns=False):
    document = batch_document(rows, phase, components, groups,
                              disordered_phase=disordered_phase, all_site_columns=all_site_columns)
    return run_document(executable, folder, document, len(rows), timeout)


def run_document(executable, folder, document, point_count, timeout=60):
    """Run a point_N batch, retaining its exact XML and raw evidence.

    This also supports controlled experiments with documented Pandat initial
    values and equilibrium modes, without changing the baseline batch builder.
    """
    names = [item.get("name") for item in ET.fromstring(document).findall("calculation")]
    if point_count < 1 or names != [f"point_{i}" for i in range(point_count)]:
        raise ValueError("Expected sequential point_N calculations and a positive point count")
    if os.name != "nt":
        raise ValueError("This Pandat batch harness requires Windows")
    executable = Path(executable).resolve(strict=True)
    folder = Path(folder)
    atomic_write(folder / "points.pbfx", document)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    with tempfile.TemporaryDirectory(prefix="altdb-pandat-") as temporary:
        work = Path(temporary)
        if not str(work).isascii():
            raise ValueError("Pandat 2022 validation requires an ASCII temporary path")
        for name in ("model.tdb", "points.pbfx"):
            shutil.copyfile(folder / name, work / name)
        log_path = work / "console.log"
        with log_path.open("wb") as log:
            process = subprocess.Popen([str(executable), "points.pbfx", "2"], cwd=work, stdin=subprocess.PIPE,
                        stdout=log, stderr=log, startupinfo=startup, creationflags=subprocess.CREATE_NEW_CONSOLE)
            start, ready_since, termination = time.monotonic(), None, "normal_exit"
            try:
                while process.poll() is None:
                    output = log_path.read_text(errors="replace")
                    complete = all((work / f"point_{i}.dat").is_file() and
                                   f"Simulation [point_{i}] done with Success." in output for i in range(point_count))
                    if complete:
                        ready_since = ready_since or time.monotonic()
                        if time.monotonic() - ready_since >= 3:
                            termination = "stopped_after_all_outputs_and_success_logs"
                            break
                    if time.monotonic()-start > timeout:
                        termination = "timeout"
                        break
                    time.sleep(.2)
            finally:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=10)
                process.stdin.close()
        shutil.copytree(work, folder / "raw")
        manifest = {"executable": str(executable), "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                    "exit_code": process.returncode, "termination": termination}
        atomic_json(folder / "execution.json", manifest)
        output = log_path.read_text(errors="replace")
        if termination == "timeout" or any(f"Simulation [point_{i}] done with Success." not in output for i in range(point_count)):
            raise ValueError(f"Pandat did not finish all points; see {folder / 'raw' / 'console.log'}")
    return manifest


def read_point(path, phase, components, groups, expected, disordered_phase=None, disordered_site_mapping=None):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        units = next(reader)
        points = [row for row in reader if (row.get("T") or "").strip()]
    if units["T"] != "K" or units["P"] != "atm" or len(points) != 1:
        raise ValueError("Unexpected Pandat units or point count")
    point = {key.upper(): value for key, value in points[0].items() if key is not None}
    units = {key.upper(): value for key, value in units.items() if key is not None}
    reported_phase = point["PHASE_NAME"]
    disorder = disordered_phase is not None and reported_phase.upper() == disordered_phase.upper()
    if reported_phase.upper() != phase.upper() and not disorder:
        raise ValueError(f"Pandat returned phase {reported_phase}, expected a single {phase}")
    if disorder and disordered_site_mapping is None and any(set(group) != set(components) for group in groups):
        raise ValueError("Disordered branch mapping requires unrestricted equivalent substitutional sites")
    row = {"phase": phase, "T_K": float(point["T"]), "P_Pa": float(point["P"])*101325,
           "G": float(point[f"G(@{reported_phase})".upper()]), "reported_phase": reported_phase}
    for name in components:
        if f"X({name})" not in point and expected["X_"+name] == 0:
            row["X_"+name] = 0.0
            continue
        if units[f"X({name})"] != "mole/mole":
            raise ValueError("Expected atomic/molar fractions")
        row["X_"+name] = float(point[f"X({name})"])
        if abs(row["X_"+name] - float(point[f"X({name}@{reported_phase})".upper()])) > 2e-6:
            raise ValueError("Pandat phase and overall compositions differ")
    occurrences = dict.fromkeys({name for group in groups for name in group}, 0)
    for site, group in enumerate(groups):
        for name in group:
            suffix = "" if occurrences[name] == 0 else f"_{occurrences[name]}"
            # 2022a shortens explicit y(EL#site@phase) column labels and adds
            # suffixes to duplicate species labels, in requested column order.
            # At the disordered limit y_i on each equivalent ordered site is
            # the independently exported y_i of the one-site reference phase.
            reported_site = (disordered_site_mapping[site]+1 if disordered_site_mapping is not None else 1) if disorder else site+1
            label = f"y({name}#{reported_site}@{reported_phase})"
            # Pandat case_sensitive databases keep their original element and
            # phase spelling in explicit wildcard-column labels.
            value = point.get(label.upper(), point.get(f"y({name}){suffix}".upper(), ""))
            if not value and name != "VA" and expected["X_"+name] == 0:
                value = "0"
            row[f"Y_{site}_{name}"] = float(value)
            occurrences[name] += 1
    return row
