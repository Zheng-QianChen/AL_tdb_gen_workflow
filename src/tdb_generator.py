"""Validated TDB phase fragments; merge with a compatible elemental reference database."""
from pathlib import Path
from itertools import product
import re
import numpy as np
import pandas as pd
from src.class_def import Phase
from src.storage import atomic_write
from src.thermodynamics import site_fractions


def process_element(value):
    species = sorted(set(value.split(":")))
    return {"sys_num": len(species), "sys_type": species}


def pre_for_model_assess(phase, file_path):
    data = phase.pt_to_hull.merge(phase.all_points, on="endmember", validate="one_to_one")
    data = data.merge(phase.subl_energy, on="endmember", validate="one_to_one")
    species = phase.tdb_model["sys_species"]
    missing = [element for element in species if element not in data.columns]
    if len(missing) > 1:
        raise ValueError("More than one composition coordinate is missing")
    if missing:
        data[missing[0]] = 1 - data[[e for e in species if e not in missing]].sum(axis=1)
    fractions = data[species].to_numpy(dtype=float)
    if (not np.isfinite(fractions).all() or np.any(fractions < -1e-8)
            or np.any(fractions > 1 + 1e-8) or not np.allclose(fractions.sum(axis=1), 1)):
        raise ValueError("Invalid atomic fractions; regenerate this checkpoint")
    weights = site_fractions(phase.tdb_model["occup_atoms_in_tdb"])
    for row, observed in zip(data.itertuples(), fractions):
        expected = {e: 0.0 for e in species}
        for element, weight in zip(row.endmember.split(":"), weights):
            expected[element] += weight
        if not np.allclose(observed, [expected[e] for e in species]):
            raise ValueError("Composition does not match endmember site fractions")
    data[["sys_num", "sys_type"]] = data["endmember"].apply(lambda value: pd.Series(process_element(value)))
    data["from"] = np.where(data["in_iter"].notna(), "VASP", "ML")
    data = data.sort_values(["above_hull", "endmember"])
    Path(file_path).mkdir(parents=True, exist_ok=True)
    data.to_csv(Path(file_path) / f"{phase.name}_tdb_gen.csv")
    return data, species


def normalize_ratio(values, decimal_places=None):
    if isinstance(values, str):
        values = [float(value) for value in values.split(":")]
    fractions = site_fractions(values)
    return [format(float(value), ".16g" if decimal_places is None else f".{decimal_places}f") for value in fractions]


def tdb_gene(model, site_elements, phase_atom_state, file_dir, phase_data_df,
             normlizesites=True, file_flag="w"):
    count = int(model[0])
    if len(site_elements) != count or len(phase_atom_state) != count:
        raise ValueError("Sublattice count does not match constituents or site ratios")
    weights = site_fractions(phase_atom_state)
    ratios = weights if normlizesites else np.asarray(phase_atom_state, dtype=float)
    scale = 1.0 if normlizesites else float(sum(phase_atom_state))
    if phase_data_df.empty:
        raise ValueError("No endmembers satisfy the export filter")
    names = phase_data_df["name"].unique()
    if len(names) != 1 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", str(names[0])):
        raise ValueError("Expected one valid TDB phase name")
    name = str(names[0]).upper()
    if any(not group for group in site_elements):
        raise ValueError("Empty sublattice constituents")
    if any(not re.fullmatch(r"[A-Z][A-Z0-9]*", e) for group in site_elements for e in group):
        raise ValueError("Invalid constituent symbol")
    energies = phase_data_df["energy"].to_numpy(dtype=float)
    if not np.isfinite(energies).all():
        raise ValueError("TDB energies must be finite")
    if phase_data_df["sub_name"].duplicated().any():
        raise ValueError("Duplicate endmember parameters")
    required = {":".join(items) for items in product(*site_elements)}
    supplied = set(phase_data_df["sub_name"])
    if supplied != required:
        raise ValueError(f"Incomplete endmember parameters: {len(required - supplied)} missing, "
                         f"{len(supplied - required)} unexpected")
    lines = ["$ Phase fragment; requires ELEMENT and GHSER functions from a compatible base database.",
             "$ Formation energies: kJ/mol-atoms; output: J/mol-formula.",
             f"PHASE {name} % {count} " + " ".join(f"{v:.16g}" for v in ratios) + " !",
             f"CONSTITUENT {name} :" + ":".join(",".join(group) for group in site_elements) + ": !"]
    subsystem = None
    for row in phase_data_df.to_dict("records"):
        elements = row["sub_name"].split(":")
        if len(elements) != count or any(e not in site_elements[i] for i, e in enumerate(elements)):
            raise ValueError(f"Endmember is incompatible with phase constituents: {row['sub_name']}")
        if subsystem != row["sub_symb"]:
            subsystem = row["sub_symb"]
            lines.append(f"\n$ {subsystem}")
        lines.append(f"PARAMETER G({name},{row['sub_name']};0) 298.15")
        lines.extend(f" +{ratio:.16g}*GHSER{element}#" for ratio, element in zip(ratios, elements))
        lines.append(f" {float(row['energy']) * 1000 * scale:+.16g}; 6000 N !")
        reference = str(row.get("Ref", "unspecified")).replace("\n", " ").replace("\r", " ")
        lines.append(f"$ source={reference}; above_hull_kJ_mol={row.get('above_hull', '')}")
    content = "\n".join(lines) + "\n"
    path = Path(file_dir)
    if file_flag == "a" and path.exists():
        content = path.read_text(encoding="utf-8") + content
    elif file_flag not in {"w", "a"}:
        raise ValueError("file_flag must be w or a")
    atomic_write(path, content)


def tdb_generate_from_MLmodel(pkl_path, iter=0, process=1, user="", mask=5, file_path="./"):
    if not np.isfinite(mask) or mask < 0:
        raise ValueError("Hull tolerance must be finite and nonnegative")
    output = Path(file_path)
    output.mkdir(parents=True, exist_ok=True)
    phase = Phase.load(Path(pkl_path) / f"model_{iter:06d}_{process}.pd")
    if not hasattr(phase, "pool_pred"):
        raise ValueError("Train a model before exporting TDB parameters")
    phase.record_path = output  # Export diagnostics must not overwrite an active run.
    phase.convex_analy()
    data, _ = pre_for_model_assess(phase, output)
    # Missing G parameters are not equivalent to excluding a phase constituent.
    # Keep every declared endmember; the tolerance only annotates the report.
    data["within_hull_tolerance"] = data["above_hull"] <= mask + 1e-8
    data.to_csv(output / f"{phase.name}_tdb_gen.csv")
    data["name"] = phase.name
    data["sub_name"] = data["endmember"]
    data["sub_symb"] = data["sys_type"].apply("_".join)
    data["Ref"] = data["from"] + ("_" + user if user else "")
    data["energy"] = data["Energy"]
    data["above_hull_new_model"] = data["above_hull"]
    filename = f"{phase.name}_{phase.iter}_raw.tdb"
    tdb_gene([len(phase.tdb_model["comp"])], phase.tdb_model["comp"],
             phase.tdb_model["occup_atoms_in_tdb"], output / filename, data)
    return {"file_path": output, "file_name_tdb": filename,
            "file_name_csv": f"{phase.name}_tdb_gen.csv"}
