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
import re
import os
from collections import defaultdict

import numpy as np
import pandas as pd
from pymatgen.core import Structure
from scipy.spatial import ConvexHull
from sklearn.base import BaseEstimator
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression, Ridge, Lasso
from sklearn.neighbors import KNeighborsRegressor
from sklearn.svm import SVR
from sklearn.neural_network import MLPRegressor
from sklearn.tree import DecisionTreeRegressor
from sklearn.model_selection import train_test_split
import xgboost as xgb
from catboost import CatBoostRegressor

import src.Hull as Hull
import src.POSCAR_generate
import src.post as post


def format_element(element_str):
    """将元素符号转为首字母大写格式"""
    return element_str.title()

# 提取为公共函数，实现代码复用
def initialize_ml_model(model_type: str, hyper_parameters: dict = None) -> BaseEstimator:
    """
    根据模型类型初始化相应的scikit-learn回归模型
    
    参数:
        model_type: 模型类型字符串
        hyper_parameters: 模型超参数字典
        
    返回:
        初始化后的模型实例
    """
    hyper_parameters = hyper_parameters or {}
    
    model_mapping = {
        'gbr':{
            "model":GradientBoostingRegressor,
            "default_params":{}},
        'rf':{
            "model":RandomForestRegressor,
            "default_params":{}},
        'lr':{
            "model":LinearRegression,
            "default_params":{}},
        'ridge':{
            "model":Ridge,
            "default_params":{}},
        'lasso':{
            "model":Lasso,
            "default_params":{}},
        'knn':{
            "model":KNeighborsRegressor,
            "default_params":{}},
        'svr':{
            "model":SVR,
            "default_params":{}},
        'mlp':{
            "model":MLPRegressor,
            "default_params":{}},
        'dt':{
            "model":DecisionTreeRegressor,
            "default_params":{}},
        'xgb': {  # 新增XGBoost模型
            "model": xgb.XGBRegressor,  # 导入XGBRegressor
            "default_params": {
                'n_estimators': 100,    # 树的数量（默认100）
                'learning_rate': 0.1,   # 学习率（默认0.1）
                'max_depth': 3,         # 树的最大深度（默认3）
                'objective': 'reg:squarederror'  # 回归任务目标函数
            }},
        'catboost': {  # 新增CatBoost模型
            "model": CatBoostRegressor,
            "default_params": {
                'verbose': 0,                # 关闭训练日志
                'iterations': 1000,          # 树的数量
                'learning_rate': 0.05,       # 学习率
                'depth': 6,                  # 树深度
                'l2_leaf_reg': 3,            # L2正则化
                'subsample': 0.8,            # 样本采样
                'early_stopping_rounds': 50, # 早停机制
                'eval_metric': 'RMSE',       # 评估指标
                'random_seed': 42            # 随机种子
            },
            "supports_cat_features": True  # 支持
        },
        # 可根据需要添加更多模型
    }
    
    # 获取模型类及默认参数
    if model_type not in model_mapping:
        raise ValueError(f"不支持的模型类型: {model_type}。支持的模型有: {list(model_mapping.keys())}")
    
    model_info = model_mapping[model_type]
    model_class = model_info["model"]
    default_params = model_info["default_params"]
    
    # 合并默认参数与用户传入的超参数（用户参数优先）
    final_params = {**default_params, **hyper_parameters}
    
    # 实例化模型
    return model_class(**final_params)

