import numpy as np
import pandas as pd
import pytest
from pycalphad import Database, Model, variables as v
from src.tdb_generator import tdb_gene, pre_for_model_assess

BASE = """ELEMENT AL FCC_A1 26.9815 0 0 !
ELEMENT NI FCC_A1 58.6934 0 0 !
FUNCTION GHSERAL 298.15 1000; 6000 N !
FUNCTION GHSERNI 298.15 3000; 6000 N !
TYPE_DEFINITION % SEQ * !
"""


@pytest.mark.parametrize("weights, elements, member, normalized", [
    ([1], [["AL"]], "AL", True),
    ([1, 12], [["AL"], ["NI"]], "AL:NI", True),
    ([1, 12], [["AL"], ["NI"]], "AL:NI", False),
])
def test_tdb_parses_and_preserves_reference_weighting(tmp_path, weights, elements, member, normalized):
    df = pd.DataFrame([{"name": "TEST", "sub_name": member, "sub_symb": "AL_NI",
                        "energy": -12.3456789, "Ref": "synthetic", "above_hull": 0}])
    path = tmp_path / "test.tdb"
    tdb_gene([len(weights)], elements, weights, path, df, normlizesites=normalized)
    db = Database(BASE + path.read_text())
    model = Model(db, ["AL", "NI"], "TEST")
    replacements = {v.T: 298.15, v.P: 101325}
    for site in model.site_fractions:
        replacements[site] = float(site.species.name == member.split(":")[site.sublattice_index])
    energy = float(model.GM.subs(replacements))
    expected_ref = sum(w * {"AL": 1000, "NI": 3000}[e] for w, e in zip(weights, member.split(":"))) / sum(weights)
    assert energy == pytest.approx(expected_ref - 12345.6789, abs=1e-6)


def test_export_does_not_change_fraction_table(phase, tmp_path):
    p = phase.phase
    p.pool_pred = pd.DataFrame({"endmember": p.pool, "y_pred_kJ_mol": [2, -20, -10, 3]})
    p.convex_analy()
    before = p.all_points.copy(deep=True)
    table, _ = pre_for_model_assess(p, tmp_path)
    np.testing.assert_allclose(table[["AL", "NI"]].sum(axis=1), 1)
    pd.testing.assert_frame_equal(p.all_points, before)


def test_incomplete_constituent_parameters_are_rejected(tmp_path):
    frame = pd.DataFrame([{"name": "TEST", "sub_name": "AL", "sub_symb": "AL", "energy": -1}])
    with pytest.raises(ValueError, match="Incomplete endmember"):
        tdb_gene([1], [["AL", "NI"]], [1], tmp_path / "bad.tdb", frame)
