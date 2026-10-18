"""G-x/G-T demo with explicitly synthetic thermodynamic parameters."""
import json
import uuid
from config import BASE_DATA_DIR
from src.gibbs import run_curve
from src.storage import atomic_json, atomic_write

SYNTHETIC_TDB = """$ SYNTHETIC DEMONSTRATION ONLY. NOT AN ASSESSED Al-Ni DATABASE.
ELEMENT AL FCC_A1 26.9815 0 0 !
ELEMENT NI FCC_A1 58.6934 0 0 !
FUNCTION GHSERAL 298.15 1000-8*T; 2000 N !
FUNCTION GHSERNI 298.15 3000-12*T; 2000 N !
TYPE_DEFINITION % SEQ * !
PHASE SYNTHETIC_B2 % 2 1 1 !
CONSTITUENT SYNTHETIC_B2 :AL,NI:AL,NI: !
PARAMETER G(SYNTHETIC_B2,AL:AL;0) 298.15 2*GHSERAL#+4000; 2000 N !
PARAMETER G(SYNTHETIC_B2,AL:NI;0) 298.15 GHSERAL#+GHSERNI#-40000; 2000 N !
PARAMETER G(SYNTHETIC_B2,NI:AL;0) 298.15 GHSERNI#+GHSERAL#-20000; 2000 N !
PARAMETER G(SYNTHETIC_B2,NI:NI;0) 298.15 2*GHSERNI#+6000; 2000 N !
"""


def prepare_gibbs_demo():
    folder = BASE_DATA_DIR / ("gibbs_demo_" + uuid.uuid4().hex[:8])
    database = folder / "synthetic.tdb"
    atomic_write(database, SYNTHETIC_TDB)
    common = {"tdb_files": [str(database)], "phase": "SYNTHETIC_B2",
              "sublattices": [["AL", "NI"], ["AL", "NI"]], "starts": 8}
    gx = {**common, "mode": "gx", "temperatures": [600, 1000, 1400], "points": 51,
          "composition_start": {"AL": 1}, "composition_end": {"NI": 1}, "x_axis": "NI"}
    gt = {**common, "mode": "gt", "temperatures": list(range(300, 1501, 20)),
          "composition": {"AL": .5, "NI": .5}}
    atomic_json(folder / "gx.json", gx)
    atomic_json(folder / "gt.json", gt)
    return folder, gx, gt


if __name__ == "__main__":
    folder, gx, gt = prepare_gibbs_demo()
    results = {"synthetic": True, "inputs": str(folder),
               "gx": run_curve(gx)["files"], "gt": run_curve(gt)["files"]}
    print(json.dumps(results, ensure_ascii=False, indent=2))