class Stack_ML_model(BaseEstimator):
    def __init__(self, eigen_table, X_columns):
        self.eigen_table = eigen_table
        self.X_columns = X_columns
        self.ML_model_type = "gbr"
        self.ML_hyper_parameters = {}
        self.models = {}
        self.final_model = None
        self.feature_importances_ = None
    
    def set_model(self,ML_model_type, ML_hyper_parameters):
        self.ML_model_type = ML_model_type
        self.ML_hyper_parameters = ML_hyper_parameters
    
    def _initialize_ml_model(self) -> BaseEstimator:
        """调用公共函数初始化模型"""
        return initialize_ml_model(self.ML_model_type, self.ML_hyper_parameters)
    
    def get_X_sub(self, X):
        X_train = pd.DataFrame(X, columns=self.X_columns)
        # 提取符合规则的列
        pattern = re.compile(r'site_\d+_(.*)')
        grouped = X_train.columns.to_series().groupby(lambda x: pattern.findall(x)[0] if pattern.findall(x) else '')
        
        # 划分数据表
        data_tables = {}
        for key, group in grouped:
            if key in self.eigen_table:
                data_tables[key] = X_train[group.tolist()]
        data_tables['all'] = X_train
        return data_tables
        
    def fit(self, X, y):
        y_train = y
        data_tables = self.get_X_sub(X)
        
        # 训练MLmodel模型
        models = {}
        for key, data in data_tables.items():
            X_sub = data_tables[key]
            model = self._initialize_ml_model()
            model.fit(X_sub, y_train)
            models[key] = model
        self.models = models
        
        # 整合模型输出
        integrated_data = pd.DataFrame()
        for key, model in models.items():
            X_sub = data_tables[key]
            y_middel = model.predict(X_sub)
            integrated_data[key] = y_middel
        
        # 训练最终的MLmodel模型
        final_X_train = integrated_data
        final_y_train = y_train
        final_model = self._initialize_ml_model()
        final_model.fit(final_X_train, final_y_train)
        self.final_model = final_model
        self.feature_importances_ = final_model.feature_importances_

    def get_X_imp(self, X):
        data_tables = self.get_X_sub(X)
        
        integrated_data = pd.DataFrame()
        for key, model in self.models.items():
            X = data_tables[key]
            y_middel = model.predict(X)
            integrated_data[key] = y_middel
        
        return integrated_data

    def predict(self,X_needpred):
        data_tables = self.get_X_sub(X_needpred)
        
        integrated_data = pd.DataFrame()
        for key, model in self.models.items():
            X = data_tables[key]
            y_middel = model.predict(X)
            integrated_data[key] = y_middel

        y = self.final_model.predict(integrated_data)
        return y

    def get_params(self, deep=True):
        return {
            'eigen_table': self.eigen_table,
            'X_columns': self.X_columns
        }

    def set_params(self, **parameters):
        for parameter, value in parameters.items():
            setattr(self, parameter, value)
        return self

