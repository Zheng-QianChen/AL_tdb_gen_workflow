import numpy as np
from pycalphad import Database
import pytest

from examples.pandat_special_models import INTERSTITIAL, magnetic_ordering_tdb
from src.gibbs import GibbsModel, calculate_curve
from src.gibbs_compare import compare_points, model_declaration


def gt(**kwargs):
    return {"tdb_files": ["test.tdb"], "phase": "TEST", "mode": "gt", "temperatures": [800],
            "composition": {"FE": .9, "C": .1}, "starts": 16, **kwargs}


def ihj_numeric(t, tc, beta, p=.4):
    tau = t/tc
    a = 518/1125+(11692/15975)*(1/p-1)
    if tau <= 1:
        g = 1-((79/(140*p))/tau+(474/497)*(1/p-1)*(tau**3/6+tau**9/135+tau**15/600))/a
    else:
        g = -(tau**-5/10+tau**-15/315+tau**-25/1500)/a
    return 8.3145*t*np.log(beta+1)*g


@pytest.mark.parametrize("x", [0, .01, .1, .5])
def test_interstitial_uses_occupied_atoms_not_total_sites(x):
    result = calculate_curve(Database(INTERSTITIAL), gt(composition={"FE": 1-x, "C": x}))
    row = result["rows"][0]
    y = x/(3*(1-x))
    entropy = 0 if y == 0 else y*np.log(y)+(1-y)*np.log(1-y)
    expected = ((1-y)*(-10000)+y*(20000-8000)+3*8.3145*800*entropy)/(1+3*y)
    assert row["Y_1_C"] == pytest.approx(y, abs=1e-10)
    assert row["Y_1_VA"] == pytest.approx(1-y, abs=1e-10)
    assert row["atoms_per_formula_unit"] == pytest.approx(1/(1-x))
    assert row["G_J_mol_atoms"] == pytest.approx(expected, abs=1e-7)
    assert "VA" not in result["components"] and "X_VA" not in row


def test_fixed_interstitial_and_comparison_occupancy_normalization():
    x = .3/1.3
    result = calculate_curve(Database(INTERSTITIAL), gt(composition={"FE": 1-x, "C": x},
                             site_fractions=[{"FE": 1}, {"C": .1, "VA": .9}]))
    result["sources"] = [{"sha256": "a"*64}]
    result["request"] = {}
    row = result["rows"][0]
    csv = f"phase,T_K,P_Pa,X_FE,X_C,G,Y_0_FE,Y_1_C,Y_1_VA\nTEST,800,101325,{1-x},{x},{row['G_J_mol_atoms']},1,.1,.9\n"
    req = {"result": "local.json", "reference_csv": "reference.csv", "software": "other", "software_version": "analytic test",
           "reference_model": model_declaration(result), "conditions_verified": True}
    assert compare_points(result, req, csv)["status"] == "within_tolerance"
    with pytest.raises(ValueError, match="unselected"):
        calculate_curve(Database(INTERSTITIAL), gt(composition={"FE": .9, "VA": .1}))


@pytest.mark.parametrize("afm", [False, True])
def test_magnetic_properties_are_partitioned_before_energy(afm):
    text = magnetic_ordering_tdb(2, interstitial=True, afm=afm)
    fixed = [{"AL": 1}, {"NI": 1}, {"VA": 1}]
    result = calculate_curve(Database(text), gt(composition={"AL": .5, "NI": .5}, site_fractions=fixed))
    row = result["rows"][0]
    assert row["TC_K"] == pytest.approx(1300)
    assert row["BMAG"] == pytest.approx(2.4)
    assert row["G_mag_J_mol_atoms"] == pytest.approx(ihj_numeric(800, 1300, 2.4), abs=1e-7)
    # Taking a difference of magnetic energies is not the partitioned model.
    naive = ihj_numeric(800, 1000, 2)+ihj_numeric(800, 600, .8)-ihj_numeric(800, 300, .4)
    assert abs(row["G_mag_J_mol_atoms"]-naive) > 100


@pytest.mark.parametrize("t", [999.999, 1000, 1000.001])
def test_magnetic_energy_at_and_around_curie_temperature(t):
    text = magnetic_ordering_tdb(2, interstitial=True)
    row = calculate_curve(Database(text), gt(phase="DIS", temperatures=[t], composition={"AL": .5, "NI": .5}))["rows"][0]
    assert row["G_mag_J_mol_atoms"] == pytest.approx(ihj_numeric(t, 1000, 2), abs=1e-7)
    assert row["G_mag_J_mol_atoms"] < -100


def test_variable_interstitial_random_limit_and_magnetic_gradient():
    db = Database(magnetic_ordering_tdb(2, variable_interstitial=True))
    x = {"AL": .45, "NI": .45, "C": .1}
    c_site = .1/(3*.9)
    fixed = [{"AL": .5, "NI": .5}]*2 + [{"C": c_site, "VA": 1-c_site}]
    ordered = calculate_curve(db, gt(composition=x, site_fractions=fixed))["rows"][0]
    base = calculate_curve(db, gt(phase="DIS", composition=x))["rows"][0]
    assert ordered["G_J_mol_atoms"] == pytest.approx(base["G_J_mol_atoms"], abs=1e-6)
    assert ordered["G_ord_J_mol_atoms"] == pytest.approx(0, abs=1e-7)
    model = GibbsModel(db, "TEST", None, [800], 101325)
    y = np.array([.8, .2, .2, .8, c_site, 1-c_site])
    gradient = model.derivative(800, 101325, *y)
    step = 1e-6
    for index in range(len(y)):
        direction = np.eye(len(y))[index]*step
        finite_difference = (model.values(800, 101325, y+direction)[0]-model.values(800, 101325, y-direction)[0])/(2*step)
        assert gradient[index] == pytest.approx(finite_difference, rel=2e-6, abs=1e-3)


def test_mobility_parameters_do_not_enter_gibbs_validation():
    text = INTERSTITIAL + """
PARAMETER MQ(TEST&FE,FE:VA;0) 298.15 MISSING_MOBILITY_FUNCTION#; 6000 N !
PARAMETER MQ(TEST&C,FE:VA;0) 298.15 2000; 6000 N !
"""
    row = calculate_curve(Database(text), gt())["rows"][0]
    reference = calculate_curve(Database(INTERSTITIAL), gt())["rows"][0]
    assert row["G_J_mol_atoms"] == pytest.approx(reference["G_J_mol_atoms"])


def test_missing_ordered_parameters_require_explicit_opt_in():
    text = magnetic_ordering_tdb(2)
    text = "\n".join(line for line in text.splitlines() if "G(TEST,AL:AL;0)" not in line)
    with pytest.raises(ValueError, match="Missing endmember"):
        calculate_curve(Database(text), gt(composition={"AL": .5, "NI": .5}))
    result = calculate_curve(Database(text), gt(composition={"AL": .5, "NI": .5}, allow_missing_ordered_endmembers=True))
    assert result["ordering_model"]["allow_missing_ordered_endmembers"]
