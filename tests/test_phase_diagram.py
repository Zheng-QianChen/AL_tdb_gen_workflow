import asyncio
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pycalphad import Database, equilibrium, variables as v
from scipy.optimize import brentq

from app import app
from config import resolve_data_path
from examples.phase_diagram_demo import eutectic_database
from src.phase_diagram import EquilibriumSystem, calculate_diagram, conditions_grid, run_diagram
from src.phase_diagram_settings import PhaseDiagramRequest
from src.storage import atomic_write
from tests.test_gibbs import R, binary_tdb


def point_request(**kwargs):
    return {"tdb_files": ["test.tdb"], "components": ["AL", "NI"], "mode": "point", "temperatures": [500],
            "composition": {"AL": .3, "NI": .7}, "sampling_density": 60, **kwargs}


def test_ideal_single_phase_matches_analytic_and_public_engine():
    db = Database(binary_tdb())
    result = calculate_diagram(db, point_request())
    row = result["rows"][0]
    x = row["solver_composition"]["NI"]
    assert result["status"] == "calculated"
    assert row["G_J_mol_atoms"] == pytest.approx(1000*(1-x)+3000*x+R*500*(x*np.log(x)+(1-x)*np.log(1-x)), abs=1e-6)
    native = equilibrium(db, ["AL", "NI"], ["TEST"], {v.N: 1, v.P: 101325, v.T: 500, v.X("NI"): x})
    assert row["G_J_mol_atoms"] == pytest.approx(float(native.GM.values.ravel()[0]), abs=1e-6)
    assert row["sampling_verified"] and row["phases"][0]["amount"] == pytest.approx(1)


def test_miscibility_gap_common_tangent_and_lever_rule():
    result = calculate_diagram(Database(binary_tdb(interactions=True)), point_request(temperatures=[300]))
    row = result["rows"][0]
    states = sorted(row["phases"], key=lambda s: s["composition"]["NI"])
    low = brentq(lambda x: R*300*np.log(x/(1-x)) + 10000*(1-2*x), 1e-6, .4)
    assert len(states) == 2 and states[0]["phase"] == states[1]["phase"] == "TEST"
    assert states[0]["instance"] != states[1]["instance"]
    assert [s["composition"]["NI"] for s in states] == pytest.approx([low, 1-low], abs=1e-7)
    assert states[1]["amount"] == pytest.approx((row["solver_composition"]["NI"]-low)/(1-2*low), abs=1e-7)
    hom = 2400 + R*300*(.3*np.log(.3)+.7*np.log(.7)) + 10000*.3*.7
    assert row["G_J_mol_atoms"] < hom-100
    assert row["audit"]["tangent_error_J_mol_atoms"] < 1e-6


def test_eutectic_solid_liquid_and_invariant_mapping():
    req = {"tdb_files": ["test.tdb"], "components": ["AL", "NI"], "temperatures": [500, 600, 700, 800, 900, 1100],
           "mode": "binary", "points": 11, "sampling_density": 60}
    result = calculate_diagram(Database(eutectic_database()), req)
    assert result["summary"]["failed_points"] == 0
    assert {s["phase"] for s in result["rows"][5]["phases"]} == {"SOLID_AL", "SOLID_NI"}
    liquid = next(r for r in result["rows"] if r["T_K"] == 900 and r["path_coordinate"] == .5)
    assert liquid["assemblage"] == "LIQUID"
    invariants = result["boundaries"]["invariants"]
    te = 10000/(10+R*np.log(2))
    assert any(abs(p["T_K"]-te) < .01 for p in invariants), result["boundaries"]
    for p in invariants:
        assert p["audit"]["tangent_error_J_mol_atoms"] < .1


