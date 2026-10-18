"""Reproduce observed occupancy equalities, then release them in the local model.

These are explicit diagnostic constraints, not assertions about undocumented
Pandat internals. Site numbering in the output is one-based.
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy.linalg import null_space
from scipy.optimize import LinearConstraint, minimize

from examples.pandat_literature_diagnosis import coordinates
from examples.pandat_occupancy_diagnosis import SELECTED
from src.gibbs import GibbsModel, read_databases
from src.storage import atomic_json


def analyze(model, row, pandat):
    composition = {c: row[f"X_{c}"] for c in model.components}
    expand, matrix, offset, _, independent = coordinates(model, composition)
    z = np.array([pandat[model.labels.index(f"Y_{site}_{c}")] for site in range(3) for c in independent])
    equality, pairs = [], []
    for first in range(4):
        for second in range(first+1, 4):
            if all(abs(pandat[model.labels.index(f"Y_{first}_{c}")]-pandat[model.labels.index(f"Y_{second}_{c}")]) < 2e-6
                   for c in model.components):
                pairs.append([first+1, second+1])
                for c in independent:
                    e = np.zeros(len(model.labels))
                    e[model.labels.index(f"Y_{first}_{c}")] = 1
                    e[model.labels.index(f"Y_{second}_{c}")] = -1
                    equality.append(e)
    equality = np.array(equality).reshape(-1, len(model.labels))
    a = equality @ matrix
    if len(a):
        z += np.linalg.lstsq(a, -equality @ offset-a @ z, rcond=None)[0]
    basis = null_space(a)

    def energy(point):
        y = expand(point)
        return float(model.values(row["T_K"], row["P_Pa"], np.clip(y, 0, 1))[0])

    def gradient(point):
        # SLSQP can trial infinitesimally infeasible points. Match the energy's
        # boundary extension instead of passing negative occupancies to log(y).
        y = np.clip(expand(point), 1e-14, 1)
        return matrix.T @ np.asarray(model.derivative(row["T_K"], row["P_Pa"], *y), dtype=float).reshape(-1)

    if basis.shape[1]:
        y0 = expand(z)
        restricted = minimize(lambda w: energy(z+basis @ w)/1000, np.zeros(basis.shape[1]),
                              jac=lambda w: basis.T @ gradient(z+basis @ w)/1000, method="SLSQP",
                              constraints=LinearConstraint(matrix @ basis, -y0, 1-y0),
                              options={"ftol": 1e-12, "maxiter": 1000})
        if not restricted.success or expand(z+basis @ restricted.x).min() < -1e-8:
            raise ValueError(f"Restricted optimization failed: {restricted.message}")
        z += basis @ restricted.x
    y = expand(z)
    result = {"equal_site_pairs": pairs, "full_degrees_of_freedom": len(z),
              "restricted_degrees_of_freedom": basis.shape[1], "G_restricted": energy(z),
              "G_local_multistart": row["G_J_mol_atoms"],
              "derivative_boundary_floor": 1e-14,
              "restricted_site_fractions": dict(zip(model.labels, y.tolist())),
              "max_composition_error": float(np.max(np.abs(model.atomic_fractions(y)-model.composition(composition)))),
              "max_site_sum_error": float(np.max(np.abs(model.site_matrix @ y-1))),
              "hessians": [], "released_optimizations": []}
    # Interior finite differences only. Eigenvalues depend on this explicitly
    # recorded coordinate system; their signs, not magnitudes, diagnose stability.
    for step in (1e-4, 5e-5, 1e-5):
        directions = np.eye(len(z))*step
        if any(expand(z+d).min() < 0 or expand(z-d).min() < 0 for d in directions):
            result["curvature_note"] = "Not evaluated: central differences would leave the feasible region"
            continue
        hessian = np.column_stack([(gradient(z+d)-gradient(z-d))/(2*step) for d in directions])
        hessian = (hessian+hessian.T)/2
        values, vectors = np.linalg.eigh(hessian)
        restricted_values = np.linalg.eigvalsh(basis.T @ hessian @ basis)
        result["hessians"].append({"step": step, "full_eigenvalues": values.tolist(),
                                   "restricted_eigenvalues": restricted_values.tolist(),
                                   "projected_gradient_norm": float(np.linalg.norm(gradient(z)))})
        if step != 1e-5:
            continue
        for sign in (-1, 1):
            delta = sign*1e-3*vectors[:, 0]
            while expand(z+delta).min() < 0:
                delta *= .5
            start = z+delta
            optimized = minimize(lambda point: energy(point)/1000, start,
                                 jac=lambda point: gradient(point)/1000, method="SLSQP",
                                 constraints=LinearConstraint(matrix, -offset, 1-offset),
                                 options={"ftol": 1e-12, "maxiter": 1000})
            final_y = expand(optimized.x)
            result["released_optimizations"].append({"sign": sign,
                "initial_energy_change": energy(start)-energy(z), "G": energy(optimized.x),
                "success": bool(optimized.success), "message": str(optimized.message),
                "feasible": bool(final_y.min() >= -1e-8 and final_y.max() <= 1+1e-8),
                "site_fractions": dict(zip(model.labels, final_y.tolist()))})
    result["coordinate_species"] = independent
    result["coordinate_matrix"] = matrix.tolist()
    result["coordinate_offset"] = offset.tolist()
    return result


def run(summary_path, output):
    source = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    result = {"source_validation": str(Path(summary_path).resolve()),
              "interpretation": "Imposed observed equalities in the local model, not verified internal Pandat constraints", "cases": []}
    for case in source["cases"]:
        if case["name"] not in SELECTED:
            continue
        row = json.loads(Path(case["local_result"]).read_text(encoding="utf-8"))["rows"][SELECTED[case["name"]]]
        folder = Path(case["folder"])
        db, _ = read_databases([str(folder/"original.tdb")])
        model = GibbsModel(db, case["phase"], None, [row["T_K"]], row["P_Pa"], True)
        with (folder/"reference.csv").open(newline="", encoding="utf-8") as stream:
            reference = list(csv.DictReader(stream))[SELECTED[case["name"]]]
        pandat = np.array([float(reference[label]) for label in model.labels])
        record = analyze(model, row, pandat)
        record.update(case=case["name"], T_K=row["T_K"], G_pandat=float(reference["G"]),
                      restricted_minus_pandat=record["G_restricted"]-float(reference["G"]))
        result["cases"].append(record)
        print(json.dumps({k: record[k] for k in ("case", "equal_site_pairs", "restricted_degrees_of_freedom", "restricted_minus_pandat", "G_restricted")}), flush=True)
        atomic_json(Path(output), result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.summary, args.output)