class Phase:
    def __init__(self,
                 iter:int,
                 name: str,
                 structure: Structure,
                 tdb_model:dict={"comp":[["FE","CO"],["FE","CO"]]},
                 record_path:str=''):
        self.name = name
        self.iter = iter
        self.structure = structure
        self.total_atoms = self.structure.num_sites
        self.tdb_model = tdb_model
        self.record_path = record_path
        # 获得体系不重复的元素种类
        self.tdb_model["sys_species"] =list({element for sublist in tdb_model["comp"] for element in sublist})
        ref = sum(self.tdb_model["occup_atoms_in_tdb"])
        self.tdb_model["Atom_weight"] = [x/ref for x in self.tdb_model["occup_atoms_in_tdb"]]
        temp = self.tdb_model["Atom_ref"]
        self.tdb_model["Atom_ref"] = pd.read_csv(temp["file"])[[temp["index_name"],temp["col_name"]]]
        self.tdb_model["Atom_ref"][temp["index_name"]] = self.tdb_model["Atom_ref"][temp["index_name"]].apply(format_element)
        energy_dict = self.tdb_model["Atom_ref"].set_index(temp["index_name"])[temp["col_name"]].to_dict()
        self.tdb_model["Atom_ref"] = energy_dict
        print(self.tdb_model["Atom_ref"])
        self.pool = self.pool_generate()
        self.subl_energy = pd.DataFrame({
            'endmember': self.pool,
            'in_iter': [np.nan] * len(self.pool),
            'DFT_1': [0] * len(self.pool),
            'DFT_2': [0] * len(self.pool),
        })
        self.subl_energy['Atom_ref'] = self.subl_energy['endmember'].apply(self.calculate_weighted_energy)
        self.ML_model_type = 'gbr'
        self.ML_hyper_parameters = {}
        self.X_bable = pd.DataFrame()
        # 为凸包预备的数据
        self.ref_points = pd.DataFrame(columns=["endmember"] + self.tdb_model["sys_species"][1:]+["Energy"])
        self.ref_points = self.ref_points.set_index('endmember')
        self.calc_points = self.ref_points.copy(deep=True)
        self.all_points = self.get_points(self.pool).set_index('endmember')
        print(self.all_points)
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
                     eigen_table:pd.DataFrame, eigen_weight, normalizer,
                           generate_DFT_path, calced_DFT_path,
                           pkl_phase_path,pkl_show_control,
                           quest):
        self.ML_model_type = ML_model_type
        self.ML_hyper_parameters = ML_hyper_parameters
        self.MLmodel = self._initialize_ml_model()
        self.ML_style = ML_style
        self.generate_DFT_path = generate_DFT_path
        self.calced_DFT_path = calced_DFT_path
        self.pkl_phase_path = pkl_phase_path
        # low:2, medium:12, high:012
        self.pkl_show_control = pkl_show_control
        self.eigen_num_per_site = len(eigen_table.columns) - 1
        self.eigen_table = eigen_table.columns.values[1:]
        self.quest = quest
        X_bable = []
        for endmember in self.pool:
            symbols = endmember.split(":")
            missing = [s for s in symbols if s not in eigen_table["symbol"].values]
            if missing:
                raise ValueError(f"无效符号: {missing}")
            result = {}
            result.update({"endmember":endmember})
            for idx, symbol in enumerate(symbols, 1):
                row = eigen_table[eigen_table["symbol"] == symbol].iloc[0]
                prefix = f"site_{idx}_"
                result.update({
                    f"{prefix}{col}": row[col]
                    for col in eigen_table.columns
                    if col != 'symbol'
                })
            X_bable.append(result)
        print(X_bable)
        self.X_bable = pd.DataFrame(X_bable)

        if normalizer == "Zscore":
            from sklearn.preprocessing import StandardScaler

            # 提取需要标准化的列
            cols = self.X_bable.columns[1:]
            # 初始化标准化器
            scaler = StandardScaler()
            # 对指定列进行标准化并覆盖原数据
            self.X_bable[cols] = scaler.fit_transform(self.X_bable[cols])
            print(self.X_bable)
        
        elif normalizer == "mmscale":
            from sklearn.preprocessing import MinMaxScaler

            # 提取目标列
            cols = self.X_bable.columns[1:]
            # 初始化并执行归一化
            scaler = MinMaxScaler(feature_range=(0, 1))  # 默认即为[0,1]
            self.X_bable[cols] = scaler.fit_transform(self.X_bable[cols])
            print(self.X_bable)

    def upload(self, up_endmem:list):
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

    def calculate_weighted_energy(self,row):
        """
        处理逻辑：
        1. 拆分冒号分隔的元素符号
        2. 格式标准化
        3. 查询每个元素的能量值
        4. 根据权重计算加权和
        """
        elements = row.split(':')
        formatted_elements = [format_element(e) for e in elements]
        energy_dict = self.tdb_model["Atom_ref"]
        
        # 验证元素与权重数量匹配
        if len(formatted_elements) != len(self.tdb_model["Atom_weight"]):
            raise ValueError("元素数量与权重参数长度不匹配")
        
        # 计算加权和
        total = 0.0
        for elem, weight in zip(formatted_elements, self.tdb_model["Atom_weight"]):
            total += energy_dict.get(elem, 0) * weight
        return total

    def add_calced_points(self,file):
        data = []
        points = []
        ref_energy_dict = dict(zip(self.subl_energy['endmember'],self.subl_energy['Atom_ref']))
        with open(file, 'r') as f:
            for line in f:
                parts = line.strip().split(',')
                if len(parts) >= 3:
                    # 字符串格式转换（下划线→冒号）
                    original_str = parts[0].replace('_', ':')  # [3,4](@ref)
                    dft_1 = float(parts[1])
                    dft_2 = float(parts[2])
                    data.append([original_str, str(self.iter), dft_1, dft_2])
                    # # 初始化自动赋0的字典
                    # temp_dict = defaultdict(float)
                    # # 遍历键值对进行累加
                    # for key, value in zip(parts[0].split('_'), self.tdb_model["ATOM_WEIGHT"]):
                    #     temp_dict[key] += value
                    # # 转换为普通字典（可选）
                    # temp_dict = dict(temp_dict)
                    # temp_dict["endmember"] = parts[0].replace('_', ':')
                    # temp_dict["Energy"] = dft_2/self.total_atoms - ref_energy_dict[original_str]
                    # points.append(temp_dict)
        data = pd.DataFrame(data, columns=['endmember', 'in_iter', 'DFT_1', 'DFT_2'])
        points = self.get_points(data['endmember']).set_index('endmember')
        # print(data['DFT_2'].values / self.total_atoms)
        # print((data["endmember"].map(ref_energy_dict)))
        points['Energy'] = ((data['DFT_2'].values / self.total_atoms) - (data["endmember"].map(ref_energy_dict)).values)*96.485
        # print(points)
        # print(self.calc_points)
        cols = list(set(self.calc_points.columns).intersection(points.columns))
        self.calc_points = pd.concat((self.calc_points,points[cols]))
        self.calc_points = self.calc_points.fillna(0)
        # 构造前一轮的测试集
        self.y_test = points["Energy"]
        # print(self.y_test)
        # print(self.calc_points)
        df2 = data
        if self.iter != 0:
            flag = [endmember for endmember in df2['endmember'].unique() if endmember in self.X_bable['endmember'].values]
            self.X_test = self.X_bable.set_index(['endmember']).loc[flag]
            # print(X_test)
            self.X_bable.reset_index()
        # 设置索引加速匹配
        df1 = self.subl_energy
        df1 = df1.drop_duplicates(subset='endmember', keep='first')
        df2 = df2.drop_duplicates(subset='endmember', keep='last')
        # 设置索引
        df1 = df1.set_index('endmember')
        df2 = df2.set_index('endmember')
        # --- 更新数据 ---
        # 方法1：直接覆盖
        df1.update(df2)  # 更新现有行，不添加新行
        df1 = df1.reset_index()
        self.subl_energy = df1
        return df2
    
    def ML(self):
        if self.iter != 0:
            # 上一轮的X_train, MLmodel, y_train
            # 本轮的 X_test(上一轮up), y_test(新添加的)
            X_train = self.X_train
            MLmodel = self.MLmodel
            # 更新pool数据
            y_train_pred = MLmodel.predict(X_train)
            # 使用当前轮次的MLmodel，预测上一轮次的X_test(也即提交出去的东西)
            self.y_pred_test_MLmodel = self.MLmodel.predict(self.X_test)
            # 从第二轮开始验证上一轮的MLmodel
            MLmodel = self.MLmodel
            X = self.X_train
            y = self.y_train
            y_train = self.y_train
            y_pred_train_MLmodel = y_train_pred
            y_test = self.y_test
            y_pred_test_MLmodel = self.y_pred_test_MLmodel
            if self.ML_style == 'flat':
                X_col = self.X_bable.columns.values[1:]
                X_imp = pd.DataFrame(X_train,columns=X_col)
            elif self.ML_style == 'stack':
                X_col = self.eigen_table
                X_imp = MLmodel.get_X_imp(X_train)
            post.assess(self.record_path,MLmodel,X_imp,X,X_train,X_col,y,y_train,y_pred_train_MLmodel,y_test,y_pred_test_MLmodel)
            post.pred_calc_fig(pkl_phase_path=self.pkl_phase_path, iter=self.iter)
        # print(self.pool_pred)
        if self.ML_style == 'flat':
            MLmodel, X_train, y_train = self.ML_flat()
        elif self.ML_style == 'stack':
            MLmodel, X_train, y_train = self.ML_stack()
        self.MLmodel = MLmodel
        # 更新上一轮的内容
        self.X_train = X_train
        self.y_train = y_train
        # self.old_MLmodel = self.MLmodel
        self.y_pred = MLmodel.predict(self.X_bable.iloc[:,1:].values)
        self.pool_pred = pd.DataFrame(zip(self.X_bable["endmember"].values, self.y_pred),columns=['endmember','y_pred_kJ_mol'])
        return MLmodel
    
    def ML_flat(self):
        y_train = self.subl_energy[self.subl_energy['in_iter'].notna()]
        print(y_train)
        common_sites = [endmember for endmember in y_train['endmember'].unique() if endmember in self.X_bable['endmember'].values]
        X_train = self.X_bable.set_index(["endmember"]).loc[common_sites]
        self.X_bable.reset_index()
        print(X_train)
        print(self.X_bable)
        X_train = X_train.values
        print(X_train)
        y_train = ((y_train['DFT_2']/self.total_atoms - y_train['Atom_ref'])*96.485).values
        print(X_train,y_train)
        # MLmodel = GradientBoostingRegressor()
        MLmodel = self._initialize_ml_model()
        MLmodel.fit(X_train, y_train)
        return MLmodel, X_train, y_train


    def ML_stack(self):
        y_train = self.subl_energy[self.subl_energy['in_iter'].notna()]
        print(y_train)
        common_sites = [endmember for endmember in y_train['endmember'].unique() if endmember in self.X_bable['endmember'].values]
        X_train = self.X_bable.set_index(["endmember"]).loc[common_sites]
        y_train = ((y_train['DFT_2']/self.total_atoms - y_train['Atom_ref'])*96.485).values
        print(X_train,y_train)
        print("im in 497")
        MLmodel = Stack_ML_model(self.eigen_table,X_train.columns)
        MLmodel.set_model(self.ML_model_type,self.ML_hyper_parameters)
        MLmodel.fit(X_train, y_train)
        return MLmodel, X_train, y_train

    def get_points(self,endmember):
        points = []
        for endmem in endmember:
            # 初始化自动赋0的字典
            temp_dict = defaultdict(float)
            # 遍历键值对进行累加
            for key, value in zip(endmem.split(':'), self.tdb_model["Atom_weight"]*100):
                temp_dict[key] += value
            # 转换为普通字典（可选）
            temp_dict = dict(temp_dict)
            temp_dict["endmember"] = endmem
            temp_dict["Energy"] = 0
            points.append(temp_dict)
        temp_col = ["endmember"] + self.ref_points.columns.values.tolist()
        points = pd.DataFrame(points,columns=temp_col)
        points = points.fillna(0)
        return points
    
    def points_modify(self,points:pd.DataFrame):
        po = points
        result = po[po.eq(100.0).any(axis=1)]  # 任意列包含 100.0
        columns = po.columns[:-1]  # 按列名顺'numpy.ndarray' object has no attribute 'eq'序选择
        mask = (po[columns] == 0.0).all(axis=1)
        ref_po = pd.concat((result,po[mask]))
        print(ref_po)
        # 生成新的索引列表
        new_index = []
        for _, row in ref_po.iterrows():
            found = None
            for col in range(len(ref_po.columns)-1):
                if row[col] == 100.0:
                    found = col
                    break
            new_index.append(found + 1 if found is not None else 0)
        ref_po = ref_po.set_index(pd.Index(new_index))
        ref_po = (ref_po.sort_index()).iloc[:,-1].values
        po_new = [0]*len(po)
        for i in range(1,len(ref_po)):
            po_new += (((po.iloc[:,i-1]).values)/100)*(ref_po[i])
        temp = po.iloc[:, :-1]
        row_sums = temp.sum(axis=1)
        po_new += (1-(row_sums/100))*ref_po[0]
        po_new = po.iloc[:,-1]-po_new
        po.iloc[:,-1] = po_new.values
        po.to_csv(self.record_path+"/points_before0.csv")
        # mask = (po.iloc[:,-1] <=1e-5)
        # po = po[mask]
        # po.to_csv("test_before1.csv")
        return po

    def convex_analy(self):
        points_df = self.all_points
        self.calc_points.to_csv(self.record_path+"/calced_points.csv")
        if self.calc_points.index.has_duplicates:
            self.calc_points = self.calc_points.reset_index(drop=True)
        temp_pool_pred = self.pool_pred.rename(columns={'y_pred_kJ_mol': 'Energy'})
        temp_pool_pred = temp_pool_pred.set_index('endmember')
        points_df.update(temp_pool_pred)
        points_df.update(self.calc_points)
        print(552)
        pd.concat((points_df,self.ref_points))
        print(553)
        all_combinations = []
        import itertools
        for k in range(points_df.shape[1]-1):
            all_combinations.extend(itertools.combinations(range(7), k))
        points = points_df.values
        points[:,0:-1] = points[:,0:-1]*100
        po = pd.DataFrame(points)
        po.to_csv(self.record_path+"/all_convex_dimention_points_before_modify.csv")
        print(points)
        points = self.points_modify(po)
        points.to_csv(self.record_path+"/all_convex_dimention_points.csv")
        points = points.values
        hull = ConvexHull(points, qhull_options="Qx Qc",incremental=True)
        all_inside = True
        for p in points:
            if p not in hull.points[hull.vertices]:
                all_inside = False
                raise ValueError
        print("所有点是否在凸包顶点或内部：", all_inside)
        # self.hull = hull
        normals, offsets, norms = Hull.generate_lower_hull_hyperplanes(hull, points)
        distances = Hull.batch_min_distance(points, normals, offsets)
        self.pt_to_hull = pd.DataFrame(zip(points_df.index.values, distances),columns=['endmember','above_hull'])
        self.pt_to_hull.to_csv(self.record_path+"/test_above_hull.csv")
        print(self.pt_to_hull)
        return 0
    
    def generate_DFT_POSCAR(self):
        print(self.quest)
        print(self.pt_to_hull)
        print(self.subl_energy)
        # 步骤1：筛选in_iter为NaN的行
        subl_filtered = self.subl_energy[self.subl_energy['in_iter'].isna()]

        # 步骤2：通过endmember列合并两个DataFrame
        self.upload_ref = self.pt_to_hull.merge(
            subl_filtered,
            on='endmember',
            how='inner'  # 保留两边都存在的endmember
        )

        # 步骤3：按条件选择样本
        # 按稳定性排序
        sorted_ref = self.upload_ref.sort_values('above_hull')

        q_near = self.quest['near_hall']
        q_above = self.quest['unstable']
        q_rand = self.quest['random']

        # 选择最稳定的q_near个（凸包上方距离最小）
        near_hull = sorted_ref.nsmallest(q_near, 'above_hull')

        # 选择最不稳定的q_above个（凸包上方距离最大）
        unstable = sorted_ref.nlargest(q_above, 'above_hull')

        # 随机选择q_rand个（排除已选部分）
        remaining = sorted_ref.drop(near_hull.index.union(unstable.index))
        random_sample = remaining.sample(
            n=min(q_rand, len(remaining)),  # 防溢出处理
            random_state=42  # 固定随机种子保证可重复性
        )

        # 步骤4：合并结果
        self.upload_ref = pd.concat([
            near_hull,
            unstable,
            random_sample
        ]).reset_index(drop=True)

        # 添加选择类型标记（可选）
        self.upload_ref['selection_type'] = ['NEAR_HULL']*q_near + ['UNSTABLE']*q_above + ['RANDOM']*q_rand
        print(self.upload_ref)
        os.makedirs(f'{self.record_path}/upload_summary/',exist_ok=True)
        self.upload_ref.to_csv(f'{self.record_path}/upload_summary/upload_summary_{self.iter}.csv')
        print(list(self.upload_ref['endmember']))
        self.upload(list(self.upload_ref['endmember']))
        return 0

    def save(self, filename):
        with open(filename, 'wb') as f:
            pickle.dump(self.__dict__, f)  # 序列化全部属性[1](@ref)

    @classmethod
    def load(cls, filename):
        instance = cls.__new__(cls)  # 创建空实例
        with open(filename, 'rb') as f:
            instance.__dict__ = pickle.load(f)  # 反序列化[1](@ref)
        return instance



if __name__=='__main__':
    import src.POSCAR_generate
    comp_list = ["CO","CU","FE","NI","TA","TI","W"]
    model = [comp_list,comp_list,comp_list]
    print(model)
    re = tuple([chr(i + 65) for i in range(26)])
    stru = src.POSCAR_generate.replace_wyckoff("test/test_data/Ce3Al11.cif", replacement_sequence=tuple(re), output_file='POSCAR')
    C14_phase = Phase(iter=0,name='C14',structure = Structure.from_file("./test/test_data/Ce3Al11.cif"), tdb_model={'each_subl_comp':model})

    iter=0
    # 测试存
    C14_phase.save('model_0.pd')
    # 测试取
    C14_phase=Phase.load('model_0.pd')
    print(C14_phase.name)

    iter=1
    C14_phase.iter += 1
    C14_phase.add_calced_points(file="test/iter.000001/calc.txt")
    # 测试存
    C14_phase.save(f'model_{iter}.pd')
    # 测试取
    C14_phase=Phase.load(f'model_{iter}.pd')
    print(C14_phase.name)