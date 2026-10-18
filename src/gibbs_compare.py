"""Compare externally calculated homogeneous-phase points with saved curves.

This module imports results; it does not invoke or emulate a commercial solver.
External model/constraint declarations remain the operator's responsibility.
"""
import csv
import hashlib
import io
import json
import uuid
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator

from config import resolve_data_path
from src.storage import atomic_json, atomic_write


class ReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    phase: str
    sublattices: list[list[str]]
    site_ratios: list[float]
    source_sha256: list[str]
    reference_state: Literal["database"]
    phase_constraint: Literal["homogeneous_single_phase"]
    site_fraction_mode: Literal["optimized", "fixed"]


class GibbsComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    result: str
    reference_csv: str
    software: Literal["pandat", "thermo-calc", "other"]
    software_version: str = Field(min_length=1)
    reference_model: ReferenceModel
    conditions_verified: Literal[True]
    energy_unit: Literal["J/mol-atoms", "kJ/mol-atoms"] = "J/mol-atoms"
    atol_J_mol_atoms: float = Field(default=1, ge=0)
    rtol: float = Field(default=0, ge=0, le=1)
    fraction_atol: float = Field(default=1e-8, gt=0, le=1e-4)

    @field_validator("software_version")
    @classmethod
    def nonblank_version(cls, value):
        if not value.strip():
            raise ValueError("Record the external software version")
        return value.strip()


def read_result(value):
    path = resolve_data_path(value)
    content = path.read_bytes()
    result = json.loads(content.decode("utf-8-sig"))
    if (not result.get("rows") or not result.get("sources")
            or result.get("energy_unit") != "J/mol-atoms"
            or result.get("phase_constraint") != "homogeneous_single_phase"):
        raise ValueError("Use a saved homogeneous-phase gibbs.json result")
    return result, {"path": str(path), "sha256": hashlib.sha256(content).hexdigest()}


def model_declaration(result):
    return ReferenceModel(phase=result["phase"], sublattices=result["sublattices"],
                          site_ratios=result["site_ratios"],
                          source_sha256=[s["sha256"] for s in result["sources"]],
                          reference_state="database", phase_constraint=result["phase_constraint"],
                          site_fraction_mode=result["site_fraction_mode"]).model_dump()