def test_interior_miscibility_island_seeds_the_requested_composition_axis():
    # A closed miscibility island misses every edge of the T-x domain.
    # Interior grid discovery must seed X(NI), the selected mapping coordinate.
    text = binary_tdb(interactions=True).replace("298.15 10000;6000", "298.15 10000-0.3*(T-500)**2;6000")
    result = calculate_diagram(Database(text), {"tdb_files": ["x"], "components": ["AL", "NI"], "mode": "binary",
        "temperatures": [300, 400, 500, 600, 700, 800], "points": 11, "sampling_density": 60, "x_component": "NI"})
    mapping = result["boundaries"]
    assert mapping["interior_grid_seeds"] >= 1
    assert mapping["lines"] and "error" not in mapping and "iteration_error" not in mapping
    assert any(r["assemblage"] == "TEST#1 + TEST#2" for r in result["rows"] if r["T_K"] == 500)


def test_ternary_three_phase_triangle_and_grid_simplex():
    req = {"tdb_files": ["test.tdb"], "components": ["AL", "NI", "FE"], "mode": "ternary",
           "temperatures": [400], "points": 4, "sampling_density": 40, "map_boundaries": False}
    result = calculate_diagram(Database(eutectic_database(("AL", "NI", "FE"))), req)
    assert len(result["rows"]) == 10
    row = next(r for r in result["rows"] if min(r["composition"].values()) > .3)
    assert len(row["phases"]) == 3
    assert [s["amount"] for s in row["phases"]] == pytest.approx([1/3]*3, abs=1e-7)
    assert row["G_J_mol_atoms"] == pytest.approx(0, abs=1e-6)
    assert all(abs(sum(r["composition"].values())-1) < 1e-12 for r in result["rows"])


def test_isopleth_pairs_compositions_and_keeps_phase_compositions_free():
    req = PhaseDiagramRequest(tdb_files=["x"], components=["AL", "NI", "FE", "CR"], mode="isopleth",
        temperatures=[400, 500], points=3, sampling_density=30,
        composition_start={"AL": .7, "NI": .1, "FE": .1, "CR": .1},
        composition_end={"AL": .1, "NI": .7, "FE": .1, "CR": .1})
    points = conditions_grid(req)
    assert len(points) == 6 and points[1]["composition"]["AL"] == pytest.approx(.4)
    result = calculate_diagram(Database(eutectic_database(("AL", "NI", "FE", "CR"))), req)
    assert result["summary"]["failed_points"] == 0
    states = result["rows"][1]["phases"]
    assert len(states) == 4
    assert any(s["composition"]["FE"] > .99 for s in states)


@pytest.mark.parametrize("change", [
    {"components": ["AL", "VA"]}, {"components": ["AL", "al"]}, {"composition": {"AL": -.1, "NI": 1.1}},
    {"composition": {"AL": .1}}, {"temperatures": [float("nan")]}, {"composition": {"AL": float("inf")}},
    {"phases": []}, {"phases": ["TEST"], "suspended_phases": ["TEST"]},
    {"mode": "binary"}, {"mode": "ternary"}, {"points": 1000}, {"composition_range": [.7, .1]},
])
def test_invalid_requests_fail_before_solving(change):
    with pytest.raises(ValueError):
        PhaseDiagramRequest.model_validate(point_request(**change))


def test_missing_phase_and_reference_are_errors():
    with pytest.raises(ValueError, match="Unknown phase"):
        calculate_diagram(Database(binary_tdb()), point_request(phases=["MISSING"]))
    text = binary_tdb().replace("FUNCTION GHSERAL 298.15 1000; 6000 N !", "")
    with pytest.raises(ValueError, match="Missing TDB function"):
        calculate_diagram(Database(text), point_request())


def test_boundary_mapping_rejects_a_gap_between_valid_temperatures():
    from symengine import Piecewise, And
    db = Database(binary_tdb())
    db.symbols["GHSERAL"] = Piecewise((1000, And(v.T >= 298.15, v.T < 400)),
                                      (1000, And(v.T >= 500, v.T < 6000)), (0, True))
    request = {"tdb_files": ["x"], "mode": "binary", "components": ["AL", "NI"],
               "temperatures": [350, 650], "points": 3}
    with pytest.raises(ValueError, match="throughout the temperature interval"):
        calculate_diagram(db, request)


