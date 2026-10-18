"""Report material/vacancy/magnetic validation, including all failed cases."""
import argparse
import json
from pathlib import Path
import uuid

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from config import BASE_DATA_DIR
from src.gibbs_compare import write_csv
from src.storage import atomic_json


def build_report(path):
    source = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = source["cases"]
    if source["status"] == "running" or len(cases) != source["expected_cases"]:
        raise ValueError("Validation must finish before reporting")
    folder = BASE_DATA_DIR/("pandat_material_report_"+uuid.uuid4().hex[:12])
    fields = ["name", "synthetic", "phase", "sublattices", "status", "points", "energy_points_passed",
              "formula_points_passed", "max_abs_G_error_J_mol_atoms", "max_formula_error_J_mol_atoms",
              "max_order_amplitude_error", "error"]
    write_csv(folder/"summary.csv", [{key: case.get(key) for key in fields} for case in cases])
    summary = {**source, "source_summary": str(Path(path).resolve()), "folder": str(folder)}
    for label, synthetic in (("material", False), ("synthetic", True)):
        rows = [case for case in cases if case["synthetic"] == synthetic]
        summary[label] = {"cases": len(rows), "passed_cases": sum(case["status"] == "passed" for case in rows),
                          "points": sum(case.get("points", 0) for case in rows),
                          "energy_points_passed": sum(case.get("energy_points_passed", 0) for case in rows),
                          "formula_points_passed": sum(case.get("formula_points_passed", 0) for case in rows),
                          "max_G_error": max((case.get("max_abs_G_error_J_mol_atoms", 0) for case in rows), default=None),
                          "max_same_Y_error": max((case.get("max_formula_error_J_mol_atoms", 0) for case in rows), default=None)}
    figure = Figure(figsize=(16, 10), layout="constrained")
    FigureCanvasAgg(figure)
    grid = figure.add_gridspec(2, 2, width_ratios=[1.6, 1])
    ax = figure.add_subplot(grid[:, 0])
    positions = np.arange(len(cases))
    for i, case in enumerate(cases):
        if "max_abs_G_error_J_mol_atoms" not in case:
            ax.text(.001, i, "ERROR / no result", color="#b91c1c", va="center")
            continue
        ax.scatter(case["max_abs_G_error_J_mol_atoms"], i, marker="o", s=48,
                   color="#b91c1c" if case["status"] != "passed" else "#2563eb",
                   label="Optimized G" if i == 0 else None)
        ax.scatter(case["max_formula_error_J_mol_atoms"], i, marker="x", s=46, color="#0f766e",
                   label="Same Pandat occupancy" if i == 0 else None)
    ax.axvline(1, color="#64748b", linestyle="--", label="1 J/mol-atoms tolerance")
    ax.axhline(sum(not case["synthetic"] for case in cases)-.5, color="#cbd5e1", linewidth=1)
    ax.set_yticks(positions, [case["name"] for case in cases], fontsize=9)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlabel("Maximum absolute G difference [J/mol-atoms]")
    ax.set_title("Unmodified material examples (top) / synthetic controls (bottom)", fontsize=11)
    ax.grid(axis="x", alpha=.2)
    ax.legend(loc="lower right", fontsize=9)
    counterexample = next((case for case in cases if case["name"] == "synthetic_4sl_coupled_fm"), None)
    order_ax, gap_ax = figure.add_subplot(grid[0, 1]), figure.add_subplot(grid[1, 1])
    if counterexample and "points" in counterexample:
        audits = json.loads((Path(counterexample["folder"])/"audits.json").read_text(encoding="utf-8"))
        temperatures = [point["T_K"] for point in audits]
        order_ax.plot(temperatures, [point["q_local"] for point in audits], "o-", label="Local optimized", color="#2563eb")
        order_ax.plot(temperatures, [point["q_pandat"] for point in audits], "s--", label="Pandat IndividualPhase", color="#b45309")
        gap_ax.plot(temperatures, [point["G_pandat"]-point["G_local"] for point in audits], "o-", color="#b91c1c")
        gap_ax.axhline(1, color="#64748b", linestyle="--")
        order_ax.legend(fontsize=9)
    else:
        order_ax.text(.5, .5, "Counterexample not in this run", transform=order_ax.transAxes, ha="center")
    order_ax.set_title("4-sublattice magnetic coupling: retained discrepancy", fontsize=11)
    order_ax.set_ylabel("RMS substitutional occupation amplitude q")
    diagnostic = Path(counterexample["folder"])/"optimization_diagnosis.json" if counterexample else None
    confirmed = False
    if diagnostic and diagnostic.is_file():
        points = json.loads(diagnostic.read_text(encoding="utf-8"))["points"]
        confirmed = bool(points) and all(point["DE_success"] and abs(point["G_independent_DE"]-point["G_local"]) < 1e-4 for point in points)
        summary["solver_diagnosis"] = str(diagnostic)
    gap_ax.set_title("Independent differential evolution confirms lower local G" if confirmed else "Optimized energy difference", fontsize=10)
    gap_ax.set_ylabel("G(Pandat) - G(local) [J/mol-atoms]")
    for panel in (order_ax, gap_ax):
        panel.set_xlabel("Temperature [K]")
        panel.grid(alpha=.2)
    figure.suptitle(f"Pandat 2022a Education: material, vacancy and magnetic validation\n"
                   f"{source['passed_cases']}/{len(cases)} cases passed | {source['energy_points_passed']}/{source['points']} optimized G points | "
                   f"{source['formula_points_passed']}/{source['points']} same-occupancy points", fontsize=16)
    summary["files"] = {key: str(folder/f"summary.{key}") for key in ("csv", "json")}
    for extension in ("png", "svg"):
        destination = folder/f"validation.{extension}"
        figure.savefig(destination, dpi=160)
        summary["files"][extension] = str(destination)
    atomic_json(folder/"summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary")
    result = build_report(parser.parse_args().summary)
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, ensure_ascii=False, indent=2))
