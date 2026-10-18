"""Create reproducible synthetic phase-diagram requests (not a material assessment).

    python -m examples.phase_diagram_demo
    python -m altdb --json phase-diagram data/phase_diagram_demo/binary.json
"""
from config import resolve_data_path
from src.storage import atomic_json, atomic_write


def eutectic_database(components=("AL", "NI")):
    weights = {"AL": 26.9815, "NI": 58.6934, "FE": 55.845, "CR": 51.996}
    text = "$ Synthetic ideal-liquid / pure-solid system; not a material database.\n"
    text += "\n".join(f"ELEMENT {c} BLANK {weights[c]} 0 0 !" for c in components)
    text += "\nTYPE_DEFINITION % SEQ * !\n"
    for c in components:
        text += f"PHASE SOLID_{c} % 1 1 !\nCONSTITUENT SOLID_{c} :{c}: !\nPARAMETER G(SOLID_{c},{c};0) 298.15 0; 2500 N !\n"
    text += f"PHASE LIQUID % 1 1 !\nCONSTITUENT LIQUID :{','.join(components)}: !\n"
    text += "\n".join(f"PARAMETER G(LIQUID,{c};0) 298.15 10000-10*T; 2500 N !" for c in components) + "\n"
    return text


def prepare():
    folder = resolve_data_path("phase_diagram_demo")
    folder.mkdir(parents=True, exist_ok=True)
    for name, components in [("binary", ["AL", "NI"]), ("ternary", ["AL", "NI", "FE"]), ("isopleth", ["AL", "NI", "FE", "CR"])]:
        path = folder / (name + ".tdb")
        atomic_write(path, eutectic_database(components))
        request = {"tdb_files": [str(path)], "components": components, "mode": name, "points": 21,
                   "temperatures": [500] if name == "ternary" else list(range(350, 1101, 25)), "sampling_density": 100}
        if name == "isopleth":
            request.update(composition_start={"AL": .8, "FE": .1, "CR": .1},
                           composition_end={"NI": .8, "FE": .1, "CR": .1})
        atomic_json(folder / (name + ".json"), request)
    atomic_json(folder / "property.json", {"tdb_files": [str(folder / "binary.tdb")], "components": ["AL", "NI"],
                "mode": "property", "composition": {"AL": .35, "NI": .65}, "temperatures": list(range(350, 1101, 10))})
    return folder


if __name__ == "__main__":
    print(prepare())
