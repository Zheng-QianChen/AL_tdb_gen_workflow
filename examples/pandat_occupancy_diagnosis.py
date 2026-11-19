"""Build a Pandat input for controlled variations of initial site occupancy."""
import xml.etree.ElementTree as ET
import numpy as np
from examples.pandat_batch import batch_document


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
