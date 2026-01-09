import numpy as np
import pandas as pd
from scipy.spatial import ConvexHull
from typing import Optional
import src.pts_and_hull as pts_and_hull
import src.Hull as Hull

class Sublattice_model:
    def __init__(
        self,
        model_representation: str,
        lattice_number: int,
        elements_list: list,
        endmembers_name: list,
        model_points: np.ndarray,
        points_outer: pd.DataFrame = None,
        convex_hull: Optional[ConvexHull] = None,
    ):
        """
        初始化 Sublattice_model 类

        参数:
            model_representation (str): 模型的表示 eg."A:B:A:B:C"
            lattice_number (int): 亚点阵数量 eg.3
            elements_list (list): 元素列表 eg.['CO', 'CU', 'FE', 'NI', 'TA', 'TI', 'W']
            endmembers_name (list): 亚点阵端际组元 eg.['CO:CU:CO:CU:FE',....]
            model_points (np.ndarray): 模型点的 n 维数组，形状为 (n_points, n-elements + 1) 
            convex_hull (ConvexHull, optional): 凸包对象
            uniq_equations (np.ndarray): 凸包的平面方程，去重
            points_outer (pd.Dataframe): 凸包外的点
        """
        self.model_representation = model_representation
        self.lattice_number = lattice_number
        self.elements_list = elements_list
        self.endmembers_name = endmembers_name
        self.model_points = model_points
        self.points_outer = points_outer
        self.points_insider = None 
        self.convex_hull = convex_hull if convex_hull is not None else ConvexHull(model_points)
        self.uniq_equations = None

    def __str__(self):
        return f"Phase Name: {self.phase_name}\nModel Representation: {self.model_representation}\nConvex Hull Vertices: {self.convex_hull.vertices}"

    def update_convex_hull(self):
        """
        更新凸包对象
        """
        self.convex_hull = ConvexHull(self.model_points)
        self.uniq_equations = np.unique(self.convex_hull.equations, axis=0)

    def update_outer_points(self):
        if len(self.points_outer) == 0:
            return np.ndarray([])
        outer_points_head = self.points_outer
        outer_points = outer_points_head[ self.elements_list[1:] + ['Energy'] ].values
        # 检查所有点是否在凸包内，在凸包内的则略过
        inside = pts_and_hull.is_inside_convex_hull(outer_points, self.uniq_equations)
        outside = ~inside
        outer_points_head = outer_points_head[outside]
        outer_points = outer_points[np.where(outside)[0]]
        # 对于不在凸包内的点，需要对它的值进行另外的处理
        # 计算距离
        min_differences = pts_and_hull.batch_distance_to_convex_hull(outer_points, self.uniq_equations)
        outer_points_head["distance_between_pt_hull"] = min_differences
        self.points_outer = outer_points_head
        return inside
    
    def pts_insert(self):
        if len(self.points_outer) == 0:
            record = pd.DataFrame([],columns = ["name","outer"])
            return record
        df = self.points_outer
        print(self.points_outer)
        record = []
        name_index = df.columns.tolist().index('endmember')
        while 1:
            min_value = self.points_outer['distance_between_pt_hull'].min()
            # print(min_value)
            result = self.points_outer[self.points_outer['distance_between_pt_hull'] == min_value]
            # print(self.convex_hull.vertices)
            name = result.iloc[0,name_index]
            print(name)
            columns = self.elements_list[1:]+['Energy']
            result = result[columns].values
            # print(result)
            self.model_points = np.vstack((self.model_points,result))
            self.update_convex_hull()
            # print(self.convex_hull.vertices)
            outer_points_head = self.points_outer
            outer_points = outer_points_head[ self.elements_list[1:] + ['Energy'] ].values
            # 检查所有点是否在凸包内，在凸包内的则略过
            inside = pts_and_hull.is_inside_convex_hull(outer_points, self.uniq_equations)
            outside = ~inside
            # print(inside)
            print(f"true_ratio = {inside.mean()},outer points num = {inside.sum()}, ")
            outer_points_head = outer_points_head[outside]
            outer_points = outer_points[np.where(outside)[0]]
            # print(outer_points_head)
            self.points_outer = outer_points_head
            record.append([name,inside.sum()])
            if len(outer_points_head) == 0:
                break
        record = pd.DataFrame(record)
        record.columns = ["name","outer"]
        print(record)
        return record
    
    def get_inside_pts_distance(self, inside_bool:np.ndarray=None):
        if inside_bool is None:
            inside_bool = pts_and_hull.is_inside_convex_hull(self.model_points, self.uniq_equations)
        insider_points = self.endmembers_name[inside_bool[len(self.elements_list):]]
        insider_temp = insider_points[ self.elements_list[1:] + ['Energy'] ].values

        w = self.uniq_equations[:,:-1]
        b = self.uniq_equations[:,-1]
        distance = Hull.batch_min_distance(insider_temp, w, b)
        insider_points["distance_between_pt_hull"] = distance
        self.points_insider = insider_points
        return inside_bool