"""Independently diagnose the synthetic 3 substitutional + 1 VA counterexample.

Reuses saved external results; never changes validation status or reference G.
This is deliberately restricted to the equiatomic AL/NI test fixture.
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy.optimize import LinearConstraint, differential_evolution

from src.gibbs import GibbsModel, read_databases
from src.storage import atomic_json


def diagnose(folder):
    folder = Path(folder).resolve()
    request = json.loads((folder/"request.json").read_text(encoding="utf-8"))
    database, _ = read_databases([str(folder/"model.tdb")])
    model = GibbsModel(database, request["phase"], None, request["temperatures"], request["pressure"])
    if (model.groups != [["AL", "NI"]]*3 + [["VA"]]
            or not np.allclose(model.ratios, [1/3]*3+[3])
            or request.get("composition") != {"AL": .5, "NI": .5}):
        raise ValueError("Diagnosis only supports the equiatomic 3 substitutional + 1 VA fixture")
    audits = json.loads((folder/"audits.json").read_text(encoding="utf-8"))
    with (folder/"reference.csv").open(encoding="utf-8", newline="") as stream:
        references = list(csv.DictReader(stream))
    output = {"folder": str(folder), "method": "scipy differential_evolution", "seed": 2026,
              "popsize": 24, "tol": 1e-10, "polish": False, "maxiter": 1000,
              "coordinates": "u=Y_0_NI, v=Y_1_NI, Y_2_NI=1.5-u-v; Y_3_VA=1",
              "bounds": [[0, 1], [0, 1]], "constraint": "0.5 <= u+v <= 1.5", "points": []}
    for audit, reference in zip(audits, references, strict=True):
        if abs(audit["G_local"]-audit["G_pandat"]) <= 1:
            continue
        temperature = audit["T_K"]

        def energy(point):
            ni = [point[0], point[1], 1.5-point[0]-point[1]]
            values = {f"Y_{site}_{element}": value for site, fraction in enumerate(ni)
                      for element, value in (("AL", 1-fraction), ("NI", fraction))}
            values["Y_3_VA"] = 1
            return float(model.values(temperature, request["pressure"], [values[key] for key in model.labels])[0])

        result = differential_evolution(energy, [(0, 1)]*2, constraints=LinearConstraint([[1, 1]], .5, 1.5),
                                        seed=2026, popsize=24, tol=1e-10, polish=False, maxiter=1000)
        pandat = np.array([float(reference[f"Y_{site}_NI"]) for site in range(3)])
        point = pandat[:2]
        eigenvalues = {}
        for step in (1e-4, 5e-5):
            directions = np.eye(2)*step
            hessian = np.empty((2, 2))
            for i in range(2):
                hessian[i, i] = (energy(point+directions[i])-2*energy(point)+energy(point-directions[i]))/step**2
            u, v = directions
            hessian[0, 1] = hessian[1, 0] = (energy(point+u+v)-energy(point+u-v)
                                            -energy(point-u+v)+energy(point-u-v))/(4*step**2)
            eigenvalues[str(step)] = np.linalg.eigvalsh(hessian).tolist()
        output["points"].append({"T_K": temperature, "G_local": audit["G_local"], "G_Pandat": audit["G_pandat"],
                                 "G_independent_DE": float(result.fun), "DE_success": bool(result.success),
                                 "DE_message": str(result.message), "DE_nfev": result.nfev,
                                 "DE_site_fractions_NI": [*result.x.tolist(), float(1.5-sum(result.x))],
                                 "Pandat_site_fractions_NI": pandat.tolist(),
                                 "G_local_at_pandat_Y": audit["G_local_at_pandat_Y"],
                                 "Pandat_tangent_Hessian_eigenvalues_by_step": eigenvalues})
    atomic_json(folder/"optimization_diagnosis.json", output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder")
    result = diagnose(parser.parse_args().folder)
    print(json.dumps(result, ensure_ascii=False, indent=2))
