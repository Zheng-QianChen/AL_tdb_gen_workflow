"""Summarize saved Pandat validation runs without recalculating their results."""
import argparse
import json
from pathlib import Path
import uuid

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from config import BASE_DATA_DIR
from src.gibbs_compare import write_csv
from src.storage import atomic_json


def build_report(paths):
    runs = [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]
    cases = sorted([case for run in runs for case in run["cases"]], key=lambda case: (case["sublattices"], case["name"]))
    if not cases or len({case["name"] for case in cases}) != len(cases):
        raise ValueError("Supply nonempty runs with no duplicate case names")
    folder = BASE_DATA_DIR / ("pandat_validation_report_" + uuid.uuid4().hex[:12])
    passed = all(run["status"] == "passed" for run in runs) and all(case["status"] == "passed" for case in cases)
    valid = [case for case in cases if "max_abs_G_error_J_mol_atoms" in case]
    ordering = [case for case in valid if case["kind"] in {"ordered", "partitioned"}]
    summary = {"status": "passed" if passed else "incomplete_or_failed", "synthetic_parameters": True,
               "source_summaries": [str(Path(path).resolve()) for path in paths],
               "software_versions": sorted({run["software_version"] for run in runs}),
               "cases": cases, "case_count": len(cases), "points": sum(case.get("points", 0) for case in cases),
               "passed_cases": sum(case["status"] == "passed" for case in cases),
               "max_abs_G_error_J_mol_atoms": max((case["max_abs_G_error_J_mol_atoms"] for case in valid), default=None),
               "max_order_amplitude_error": max((case["max_order_amplitude_error"] for case in ordering), default=None)}
    fields = ["name", "sublattices", "kind", "status", "points", "max_abs_G_error_J_mol_atoms",
              "rmse_J_mol_atoms", "max_formula_error_at_same_Y_J_mol_atoms", "max_order_amplitude_error"]
    write_csv(folder / "summary.csv", [{key: case.get(key) for key in fields} for case in cases])
    figure = Figure(figsize=(12, 9), layout="constrained")
    FigureCanvasAgg(figure)
    grid = figure.add_gridspec(2, 2, width_ratios=[1.05, 1])
    errors = figure.add_subplot(grid[:, 0])
    palette = {3: "#2563eb", 4: "#0f766e", 5: "#b45309"}
    errors.barh([case["name"] for case in valid], [case["max_abs_G_error_J_mol_atoms"] for case in valid],
                color=[palette[case["sublattices"]] for case in valid])
    errors.invert_yaxis()
    errors.set_xlabel("Maximum |G(local) - G(Pandat)| [J/mol-atoms]")
    errors.set_title("Single-point energy agreement\nAcceptance tolerance: 1 J/mol-atoms", fontsize=12)
    errors.grid(axis="x", alpha=.2)
    for index, kind in enumerate(("ordered", "partitioned")):
        ax = figure.add_subplot(grid[index, 1])
        for case in ordering:
            if case["kind"] != kind:
                continue
            points = json.loads((Path(case["folder"]) / "audits.json").read_text(encoding="utf-8"))
            temperatures = [point["T_K"] for point in points]
            color = palette[case["sublattices"]]
            ax.plot(temperatures, [point["order_amplitude_local"] for point in points],
                    color=color, label=f"{case['sublattices']} SL local")
            ax.plot(temperatures, [point["order_amplitude_pandat"] for point in points],
                    color=color, marker="o", fillstyle="none", linestyle="none", label=f"{case['sublattices']} SL Pandat")
        ax.set_title("Chemical ordering in CEF" if kind == "ordered" else "Coupled ordered/disordered model", fontsize=12)
        ax.set_xlabel("Temperature [K]")
        ax.set_ylabel("RMS site-occupation order amplitude")
        ax.set_ylim(-.02, .55)
        ax.grid(alpha=.2)
        ax.legend(fontsize=8, ncol=2)
    figure.suptitle(f"Pandat 2022a Education cross-validation\n{summary['passed_cases']}/{len(cases)} cases passed | "
                   f"{summary['points']} points | Synthetic parameters", fontsize=16)
    files = {extension: str(folder / f"validation.{extension}") for extension in ("png", "svg")}
    for extension, path in files.items():
        figure.savefig(path, dpi=160)
    summary["files"] = {**files, "json": str(folder / "summary.json"), "csv": str(folder / "summary.csv")}
    atomic_json(folder / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summaries", nargs="+")
    report = build_report(parser.parse_args().summaries)
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=False, indent=2))
