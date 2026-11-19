"""Construct independent site coordinates for a composition-constrained calculation."""
import numpy as np


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
