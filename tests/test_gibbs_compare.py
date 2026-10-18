import copy
import csv
import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app import app
from config import BASE_DATA_DIR
from src.gibbs_compare import compare_points, model_declaration, prepare_reference
from src.storage import atomic_json, atomic_write


@pytest.fixture
def local_result():
    # Independent analytic ideal solution points, not commercial-solver evidence.
    return {"phase": "TEST", "components": ["AL", "NI"], "sublattices": [["AL", "NI"]],
            "site_ratios": [1], "sources": [{"path": "synthetic.tdb", "sha256": "a"*64}],
            "energy_unit": "J/mol-atoms", "phase_constraint": "homogeneous_single_phase",
            "site_fraction_mode": "optimized", "request": {},
            "rows": [{"T_K": 1000., "P_Pa": 101325., "X_AL": 1., "X_NI": 0.,
                      "G_J_mol_atoms": 1000., "Y_0_AL": 1., "Y_0_NI": 0.},
                     {"T_K": 1000., "P_Pa": 101325., "X_AL": .5, "X_NI": .5,
                      "G_J_mol_atoms": -3763.172226765665, "Y_0_AL": .5, "Y_0_NI": .5}]}


def request(result, **kwargs):
    return {"result": "local.json", "reference_csv": "external.csv", "software": "pandat",
            "software_version": "TEST FIXTURE ONLY", "reference_model": model_declaration(result),
            "conditions_verified": True, **kwargs}


def reference(rows=None):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["phase", "T_K", "P_Pa", "X_AL", "X_NI", "G"])
    writer.writerows(rows if rows is not None else [["TEST", 1000, 101325, .5, .5, -3763.],
                                                   ["TEST", 1000, 101325, 1, 0, 1000.5]])
    return stream.getvalue()


def test_reordered_points_absolute_errors_and_subset(local_result):
    report = compare_points(local_result, request(local_result), reference())
    assert report["status"] == "within_tolerance"
    assert report["all_points_compared"]
    assert [r["local_index"] for r in report["rows"]] == [1, 0]
    assert report["max_abs_error_J_mol_atoms"] == pytest.approx(.5)
    assert report["rmse_J_mol_atoms"] == pytest.approx(((.172226765665**2+.5**2)/2)**.5)
    report = compare_points(local_result, request(local_result, energy_unit="kJ/mol-atoms"),
                            reference([["TEST", 1000, 101325, 1, 0, 1.005]]))
    assert report["status"] == "outside_tolerance"
    assert report["max_abs_error_J_mol_atoms"] == pytest.approx(5)
    assert report["uncompared_points"] == 1 and not report["all_points_compared"]


@pytest.mark.parametrize("row,match", [
    (["TEST", 1001, 101325, 1, 0, 1000], "matching"),
    (["TEST", 1000, 1, 1, 0, 1000], "matching"),
    (["TEST", 1000, 101325, .3, .7, 1000], "matching"),
    (["TEST#2", 1000, 101325, 1, 0, 1000], "phase mismatch"),
    (["TEST", 1000, 101325, 1, 0, ""], "independently calculated"),
    (["TEST", 1000, 101325, 1, 0, "nan"], "invalid"),
    (["TEST", 1000, 101325, .3, .3, 1000], "invalid"),
])
def test_mismatched_and_invalid_points(local_result, row, match):
    with pytest.raises(ValueError, match=match):
        compare_points(local_result, request(local_result), reference([row]))


def test_duplicates_empty_and_model_mismatch(local_result):
    row = ["TEST", 1000, 101325, 1, 0, 1000]
    with pytest.raises(ValueError, match="duplicate"):
        compare_points(local_result, request(local_result), reference([row, row]))
    with pytest.raises(ValueError, match="no calculation points"):
        compare_points(local_result, request(local_result), reference([]))
    req = request(local_result)
    req["reference_model"]["source_sha256"] = ["b"*64]
    with pytest.raises(ValueError, match="Reference model differs"):
        compare_points(local_result, req, reference())
    ambiguous = copy.deepcopy(local_result)
    ambiguous["rows"].append(ambiguous["rows"][0])
    with pytest.raises(ValueError, match="found 2"):
        compare_points(ambiguous, request(ambiguous), reference([row]))


