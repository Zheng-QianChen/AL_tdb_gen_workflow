import numpy as np
import pandas as pd
import pytest
from sklearn.base import clone
from sklearn.model_selection import cross_val_score
from src.ml import Stack_ML_model


@pytest.mark.parametrize("kind, parameters", [("rf", {"n_estimators": 3}), ("lr", {}), ("dt", {})])
def test_clone_fit_and_cross_validation(kind, parameters):
    X = pd.DataFrame({"site_1_z": np.arange(12), "site_2_z": np.arange(12)[::-1]})
    y = np.sin(np.arange(12))
    model = Stack_ML_model(["z"], list(X), kind, parameters, cv=3)
    copied = clone(model)
    assert copied.ML_model_type == kind
    assert copied.ML_hyper_parameters == parameters
    copied.fit(X, y)
    assert np.isfinite(copied.predict(X)).all()
    assert np.isfinite(cross_val_score(model, X, y, cv=3, scoring="neg_mean_squared_error")).all()


def test_stacking_features_are_out_of_fold():
    X = pd.DataFrame({"site_1_z": np.arange(20)})
    y = np.random.default_rng(2).normal(size=20)
    model = Stack_ML_model(["z"], list(X), "dt", cv=5).fit(X, y)
    # A fully grown tree memorizes training labels; OOF predictions must not.
    np.testing.assert_allclose(model.models["all"].predict(X), y)
    assert not np.allclose(model.oof_predictions_["all"], y)
