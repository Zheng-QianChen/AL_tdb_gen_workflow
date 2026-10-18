"""Audit selected literature points with pycalphad's native single-set solver.

Use a clean pycalphad installation. The native model is an upstream baseline;
the project model with the native solver isolates solver differences. Neither
mode certifies a global minimum. This diagnostic is limited to the selected
four substitutional sites, optionally followed by one fixed vacancy site.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import warnings

import numpy as np
import pycalphad
from pycalphad import Database, Model, variables as v
from pycalphad.codegen.phase_record_factory import PhaseRecordFactory
from pycalphad.core.composition_set import CompositionSet
from pycalphad.core.solver import Solver
from scipy.optimize import linprog

SELECTED = [("AlNi_gx", 3), ("AlNi_gt_2", 0), ("FeNi_gt_1", 1),
            ("AlFe_gt_2", 2), ("AlFeNb_gx", 4)]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def feasible_starts(composition, n_random=36):
    """Independent seeds: transportation-polytope vertices and convex mixtures."""
    x = np.array(list(composition.values()), dtype=float)
    nc = len(x)
    uniform = np.tile(x, 4)
    rows = np.kron(np.eye(4), np.ones((1, nc)))
    totals = np.tile(np.eye(nc), (1, 4))
    matrix = np.vstack([rows, totals[:-1]])
    rhs = np.r_[np.ones(4), 4*x[:-1]]
    rng = np.random.default_rng(20261018)
    vertices = []
    for _ in range(n_random):
        opt = linprog(rng.normal(size=4*nc), A_eq=matrix, b_eq=rhs,
                      bounds=(0, 1), method="highs")
        if not opt.success:
            raise RuntimeError(opt.message)
        vertices.append(opt.x)
    result = [("uniform", uniform)]
    for idx, vertex in enumerate(vertices):
        if idx < n_random//3:
            point = .999*vertex + .001*uniform
        else:
            choices = rng.choice(len(vertices), 3, replace=False)
            point = .999*(rng.dirichlet(np.ones(3)) @ np.array(vertices)[choices]) + .001*uniform
        assert np.max(np.abs(matrix@point-rhs)) < 1e-10
        result.append((f"independent_{idx:02}", point))
    return result


def run(baseline, out, n_random):
    out.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parents[1]/"src/thermo_model.py"
    spec = importlib.util.spec_from_file_location("project_thermo_model", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    baseline_data = json.loads((baseline/"summary.json").read_text(encoding="utf-8"))
    summary = {"engine": "pycalphad", "version": pycalphad.__version__,
               "constraint": "one homogeneous composition set; no phase splitting",
               "seed": 20261018, "global_minimum_certified": False,
               "project_model_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "baseline": str(baseline.resolve()), "cases": []}
    for name, index in SELECTED:
        case = next(c for c in baseline_data["cases"] if c["name"] == name)
        row = json.loads(Path(case["local_result"]).read_text(encoding="utf-8"))["rows"][index]
        folder = Path(case["folder"])
        with (folder/"reference.csv").open(encoding="utf-8-sig", newline="") as stream:
            reference = list(csv.DictReader(stream))[index]
        phase = case["phase"]
        composition = {key[2:]: value for key, value in row.items() if key.startswith("X_")}
        db = Database(str(folder/"original.tdb"))
        ratios = db.phases[phase].sublattices
        assert np.allclose(ratios[:4], .25) and len(ratios) in (4, 5)
        components = sorted(composition)+["VA"]
        seeds = feasible_starts(composition, n_random)
        point = {"case": name, "index": index, "phase": phase, "T_K": row["T_K"],
                 "P_Pa": row["P_Pa"], "composition": composition,
                 "original_tdb": str(folder/"original.tdb"),
                 "tdb_sha256": hashlib.sha256((folder/"original.tdb").read_bytes()).hexdigest(),
                 "G_local": row["G_J_mol_atoms"], "G_Pandat": float(reference["G"]),
                 "modes": {}}
        case_out = out/name
        case_out.mkdir(exist_ok=True)
        for mode, cls in [("native_model_native_solver", Model),
                          ("project_model_native_solver", module.ThermodynamicModel)]:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                model = cls(db, components, phase)
            labels = [f"Y_{s.sublattice_index}_{s.species.name}" for s in model.site_fractions]
            # Do not silently reinterpret a different site/species arrangement.
            assert labels[:4*len(composition)] == [f"Y_{i}_{c}" for i in range(4) for c in composition]
            if len(ratios) == 5:
                assert labels[-1] == "Y_4_VA"
            record = PhaseRecordFactory(db, components, [v.N, v.P, v.T], {phase: model})[phase]
            conditions = {v.N: 1., v.P: row["P_Pa"], v.T: row["T_K"],
                          **{v.X(c): composition[c] for c in list(composition)[:-1]}}
            state = np.array([conditions[s] for s in record.state_variables])

            def evaluate(y):
                cs = CompositionSet(record)
                cs.update(np.asarray(y, dtype=float), 1., state.copy())
                return cs

            fixed = {}
            for label, values in [("local_occupancy", row), ("Pandat_occupancy", reference)]:
                cs = evaluate([float(values[k]) for k in labels])
                fixed[label] = {"G": float(cs.energy), "X": np.asarray(cs.X).tolist()}
            runs = []
            full_seeds = []
            for seed_name, four_sites in seeds:
                y0 = np.r_[four_sites, 1.] if len(ratios) == 5 else four_sites.copy()
                full_seeds.append({"name": seed_name, "site_fractions": dict(zip(labels, y0.tolist()))})
                cs = evaluate(y0)
                try:
                    result = Solver(remove_metastable=False).solve([cs], conditions)
                    y = np.asarray(cs.dof)[len(record.state_variables):].copy()
                    x = dict(zip(record.nonvacant_elements, np.asarray(cs.X).tolist()))
                    comp_error = max(abs(x[c]-composition[c]) for c in composition)
                    site_error = max(abs(sum(y[j] for j, s in enumerate(model.site_fractions)
                                            if s.sublattice_index == i)-1.) for i in range(len(ratios)))
                    finite = bool(np.all(np.isfinite(np.r_[y, cs.energy, cs.NP, list(x.values())])))
                    feasible = bool(finite and comp_error < 1e-7 and site_error < 1e-7
                                    and y.min() >= -1e-10 and y.max() <= 1+1e-10 and abs(cs.NP-1) < 1e-7)
                    runs.append({"seed": seed_name, "converged": bool(result.converged),
                                 "feasible": feasible, "G": float(cs.energy) if finite else None,
                                 "max_composition_error": comp_error if finite else None,
                                 "max_site_sum_error": site_error if finite else None,
                                 "NP": float(cs.NP) if finite else None,
                                 "site_fractions": dict(zip(labels, y.tolist())) if finite else None})
                except Exception as exc:
                    runs.append({"seed": seed_name, "converged": False, "feasible": False,
                                 "error": f"{type(exc).__name__}: {exc}"})
            accepted = [r for r in runs if r["converged"] and r["feasible"]]
            best = min(accepted, key=lambda r: r["G"]) if accepted else None
            point["modes"][mode] = {"warnings": [str(w.message) for w in caught],
                "fixed_occupancy": fixed, "attempts": len(runs), "accepted": len(accepted),
                "best": best, "runs": runs}
            write_json(case_out/"independent_seeds.json", full_seeds)
            print(name, mode, "accepted", len(accepted), "best", best["G"] if best else None, flush=True)
        summary["cases"].append(point)
        write_json(out/"pycalphad.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--random-starts", type=int, default=36)
    args = parser.parse_args()
    if args.random_starts < 3:
        parser.error("--random-starts must be >=3")
    run(args.baseline, args.out, args.random_starts)
