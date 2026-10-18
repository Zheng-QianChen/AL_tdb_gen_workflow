import xml.etree.ElementTree as ET

import numpy as np
from pycalphad import Database
import pytest

from examples.pandat_batch import read_point, run_document
from examples.pandat_occupancy_diagnosis import experiment_document
from examples.pandat_symmetry_diagnosis import analyze
from src.gibbs import GibbsModel
from tests.test_gibbs import binary_tdb


@pytest.fixture
def ideal_model():
    return GibbsModel(Database(binary_tdb((.25,)*4)), "TEST", None, [500], 101325, False)


def test_initial_values_use_one_based_sites_and_separate_modes(ideal_model):
    row = {"T_K": 500, "P_Pa": 101325, "X_AL": .5, "X_NI": .5}
    seed = np.array([.8, .2, .4, .6, .4, .6, .4, .6])
    variants = [("baseline", None, None), ("seeded", "local", "chosen")]
    root = ET.fromstring(experiment_document(row, ideal_model, {"chosen": seed}, variants, {"AL": -1000, "NI": -2000}))
    baseline, local = root.findall("calculation")
    assert baseline.find("system/condition/individual_phase").get("value") == "true"
    assert baseline.find(".//initial_value") is None
    assert local.find("system/condition/individual_phase") is None
    assert local.find("system/condition/equilibrium_type").get("type") == "local"
    assert local.find(".//initial_value/mu[@species='AL']").get("value") == "-1000"
    exported = local.findall(".//phase_point/y")
    assert [item.get("sublattice") for item in exported] == [str(i) for i in range(1, 5) for _ in range(2)]
    assert np.allclose([float(item.get("value")) for item in exported], seed)


def test_seed_must_conserve_composition_and_normalize_sites(ideal_model):
    row = {"T_K": 500, "P_Pa": 101325, "X_AL": .5, "X_NI": .5}
    for seed, message in (([.6, .4]*4, "conserve"), ([.5, .4]*4, "Invalid")):
        with pytest.raises(ValueError, match=message):
            experiment_document(row, ideal_model, {"chosen": seed}, [("seeded", "local", "chosen")])


def test_released_symmetry_does_not_invent_instability_in_ideal_solution(ideal_model):
    y = np.array([.5]*8)
    row = {"T_K": 500, "P_Pa": 101325, "X_AL": .5, "X_NI": .5,
           "G_J_mol_atoms": ideal_model.values(500, 101325, y)[0]}
    result = analyze(ideal_model, row, y)
    assert result["restricted_degrees_of_freedom"] == 0
    assert result["full_degrees_of_freedom"] == 3
    assert all(min(item["full_eigenvalues"]) > 0 for item in result["hessians"])
    assert all(item["success"] and item["feasible"] and item["G"] == pytest.approx(row["G_J_mol_atoms"], abs=1e-6)
               for item in result["released_optimizations"])


def test_bad_batch_count_fails_before_executable_access(tmp_path):
    with pytest.raises(ValueError, match="sequential"):
        run_document("missing.exe", tmp_path, '<pbfx><calculation name="point_1"/></pbfx>', 1)


def test_global_same_phase_split_is_not_a_homogeneous_reference(tmp_path):
    path = tmp_path/"split.dat"
    path.write_text("T\tP\tphase_name\nK\tatm\t\n500\t1\tFCC4+FCC4\n")
    with pytest.raises(ValueError, match="expected a single"):
        read_point(path, "FCC4", ["FE", "NI"], [["FE", "NI"]]*4, {"X_FE": .5, "X_NI": .5})
