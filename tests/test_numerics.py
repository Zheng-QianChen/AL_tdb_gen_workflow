import numpy as np
import pandas as pd
import pytest
from scipy.spatial import ConvexHull
from scipy.optimize import linprog
from src.Hull import energy_above_hull, generate_lower_hull_hyperplanes, batch_min_distance
from src.thermodynamics import formation_energy, EV_PER_ATOM_TO_KJ_PER_MOL


def test_triangle_keeps_zero_and_signed_distance():
    points = np.array([[0, 0], [50, -10], [100, 0]])
    w, b, _ = generate_lower_hull_hyperplanes(ConvexHull(points))
    np.testing.assert_allclose(batch_min_distance(points, w, b), 0, atol=1e-8)
    np.testing.assert_allclose(batch_min_distance([[25, -8], [25, 3]], w, b), [-3, 8])


@pytest.mark.parametrize("points, expected", [
    ([[0, 0], [.5, 0], [1, 0]], [0, 0, 0]),
    ([[.5, -1], [.5, 3]], [0, 4]),
    ([[0, 2], [.5, 6], [1, 4]], [0, 3, 0]),
    ([[2], [5]], [0, 3]),
    ([[0, 0, 0], [.5, .5, 3], [1, 1, 2]], [0, 2, 0]),
])
def test_degenerate_hulls(points, expected):
    np.testing.assert_allclose(energy_above_hull(points), expected, atol=1e-8)


def test_ternary_envelope_matches_linear_programming():
    rng = np.random.default_rng(19)
    x = np.vstack([np.eye(3), rng.dirichlet([1, 1, 1], 15)])
    e = rng.normal(size=len(x))
    expected = []
    for composition, energy in zip(x, e):
        result = linprog(e, A_eq=x.T, b_eq=composition, bounds=(0, None), method="highs")
        assert result.success
        expected.append(energy - result.fun)
    np.testing.assert_allclose(energy_above_hull(np.column_stack([x[:, 1:], e])), expected, atol=1e-7)


def test_formation_energy_uses_actual_cell_size():
    assert formation_energy(-12, 3, -3) == pytest.approx(-EV_PER_ATOM_TO_KJ_PER_MOL)
    with pytest.raises(ValueError):
        formation_energy(np.nan, 3, -3)


def test_compositions_are_idempotent_and_dft_overrides_prediction(phase):
    p = phase.phase
    p.pool_pred = pd.DataFrame({"endmember": p.pool, "y_pred_kJ_mol": [2, -20, -10, 3]})
    p.convex_analy()
    before = p.all_points.copy(deep=True)
    p.convex_analy()
    pd.testing.assert_frame_equal(before, p.all_points)
    assert p.all_points.loc["AL:NI", "NI"] == .5
    assert p.pt_to_hull.set_index("endmember").loc["NI:AL", "above_hull"] == pytest.approx(10)
    p.calc_points = pd.DataFrame({"NI": [.5], "Energy": [-30]}, index=["NI:AL"])
    p.convex_analy()
    assert p.all_points.loc["NI:AL", "Energy"] == -30
    assert p.pt_to_hull.set_index("endmember").loc["AL:NI", "above_hull"] == pytest.approx(10)


def test_missing_reference_rejected(phase):
    del phase.phase.tdb_model["Atom_ref"]["Ni"]
    with pytest.raises(ValueError, match="Missing reference"):
        phase.phase.calculate_weighted_energy("AL:NI")


def test_selection_is_disjoint_and_handles_exhaustion(phase, monkeypatch):
    p = phase.phase
    p.pt_to_hull = pd.DataFrame({"endmember": p.pool, "above_hull": [0, 2, 3, 4]})
    p.quest = {"near_hall": 2, "unstable": 2, "random": 20}
    uploaded = []
    monkeypatch.setattr(p, "upload", lambda members: uploaded.extend(members))
    assert p.generate_DFT_POSCAR() == 4
    assert len(set(uploaded)) == 4
    p.subl_energy["in_iter"] = 0
    assert p.generate_DFT_POSCAR() == 0


def test_model_rmse_measures_bias_and_empty_means_no_missed_points(tmp_path):
    from src.model_score import get_model_score
    cols = ["index", "endmember", "from", "AL", "NI", "Energy", "distance_between_pt_hull"]
    folder = tmp_path / "scores"
    folder.mkdir()
    pd.DataFrame([[0, "AL:NI", "ML", .5, .5, -20, -10],
                  [1, "NI:AL", "ML", .5, .5, -20, -10]], columns=cols).to_csv(folder / "bad.csv")
    pd.DataFrame(columns=cols).to_csv(folder / "exact.csv")
    scores = get_model_score(folder, cols, tmp_path / "log.txt").set_index("model")
    assert scores.loc["bad.csv", "RMSE"] == 10
    assert scores.loc["exact.csv", "RMSE"] == 0
