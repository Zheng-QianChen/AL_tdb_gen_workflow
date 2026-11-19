"""Read structures from fixed public endpoints for an explicitly selected system."""

import os
import requests
from pymatgen.core import Structure
from src.project_catalog import symbols


def fetch_structures(provider, elements, offset=0):
    system = symbols(elements)
    if provider == "mp":
        token = os.getenv("MP_API_KEY")
        if not token:
            raise ValueError("请在启动服务前设置 MP_API_KEY")
        url = "https://api.materialsproject.org/materials/summary/"
        params = {
            "chemsys": "-".join(system),
            "_fields": "material_id,structure,formula_pretty",
            "_limit": 20,
            "_skip": offset,
            "deprecated": "false",
        }
        headers = {"X-API-KEY": token}
    elif provider == "oqmd":
        url = "https://oqmd.org/oqmdapi/formationenergy"
        params = {
            "composition": "-".join(system),
            "filter": f"ntypes={len(system)}",
            "fields": "name,entry_id,unit_cell,sites",
            "format": "json",
            "limit": 20,
            "offset": offset,
        }
        headers = {}
    else:
        raise ValueError("未知的外部结构库")
    response = requests.get(
        url, params=params, headers=headers, timeout=(6, 30), allow_redirects=False
    )
    if response.status_code != 200:
        raise ConnectionError(f"{provider} 返回 HTTP {response.status_code}")
    rows = response.json()["data"]
    result = []
    for row in rows:
        if provider == "mp":
            structure = Structure.from_dict(row["structure"])
            ref = str(row["material_id"])
        else:
            species, coords = [], []
            for site in row["sites"]:
                element, position = site.split("@", 1)
                species.append(element.strip())
                coords.append([float(v) for v in position.replace(",", " ").split()])
            structure = Structure(row["unit_cell"], species, coords)
            ref = str(row["entry_id"])
        if {el.symbol for el in structure.composition.elements} == set(system):
            result.append((ref, structure))
    return result, len(rows)