def test_fixed_sites_require_reference_occupancy(local_result):
    local_result["site_fraction_mode"] = "fixed"
    with pytest.raises(ValueError, match="all site fractions"):
        compare_points(local_result, request(local_result), reference())
    text = "phase,T_K,P_Pa,X_AL,X_NI,G,Y_0_AL,Y_0_NI\nTEST,1000,101325,.5,.5,-3763,.5,.5\n"
    report = compare_points(local_result, request(local_result), text)
    assert report["max_abs_delta_Y"] == 0
    with pytest.raises(ValueError, match="overall composition"):
        compare_points(local_result, request(local_result), text.replace("-3763,.5,.5", "-3763,.6,.4"))


def test_explicit_fraction_rounding_tolerance(local_result):
    point = local_result["rows"][1]
    point.update(X_AL=1/3, X_NI=2/3, Y_0_AL=1/3, Y_0_NI=2/3)
    text = "phase,T_K,P_Pa,X_AL,X_NI,G,Y_0_AL,Y_0_NI\nTEST,1000,101325,.333333,.666667,-3763,.333333,.666667\n"
    with pytest.raises(ValueError, match="matching"):
        compare_points(local_result, request(local_result), text)
    local_result["site_fraction_mode"] = "fixed"
    report = compare_points(local_result, request(local_result, fraction_atol=2e-6), text)
    assert report["status"] == "within_tolerance"
    # Explicit precision allowance never merges multiple candidate points.
    duplicate = copy.deepcopy(point)
    duplicate.update(X_AL=1/3+1e-6, X_NI=2/3-1e-6)
    local_result["rows"].append(duplicate)
    with pytest.raises(ValueError, match="found 2"):
        compare_points(local_result, request(local_result, fraction_atol=2e-6), text)


def test_template_web_and_cli_exit_codes(local_result, capsys):
    from pathlib import Path
    from altdb.cli import main
    path = BASE_DATA_DIR / f"comparison_test_{uuid.uuid4().hex}.json"
    atomic_json(path, local_result)
    template = prepare_reference(str(path))
    req_path = Path(template["files"]["request"])
    req = json.loads(req_path.read_text(encoding="utf-8"))
    assert req["conditions_verified"] is False
    table = list(csv.DictReader(Path(template["files"]["csv"]).read_text().splitlines()))
    assert all(row["G"] == "" and row["Y_0_AL"] == "" for row in table)
    with TestClient(app) as client:
        assert client.post("/gibbs/compare", json=req).status_code == 422
        req.update(conditions_verified=True, software="pandat", software_version="TEST FIXTURE ONLY")
        atomic_write(req["reference_csv"], reference())
        response = client.post("/gibbs/compare", json=req)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "within_tolerance"
        assert client.get(response.json()["urls"]["csv"]).status_code == 200
        assert client.post("/gibbs/reference-template", json={"result": "../outside.json"}).status_code == 422
    req["atol_J_mol_atoms"] = .1
    atomic_json(req_path, req)
    assert main(["--json", "gibbs-compare", str(req_path)]) == 5
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "outside_tolerance" and "rows" not in report
    assert Path(report["files"]["json"]).is_file()


def test_pandat_batch_and_units_parser(local_result, tmp_path):
    import xml.etree.ElementTree as ET
    from examples.pandat_benchmark import batch_document, read_pandat_point
    document = ET.fromstring(batch_document(local_result["rows"]))
    calculations = document.findall("calculation")
    assert len(calculations) == 2
    assert all(calc.find("output").get("unit") == "" for calc in calculations)
    assert calculations[0].find("system/points/point/statespace/P").get("value") == "1"
    path = tmp_path / "point.dat"
    path.write_text("T\tP\tx(AL)\tx(NI)\tphase_name\tG(@SYNTHETIC_B2)\tx(AL@SYNTHETIC_B2)\tx(NI@SYNTHETIC_B2)\n"
                    "K\tatm\tmole/mole\tmole/mole\t\t\tmole/mole\tmole/mole\n"
                    "1000\t1\t0.5\t0.5\tSYNTHETIC_B2\t-28037.73197\t0.5\t0.5\n\t\t\t\t\t\t\t\n")
    parsed = read_pandat_point(path)
    assert parsed["P_Pa"] == 101325
    assert parsed["G"] == pytest.approx(-28037.73197)
    path.write_text(path.read_text().replace("K\tatm", "C\tatm"))
    with pytest.raises(ValueError, match="Unexpected Pandat units"):
        read_pandat_point(path)
