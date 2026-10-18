"""Diagnose the largest saved discrepancy per material without changing results.

Independent differential evolution uses three independent sites; composition
conservation determines the fourth. No external or local solution seeds the
population. Supports four equal substitutional sites plus optional fixed VA.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, differential_evolution, minimize

from src.gibbs import GibbsModel, read_databases
from src.storage import atomic_json


def coordinates(model, composition):
    if len(model.groups) not in (4, 5) or not np.allclose(model.ratios[:4], .25):
        raise ValueError("Diagnosis requires four equal substitutional sites")
    if any(group != model.components for group in model.groups[:4]) or (len(model.groups) == 5 and model.groups[4] != ["VA"]):
        raise ValueError("Diagnosis only supports unrestricted elemental sites and optional fixed VA")
    # Eliminate the most abundant species for better sampling of dilute alloys.
    elements = sorted(model.components, key=lambda element: (composition[element], element))
    independent = elements[:-1]
    dimensions = 3*len(independent)

    def expand(point):
        first = np.asarray(point).reshape(3, len(independent))
        last = 4*np.array([composition[element] for element in independent])-first.sum(axis=0)
        sites = np.vstack([first, last])
        sites = np.column_stack([sites, 1-sites.sum(axis=1)])
        values = {f"Y_{i}_{element}": sites[i, j] for i in range(4) for j, element in enumerate(elements)}
        values["Y_4_VA"] = 1
        return np.array([values[label] for label in model.labels])

    offset = expand(np.zeros(dimensions))
    matrix = np.column_stack([expand(direction)-offset for direction in np.eye(dimensions)])
    bounds = [(max(0, 4*composition[element]-3), min(1, 4*composition[element])) for _ in range(3) for element in independent]
    return expand, matrix, offset, bounds, independent


def diagnose(path, all_failures=False):
    summary = json.loads(Path(path).read_text(encoding="utf-8"))
    if summary["status"] == "running":
        raise ValueError("Wait for the validation to finish")
    selected, failures = {}, []
    for case in summary["cases"]:
        folder = Path(case["folder"])
        if not (folder/"audits.json").is_file():
            continue
        for index, row in enumerate(json.loads((folder/"audits.json").read_text(encoding="utf-8"))):
            error = abs(row["equilibrium_delta_J_mol_atoms"])
            if error > 1:
                failures.append({"case": case, "row": row, "index": index, "error": error})
            if error > max(1, selected.get(case["material"], {}).get("error", 0)):
                selected[case["material"]] = {"case": case, "row": row, "index": index, "error": error}
    output = {"method": "independent scipy differential_evolution followed by constrained SLSQP polish",
              "selection": "all optimized-G discrepancies above 1 J/mol-atoms" if all_failures else "largest absolute optimized-G discrepancy per material", "seed": 20261018,
              "popsize": 24, "maxiter": 1200, "tol": 1e-10, "points": []}
    destination = Path(summary["folder"])/"optimization_diagnosis.json"
    for item in (failures if all_failures else selected.values()):
        case, row = item["case"], item["row"]
        material = case["material"]
        folder = Path(case["folder"])
        db, _ = read_databases([str(folder/"original.tdb")])
        model = GibbsModel(db, case["phase"], None, [row["T_K"]], 101325, True)
        composition = {key[2:]: value for key, value in row.items() if key.startswith("X_")}
        expand, matrix, offset, bounds, independent = coordinates(model, composition)
        constraint = LinearConstraint(matrix, -offset, 1-offset)

        def energy(point):
            y = expand(point)
            if y.min() < -1e-8 or y.max() > 1+1e-8:
                return 1e10
            return float(model.values(row["T_K"], 101325, np.clip(y, 0, 1))[0])

        print(f"Diagnosing {case['name']} point {item['index']}", flush=True)
        result = differential_evolution(energy, bounds, constraints=constraint, seed=output["seed"],
                                        popsize=output["popsize"], maxiter=output["maxiter"], tol=output["tol"], polish=False)
        polished = minimize(lambda point: energy(point)/1000, result.x, method="SLSQP",
                            bounds=Bounds(*np.array(bounds).T), constraints=constraint, options={"ftol": 1e-12, "maxiter": 1000})
        de_y, polished_y = expand(result.x), expand(polished.x)
        valid = polished.success and polished_y.min() >= -1e-9 and polished_y.max() <= 1+1e-9
        use_polish = valid and energy(polished.x) <= result.fun
        y = polished_y if use_polish else de_y
        best = energy(polished.x) if use_polish else float(result.fun)
        record = {"material": material, "case": case["name"], "point_index": item["index"], "T_K": row["T_K"],
                  "composition": composition, "G_local": row["G_local"], "G_pandat": row["G_pandat"],
                  "G_independent": best, "G_independent_raw_DE": float(result.fun), "DE_success": bool(result.success),
                  "DE_message": str(result.message), "DE_nfev": result.nfev, "polish_used": bool(use_polish),
                  "difference_from_local_J_mol_atoms": best-row["G_local"],
                  "site_fractions": dict(zip(model.labels, y.tolist())), "independent_species": independent,
                  "bounds": bounds, "constraint_matrix": matrix.tolist(), "constraint_offset": offset.tolist(),
                  "max_composition_error": float(np.max(np.abs(model.atomic_fractions(y)-model.composition(composition)))),
                  "max_site_sum_error": float(np.max(np.abs(model.site_matrix @ y-1)))}
        output["points"].append(record)
        atomic_json(destination, output)
        print(json.dumps({key: record[key] for key in ("material", "G_independent", "DE_success", "difference_from_local_J_mol_atoms")}), flush=True)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary")
    parser.add_argument("--all-failures", action="store_true")
    args = parser.parse_args()
    output = diagnose(args.summary, args.all_failures)
    print(json.dumps({"selection": output["selection"], "points": len(output["points"])}, ensure_ascii=False))
