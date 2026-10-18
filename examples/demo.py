"""Small synthetic B2 run. Energies are invented and are NOT scientific data."""
import argparse
import asyncio
import json
from pathlib import Path
import uuid

from config import BASE_DATA_DIR, RUN_DIR
from src.main_process.al_manager import ALManager
from src.storage import atomic_json, atomic_write
from src.thermodynamics import EV_PER_ATOM_TO_KJ_PER_MOL

POSCAR = """Synthetic AlNi B2
1.0
3 0 0
0 3 0
0 0 3
Al Ni
1 1
Direct
0 0 0
0.5 0.5 0.5
"""
REFERENCE = {"AL": -3.0, "NI": -5.0}
ENERGY = {"AL:AL": 2.0, "AL:NI": -20.0, "NI:AL": -10.0, "NI:NI": 3.0}


def prepare_demo(name=None):
    name = name or "demo_" + uuid.uuid4().hex[:8]
    folder = BASE_DATA_DIR / name
    folder.mkdir(parents=True, exist_ok=False)
    atomic_write(folder / "POSCAR", POSCAR)
    atomic_write(folder / "references.csv", "symbol,energy\nAl,-3\nNi,-5\n")
    atomic_write(folder / "descriptors.csv", "symbol,number,radius\nAl,13,1.43\nNi,28,1.24\n")
    data = {
        "phase_name": "DEMO_B2", "record_path": f"{name}/record",
        "structure_file": f"{name}/POSCAR", "structure_out_file": f"{name}/structure/POSCAR",
        "structure_convert_to_primitive": "no", "init_random_n": 1, "random_seed": 42,
        "tdb_model": {"site_holder": ["A", "B"], "sublattice_number": 2,
            "occup_atoms_in_tdb": [1, 1], "comp": [["AL", "NI"], ["AL", "NI"]],
            "Atom_ref": {"file": f"{name}/references.csv", "index_name": "symbol", "col_name": "energy"}},
        "AL_set": {"ML_model": "gbr", "ML_style": "flat",
            "ML_hyper_parameters": {"n_estimators": 10, "max_depth": 2},
            "descriptor": {f"{name}/descriptors.csv": {"index_name": "symbol", "col_name": ["number", "radius"]}},
            "normalizer": "Zscore", "quest": {"near_hall": 1, "unstable": 0, "random": 0},
            "generate_DFT_path": f"{name}/generated", "calced_DFT_path": f"{name}/calculated",
            "pkl_phase_path": f"{name}/checkpoints"}}
    path = RUN_DIR / f"{name}.json"
    atomic_json(path, data)
    return path, data


def write_synthetic_results(runner):
    folder = Path(runner.phase.generate_DFT_path) / str(runner.iter)
    members = [path.parent.name.replace("_", ":") for path in sorted(folder.glob("*/POSCAR"))]
    rows = []
    for member in members:
        reference = sum(REFERENCE[e] for e in member.split(":")) / 2
        total = (reference + ENERGY[member] / EV_PER_ATOM_TO_KJ_PER_MOL) * 2
        rows.append(f"{member},{total:.16g},{total:.16g}")
    target = Path(runner.phase.calced_DFT_path) / f"iter.{runner.iter:06d}" / "calc.txt"
    atomic_write(target, "\n".join(rows) + "\n")
    return target


async def run_demo():
    path, _ = prepare_demo()
    manager = ALManager()
    try:
        await manager.create_and_start_task("demo", path)
        runner = manager.tasks["demo"]
        async with asyncio.timeout(90):
            while runner.running:
                if runner.phase is not None and runner.process == 1:
                    target = Path(runner.phase.calced_DFT_path) / f"iter.{runner.iter:06d}" / "calc.txt"
                    if not target.exists():
                        write_synthetic_results(runner)
                await asyncio.sleep(.1)
            await runner.main_task
        if runner.error:
            raise RuntimeError(runner.error)
        result = await runner._run_sync(runner.output_tdb_file, "synthetic", 100)
        print(json.dumps({"config": str(path), "tdb": str(result["file_path"] / result["file_name_tdb"]),
                          "iterations": runner.iter, "synthetic": True}, indent=2))
    finally:
        await manager.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    if parser.parse_args().prepare_only:
        print(prepare_demo()[0])
    else:
        asyncio.run(run_demo())
