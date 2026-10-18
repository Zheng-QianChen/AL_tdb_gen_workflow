"""Controlled Pandat mode/initial-occupancy experiments on saved discrepancies.

Known local minima are deliberate diagnostic seeds, not independent validation.
The source validation and its failed comparisons are never overwritten.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import uuid
import xml.etree.ElementTree as ET

import numpy as np

from examples.pandat_batch import batch_document, read_point, run_document
from src.gibbs import GibbsModel, read_databases
from src.storage import atomic_json


SELECTED = {"AlNi_gx": 3, "AlNi_gt_2": 0, "FeNi_gt_1": 1, "AlFe_gt_2": 2, "AlFeNb_gx": 4}
VARIANTS = [
    ("legacy_default", None, None),
    ("individual_default", "individual", None),
    ("individual_local_seed", "individual", "local"),
    ("local_pandat_seed", "local", "pandat"),
    ("local_asymmetric_seed", "local", "asymmetric"),
    ("local_local_seed", "local", "local"),
    ("local_permuted_seed", "local", "permuted"),
    ("global_default", "global", None),
    ("global_local_seed", "global", "local"),
]


def experiment_document(row, model, seeds, variants, chemical_potentials=None):
    """Use the documented 1-based sublattice initial_value format (2022 manual)."""
    document = ET.Element("pbfx", version="1.0")
    ET.SubElement(ET.SubElement(document, "Header"), "Application", name="Pandat", version="2022")
    for index, (_, mode, seed_name) in enumerate(variants):
        calculation = ET.fromstring(batch_document([row], model.phase, model.components, model.groups,
                                                   all_site_columns=True)).find("calculation")
        calculation.set("name", f"point_{index}")
        table = calculation.find("output/tables/table")
        table.set("name", f"point_{index}.dat")
        for name in ("f(@*)", "struct(@*)", "mu(*)"):
            ET.SubElement(table, "column", name=name)
        if mode:
            condition = calculation.find("system/condition")
            condition.clear()
            ET.SubElement(condition, "equilibrium_type", type=mode)
        if seed_name:
            y = np.asarray(seeds[seed_name], dtype=float)
            if (len(y) != len(model.labels) or not np.all(np.isfinite(y)) or y.min() < -1e-8
                    or y.max() > 1+1e-8 or not np.allclose(model.site_matrix @ y, 1, atol=1e-6)):
                raise ValueError("Invalid initial site fractions")
            expected = model.composition({element: row[f"X_{element}"] for element in model.components})
            if not np.allclose(model.atomic_fractions(y), expected, atol=2e-6, rtol=0):
                raise ValueError("Initial site fractions must conserve the requested composition")
            initial = ET.SubElement(calculation.find("system/points/point"), "initial_value")
            for species, potential in (chemical_potentials or {}).items():
                ET.SubElement(initial, "mu", species=species, value=format(float(potential), ".17g"))
            phase = ET.SubElement(initial, "phase_point", phase_name=model.phase)
            for label, value in zip(model.labels, y):
                _, site, species = label.split("_", 2)
                ET.SubElement(phase, "y", species=species, sublattice=str(int(site)+1),
                              value=format(float(np.clip(value, 0, 1)), ".17g"))
        document.append(calculation)
    ET.indent(document, space="  ")
    return ET.tostring(document, encoding="unicode")


def raw_point(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        units = next(reader)
        rows = [{k: v for k, v in row.items() if k is not None}
                for row in reader if (row.get("T") or "").strip()]
    return {"units": {k: v for k, v in units.items() if k is not None}, "rows": rows}


def run(summary_path, executable, output=None, case_names=None, variant_names=None):
    summary_path = Path(summary_path).resolve()
    source = json.loads(summary_path.read_text(encoding="utf-8"))
    destination = Path(output or f"data/pandat_occupancy_diagnosis_{uuid.uuid4().hex[:12]}").resolve()
    destination.mkdir(parents=True, exist_ok=False)
    variants = [item for item in VARIANTS if not variant_names or item[0] in variant_names]
    if not variants:
        raise ValueError("No variants selected")
    result = {"source_validation": str(summary_path), "folder": str(destination),
              "seed_provenance": "Known local minima and previously exported Pandat occupancies; targeted diagnosis, not independent validation",
              "initial_chemical_potentials": "Pandat default-mode output at the same T/P/composition", "cases": [], "status": "running"}
    for case in source["cases"]:
        if case["name"] not in SELECTED or (case_names and case["name"] not in case_names):
            continue
        index = SELECTED[case["name"]]
        folder = Path(case["folder"])
        local = json.loads(Path(case["local_result"]).read_text(encoding="utf-8"))
        row = local["rows"][index]
        db, _ = read_databases([str(folder/"original.tdb")])
        model = GibbsModel(db, case["phase"], None, [row["T_K"]], row["P_Pa"], True)
        with (folder/"reference.csv").open(newline="", encoding="utf-8") as stream:
            reference = list(csv.DictReader(stream))[index]
        own = np.array([row[label] for label in model.labels])
        pandat = np.array([float(reference[label]) for label in model.labels])
        # Mix two feasible states to break equality without changing composition.
        asymmetric = .999*pandat+.001*own
        permuted = own.copy()
        # Swapping sites 0/1 is an equivalent operation for the FCC cases; BCC
        # permutations are recorded as alternate starts, not assumed equivalent.
        for element in model.components:
            a, b = model.labels.index(f"Y_0_{element}"), model.labels.index(f"Y_1_{element}")
            permuted[a], permuted[b] = own[b], own[a]
        seeds = {"local": own, "pandat": pandat, "asymmetric": asymmetric, "permuted": permuted}
        target = destination/case["name"]
        target.mkdir()
        shutil.copyfile(folder/"model.tdb", target/"model.tdb")
        record = {"case": case["name"], "point_index": index, "phase": case["phase"],
                  "T_K": row["T_K"], "composition": {c: row[f"X_{c}"] for c in model.components},
                  "G_local": row["G_J_mol_atoms"], "G_pandat_baseline": float(reference["G"]),
                  "database_sha256": hashlib.sha256((target/"model.tdb").read_bytes()).hexdigest(),
                  "seed_occupancies": {key: dict(zip(model.labels, value.tolist())) for key, value in seeds.items()},
                  "variants": []}
        result["cases"].append(record)
        print(f"Running {case['name']} ({len(variants)} variants) in {target}", flush=True)
        try:
            baseline = target/"baseline"
            baseline.mkdir()
            shutil.copyfile(target/"model.tdb", baseline/"model.tdb")
            baseline_document = experiment_document(row, model, seeds, VARIANTS[:1])
            run_document(executable, baseline, baseline_document, 1, timeout=90)
            baseline_row = raw_point(baseline/"raw"/"point_0.dat")["rows"][0]
            chemical_potentials = {element: float(baseline_row[f"mu({element})"]) for element in model.components}
            record["initial_chemical_potentials"] = chemical_potentials
        except (ValueError, OSError) as error:
            record["execution_error"] = str(error)
            atomic_json(destination/"summary.json", result)
            continue
        for i, (name, mode, seed) in enumerate(variants):
            item = {"variant": name, "equilibrium_type": mode or "legacy individual_phase=true", "seed": seed}
            record["variants"].append(item)
            # Separate processes prevent a local-mode crash from suppressing
            # later variants, and prevent state leaking between calculations.
            attempt = target/name
            attempt.mkdir()
            shutil.copyfile(target/"model.tdb", attempt/"model.tdb")
            try:
                document = experiment_document(row, model, seeds, [variants[i]], chemical_potentials)
                item["execution"] = run_document(executable, attempt, document, 1, timeout=60)
            except (ValueError, OSError) as error:
                item["execution_error"] = str(error)
            path = attempt/"raw"/"point_0.dat"
            log = attempt/"raw"/"console.log"
            if not path.is_file() or not log.is_file() or "Simulation [point_0] done with Success." not in log.read_text(errors="replace"):
                item.update(status="execution_failed", reason="Missing DAT or success log")
                print(json.dumps({"variant": name, "status": item["status"]}), flush=True)
                atomic_json(destination/"summary.json", result)
                continue
            item["raw_output"] = raw_point(path)
            try:
                ordering = local.get("ordering_model") or {}
                parsed = read_point(path, model.phase, model.components, model.groups, row,
                                    disordered_phase=ordering.get("disordered_phase"),
                                    disordered_site_mapping=ordering.get("disordered_site_mapping"))
                y = np.array([parsed[label] for label in model.labels])
                item.update(status="homogeneous_result", result=parsed,
                            delta_from_local_J_mol_atoms=parsed["G"]-record["G_local"],
                            formula_delta_J_mol_atoms=float(model.values(row["T_K"], row["P_Pa"], y)[0])-parsed["G"],
                            max_composition_error=float(np.max(np.abs(model.atomic_fractions(y)-model.composition(record["composition"])))),
                            max_site_sum_error=float(np.max(np.abs(model.site_matrix @ y-1))))
            except (ValueError, KeyError, TypeError) as error:
                item.update(status="not_comparable_as_homogeneous", reason=str(error))
            print(json.dumps({k: item[k] for k in ("variant", "status", "delta_from_local_J_mol_atoms", "formula_delta_J_mol_atoms") if k in item}), flush=True)
            atomic_json(destination/"summary.json", result)
        atomic_json(destination/"summary.json", result)
    result["status"] = "completed_with_execution_failures" if any(
        "execution_error" in case or any(v["status"] == "execution_failed" for v in case["variants"])
        for case in result["cases"]) else "completed"
    atomic_json(destination/"summary.json", result)
    print(destination/"summary.json", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary")
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output")
    parser.add_argument("--cases", nargs="+", choices=SELECTED)
    parser.add_argument("--variants", nargs="+", choices=[item[0] for item in VARIANTS])
    args = parser.parse_args()
    run(args.summary, args.executable, args.output, args.cases, args.variants)