@pytest.mark.parametrize("count,interstitial", [(3, False), (4, False), (4, True), (5, False)])
def test_multisublattice_magnetic_ordering_uses_project_energy(count, interstitial):
    from examples.pandat_special_models import magnetic_ordering_tdb
    from src.gibbs import GibbsModel
    db = Database(magnetic_ordering_tdb(count, interstitial=interstitial))
    request = point_request(composition={"AL": .5, "NI": .5}, temperatures=[800], sampling_density=100)
    result = calculate_diagram(db, request)
    assert result["summary"]["accepted_points"] == 1
    assert result["excluded_phases"]["DIS"].startswith("represented by ordered")
    assert result["models"]["TEST"]["ordering"]["kind"] == "partitioned_order_disorder"
    model = GibbsModel(db, "TEST", None, [800], 101325)
    row = result["rows"][0]
    for state in row["phases"]:
        y = [state["site_fractions"][key] for key in model.labels]
        assert state["G_J_mol_atoms"] == pytest.approx(model.values(800, 101325, y)[0], abs=1e-6)
        if interstitial:
            assert state["site_fractions"][f"Y_{count}_VA"] == pytest.approx(1)


def test_variable_interstitial_atom_normalization():
    from examples.pandat_special_models import INTERSTITIAL
    from src.gibbs import calculate_curve
    db = Database(INTERSTITIAL)
    request = point_request(components=["FE", "C"], composition={"FE": .9, "C": .1}, temperatures=[800])
    row = calculate_diagram(db, request)["rows"][0]
    hom = calculate_curve(db, {"tdb_files": ["x"], "phase": "TEST", "mode": "gt", "composition": request["composition"], "temperatures": [800]})["rows"][0]
    assert row["status"] == "accepted"
    assert row["G_J_mol_atoms"] == pytest.approx(hom["G_J_mol_atoms"], abs=1e-4)
    assert row["phases"][0]["site_fractions"]["Y_1_C"] == pytest.approx(.1/(3*.9), abs=1e-7)


def test_pure_faces_do_not_add_trace_components():
    result = calculate_diagram(Database(eutectic_database()), point_request(composition={"AL": 1}))
    row = result["rows"][0]
    assert row["status"] == "accepted" and row["assemblage"] == "SOLID_AL"
    assert row["solver_composition"] == {"AL": 1., "NI": 0.}
    assert row["undefined_chemical_potentials"] == ["NI"]
    assert "NI" not in row["chemical_potentials_J_mol_atoms"]


def test_vacancy_only_endmember_is_not_a_stable_phase():
    text = binary_tdb().replace("CONSTITUENT TEST :AL,NI:", "CONSTITUENT TEST :AL,NI,VA:")
    text = "ELEMENT VA VACUUM 0 0 0 !\n" + text + "\nPARAMETER G(TEST,VA;0) 298.15 100000; 6000 N !\n"
    row = calculate_diagram(Database(text), point_request())["rows"][0]
    assert row["status"] == "accepted"
    assert row["phases"][0]["site_fractions"]["Y_0_VA"] < 1e-5


def test_failed_points_are_retained_without_fake_success(monkeypatch):
    def fail(*args):
        raise ValueError("forced nonconvergence")
    monkeypatch.setattr(EquilibriumSystem, "solve_once", fail)
    result = calculate_diagram(Database(binary_tdb()), point_request())
    assert result["status"] == "partial" and result["summary"]["failed_points"] == 1
    row = result["rows"][0]
    assert row["phases"] == [] and "G_J_mol_atoms" not in row
    assert len(row["attempts"]) == 2


