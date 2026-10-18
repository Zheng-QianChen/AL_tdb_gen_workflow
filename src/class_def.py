#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@文件        :class_def.py
@说明        :AL4tdb_v2.0
@时间        :2025/03/24 03:09:43
@作者        :郑芊宸 gz1999zqc@163.com
@版本        :2.0
'''


import pickle
import hashlib
import os
from collections import defaultdict

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator
from src.ml import initialize_ml_model, Stack_ML_model
from src.thermodynamics import formation_energy, site_fractions
from src.storage import atomic_write, atomic_json
from pathlib import Path
from copy import deepcopy

from config import resolve_data_path

import src.Hull as Hull
import src.POSCAR_generate
import src.post as post


def format_element(element_str):
    """将元素符号转为首字母大写格式"""
    return element_str.title()

# 提取为公共函数，实现代码复用




class Phase:

    def __init__(self, iter, name, structure, tdb_model=None, record_path=""):
        if tdb_model is None:
            raise ValueError("A sublattice model and reference energies are required")
        self.checkpoint_version = 2
        self.name, self.iter, self.structure = name, iter, structure
        self.total_atoms = structure.num_sites
        self.record_path = Path(record_path)
        self.record_path.mkdir(parents=True, exist_ok=True)
        self.tdb_model = deepcopy(tdb_model)
        model = self.tdb_model
        if not model["comp"] or any(not group for group in model["comp"]):
            raise ValueError("Each sublattice needs at least one species")
        if len(model["comp"]) != len(model["occup_atoms_in_tdb"]):
            raise ValueError("Sublattice species and site counts must have equal lengths")
        model["sys_species"] = sorted({e for group in model["comp"] for e in group})
        model["Atom_weight"] = site_fractions(model["occup_atoms_in_tdb"]).tolist()
        ref = model["Atom_ref"]
        table = pd.read_csv(resolve_data_path(ref["file"]))[[ref["index_name"], ref["col_name"]]]
        table[ref["index_name"]] = table[ref["index_name"]].str.title()
        if table[ref["index_name"]].duplicated().any():
            raise ValueError("Duplicate element reference energies")
        energies = pd.to_numeric(table[ref["col_name"]], errors="raise")
        if not np.isfinite(energies).all():
            raise ValueError("Reference energies must be finite")
        model["Atom_ref"] = dict(zip(table[ref["index_name"]], energies))
        missing = [e for e in model["sys_species"] if e.title() not in model["Atom_ref"]]
        if missing:
            raise ValueError(f"Missing reference energies: {missing}")
        self.pool = self.pool_generate()
        self.subl_energy = pd.DataFrame({
            "endmember": self.pool, "in_iter": np.full(len(self.pool), np.nan),
            "DFT_1": np.zeros(len(self.pool)), "DFT_2": np.zeros(len(self.pool)),
        })
        self.subl_energy["Atom_ref"] = self.subl_energy["endmember"].apply(self.calculate_weighted_energy)
        species = model["sys_species"]
        columns = species[1:] + ["Energy"]
        self.ref_points = pd.DataFrame(
            np.column_stack((np.eye(len(species))[:, 1:], np.zeros(len(species)))),
            columns=columns, index=pd.Index(species, name="endmember"))
        self.calc_points = pd.DataFrame(columns=columns, dtype=float)
        self.all_points = self.get_points(self.pool).set_index("endmember")
        self.ML_model_type, self.ML_hyper_parameters = "gbr", {}
        self.X_bable = pd.DataFrame()
        self.MLmodel = self._initialize_ml_model()


    def _initialize_ml_model(self) -> BaseEstimator:
        """调用公共函数初始化模型"""
        return initialize_ml_model(self.ML_model_type, self.ML_hyper_parameters)

    def pool_generate(self):
        from itertools import product
        model = self.tdb_model['comp']
        combined = [":".join(items) for items in product(*model)]
        print(len(combined))
        return combined



    def X_table_init(self, ML_model_type, ML_hyper_parameters, ML_style,
                     eigen_table, eigen_weight, normalizer, generate_DFT_path,
                     calced_DFT_path, pkl_phase_path, pkl_show_control, quest):
        self.ML_model_type, self.ML_hyper_parameters = ML_model_type, ML_hyper_parameters
        if ML_style not in {"flat", "stack"}:
            raise ValueError("ML_style must be flat or stack")
        self.ML_style, self.quest = ML_style, quest
        self.MLmodel = self._initialize_ml_model()
        self.generate_DFT_path, self.calced_DFT_path = Path(generate_DFT_path), Path(calced_DFT_path)
        self.pkl_phase_path, self.pkl_show_control = Path(pkl_phase_path), pkl_show_control
        features = eigen_table.copy()
        features["symbol"] = features["symbol"].str.upper()
        if features["symbol"].duplicated().any():
            raise ValueError("Descriptor symbols must be unique")
        features = features.set_index("symbol").apply(pd.to_numeric, errors="raise")
        required = self.tdb_model["sys_species"]
        if not set(required).issubset(features.index):
            raise ValueError("Descriptors are missing required elements")
        if not np.isfinite(features.loc[required].to_numpy()).all():
            raise ValueError("Descriptors must be finite for every required element")
        self.eigen_table = features.columns.to_numpy()
        self.eigen_num_per_site = len(features.columns)
        self.X_bable = pd.DataFrame([
            {"endmember": member, **{
                f"site_{site}_{column}": features.loc[element, column]
                for site, element in enumerate(member.split(":"), 1)
                for column in features.columns}}
            for member in self.pool])
        cols = self.X_bable.columns[1:]
        from sklearn.preprocessing import StandardScaler, MinMaxScaler
        if normalizer not in {"Zscore", "mmscale"}:
            raise ValueError("normalizer must be Zscore or mmscale")
        self.scaler = StandardScaler() if normalizer == "Zscore" else MinMaxScaler()
        # The complete, known candidate pool defines the descriptor scale.
        self.X_bable[cols] = self.scaler.fit_transform(self.X_bable[cols])

    def upload(self, up_endmem:list):
        up_endmem = sorted(set(up_endmem))
        os.makedirs(f"{self.generate_DFT_path}/{self.iter}",exist_ok=True)
        holder = self.tdb_model["site_holder"]
        print(holder)
        for endmem in up_endmem:
            endmem = f"{endmem}"
            temp = [element.capitalize() for element in endmem.split(":")]
            ele_map = dict(zip(holder, temp))
            lat_name = endmem.replace(":","_")
            src.POSCAR_generate.POSCAR_generate(in_poscar=self.structure,
                                                replace_map=ele_map,
                                                out_poscar_path=f"{self.generate_DFT_path}/{self.iter}/{lat_name}/POSCAR")
        tasks = []
        for index, member in enumerate(up_endmem):
            relative = member.replace(":", "_") + "/POSCAR"
            path = self.generate_DFT_path / str(self.iter) / relative
            tasks.append({"task_id": f"task.{index:06d}", "endmember": member,
                          "poscar": relative, "natoms": self.total_atoms,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        atomic_json(self.generate_DFT_path / str(self.iter) / "tasks.json",
                    {"version": 1, "iteration": self.iter, "tasks": tasks})


    def calculate_weighted_energy(self, row):
        elements = [format_element(e) for e in row.split(":")]
        weights = self.tdb_model["Atom_weight"]
        if len(elements) != len(weights):
            raise ValueError("Element and sublattice counts differ")
        references = self.tdb_model["Atom_ref"]
        missing = [e for e in elements if e not in references]
        if missing:
            raise ValueError(f"Missing reference energies: {missing}")
        return sum(references[e] * weight for e, weight in zip(elements, weights))


    def add_calced_points(self, file, expected=None):
        rows = []
        with open(file, encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                parts = line.strip().split(",")
                if len(parts) != 3:
                    raise ValueError(f"calc.txt line {line_number}: expected endmember,DFT_1,DFT_2")
                member = parts[0].strip().replace("_", ":").upper()
                if member not in self.pool:
                    raise ValueError(f"Unknown endmember on line {line_number}: {member}")
                values = [float(value) for value in parts[1:]]
                if not np.isfinite(values).all():
                    raise ValueError(f"Nonfinite DFT energy on line {line_number}")
                rows.append([member, self.iter, *values])
        if not rows:
            raise ValueError("calc.txt contains no results")
        data = pd.DataFrame(rows, columns=["endmember", "in_iter", "DFT_1", "DFT_2"])
        if expected is not None:
            if data["endmember"].duplicated().any():
                raise ValueError("Duplicate endmember results in the current batch")
            if set(data["endmember"]) != set(expected):
                raise ValueError("Results must cover exactly the requested endmembers for this round")
        data = data.drop_duplicates("endmember", keep="last").set_index("endmember")
        reference = self.subl_energy.set_index("endmember")["Atom_ref"].loc[data.index]
        points = self.get_points(data.index).set_index("endmember")
        points["Energy"] = formation_energy(data["DFT_2"].to_numpy(), self.total_atoms, reference.to_numpy())
        known = self.subl_energy.set_index("endmember")
        novel = data.index[known.loc[data.index, "in_iter"].isna()]
        self.y_test = points.loc[novel, "Energy"].to_numpy()
        self.X_test = self.X_bable.set_index("endmember").loc[novel]
        self.calc_points = pd.concat([self.calc_points, points])
        self.calc_points = self.calc_points[~self.calc_points.index.duplicated(keep="last")]
        known.update(data)
        self.subl_energy = known.reset_index()
        return data


    def ML(self):
        if self.iter and len(getattr(self, "y_test", [])) and hasattr(self, "X_train"):
            train_prediction = self.MLmodel.predict(self.X_train)
            test_prediction = self.MLmodel.predict(self.X_test)
            self.y_pred_test_MLmodel = test_prediction
            importance = (self.MLmodel.get_X_imp(self.X_train) if self.ML_style == "stack"
                          else pd.DataFrame(self.X_train))
            post.assess(self.record_path, self.MLmodel, importance, self.X_train,
                        self.X_train, importance.columns, self.y_train, self.y_train,
                        train_prediction, self.y_test, test_prediction)
            post.pred_calc_fig(self.pkl_phase_path, self.iter, phase=self)
        train = self.ML_stack if self.ML_style == "stack" else self.ML_flat
        self.MLmodel, self.X_train, self.y_train = train()
        self.y_pred = self.MLmodel.predict(self.X_bable.drop(columns="endmember"))
        self.pool_pred = pd.DataFrame({"endmember": self.X_bable["endmember"],
                                      "y_pred_kJ_mol": self.y_pred})
        return self.MLmodel


    def ML_flat(self):
        training = self.subl_energy.loc[self.subl_energy["in_iter"].notna()].set_index("endmember")
        if training.empty:
            raise ValueError("No DFT training data")
        X_train = self.X_bable.set_index("endmember").loc[training.index]
        y_train = formation_energy(training["DFT_2"].to_numpy(), self.total_atoms, training["Atom_ref"].to_numpy())
        model = self._initialize_ml_model().fit(X_train, y_train)
        return model, X_train, y_train



    def ML_stack(self):
        training = self.subl_energy.loc[self.subl_energy["in_iter"].notna()].set_index("endmember")
        X_train = self.X_bable.set_index("endmember").loc[training.index]
        y_train = formation_energy(training["DFT_2"].to_numpy(), self.total_atoms, training["Atom_ref"].to_numpy())
        model = Stack_ML_model(self.eigen_table, X_train.columns,
                               self.ML_model_type, self.ML_hyper_parameters)
        model.fit(X_train, y_train)
        return model, X_train, y_train


    def get_points(self, endmember):
        points = []
        for member in endmember:
            elements = member.split(":")
            if len(elements) != len(self.tdb_model["Atom_weight"]):
                raise ValueError("Invalid endmember sublattice count")
            fractions = defaultdict(float)
            for element, weight in zip(elements, self.tdb_model["Atom_weight"]):
                fractions[element] += weight
            points.append({**fractions, "endmember": member, "Energy": 0.0})
        columns = ["endmember"] + self.tdb_model["sys_species"][1:] + ["Energy"]
        return pd.DataFrame(points, columns=columns).fillna(0.0)


    def points_modify(self, points):
        """Legacy helper: return an independent array/table, never mutate inputs."""
        return points.copy(deep=True) if isinstance(points, pd.DataFrame) else np.array(points, copy=True)


    def convex_analy(self):
        points = self.get_points(self.pool).set_index("endmember")
        predictions = self.pool_pred.set_index("endmember")["y_pred_kJ_mol"]
        points["Energy"] = predictions.reindex(points.index)
        if self.calc_points.index.has_duplicates:
            self.calc_points = self.calc_points[~self.calc_points.index.duplicated(keep="last")]
        known = points.index.intersection(self.calc_points.index)
        points.loc[known, "Energy"] = self.calc_points.loc[known, "Energy"]
        if not np.isfinite(points.to_numpy(dtype=float)).all():
            raise ValueError("Missing or nonfinite endmember predictions")
        distances = Hull.energy_above_hull(points.to_numpy(dtype=float, copy=True))
        self.all_points = points
        self.pt_to_hull = pd.DataFrame({"endmember": points.index, "above_hull": distances})
        self.calc_points.to_csv(self.record_path / "calced_points.csv")
        self.all_points.to_csv(self.record_path / "all_convex_dimention_points.csv")
        self.pt_to_hull.to_csv(self.record_path / "test_above_hull.csv", index=False)
        return 0


    def generate_DFT_POSCAR(self):
        candidates = self.pt_to_hull.merge(
            self.subl_energy.loc[self.subl_energy["in_iter"].isna()], on="endmember",
            how="inner", validate="one_to_one").sort_values(["above_hull", "endmember"])
        batches = []
        for key, label in [("near_hall", "NEAR_HULL"), ("unstable", "UNSTABLE"), ("random", "RANDOM")]:
            count = self.quest[key]
            if not isinstance(count, int) or count < 0:
                raise ValueError("Query counts must be nonnegative integers")
            count = min(count, len(candidates))
            if key == "near_hall":
                selected = candidates.head(count).copy()
            elif key == "unstable":
                selected = candidates.tail(count).copy()
            else:
                selected = candidates.sample(n=count, random_state=getattr(self, "random_seed", 42) + self.iter).copy()
            selected["selection_type"] = label
            batches.append(selected)
            candidates = candidates.drop(selected.index)
        self.upload_ref = pd.concat(batches, ignore_index=True)
        summary = self.record_path / "upload_summary"
        summary.mkdir(parents=True, exist_ok=True)
        self.upload_ref.to_csv(summary / f"upload_summary_{self.iter}.csv", index=False)
        if not self.upload_ref.empty:
            self.upload(self.upload_ref["endmember"].tolist())
        return len(self.upload_ref)


    def save(self, filename):
        atomic_write(filename, pickle.dumps(self.__dict__), binary=True)


    @classmethod
    def load(cls, filename):
        with open(filename, "rb") as stream:
            state = pickle.load(stream)
        if state.get("checkpoint_version") != 2:
            raise ValueError("Legacy checkpoint uses unverified energy/composition conventions; start a new run directory")
        instance = cls.__new__(cls)
        instance.__dict__ = state
        return instance
