import copy
import hashlib

import numpy as np
from pycalphad import Database
import pytest

from examples.pandat_models import cef_tdb
from config import BASE_DATA_DIR
from src.gibbs import GibbsModel, calculate_curve, read_databases
from src.storage import atomic_write


def gt(**kwargs):
    return {"tdb_files": ["model.tdb"], "phase": "TEST", "mode": "gt",
            "temperatures": [1000], "composition": {"AL": .5, "NI": .5}, "starts": 16, **kwargs}


@pytest.mark.parametrize("n", [3, 4, 5])
@pytest.mark.parametrize("weighted", [False, True])
def test_multisublattice_ideal_matches_analytic(n, weighted):
    ratios = list(range(1, n+1)) if weighted else [1]*n
    result = calculate_curve(Database(cef_tdb(n, ratios=ratios)), gt(composition={"AL": .3, "NI": .7}))
    row = result["rows"][0]
    expected = .3*(1000-8000)+.7*(3000-12000)+8.3145*1000*(.3*np.log(.3)+.7*np.log(.7))
    assert row["G_J_mol_atoms"] == pytest.approx(expected, abs=1e-6)
    assert [row[f"Y_{site}_NI"] for site in range(n)] == pytest.approx([.7]*n, abs=2e-6)


@pytest.mark.parametrize("n", [3, 4, 5])
@pytest.mark.parametrize("kind", ["ordered", "partitioned"])
def test_ordering_disappears_on_heating(n, kind):
    fraction = (n-n//2)/n
    result = calculate_curve(Database(cef_tdb(n, kind)), gt(temperatures=[400, 3200], starts=32,
                            composition={"AL": 1-fraction, "NI": fraction}))
    low, high = result["rows"]
    assert np.std([low[f"Y_{i}_NI"] for i in range(n)]) > .1
    assert np.std([high[f"Y_{i}_NI"] for i in range(n)]) < 1e-4
    assert sum(low[f"Y_{i}_NI"] for i in range(n))/n == pytest.approx(fraction, abs=1e-7)
    assert sum(high[f"Y_{i}_NI"] for i in range(n))/n == pytest.approx(fraction, abs=1e-7)


@pytest.mark.parametrize("n", [3, 4, 5])
def test_partitioned_random_limit_is_disordered_energy(n):
    text = cef_tdb(n, "partitioned")
    fixed = [{"AL": .3, "NI": .7}]*n
    ordered = calculate_curve(Database(text), gt(composition=fixed[0], site_fractions=fixed))
    disordered = calculate_curve(Database(text), gt(phase="DIS", composition=fixed[0]))
    assert ordered["rows"][0]["G_J_mol_atoms"] == pytest.approx(disordered["rows"][0]["G_J_mol_atoms"], abs=1e-7)
    assert ordered["rows"][0]["G_ord_J_mol_atoms"] == pytest.approx(0, abs=1e-7)
    assert ordered["ordering_model"]["kind"] == "partitioned_order_disorder"


@pytest.mark.parametrize("n", [3, 4, 5])
def test_partitioned_arbitrary_occupation_matches_pair_model(n):
    ratios = np.arange(1, n+1)
    model = GibbsModel(Database(cef_tdb(n, "partitioned", ratios=ratios.tolist())), "TEST", None, [900], 101325)
    y_ni = np.linspace(.1, .9, n)
    weights = ratios / ratios.sum()
    x = weights @ y_ni
    unlike_pairs = sum(y_ni[i]*(1-y_ni[j]) + (1-y_ni[i])*y_ni[j] for i in range(n) for j in range(i+1, n))
    pair_energy = -12000*(n-1)*unlike_pairs/(n*(n-1)/2)
    random_pair_energy = -12000*(n-1)*2*x*(1-x)
    expected = ((1-x)*(1000-8*900) + x*(3000-12*900) + (3000-.5*900)*x*(1-x)
                + 8.3145*900*(weights @ ((1-y_ni)*np.log(1-y_ni)+y_ni*np.log(y_ni)))
                + pair_energy-random_pair_energy)
    y = np.column_stack((1-y_ni, y_ni)).ravel()
    assert model.values(900, 101325, y)[0] == pytest.approx(expected, abs=1e-7)


def test_pandat_ordering_keyword_keeps_original_source_hash():
    text = cef_tdb(3, "partitioned", ratios=[1/3]*3, ordering_keyword="DISORDER_PART")
    # Do not accidentally rewrite a function name or comment containing it.
    text += "\nFUNCTION DISORDER_PART 298.15 5; 6000 N !\n$ DISORDER_PART comment\n"
    path = BASE_DATA_DIR / "pandat_ordering_alias.tdb"
    atomic_write(path, text)
    db, sources = read_databases([str(path)])
    assert "DISORDER_PART" in db.symbols
    assert db.phases["TEST"].model_hints["disordered_phase"] == "DIS"
    assert sources[0]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert sources[0]["parser_normalizations"] == {"DISORDER_PART_to_DISORDERED_PART": 1}
    result = calculate_curve(db, gt())
    assert result["ordering_model"]["kind"] == "partitioned_order_disorder"


def test_partitioned_restriction_preserves_counterfactual_and_database():
    db = Database(cef_tdb(3, "partitioned"))
    before = copy.deepcopy(db.phases["TEST"].constituents)
    unrestricted = GibbsModel(db, "TEST", None, [1000], 101325)
    groups = [["AL"], ["AL", "NI"], ["AL", "NI"]]
    restricted = GibbsModel(db, "TEST", groups, [1000], 101325)
    assert db.phases["TEST"].constituents == before
    assert restricted.values(1000, 101325, [1, .25, .75, .25, .75])[0] == pytest.approx(
        unrestricted.values(1000, 101325, [1, 0, .25, .75, .25, .75])[0], abs=1e-7)


def test_partitioned_dependencies_and_physics_rejected():
    text = cef_tdb(3, "partitioned")
    with pytest.raises(ValueError, match="Missing TDB function UNDEFINED"):
        calculate_curve(Database(text.replace("G(DIS,AL;0) 298.15 GHSERAL#", "G(DIS,AL;0) 298.15 UNDEFINED#")), gt())
    with pytest.raises(ValueError, match="conventional IHJ"):
        calculate_curve(Database(text + "PARAMETER NT(TEST,AL:AL:AL;0) 298.15 500; 6000 N !"), gt())
    # A parameter excluded from the physical occupation still contributes in
    # the disordered subtraction G_ord(x), so it cannot silently be omitted.
    text = "\n".join(line for line in text.splitlines() if "G(TEST,NI:NI:NI;0)" not in line)
    with pytest.raises(ValueError, match="Missing endmember"):
        calculate_curve(Database(text), gt(sublattices=[["AL"], ["AL", "NI"], ["AL", "NI"]]))


def test_fixed_five_sublattice_constitution_unequal_weights():
    ratios = [1, 2, 3, 4, 5]
    sites = [{"AL": 1}, {"NI": 1}, {"AL": .2, "NI": .8}, {"NI": 1}, {"AL": .4, "NI": .6}]
    x_ni = sum(r*s.get("NI", 0) for r, s in zip(ratios, sites))/sum(ratios)
    text = cef_tdb(5, "nonideal", ratios=ratios)
    result = calculate_curve(Database(text), gt(composition={"AL": 1-x_ni, "NI": x_ni}, site_fractions=sites))
    row = result["rows"][0]
    assert row["method"] == "fixed_site_fractions"
    assert [row[f"Y_{i}_NI"] for i in range(5)] == pytest.approx([0, 1, .8, 1, .6])
