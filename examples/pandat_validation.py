"""Validate 3/4/5-sublattice and chemical ordering models against real Pandat."""
import argparse
import json
import sys
import uuid

import numpy as np

from config import BASE_DATA_DIR
from examples.pandat_batch import read_point, run_batch
from examples.pandat_models import cases
from src.gibbs import GibbsModel, read_databases, run_curve
from src.gibbs_compare import model_declaration, run_comparison, write_csv
from src.storage import atomic_json, atomic_write


def audit_case(case, folder, executable, version):
    database = folder / "model.tdb"
    atomic_write(database, case["tdb"])
    request = {"tdb_files": [str(database)], "phase": "TEST", "pressure": 101325, **case["request"]}
    atomic_json(folder / "request.json", request)
    local = run_curve(request)
    disordered_phase = local["ordering_model"].get("disordered_phase")
    execution = run_batch(executable, folder, local["rows"], local["phase"], local["components"], local["sublattices"],
                          disordered_phase=disordered_phase)
    references = [read_point(folder / "raw" / f"point_{i}.dat", local["phase"], local["components"], local["sublattices"], local["rows"][i],
                             disordered_phase=disordered_phase)
                  for i in range(len(local["rows"]))]
    reference_csv = folder / "reference.csv"
    write_csv(reference_csv, references)
    comparison_request = {"result": local["files"]["json"], "reference_csv": str(reference_csv),
                          "software": "pandat", "software_version": version,
                          "reference_model": model_declaration(local), "conditions_verified": True,
                          "energy_unit": "J/mol-atoms", "atol_J_mol_atoms": 1, "rtol": 0,
                          "fraction_atol": 2e-6}
    atomic_json(folder / "compare.json", comparison_request)
    report = run_comparison(comparison_request)
    db, _ = read_databases([str(database)])
    model = GibbsModel(db, "TEST", local["sublattices"], request["temperatures"], 101325)
    audits = []
    for point, reference in zip(local["rows"], references):
        y_local = np.array([point[label] for label in model.labels])
        y_external = np.array([reference[label] for label in model.labels])
        external_expression = float(model.values(point["T_K"], point["P_Pa"], y_external)[0])
        audit = {"T_K": point["T_K"], **{key: value for key, value in point.items() if key.startswith("X_")},
                 "pandat_reported_phase": reference["reported_phase"],
                 "formula_delta_at_pandat_Y_J_mol_atoms": external_expression-reference["G"],
                 "G_local_at_pandat_Y_J_mol_atoms": external_expression,
                 "G_local_min_J_mol_atoms": point["G_J_mol_atoms"], "G_pandat_J_mol_atoms": reference["G"]}
        if case["kind"] in {"ordered", "partitioned"}:
            x = point["X_NI"]
            local_ni = np.array([point[f"Y_{i}_NI"] for i in range(case["n"])])
            external_ni = np.array([reference[f"Y_{i}_NI"] for i in range(case["n"])])
            weights = model.ratios/model.ratios.sum()
            random = np.array([point["X_"+variable.species.name] for variable in model.variables])
            audit.update({"order_amplitude_local": float(np.sqrt(weights @ ((local_ni-x)**2))),
                          "order_amplitude_pandat": float(np.sqrt(weights @ ((external_ni-x)**2))),
                          "ordering_gain_J_mol_atoms": float(model.values(point["T_K"], point["P_Pa"], random)[0] - point["G_J_mol_atoms"])})
        audits.append(audit)
    atomic_json(folder / "audits.json", audits)
    max_formula_error = max(abs(row["formula_delta_at_pandat_Y_J_mol_atoms"]) for row in audits)
    order_check = True
    max_order_error = None
    if case["kind"] in {"ordered", "partitioned"}:
        max_order_error = max(abs(row["order_amplitude_local"] - row["order_amplitude_pandat"]) for row in audits)
        order_check = (max_order_error <= 1e-3 and audits[0]["order_amplitude_local"] > .1
                       and audits[0]["order_amplitude_pandat"] > .1
                       and audits[-1]["order_amplitude_local"] < 1e-4
                       and audits[-1]["order_amplitude_pandat"] < 1e-4
                       and min(row["ordering_gain_J_mol_atoms"] for row in audits) >= -1e-5)
    return {"name": case["name"], "sublattices": case["n"], "kind": case["kind"],
            "status": "passed" if report["status"] == "within_tolerance" and max_formula_error <= 1 and order_check else "failed",
            "points": report["compared_points"], "max_abs_G_error_J_mol_atoms": report["max_abs_error_J_mol_atoms"],
            "rmse_J_mol_atoms": report["rmse_J_mol_atoms"], "max_formula_error_at_same_Y_J_mol_atoms": max_formula_error,
            "max_order_amplitude_error": max_order_error, "ordering_checks_passed": order_check,
            "folder": str(folder), "local_result": local["files"]["json"], "comparison": report["files"]["json"],
            "disordered_branch_mapping": disordered_phase,
            "execution": execution}


def validate(executable, version, selected=None):
    folder = BASE_DATA_DIR / ("pandat_validation_" + uuid.uuid4().hex[:12])
    chosen = [case for case in cases() if selected is None or case["name"] in selected]
    if not chosen or (selected and set(selected) != {case["name"] for case in chosen}):
        raise ValueError("Unknown or empty validation case selection")
    summary = {"synthetic_parameters": True, "software_version": version, "folder": str(folder), "cases": []}
    for case in chosen:
        print(f"Validating {case['name']} ...", file=sys.stderr, flush=True)
        try:
            result = audit_case(case, folder / case["name"], executable, version)
        except Exception as exc:
            result = {"name": case["name"], "sublattices": case["n"], "kind": case["kind"],
                      "status": "error", "error": f"{type(exc).__name__}: {exc}"}
        summary["cases"].append(result)
        summary["passed_cases"] = sum(row["status"] == "passed" for row in summary["cases"])
        summary["completed_cases"] = len(summary["cases"])
        summary["expected_cases"] = len(chosen)
        summary["status"] = "running"
        atomic_json(folder / "summary.json", summary)
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr, flush=True)
    summary["status"] = "passed" if summary["passed_cases"] == len(chosen) else "failed"
    atomic_json(folder / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--cases", nargs="+")
    args = parser.parse_args()
    summary = validate(args.executable, args.version, args.cases)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    sys.exit(0 if summary["status"] == "passed" else 5)
