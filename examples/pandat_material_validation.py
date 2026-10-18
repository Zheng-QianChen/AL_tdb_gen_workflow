"""Validate installed material databases and targeted synthetic controls."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid

import numpy as np

from config import BASE_DATA_DIR
from examples.pandat_batch import read_point, run_batch
from examples.pandat_special_models import INTERSTITIAL, magnetic_ordering_tdb
from src.gibbs import GibbsModel, read_databases, run_curve
from src.gibbs_compare import model_declaration, run_comparison, write_csv
from src.storage import atomic_json, atomic_write


def material_cases(installation):
    contour = Path(installation)/"Pandat 2022 Examples/PanPhaseDiagram/Contour"
    book = Path(installation)/"Pandat 2022 Example book"
    def gx(phase, temperatures, start, end, **kwargs):
        return {"phase": phase, "mode": "gx", "temperatures": temperatures, "points": 3,
                "composition_start": start, "composition_end": end, "starts": 32, **kwargs}
    definitions = [
        ("FeC_BCC_interstitial_magnetic", contour/"FeC.tdb", gx("BCC", [600, 900, 1043, 1200], {"FE": 1}, {"FE": .98, "C": .02})),
        ("FeC_FCC_interstitial_magnetic", contour/"FeC.tdb", gx("FCC", [600, 1000, 1400], {"FE": 1}, {"FE": .92, "C": .08})),
        ("FeCrNi_SIGMA_3sl", book/"FeCrNi.tdb", gx("SIGMA", [700, 1200], {"CR": .65, "FE": .3, "NI": .05}, {"CR": .45, "FE": .4, "NI": .15})),
        ("FeCrNi_BCC_magnetic", book/"FeCrNi.tdb", gx("BCC", [600, 1000, 1400], {"CR": .1, "FE": .8, "NI": .1}, {"CR": .3, "FE": .6, "NI": .1})),
        ("FeCrNi_FCC_magnetic", book/"FeCrNi.tdb", gx("FCC", [600, 1000, 1400], {"CR": .1, "FE": .8, "NI": .1}, {"CR": .3, "FE": .6, "NI": .1})),
        ("AlNi_AL3NI2_variable_vacancy", book/"AlNi_Prep.tdb", gx("AL3NI2", [600, 1200], {"AL": .65, "NI": .35}, {"AL": .55, "NI": .45})),
        ("AlNi_L12_fixed_vacancy", book/"AlNi_Prep.tdb", gx("L12_FCC", [600, 1000, 1400], {"AL": .2, "NI": .8}, {"AL": .3, "NI": .7})),
        ("AlFe_AL13FE4_variable_vacancy", contour/"AlFe.tdb", gx("AL13FE4", [600, 1200], {"AL": .73, "FE": .27}, {"AL": .765, "FE": .235})),
        ("AlFe_B2_ordering_magnetic_reference", contour/"AlFe.tdb", gx("BCC_B2", [500, 900, 1300], {"AL": .15, "FE": .85}, {"AL": .5, "FE": .5}, allow_missing_ordered_endmembers=True)),
    ]
    cases = [{"name": name, "source": source, "request": request, "synthetic": False} for name, source, request in definitions]
    cases.append({"name": "synthetic_interstitial", "tdb": INTERSTITIAL, "synthetic": True,
                  "request": gx("TEST", [500, 1200], {"FE": 1}, {"FE": .75, "C": .25})})
    for n in (2, 3, 4):
        for afm in (False, True):
            cases.append({"name": f"synthetic_{n+1}sl_coupled_{'afm' if afm else 'fm'}", "synthetic": True,
                          "tdb": magnetic_ordering_tdb(n, interstitial=True, afm=afm, dialect="DISORDER_PART"),
                          "request": {"phase": "TEST", "mode": "gt", "temperatures": [400, 800, 1000, 1200, 1800, 3200],
                                      "composition": {"AL": .5, "NI": .5}, "starts": 32}})
    cases.append({"name": "synthetic_3sl_coupled_variable_interstitial", "synthetic": True,
                  "tdb": magnetic_ordering_tdb(2, variable_interstitial=True, dialect="DISORDER_PART"),
                  "request": {"phase": "TEST", "mode": "gt", "temperatures": [400, 800, 1000, 1200, 1800, 3200],
                              "composition": {"AL": .45, "NI": .45, "C": .1}, "starts": 32}})
    return cases


def audit(case, folder, executable, version):
    path = folder/"model.tdb"
    folder.mkdir(parents=True)
    if "source" in case:
        shutil.copyfile(case["source"], path)
        provenance = {"path": str(case["source"]), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "kind": case.get("source_kind", "unmodified_installed_material_example")}
    else:
        atomic_write(path, case["tdb"])
        provenance = {"kind": "synthetic_control", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    local_path = path
    if "local_source" in case:
        local_path = folder/"original.tdb"
        shutil.copyfile(case["local_source"], local_path)
        provenance["local_source"] = {"path": str(case["local_source"]),
                                      "sha256": hashlib.sha256(local_path.read_bytes()).hexdigest()}
    if "provenance" in case:
        provenance["details"] = case["provenance"]
    atomic_json(folder/"source.json", provenance)
    request = {"tdb_files": [str(local_path)], "pressure": 101325, **case["request"]}
    atomic_json(folder/"request.json", request)
    local = run_curve(request)
    order = local["ordering_model"]
    execution = run_batch(executable, folder, local["rows"], local["phase"], local["components"], local["sublattices"],
                          disordered_phase=order.get("disordered_phase"), all_site_columns=True)
    references = [read_point(folder/"raw"/f"point_{i}.dat", local["phase"], local["components"], local["sublattices"], row,
                             disordered_phase=order.get("disordered_phase"), disordered_site_mapping=order.get("disordered_site_mapping"))
                  for i, row in enumerate(local["rows"])]
    write_csv(folder/"reference.csv", references)
    compare = {"result": local["files"]["json"], "reference_csv": str(folder/"reference.csv"), "software": "pandat",
               "software_version": version, "reference_model": model_declaration(local), "conditions_verified": True,
               "fraction_atol": 3e-6, "atol_J_mol_atoms": 1, "rtol": 0}
    atomic_json(folder/"compare.json", compare)
    report = run_comparison(compare)
    db, _ = read_databases([str(local_path)])
    model = GibbsModel(db, local["phase"], local["sublattices"], request["temperatures"], 101325,
                       request.get("allow_missing_ordered_endmembers", False))
    audits = []
    for row, reference in zip(local["rows"], references):
        y = np.array([reference[label] for label in model.labels])
        same_y = float(model.values(row["T_K"], row["P_Pa"], y)[0])
        entry = {"T_K": row["T_K"], **{key: value for key, value in row.items() if key.startswith("X_")},
                 "G_local": row["G_J_mol_atoms"], "G_pandat": reference["G"], "G_local_at_pandat_Y": same_y,
                 "equilibrium_delta_J_mol_atoms": row["G_J_mol_atoms"]-reference["G"],
                 "formula_delta_J_mol_atoms": same_y-reference["G"], "pandat_reported_phase": reference["reported_phase"],
                 "G_magnetic_local": row["G_mag_J_mol_atoms"], "TC_local_K": row["TC_K"], "BMAG_local": row["BMAG"],
                 "atoms_per_formula_unit_local": row["atoms_per_formula_unit"],
                 "atoms_per_formula_unit_pandat_Y": float(model.atom_vector @ y)}
        if "ordering_sublattices" in order:
            sites = order["ordering_sublattices"]
            element = next(name for name in model.groups[sites[0]] if name != "VA")
            w = model.ratios[sites]/model.ratios[sites].sum()
            for label, point in (("local", row), ("pandat", reference)):
                occupations = np.array([point[f"Y_{site}_{element}"] for site in sites])
                entry["q_"+label] = float(np.sqrt(w @ (occupations-w @ occupations)**2))
        audits.append(entry)
    atomic_json(folder/"audits.json", audits)
    max_formula = max(abs(point["formula_delta_J_mol_atoms"]) for point in audits)
    q_errors = [abs(point["q_local"]-point["q_pandat"]) for point in audits if "q_local" in point]
    return {"name": case["name"], "synthetic": case["synthetic"], "phase": local["phase"], "sublattices": len(local["sublattices"]),
            "status": "passed" if report["status"] == "within_tolerance" and max_formula <= 1 and max(q_errors, default=0) <= 1e-3 else "failed",
            "points": len(audits), "max_abs_G_error_J_mol_atoms": report["max_abs_error_J_mol_atoms"],
            "energy_points_passed": sum(abs(point["equilibrium_delta_J_mol_atoms"]) <= 1 for point in audits),
            "formula_points_passed": sum(abs(point["formula_delta_J_mol_atoms"]) <= 1 for point in audits),
            "max_formula_error_J_mol_atoms": max_formula, "max_order_amplitude_error": max(q_errors, default=None),
            "local_result": local["files"]["json"], "comparison": report["files"]["json"], "folder": str(folder),
            "source": provenance, "execution": execution}


def validate(executable, version, selected=None):
    installation = Path(executable).resolve().parent.parent
    chosen = [case for case in material_cases(installation) if not selected or case["name"] in selected]
    if not chosen or (selected and set(selected) != {case["name"] for case in chosen}):
        raise ValueError("Unknown or empty case selection")
    folder = BASE_DATA_DIR/("pandat_material_validation_"+uuid.uuid4().hex[:12])
    summary = {"folder": str(folder), "software_version": version, "cases": [], "expected_cases": len(chosen),
               "tolerances": {"energy_J_mol_atoms": 1, "fraction": 3e-6, "order_amplitude": 1e-3}}
    for case in chosen:
        print("Validating " + case["name"], file=sys.stderr, flush=True)
        try:
            result = audit(case, folder/case["name"], executable, version)
        except Exception as exc:
            result = {"name": case["name"], "synthetic": case["synthetic"], "status": "error", "error": f"{type(exc).__name__}: {exc}",
                      "folder": str(folder/case["name"])}
        summary["cases"].append(result)
        summary["status"] = "running"
        atomic_json(folder/"summary.json", summary)
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr, flush=True)
    summary["status"] = "passed" if all(case["status"] == "passed" for case in summary["cases"]) else "failed"
    summary["points"] = sum(case.get("points", 0) for case in summary["cases"])
    summary["passed_cases"] = sum(case["status"] == "passed" for case in summary["cases"])
    for key in ("energy_points_passed", "formula_points_passed"):
        summary[key] = sum(case.get(key, 0) for case in summary["cases"])
    atomic_json(folder/"summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--cases", nargs="+")
    args = parser.parse_args()
    summary = validate(args.executable, args.version, args.cases)
    print(json.dumps({key: value for key, value in summary.items() if key != "cases"}, ensure_ascii=False, indent=2))
    sys.exit(0 if summary["status"] == "passed" else 5)