def test_density_change_keeps_lower_energy_and_reports_refinement(monkeypatch):
    original = EquilibriumSystem.solve_once
    def shifted(self, point, density):
        result = original(self, point, density)
        if density == 60:
            result["G_J_mol_atoms"] += 1
        return result
    monkeypatch.setattr(EquilibriumSystem, "solve_once", shifted)
    result = calculate_diagram(Database(binary_tdb()), point_request())
    assert result["status"] == "partial" and result["summary"]["needs_refinement_points"] == 1
    assert result["rows"][0]["sampling_density"] == 120


@pytest.fixture
def diagram_database():
    path = resolve_data_path("phase-diagram-test/model.tdb")
    atomic_write(path, eutectic_database())
    return path


def test_cli_api_and_exports(diagram_database, tmp_path, capsys):
    from altdb.cli import main
    req = point_request(tdb_files=[str(diagram_database)])
    path = tmp_path / "request.json"
    path.write_text(json.dumps(req), encoding="utf-8-sig")
    assert main(["--json", "phase-diagram", str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    saved = json.loads(Path(report["files"]["json"]).read_text(encoding="utf-8"))
    assert saved["sources"][0]["sha256"] and len(saved["rows"][0]["phases"]) == 2
    assert Path(report["files"]["png"]).read_bytes().startswith(b"\x89PNG")
    assert "NP" in Path(report["files"]["phases"]).read_text()
    assert "<html" in Path(report["files"]["html"]).read_text(encoding="utf-8")
    with TestClient(app) as client:
        assert client.get("/phase-diagram").status_code == 200
        options = client.post("/phase-diagram/options", json={"tdb_files": [str(diagram_database)]})
        assert options.status_code == 200
        response = client.post("/phase-diagram/calculate", json=req)
        assert response.status_code == 200, response.text
        for url in response.json()["urls"].values():
            assert client.get(url).status_code == 200
        invalid = client.post("/phase-diagram/calculate", json={**req, "tdb_files": ["../outside.tdb"]})
        assert invalid.status_code == 422


def test_standalone_tui_runs_without_training_config(diagram_database):
    from altdb.tui import PhaseDiagramApp
    from textual.widgets import DataTable
    result = run_diagram(point_request(tdb_files=[str(diagram_database)]))
    async def exercise():
        calls = []
        async def fake(arguments):
            calls.append(arguments)
            return 0, result, ""
        terminal = PhaseDiagramApp("diagram.json", command_runner=fake)
        async with terminal.run_test(size=(100, 30)) as pilot:
            await pilot.click("#diagram-run")
            await terminal.workers.wait_for_complete()
            assert calls == [["phase-diagram", "diagram.json"]]
            assert terminal.query_one(DataTable).row_count == 1
            assert not terminal.busy
    asyncio.run(exercise())


def test_external_comparison_requires_import_convergence_and_result_file(tmp_path):
    from examples.phase_diagram_tc_check import parse_checks
    rows = [{"point_id": 0, "T_K": 500, "composition": {"AL": .5, "NI": .5}, "G_J_mol_atoms": -1000}]
    raw = "POLY:\nREINITIATE_MODULE\nCalculated solution in 0.01 s using 2 iterations.\nGM=-1000\n"
    assert not parse_checks(raw, rows, tmp_path, True, True)[0]["energy_agrees"]
    (tmp_path / "point_000.txt").write_text("native equilibrium output")
    assert parse_checks(raw, rows, tmp_path, True, True)[0]["energy_agrees"]
    assert not parse_checks(raw, rows, tmp_path, False, True)[0]["energy_agrees"]
    assert not parse_checks(raw, rows, tmp_path, True, False)[0]["energy_agrees"]
    assert not parse_checks(raw + "ERROR: failed\n", rows, tmp_path, True, True)[0]["energy_agrees"]
    assert not parse_checks("POLY: REINITIATE_MODULE\nGM=-1000", rows, tmp_path, True, True)[0]["energy_agrees"]
