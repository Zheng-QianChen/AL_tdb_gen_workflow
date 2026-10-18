import json
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pycalphad import Database, Model, variables as v

from app import app
from config import BASE_DATA_DIR
from src.gibbs import calculate_curve, run_curve, source_options
from src.gibbs_settings import GibbsRequest
from src.storage import atomic_write
from tests.test_tdb import BASE

R = 8.3145  # Constant used by the pinned pycalphad version.


def binary_tdb(ratios=(1,), interactions=False, ordering=0):
    import itertools
    text = BASE + f"PHASE TEST % {len(ratios)} " + " ".join(map(str, ratios)) + " !\n"
    text += "CONSTITUENT TEST :" + ":".join("AL,NI" for _ in ratios) + ": !\n"
    for member in itertools.product(["AL", "NI"], repeat=len(ratios)):
        energy = ordering * sum(ratios) if len(set(member)) > 1 else 0
        expression = "+".join(f"{ratio}*GHSER{element}#" for ratio, element in zip(ratios, member))
        text += f"PARAMETER G(TEST,{':'.join(member)};0) 298.15 {expression}{energy:+g};6000 N !\n"
    if interactions:
        text += "PARAMETER G(TEST,AL,NI;0) 298.15 10000;6000 N !\n"
    return text


def request(**kwargs):
    return {"tdb_files": ["model.tdb"], "phase": "TEST", "temperatures": [1000],
            "mode": "gx", "composition_start": {"AL": 1}, "composition_end": {"NI": 1},
            "points": 5, "starts": 6, **kwargs}


def test_ideal_gx_endpoints_entropy_and_terms():
    result = calculate_curve(Database(binary_tdb()), request())
    for row in result["rows"]:
        x = row["X_NI"]
        ideal = R * 1000 * sum(y * np.log(y) for y in (x, 1-x) if y)
        assert row["G_J_mol_atoms"] == pytest.approx(1000*(1-x)+3000*x+ideal, abs=1e-7)
        assert row["G_idmix_J_mol_atoms"] == pytest.approx(ideal, abs=1e-7)
        assert sum(row[f"G_{term}_J_mol_atoms"] for term in result["contributions"]) == pytest.approx(row["G_J_mol_atoms"])


def test_gt_nonideal_energy_and_homogeneous_miscibility_gap():
    req = {"tdb_files": ["model.tdb"], "phase": "TEST", "mode": "gt", "composition": {"AL": .5, "NI": .5},
           "temperatures": [300, 600, 1000]}
    result = calculate_curve(Database(binary_tdb(interactions=True)), req)
    for row in result["rows"]:
        assert row["G_J_mol_atoms"] == pytest.approx(2000 + 2500 - R*row["T_K"]*np.log(2))
    # At 300 K this regular solution lies above the two-phase linear envelope.
    # A single-phase curve must preserve that nonconvex region.
    assert result["rows"][0]["G_J_mol_atoms"] > 2000


def test_unequal_site_ratios_internal_equilibration():
    result = calculate_curve(Database(binary_tdb((1, 3))), request(points=3))
    row = result["rows"][1]
    for site in (0, 1):
        assert row[f"Y_{site}_AL"] == pytest.approx(.5, abs=1e-6)
        assert row[f"Y_{site}_NI"] == pytest.approx(.5, abs=1e-6)
    assert row["G_J_mol_atoms"] == pytest.approx(2000 - R*1000*np.log(2), abs=1e-6)
    assert result["rows"][0]["method"] == "unique_constitution"


def test_ordering_minimum_below_random_occupancy_and_direct_model():
    text = binary_tdb((1, 1), ordering=-30000)
    req = {"tdb_files": ["model.tdb"], "phase": "TEST", "mode": "gt", "composition": {"AL": .5, "NI": .5},
           "temperatures": [500], "starts": 12}
    row = calculate_curve(Database(text), req)["rows"][0]
    assert abs(row["Y_0_AL"] - row["Y_1_AL"]) > .95
    model = Model(Database(text), ["AL", "NI"], "TEST")
    values = {v.T: 500, v.P: 101325}
    values.update({s: row[f"Y_{s.sublattice_index}_{s.species.name}"] for s in model.site_fractions})
    assert row["G_J_mol_atoms"] == pytest.approx(float(model.GM.subs(values)), abs=1e-6)
    random = {v.T: 500, v.P: 101325, **{s: .5 for s in model.site_fractions}}
    assert row["G_J_mol_atoms"] < float(model.GM.subs(random)) - 10000


def test_selected_sublattice_constraints_and_feasible_range():
    req = request(sublattices=[["AL"], ["AL", "NI"]], composition_end={"AL": .25, "NI": .75}, points=3)
    result = calculate_curve(Database(binary_tdb((1, 3))), req)
    last = result["rows"][-1]
    assert last["Y_0_AL"] == pytest.approx(1)
    assert last["Y_1_NI"] == pytest.approx(1)
    assert last["G_J_mol_atoms"] == pytest.approx(2500)
    with pytest.raises(ValueError, match="infeasible"):
        calculate_curve(Database(binary_tdb((1, 3))), {**req, "composition_end": {"NI": 1}})


def test_fixed_site_fraction_gt_matches_constitution():
    req = {"tdb_files": ["model.tdb"], "phase": "TEST", "mode": "gt", "composition": {"AL": .25, "NI": .75},
           "temperatures": [500, 1000], "site_fractions": [{"AL": 1}, {"NI": 1}]}
    result = calculate_curve(Database(binary_tdb((1, 3))), req)
    assert [r["G_J_mol_atoms"] for r in result["rows"]] == pytest.approx([2500, 2500])
    with pytest.raises(ValueError, match="match overall composition"):
        calculate_curve(Database(binary_tdb((1, 3))), {**req, "composition": {"AL": .5, "NI": .5}})
    with pytest.raises(ValueError, match="per sublattice"):
        calculate_curve(Database(binary_tdb((1, 3))), {**req, "site_fractions": []})


