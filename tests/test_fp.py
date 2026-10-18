import json
from pathlib import Path

import dpdata
import numpy as np
import pytest
from pymatgen.io.vasp.inputs import Poscar

from src.fp import collect, dispatch, prepare, prepared, read_labels, load_labels
from src.storage import atomic_json


@pytest.fixture
def batch(phase, tmp_path):
    phase._checkpoint()
    (tmp_path / "INCAR").write_text("ENCUT = 400\nKSPACING = 0.2\nNSW = 0\n")
    # Deliberately tiny fake potentials; no licensed VASP data are in tests.
    for symbol in ("Al", "Ni"):
        (tmp_path / f"POTCAR.{symbol}").write_text(f"TITEL = PAW_PBE {symbol} TEST_ONLY\n")
    machine = tmp_path / "machine.json"
    atomic_json(machine, {"command": "srun vasp_std",
        "machine": {"batch_type": "Slurm", "context_type": "LocalContext", "remote_root": str(tmp_path / "remote")},
        "resources": {"number_node": 1, "cpu_per_node": 2, "gpu_per_node": 0, "group_size": 1, "queue_name": "test"},
        "input_files": {"INCAR": "INCAR"}, "potcars": {"AL": "POTCAR.Al", "NI": "POTCAR.Ni"},
        "result_format": "deepmd/npy", "result_file": "result", "backward_files": ["result"]})
    return phase.input_json, machine


def dataset(folder, task, *, energies=(-9.0, -8.0), wrong=False):
    names = list(task["composition"])
    counts = list(task["composition"].values())
    if wrong:
        names[0] = "He"
    natoms = sum(counts)
    labels = dpdata.LabeledSystem(data={"atom_names": names, "atom_numbs": counts,
        "atom_types": np.repeat(np.arange(len(names)), counts), "orig": np.zeros(3),
        "cells": np.repeat((np.eye(3) * 3)[None, :, :], len(energies), axis=0),
        "coords": np.zeros((len(energies), natoms, 3)), "forces": np.zeros((len(energies), natoms, 3)),
        "energies": np.array(energies)})
    labels.to("deepmd/npy", str(folder / "result"))


def test_prepare_idempotent_and_input_drift(batch):
    config, machine = batch
    first = prepare(config, machine)
    assert prepare(config, machine) == first
    _, _, _, fp, manifest, _ = prepared(config)
    for task in manifest["tasks"]:
        folder = fp / task["task_id"]
        symbols = Poscar.from_file(folder / "POSCAR", check_for_potcar=False).site_symbols
        expected = "".join(f"TITEL = PAW_PBE {symbol} TEST_ONLY\n" for symbol in symbols)
        assert (folder / "POTCAR").read_text() == expected
    (fp / manifest["tasks"][0]["task_id"] / "INCAR").write_text("changed")
    with pytest.raises(ValueError, match="Prepared input changed"):
        dispatch(config, machine, dry_run=True)


def test_potcar_species_mismatch_is_rejected(batch):
    config, machine = batch
    (machine.parent / "POTCAR.Al").write_text("TITEL = PAW_PBE Fe TEST_ONLY\n")
    with pytest.raises(ValueError, match="POTCAR TITEL"):
        prepare(config, machine)


def test_dry_run_never_constructs_machine(batch, monkeypatch):
    from dpdispatcher import Machine
    config, machine = batch
    prepare(config, machine)
    monkeypatch.setattr(Machine, "load_from_dict", lambda *_: pytest.fail("dry run connected"))
    plan = dispatch(config, machine, dry_run=True)
    assert not plan["connects_to_cluster"] and plan["task_count"] > 0


def test_real_dispatcher_slurm_objects_and_stable_recovery(batch, monkeypatch):
    from dpdispatcher import Submission
    config, machine = batch
    prepare(config, machine)
    calls = []

    def simulate(self, **kwargs):
        calls.append((self, kwargs))
        return {}

    # Build the genuine Slurm/Resources/Task/Submission objects; replace only
    # the scheduler boundary so CI never invokes sbatch or contacts a cluster.
    monkeypatch.setattr(Submission, "run_submission", simulate)
    monkeypatch.setattr(Submission, "check_all_finished", lambda _: False)
    first = dispatch(config, machine)
    second = dispatch(config, machine, wait=True)
    assert first["submission_hash"] and first["submission_hash"] == second["submission_hash"]
    assert calls[0][1] == {"exit_on_submit": True, "clean": False, "check_interval": 30}
    assert calls[1][1]["exit_on_submit"] is False
    assert len(calls[0][0].belonging_tasks) == first["task_count"]
    assert all(t.command == "srun vasp_std" for t in calls[0][0].belonging_tasks)


def test_dispatch_interruption_keeps_recovery_record(batch, monkeypatch):
    from dpdispatcher import Submission
    config, machine = batch
    prepare(config, machine)
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(Submission, "run_submission", interrupt)
    with pytest.raises(KeyboardInterrupt):
        dispatch(config, machine, wait=True)
    fp = prepared(config)[3]
    report = json.loads((fp / "dispatch.json").read_text())
    assert report["status"] == "interrupted_or_failed" and report["submission_hash"]