def write_csv(path, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(path, stream.getvalue())


def prepare_reference(result_path):
    result, provenance = read_result(result_path)
    folder = resolve_data_path("gibbs_comparisons") / ("template_" + uuid.uuid4().hex[:12])
    conditions = ["T_K", "P_Pa", *["X_" + name for name in result["components"]]]
    sites = [key for key in result["rows"][0] if key.startswith("Y_")]
    # Never copy local energies or optimized occupations into reference fields.
    rows = [{"phase": result["phase"], **{key: row[key] for key in conditions}, "G": "",
             **{key: row[key] if result["site_fraction_mode"] == "fixed" else "" for key in sites}}
            for row in result["rows"]]
    reference = folder / "reference.csv"
    write_csv(reference, rows)
    request = {"result": provenance["path"], "reference_csv": str(reference),
               "software": "thermo-calc", "software_version": "",
               "reference_model": model_declaration(result), "conditions_verified": False,
               "energy_unit": "J/mol-atoms", "atol_J_mol_atoms": 1.0, "rtol": 0.0}
    atomic_json(folder / "compare.json", request)
    atomic_json(folder / "conditions.json", {"local_result": provenance, "model": model_declaration(result),
                "sources": result["sources"], "request": result["request"], "rows": rows,
                "instructions": ["Calculate G independently in Pandat or Thermo-Calc and fill reference.csv.",
                    "Rows may be removed to compare a subset; do not leave blank G values.",
                    "Match the database, sublattice restrictions, reference state and phase constraint.",
                    "Record software_version and set conditions_verified only after checking the external setup."]})
    return {"status": "reference_template", "point_count": len(rows),
            "files": {"csv": str(reference), "request": str(folder / "compare.json"),
                      "conditions": str(folder / "conditions.json")}}


def compare_points(result, request, reference_text):
    request = GibbsComparisonRequest.model_validate(request)
    declared = request.reference_model.model_dump()
    expected = model_declaration(result)
    declared["phase"] = declared["phase"].upper()
    declared["sublattices"] = [sorted(name.upper() for name in group) for group in declared["sublattices"]]
    expected["sublattices"] = [sorted(group) for group in expected["sublattices"]]
    if declared != expected:
        raise ValueError("Reference model differs: check phase, sublattices, site ratios, TDB hashes and constraints")
    reader = csv.DictReader(io.StringIO(reference_text.lstrip("\ufeff")))
    columns = reader.fieldnames or []
    conditions = ["T_K", "P_Pa", *["X_" + name for name in result["components"]]]
    sites = [key for key in result["rows"][0] if key.startswith("Y_")]
    required = {"phase", "G", *conditions}
    if len(columns) != len(set(columns)) or not required <= set(columns):
        raise ValueError("Reference CSV requires unique phase,T_K,P_Pa,G and all X_<ELEMENT> columns")
    if any(key.startswith(("X_", "Y_")) and key not in conditions + sites for key in columns):
        raise ValueError("Reference CSV contains unexpected composition/site columns")
    local = np.asarray([[row[key] for key in conditions] for row in result["rows"]], dtype=float)
    if not np.isfinite(local).all():
        raise ValueError("Local result has nonfinite conditions")
    fraction_atol = request.fraction_atol
    tolerances = np.array([1e-6, .01, *[fraction_atol for _ in result["components"]]])
    used, rows = set(), []
    scale = 1000 if request.energy_unit == "kJ/mol-atoms" else 1
    for line, reference in enumerate(reader, start=2):
        if len(rows) >= 2000:
            raise ValueError("Compare at most 2000 reference points per request")
        if None in reference or any(reference.get(key) is None for key in required):
            raise ValueError(f"CSV line {line}: inconsistent column count")
        if reference["phase"].strip().upper() != result["phase"]:
            raise ValueError(f"CSV line {line}: phase mismatch; use one homogeneous phase, not split composition sets")
        try:
            values = np.array([float(reference[key]) for key in conditions])
            energy = float(reference["G"]) * scale
        except (ValueError, TypeError) as exc:
            raise ValueError(f"CSV line {line}: fill finite numeric conditions and independently calculated G") from exc
        if (not np.isfinite(values).all() or not np.isfinite(energy) or np.any(values[:2] <= 0)
                or np.any(values[2:] < 0) or not np.isclose(values[2:].sum(), 1, atol=fraction_atol, rtol=0)):
            raise ValueError(f"CSV line {line}: invalid T/P, composition or G")
        matches = np.flatnonzero(np.all(np.abs(local - values) <= tolerances, axis=1))
        if len(matches) != 1:
            raise ValueError(f"CSV line {line}: expected exactly one matching T/P/composition point, found {len(matches)}; no interpolation is used")
        index = int(matches[0])
        if index in used:
            raise ValueError(f"CSV line {line}: duplicate reference point")
        used.add(index)
        point = result["rows"][index]
        site_error = None
        supplied_sites = [key for key in sites if (reference.get(key) or "").strip()]
        if supplied_sites or result["site_fraction_mode"] == "fixed":
            if len(supplied_sites) != len(sites):
                raise ValueError(f"CSV line {line}: supply all site fractions, including zeros")
            try:
                occupancy = {key: float(reference[key]) for key in sites}
            except ValueError as exc:
                raise ValueError(f"CSV line {line}: invalid site fractions") from exc
            if any(not np.isfinite(y) or y < 0 or y > 1 for y in occupancy.values()):
                raise ValueError(f"CSV line {line}: invalid site fractions")
            composition = dict.fromkeys(result["components"], 0.0)
            for site, (group, ratio) in enumerate(zip(result["sublattices"], result["site_ratios"])):
                if not np.isclose(sum(occupancy[f"Y_{site}_{name}"] for name in group), 1, atol=fraction_atol, rtol=0):
                    raise ValueError(f"CSV line {line}: site fractions must sum to one")
                for name in group:
                    if name != "VA":
                        composition[name] += ratio * occupancy[f"Y_{site}_{name}"]
            total_atoms = sum(composition.values())
            if total_atoms <= 0:
                raise ValueError(f"CSV line {line}: zero-atom configuration")
            composition = {name: amount/total_atoms for name, amount in composition.items()}
            if any(abs(composition[name] - values[2+i]) > fraction_atol for i, name in enumerate(result["components"])):
                raise ValueError(f"CSV line {line}: site fractions differ from overall composition")
            site_error = max(abs(occupancy[key] - point[key]) for key in sites)
            if result["site_fraction_mode"] == "fixed" and site_error > fraction_atol:
                raise ValueError(f"CSV line {line}: fixed site fractions differ from local calculation")
        local_energy = float(point["G_J_mol_atoms"])
        if not np.isfinite(local_energy):
            raise ValueError("Local result has nonfinite G")
        delta = local_energy - energy
        tolerance = request.atol_J_mol_atoms + request.rtol * abs(energy)
        rows.append({"local_index": index, "reference_line": line, "phase": result["phase"],
                     **dict(zip(conditions, values.tolist())), "G_local_J_mol_atoms": local_energy,
                     "G_reference_J_mol_atoms": energy, "delta_G_J_mol_atoms": delta,
                     "abs_delta_G_J_mol_atoms": abs(delta), "tolerance_J_mol_atoms": tolerance,
                     "passed": abs(delta) <= tolerance, "max_abs_delta_Y": site_error})
    if not rows:
        raise ValueError("Reference CSV contains no calculation points")
    differences = np.asarray([row["delta_G_J_mol_atoms"] for row in rows])
    site_errors = [row["max_abs_delta_Y"] for row in rows if row["max_abs_delta_Y"] is not None]
    return {"status": "within_tolerance" if all(row["passed"] for row in rows) else "outside_tolerance",
            "software": request.software, "software_version": request.software_version,
            "external_setup_verification": "user_declared", "reference_model": declared,
            "compared_points": len(rows), "local_points": len(local), "uncompared_points": len(local)-len(rows),
            "all_points_compared": len(rows) == len(local), "passed_points": sum(row["passed"] for row in rows),
            "max_abs_error_J_mol_atoms": float(np.abs(differences).max()),
            "rmse_J_mol_atoms": float(np.sqrt(np.mean(differences**2))),
            "mean_signed_error_J_mol_atoms": float(differences.mean()),
            "points_with_site_fractions": len(site_errors),
            "max_abs_delta_Y": max(site_errors) if site_errors else None,
            "rows": rows,
            "notes": ["Differences are local minus external G; tolerance applies only to imported points.",
                      "TDB/constraints are declared by the operator, not verified against an external solver session.",
                      "Equivalent ordered occupations may differ while giving the same G; optimized Y differences are diagnostic."]}


def run_comparison(request):
    request = GibbsComparisonRequest.model_validate(request)
    result, local_source = read_result(request.result)
    path = resolve_data_path(request.reference_csv)
    reference = path.read_bytes()
    report = compare_points(result, request, reference.decode("utf-8-sig"))
    folder = resolve_data_path("gibbs_comparisons") / ("comparison_" + uuid.uuid4().hex[:12])
    report.update({"request": request.model_dump(), "local_result": local_source,
                   "external_result": {"path": str(path), "sha256": hashlib.sha256(reference).hexdigest()},
                   "files": {"csv": str(folder / "comparison.csv"), "json": str(folder / "comparison.json")}})
    write_csv(folder / "comparison.csv", report["rows"])
    atomic_json(folder / "comparison.json", report)
    return report
