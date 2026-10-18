import xml.etree.ElementTree as ET

import pytest

from examples.pandat_batch import batch_document, read_point


def test_explicit_site_columns_and_nonunit_pressure():
    groups = [["AL", "NI"], ["NI"], ["AL", "NI"]]
    point = {"T_K": 900, "P_Pa": 202650, "X_AL": .2, "X_NI": .8}
    xml = ET.fromstring(batch_document([point], "TEST", ["AL", "NI"], groups))
    assert xml.find("calculation/system/points/point/statespace/P").get("value") == "2"
    columns = [column.get("name") for column in xml.findall("calculation/output/tables/table/column")]
    assert columns[-5:] == ["y(AL#1@TEST)", "y(NI#1@TEST)", "y(NI#2@TEST)", "y(AL#3@TEST)", "y(NI#3@TEST)"]


def test_2022_site_aliases_for_different_constituent_sets(tmp_path):
    groups = [["AL", "NI"], ["NI"], ["AL", "NI"]]
    path = tmp_path / "point.dat"
    path.write_text("T\tP\tx(AL)\tx(NI)\tphase_name\tG(@TEST)\tx(AL@TEST)\tx(NI@TEST)\ty(AL)\ty(NI)\ty(NI)_1\ty(AL)_1\ty(NI)_2\n"
                    "K\tatm\tmole/mole\tmole/mole\t\t\tmole/mole\tmole/mole\t\t\t\t\t\n"
                    "900\t2\t.2\t.8\tTEST\t-20000\t.2\t.8\t.4\t.6\t1\t.2\t.8\n")
    parsed = read_point(path, "TEST", ["AL", "NI"], groups, {"X_AL": .2, "X_NI": .8})
    assert parsed["Y_1_NI"] == 1
    assert parsed["Y_2_AL"] == .2
    assert parsed["Y_2_NI"] == .8
    assert parsed["P_Pa"] == 202650


def test_omitted_zero_component_is_only_allowed_at_requested_endpoint(tmp_path):
    path = tmp_path / "endpoint.dat"
    path.write_text("T\tP\tx(NI)\tphase_name\tG(@TEST)\tx(NI@TEST)\ty(AL)\ty(NI)\n"
                    "K\tatm\tmole/mole\t\t\tmole/mole\t\t\n"
                    "900\t1\t1\tTEST\t-8000\t1\t\t1\n")
    parsed = read_point(path, "TEST", ["AL", "NI"], [["AL", "NI"]], {"X_AL": 0, "X_NI": 1})
    assert parsed["X_AL"] == parsed["Y_0_AL"] == 0
    with pytest.raises((ValueError, KeyError)):
        read_point(path, "TEST", ["AL", "NI"], [["AL", "NI"]], {"X_AL": .1, "X_NI": .9})


def test_disordered_branch_requires_declared_mapping_and_exported_y(tmp_path):
    path = tmp_path / "disordered.dat"
    path.write_text("T\tP\tx(AL)\tx(NI)\tphase_name\tG(@DIS)\tx(AL@DIS)\tx(NI@DIS)\ty(AL#1@DIS)\ty(NI#1@DIS)\n"
                    "K\tatm\tmole/mole\tmole/mole\t\t\tmole/mole\tmole/mole\t\t\n"
                    "3200\t1\t.4\t.6\tDIS\t-50000\t.4\t.6\t.4\t.6\n")
    groups = [["AL", "NI"]]*5
    expected = {"X_AL": .4, "X_NI": .6}
    with pytest.raises(ValueError, match="expected a single"):
        read_point(path, "TEST", ["AL", "NI"], groups, expected)
    row = read_point(path, "TEST", ["AL", "NI"], groups, expected, disordered_phase="DIS")
    assert row["phase"] == "TEST" and row["reported_phase"] == "DIS"
    assert [row[f"Y_{i}_NI"] for i in range(5)] == [.6]*5
    with pytest.raises(ValueError, match="unrestricted equivalent"):
        read_point(path, "TEST", ["AL", "NI"], [["AL"], ["AL", "NI"]], expected, disordered_phase="DIS")
    xml = ET.fromstring(batch_document([{**expected, "T_K": 3200, "P_Pa": 101325}], "TEST", ["AL", "NI"], groups,
                                      disordered_phase="DIS"))
    columns = [column.get("name") for column in xml.findall("calculation/output/tables/table/column")]
    assert columns[-1] == "y(*@*)"