def test_pipeline_with_synthetic_scheduler_runs_multiple_rounds(batch, monkeypatch, capsys):
    from altdb.cli import main
    from dpdispatcher import Submission
    from examples.demo import ENERGY, REFERENCE
    from src.thermodynamics import EV_PER_ATOM_TO_KJ_PER_MOL
    config, machine = batch
    rounds = []

    def compute(self, **kwargs):
        folder = Path(self.work_base)
        manifest = json.loads((folder / "manifest.json").read_text())
        rounds.append(manifest["iteration"])
        for task in manifest["tasks"]:
            member = task["endmember"]
            reference = sum(REFERENCE[e] for e in member.split(":")) / 2
            total = (reference + ENERGY[member] / EV_PER_ATOM_TO_KJ_PER_MOL) * task["natoms"]
            dataset(folder / task["task_id"], task, energies=(total,))
        return {}

    monkeypatch.setattr(Submission, "run_submission", compute)
    monkeypatch.setattr(Submission, "check_all_finished", lambda _: True)
    capsys.readouterr()
    code = main(["--json", "pipeline", str(config), str(machine)])
    output = capsys.readouterr()
    assert code == 0, output.out + output.err
    assert json.loads(output.out)["status"] == "completed"
    assert rounds == list(range(len(rounds))) and len(rounds) >= 2


def test_collection_requires_complete_batch_and_exports_final_frame(batch):
    config, machine = batch
    prepare(config, machine)
    _, _, calculated, fp, manifest, _ = prepared(config)
    tasks = manifest["tasks"]
    assert len(tasks) > 1
    dataset(fp / tasks[0]["task_id"], tasks[0])
    pending = collect(config)
    assert pending["status"] == "pending" and pending["valid"] == 1
    assert not (calculated / "calc.txt").exists()
    for task in tasks[1:]:
        dataset(fp / task["task_id"], task)
    ready = collect(config)
    assert ready["status"] == "ready" and ready["invalid"] == 0
    assert all(r["frame"] == 1 and r["energy_ev_cell"] == -8 for r in ready["records"])
    assert all(line.endswith(",-8,-8") for line in (calculated / "calc.txt").read_text().splitlines())
    for task in tasks:
        final = load_labels(fp / "datasets" / task["task_id"], "deepmd/npy")
        assert len(final) == 1 and final.data["energies"][0] == -8
    assert collect(config) == ready
    (calculated / "calc.txt").write_text("tampered\n")
    with pytest.raises(ValueError, match="already published"):
        collect(config)


@pytest.mark.parametrize("wrong, energies, message", [(True, (-8.0,), "species"), (False, (np.nan,), "Nonfinite")])
def test_bad_labels_never_published(batch, wrong, energies, message):
    config, machine = batch
    prepare(config, machine)
    _, _, calculated, fp, manifest, _ = prepared(config)
    for task in manifest["tasks"]:
        dataset(fp / task["task_id"], task, energies=energies, wrong=wrong)
    report = collect(config)
    assert report["status"] == "pending" and report["valid"] == 0
    assert message in report["failures"][0]["error"]
    assert not (calculated / "calc.txt").exists()


def outcar_frame(energy, electronic_steps=2, truncated=False):
    force = "0 0 0 0 0 0\n" if truncated else "0 0 0 0 0 0\n1.5 1.5 1.5 0 0 0\n"
    return (f"-------------------------------- Iteration 1( {electronic_steps})\n"
            "VOLUME and BASIS-vectors are now :\nblank\nblank\nblank\nblank\n"
            "3 0 0\n0 3 0\n0 0 3\n"
            "POSITION TOTAL-FORCE (eV/Angst)\n------------------------\n" + force +
            f"free  energy   TOTEN  = {energy} eV\n")


@pytest.mark.parametrize("problem", [None, "electronic", "ionic", "unfinished", "damaged"])
def test_real_outcar_parser_rejects_bad_final_frame(tmp_path, problem):
    (tmp_path / "INCAR").write_text("NSW = 10\nIBRION = 2\n" if problem == "ionic" else "NSW = 0\n")
    text = "TITEL = PAW_PBE Al TEST\nNELM = 60;\nNWRITE = 2\nions per type = 2\n"
    text += outcar_frame(-7.0)
    text += outcar_frame(-8.0, 60 if problem == "electronic" else 2, problem == "damaged")
    if problem != "unfinished":
        text += "General timing and accounting informations for this job:\n"
    (tmp_path / "OUTCAR").write_text(text)
    task = {"task_id": "task.000000", "endmember": "AL:AL", "natoms": 2, "composition": {"Al": 2}}
    if problem:
        with pytest.raises(ValueError, match="converged|incomplete"):
            read_labels(tmp_path, task, "vasp/outcar", "OUTCAR")
    else:
        labels, record = read_labels(tmp_path, task, "vasp/outcar", "OUTCAR")
        assert len(labels) == 1 and record["energy_ev_cell"] == -8.0
        assert record["frame"] == 1 and record["convergence"] == "checked"