@pytest.mark.parametrize("change,message", [
    ({"temperatures": [100]}, "not defined"),
    ({"temperatures": [6000]}, "not defined"),
    ({"sublattices": [["AL", "FE"]]}, "valid constituent"),
    ({"composition_start": {"AL": .2}}, "sum to one"),
    ({"composition_start": {"AL": float('nan')}}, "finite"),
    ({"x_axis": "FE"}, "x_axis"),
])
def test_invalid_inputs_rejected(change, message):
    with pytest.raises(ValueError, match=message):
        calculate_curve(Database(binary_tdb()), request(**change))


def test_missing_references_and_endmember_rejected():
    text = binary_tdb().replace("FUNCTION GHSERAL 298.15 1000; 6000 N !", "")
    with pytest.raises(ValueError, match="Missing TDB function GHSERAL"):
        calculate_curve(Database(text), request())
    text = "\n".join(line for line in binary_tdb().splitlines() if "G(TEST,NI;0)" not in line)
    with pytest.raises(ValueError, match="Missing endmember"):
        calculate_curve(Database(text), request())


def test_input_model_requires_gt_composition():
    with pytest.raises(ValueError, match="fixed overall composition"):
        GibbsRequest(tdb_files=["model.tdb"], mode="gt", temperatures=[1000])


def test_multicomponent_composition_path():
    text = BASE + """ELEMENT MO BCC_A2 95.95 0 0 !
PHASE TEST % 1 1 !
CONSTITUENT TEST :AL,NI,MO: !
PARAMETER G(TEST,AL;0) 298.15 1000; 6000 N !
PARAMETER G(TEST,NI;0) 298.15 3000; 6000 N !
PARAMETER G(TEST,MO;0) 298.15 2000; 6000 N !
"""
    result = calculate_curve(Database(text), request(composition_start={"AL": .5, "MO": .5},
                            composition_end={"NI": .5, "MO": .5}, x_axis="NI", points=3))
    for row in result["rows"]:
        x = np.array([row["X_AL"], row["X_NI"], row["X_MO"]])
        energy = x @ [1000, 3000, 2000] + R*1000*sum(y*np.log(y) for y in x if y)
        assert row["G_J_mol_atoms"] == pytest.approx(energy, abs=1e-6)
        assert row["X_MO"] == pytest.approx(.5)


def test_duplicate_parameters_and_function_dependency_range():
    text = binary_tdb() + "PARAMETER G(TEST,NI;0) 298.15 GHSERNI#;6000 N !\n"
    with pytest.raises(ValueError, match="Duplicate phase parameters"):
        calculate_curve(Database(text), request())
    text = binary_tdb().replace("1000; 6000 N !", "+NESTED#; 6000 N !")
    text += "FUNCTION NESTED 298.15 1000; 900 N !\n"
    with pytest.raises(ValueError, match="NESTED is not defined"):
        calculate_curve(Database(text), request())


@pytest.fixture
def database_file():
    path = BASE_DATA_DIR / f"gibbs_test_{uuid.uuid4().hex}.tdb"
    atomic_write(path, binary_tdb((1, 3)))
    return path


def test_artifact_export_and_cli(database_file, tmp_path, capsys):
    from altdb.cli import main
    req = request(tdb_files=[str(database_file)], points=3)
    input_file = tmp_path / "curve.json"
    atomic_write(input_file, json.dumps(req))
    code = main(["--json", "gibbs", str(input_file)])
    result = json.loads(capsys.readouterr().out)
    assert code == 0, result
    assert result["sources"][0]["sha256"]
    from pathlib import Path
    assert Path(result["files"]["png"]).read_bytes().startswith(b"\x89PNG")
    assert "G_J_mol_atoms" in Path(result["files"]["csv"]).read_text()
    saved = json.loads(Path(result["files"]["json"]).read_text(encoding="utf-8"))
    assert len(saved["rows"]) == 3 and saved["request"]["sublattices"] is None


def test_web_options_curve_and_data_root(database_file):
    assert source_options({"tdb_files": [str(database_file)]})["site_ratios"] == [1, 3]
    with TestClient(app) as client:
        assert client.get("/gibbs").status_code == 200
        options = client.post("/gibbs/options", json={"tdb_files": [str(database_file)]})
        assert options.status_code == 200
        assert options.json()["sublattices"] == [["AL", "NI"], ["AL", "NI"]]
        result = client.post("/gibbs/calculate", json=request(tdb_files=[str(database_file)], points=3))
        assert result.status_code == 200, result.text
        assert client.get(result.json()["urls"]["csv"]).status_code == 200
        bad = client.post("/gibbs/calculate", json=request(tdb_files=["../outside.tdb"]))
        assert bad.status_code == 422


def test_workflow_checkpoint_curve_uses_complete_formation_model(phase):
    import pandas as pd
    p = phase.phase
    p.pool_pred = pd.DataFrame({"endmember": p.pool, "y_pred_kJ_mol": [2, -20, -10, 3]})
    phase.process = 0
    phase._checkpoint()
    reference = BASE_DATA_DIR / f"reference_{uuid.uuid4().hex}.tdb"
    atomic_write(reference, BASE)
    result = run_curve(request(config=str(phase.input_json), phase="DEMO_B2", tdb_files=[str(reference)], points=3))
    assert result["checkpoint"]["checkpoint"] == "model_000000_0.pd"
    assert len(result["sources"]) == 2 and result["phase"] == "DEMO_B2"
