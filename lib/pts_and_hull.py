import numpy as np
import pandas as pd
from scipy.spatial import ConvexHull

def is_inside_convex_hull(points: np.ndarray, hull_equations: np.ndarray, tol: float = 1e-8, test_flag : bool = False) -> np.ndarray:
    """
    判断点是否位于凸包内部或边界上。

    参数:
        points (numpy.ndarray): 待检测的点，形状为 (n_points, n_dims)，其中 n_points 是点的数量，n_dims 是维度。
        hull_equations (numpy.ndarray): 凸包的面方程，形状为 (n_faces, n_dims + 1)。每个面方程表示为 [a1, a2, ..., an, b]，对应不等式 ax1 + ax2 + ... + axn + b <= 0。
        tol (float): 容差值，用于判断不等式是否满足，默认为 1e-8。
        test_flag (bool): 用于输出点与直线的关系便于调试程序

    返回:
        numpy.ndarray: 布尔数组，形状为 (n_points,)，指示每个点是否在凸包内部或边界上。
    """
    # 计算不等式值
    inequalities = points @ hull_equations[:, :-1].T + hull_equations[:, -1]
    # 计算法向量范数
    normals = hull_equations[:, :-1]
    normal_norms = np.linalg.norm(normals, axis=1)
    # 评估点与超平面的距离
    distances = inequalities / normal_norms
    # 判断点是否在凸包内部
    print(distances)

    if test_flag:
        print(distances.max())
        print(inequalities.max())

    return np.all(distances <= tol, axis=1)



def batch_distance_to_convex_hull(points: np.ndarray, equations: np.ndarray) -> np.ndarray:
    """
    计算多个点到凸包的距离。

    参数:
        points (numpy.ndarray): 输入点集，形状为 (n_points, n_dims)，其中 n_points 是点的数量，n_dims 是维度。
        equations (ConvexHull.equations,np.ndarray): 凸包的平面对象，由 scipy.spatial.ConvexHull 生成，本质是numpy.ndarray，形状为(n_equations, n_dims+1),为 n_dims 的平面方程。

    返回:
        numpy.ndarray: 每个点到凸包的最小距离，形状为 (n_points,)。
    """
    num_points = points.shape[0]
    min_differences = np.full(num_points, np.inf)
    
    for equation in equations:
        a = equation[:-1]
        b = equation[-1]
        if a[-1] == 0:
            print(equation)
            continue
        
        # 计算投影点的第n维坐标
        x_n = -(a[:-1] @ points[:, :-1].T + b) / a[-1]
        projections = np.hstack([points[:, :-1], x_n.T.reshape(-1, 1)])
        
        # 检查投影点是否在凸包内部
        # 这是因为凸包超平面方程以单纯形方式去考虑就太复杂了，采用投影方式
        # 如果投影点在凸包上,说明点沿着能量轴的投影就在该面上
        inside = is_inside_convex_hull(projections, equations, test_flag=1)
        
        # 计算差值
        differences = points[:, -1] - projections[:, -1]
        differences[~inside] = np.inf  # 不在凸包内的点的差值设为无穷大
        
        # 更新最小差值,比较差值的绝对值
        # 虽然按照我的脑测，因为在最初的数据集中去除了生成焓大于0的部分，所以应该都是负号
        # 为了计算的稳定性，在此处仍然选择绝对值比较处理
        abs_differences = np.abs(differences)
        abs_min_differences = np.abs(min_differences)
        min_differences = np.where(abs_differences < abs_min_differences, differences, min_differences)
    
    return min_differences

