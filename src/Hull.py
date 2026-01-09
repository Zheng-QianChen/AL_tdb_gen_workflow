import numpy as np
from scipy.spatial import ConvexHull


def generate_lower_hull_hyperplanes(hull:ConvexHull, points:np.ndarray):
    """
    生成凸包下半部分所有存在至少一个顶点能量值<0的超平面参数
    
    参数说明：
    hull : scipy.spatial.ConvexHull 对象
    points : 原始点集数组，形状为 (n_points, n_dim)
    
    返回：
    (normals, offsets, norms) : 超平面参数元组
        - normals : 法向量数组，形状 (n_hyperplanes, n_dim)
        - offsets : 偏移量数组，形状 (n_hyperplanes,)
        - norms   : 法向量模长数组，形状 (n_hyperplanes,)
    """
    
    normals = []
    offsets = []
    norms = []
    points_ref = np.zeros(points.shape[1])
    points_ref[0] = 0.5
    refresh_points = []

    for face in hull.simplices:
        # 获取当前面对应的顶点坐标
        vertices = points[face]  # 形状 (n_vertices_in_face, n_dim)
        homogeneous = vertices
        rank = np.linalg.matrix_rank(homogeneous)
        if rank != points.shape[1]:
            continue

        # 条件1: 检查是否存在顶点能量值<0
        if np.any(vertices[:, -1] < 0):
            # continue
            # ----------------------------
            # 超平面方程计算
            # ----------------------------
            # 使用协方差矩阵最小特征向量
            centroid = np.mean(vertices, axis=0)
            centered = vertices - centroid
            # 检测全零维度
            zero_dims = np.where(np.all(centered == 0, axis=0))[0]
            # 计算协方差矩阵并修正
            cov_matrix = np.cov(centered, rowvar=False)
            _, eig_vectors = np.linalg.eigh(cov_matrix)
            normal = eig_vectors[:, 0].copy()  # 取最小特征值对应向量
            # 强制全零维度的系数为0
            normal[zero_dims] = 0

            # 单位化法向量
            norm = np.linalg.norm(normal)
            if norm < 1e-10:  # 防止零向量
                continue
            normal /= norm
            
            # 计算偏移量 (平面方程: normal·x + offset = 0)
            offset = -np.dot(normal, centroid)
            
            # 验证平面方程是否通过所有顶点
            residuals = np.abs(np.dot(vertices, normal) + offset)
            if not np.all(residuals < 1e-6):  # 允许浮点误差
                raise ValueError("平面方程生成失败")
            
            sign = np.dot(points_ref, normal) + offset
            if sign < 0:
                normal = -normal
                offset = -offset

            rasiduals:np.ndarray = np.dot(points, normal) + offset
            if (np.abs(np.max(rasiduals)) < 1e-3) or (np.abs(np.min(rasiduals)) < 1e-3):
                pass
            else:
                print(np.max(rasiduals), np.min(rasiduals))
                Warning("Please check the hull set: maybe it has some numerical problem")

            
            # 存储参数
            normals.append(normal)
            offsets.append(offset)
            norms.append(1.0)  # 已单位化，模长为1
    # if flag == True:
    #     temp = np.array(refresh_points)
    #     print(hull.vertices,len(hull.vertices))
    #     hull.add_points(points[temp])
    #     print(hull.vertices,len(hull.vertices))
    #     generate_lower_hull_hyperplanes(hull, hull.points)

    # 转换为NumPy数组
    return (
        np.array(normals), 
        np.array(offsets), 
        np.array(norms)
    )

def batch_min_distance(points, w:np.ndarray, b:np.ndarray):
    """
    批量计算所有点到超平面的最小距离
    :param points: 点集矩阵 (n_points, n_dim)
    :param w: 超平面法向量矩阵 (n_hyperplanes, n_dim)
    :param b: 超平面偏移量 (n_hyperplanes,)
    :param norms: 法向量模长 (n_hyperplanes,)
    :return: 最小距离数组 (n_points,)
    """
    print(w)
    print(w[:,-1])
    valid_mask = np.ones(w.shape[0], dtype=bool)
    valid_mask &= (np.abs(w[:,-1]) >= 1e-6)
    w = w[valid_mask]
    b = b[valid_mask]
    b = b.reshape((1,w.shape[0]))
    a_e = w[:,-1].reshape((1,w.shape[0]))
    distances = np.dot(points, w.T) + b
    distances = -( distances/ a_e)
    eps = 1e-2
    def is_same_sign(col):
        base_sign = np.sign(np.mean(col))
        return np.all(np.abs(col - base_sign * np.abs(col)) <= eps)
    
    sign_check = np.apply_along_axis(is_same_sign, axis=0, arr=distances)
    print(np.mean(sign_check))
    abs_distances = distances[:,sign_check]
    abs_distances = np.abs(abs_distances)
    return np.min(abs_distances, axis=1)

    # # 1. 筛选有效的超平面（排除法向量最后分量过小的平面）
    # valid_mask = np.abs(w[:, -1]) >= 1e-6
    # w_valid = w[valid_mask]
    # a_e = w_valid[:, -1]  # (n_valid,)
    
    # # 2. 分块处理点集
    # min_distances = np.empty(len(points), dtype=np.float64)  # 存储结果
    # block_size = 4000  # 根据可用内存调整块大小
    
    # for i in range(0, len(points), block_size):
    #     # 3. 获取当前块的点
    #     points_block = points[i:i+block_size]  # (block_size, n_dim)
        
    #     # 4. 计算当前块到所有有效超平面的距离
    #     # 分解为两个小矩阵运算，避免直接生成大矩阵
    #     dot_product = np.dot(points_block, w_valid.T)  # (block_size, n_valid)
        
    #     # 5. 计算最终距离
    #     scaled_distances = -dot_product / a_e  # (block_size, n_valid)
        
    #     # 6. 筛选符号相同的超平面（仅需计算当前块）
    #     eps = 1e-2
    #     sign_check = np.apply_along_axis(
    #         lambda col: np.all(np.abs(col - np.sign(np.median(col)) * np.abs(col)) <= eps),
    #         axis=0, 
    #         arr=scaled_distances
    #     )
        
    #     # 7. 处理有效距离并找到最小距离
    #     if np.any(sign_check):
    #         # 仅保留符号一致的超平面
    #         valid_distances = scaled_distances[:, sign_check]  # (block_size, n_sign_valid)
    #         abs_distances = np.abs(valid_distances)
    #         min_distances[i:i+block_size] = np.min(abs_distances, axis=1)
    #     else:
    #         # 如果没有符合条件的超平面，设置一个默认值
    #         min_distances[i:i+block_size] = np.inf
    
    # return min_distances