"""Clone-compatible regression models with out-of-fold stacking."""
import re
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression, Ridge, Lasso
from sklearn.neighbors import KNeighborsRegressor
from sklearn.svm import SVR
from sklearn.neural_network import MLPRegressor
from sklearn.tree import DecisionTreeRegressor
from sklearn.model_selection import KFold, cross_val_predict


def initialize_ml_model(model_type, hyper_parameters=None):
    parameters = dict(hyper_parameters or {})
    models = {"gbr": GradientBoostingRegressor, "rf": RandomForestRegressor,
              "lr": LinearRegression, "ridge": Ridge, "lasso": Lasso,
              "knn": KNeighborsRegressor, "svr": SVR, "mlp": MLPRegressor,
              "dt": DecisionTreeRegressor}
    if model_type == "xgb":
        try:
            from xgboost import XGBRegressor
        except ImportError as exc:
            raise ImportError("Install the xgboost extra to use model 'xgb'") from exc
        models["xgb"] = XGBRegressor
        parameters = {"n_estimators": 100, "learning_rate": 0.1, "max_depth": 3,
                      "objective": "reg:squarederror", **parameters}
    elif model_type == "catboost":
        try:
            from catboost import CatBoostRegressor
        except ImportError as exc:
            raise ImportError("Install the catboost extra to use model 'catboost'") from exc
        models["catboost"] = CatBoostRegressor
        parameters = {"verbose": 0, "iterations": 1000, "learning_rate": .05,
                      "depth": 6, "random_seed": 42, **parameters}
    if model_type not in models:
        raise ValueError(f"Unsupported model: {model_type}")
    estimator = models[model_type]
    if "random_state" in estimator().get_params():
        parameters.setdefault("random_state", 42)
    return estimator(**parameters)


class Stack_ML_model(RegressorMixin, BaseEstimator):
    def __init__(self, eigen_table, X_columns, ML_model_type="gbr",
                 ML_hyper_parameters=None, cv=5, random_state=42):
        self.eigen_table = eigen_table
        self.X_columns = X_columns
        self.ML_model_type = ML_model_type
        self.ML_hyper_parameters = ML_hyper_parameters
        self.cv = cv
        self.random_state = random_state

    def set_model(self, ML_model_type, ML_hyper_parameters):
        self.set_params(ML_model_type=ML_model_type, ML_hyper_parameters=ML_hyper_parameters)
        return self

    def _initialize_ml_model(self):
        return initialize_ml_model(self.ML_model_type, self.ML_hyper_parameters)

    def get_X_sub(self, X):
        frame = pd.DataFrame(np.asarray(X), columns=self.X_columns)
        groups = {}
        for column in frame.columns:
            match = re.fullmatch(r"site_\d+_(.*)", column)
            if match and match[1] in self.eigen_table:
                groups.setdefault(match[1], []).append(column)
        return {**{name: frame[columns] for name, columns in groups.items()}, "all": frame}

    def fit(self, X, y):
        y = np.asarray(y, dtype=float)
        if len(y) < 2:
            raise ValueError("Stacking needs at least two training samples")
        folds = KFold(n_splits=min(self.cv, len(y)), shuffle=True, random_state=self.random_state)
        groups = self.get_X_sub(X)
        self.models = {}
        oof = pd.DataFrame(index=np.arange(len(y)))
        for name, frame in groups.items():
            model = self._initialize_ml_model()
            oof[name] = cross_val_predict(model, frame, y, cv=folds, method="predict")
            self.models[name] = model.fit(frame, y)
        self.final_model = self._initialize_ml_model().fit(oof, y)
        self.n_features_in_ = np.asarray(X).shape[1]
        self.oof_predictions_ = oof
        if hasattr(self.final_model, "feature_importances_"):
            self.feature_importances_ = self.final_model.feature_importances_
        elif hasattr(self, "feature_importances_"):
            del self.feature_importances_
        return self

    def get_X_imp(self, X):
        groups = self.get_X_sub(X)
        return pd.DataFrame({name: model.predict(groups[name]) for name, model in self.models.items()})

    def predict(self, X):
        return self.final_model.predict(self.get_X_imp(X))
