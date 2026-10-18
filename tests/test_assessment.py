import pandas as pd
from pycalphad import Database
from src.main_process.subl_model_assess import subl_assess
from src.tdb_generator import pre_for_model_assess
from tests.test_tdb import BASE


def test_score_and_repeated_assessed_export(phase, tmp_path):
    p = phase.phase
    p.pool_pred = pd.DataFrame({"endmember": p.pool, "y_pred_kJ_mol": [2, -20, -10, 3]})
    p.convex_analy()
    pre_for_model_assess(p, tmp_path)
    analyzer = subl_assess(phase.input_json, tmp_path / "DEMO_B2_tdb_gen.csv", tmp_path)
    assert analyzer.vasp_ml_data is not None
    analyzer.get_model_result_raw([1, 2])
    score = pd.read_csv(analyzer.working_path / "model_score.csv").set_index("model")
    assert score.loc["1_A_A.csv", "RMSE"] > 10
    assert score.loc["2_A_B.csv", "RMSE"] == 0
    candidate = [[2, "A:B"]]
    analyzer.output_all_tdb_file_assessed(candidate, save_path=tmp_path / "export")
    analyzer.output_all_tdb_file_assessed(candidate, save_path=tmp_path / "export")
    assert candidate == [[2, "A:B"]]
    path = next((tmp_path / "export").glob("*.tdb"))
    db = Database(BASE + path.read_text())
    assert "DEMO_B2" in db.phases
    analyzer.output_all_tdb_file_assessed(candidate, site_elements=[["AL"], ["AL"]],
                                         save_path=tmp_path / "pure")
    pure = next((tmp_path / "pure").glob("*.tdb"))
    assert len(Database(BASE + pure.read_text())._parameters.all()) == 1
