
from ast import literal_eval
import numpy as np
import pandas as pd
import src.generate as generate
from scipy.spatial import ConvexHull
import src.pts_and_hull as pts_and_hull
from src.MODEL import *
from pathlib import Path



# def modify_ml_data(
#     calc_points: pd.DataFrame, 
#     elements_list: list
# ) -> pd.DataFrame:
#     """
#     将字典型化学成分数据转换为结构化列。

#     参数:
#         calc_points (pd.DataFrame): 原始数据，包含化学成分等信息。
#         elements_list (list[str]): 元素名称列表。

#     返回:
#         pd.DataFrame: 处理后的数据框，化学成分已展开为列。
#     """
#     # 处理初始数据，将字典型转化为成分列
#     calc_points['chemical_part'] = calc_points['chemical_part'].apply(literal_eval)
#     df_expanded = calc_points['chemical_part'].apply(pd.Series)
#     calc_points = pd.concat([calc_points.drop(columns=['chemical_part']), df_expanded], axis=1)
#     calc_points[elements_list] = calc_points[elements_list].fillna(0)
#     return calc_points

def modify_ml_data_100(vasp_ml_data:pd.DataFrame, elements_list):
    # sourcery skip: replace-interpolation-with-fstring
    # vasp_ml_data = modify_ml_data(vasp_ml_data, elements_list)
    vasp_ml_data['index'] = vasp_ml_data.index
    col_get = ['index','endmember','from',] + elements_list + ['Energy']
    raw_points = vasp_ml_data[col_get]
    for col in elements_list:
        raw_points[col] *= 100
    # 用于封顶盖的 identity_matrix
    max_energy = (vasp_ml_data['Energy'].max() - vasp_ml_data['Energy'].min()) +1
    identity_matrix = np.eye(len(elements_list)+1)[:-1,1:]*100
    identity_matrix[:,-1] = max_energy
    print(identity_matrix)
    print(raw_points)
    return vasp_ml_data, identity_matrix, raw_points


def model_assess(
    vasp_ml_data: pd.DataFrame,
    site_elements: list,
    candidate_model: list,
    log1: str = "report.csv",
    log2: str = "log.txt",
    result_dir: str = "result/"
) -> None:
    """
    评估机器学习模型的性能。

    参数:
        vasp_ml_data (pd.DataFrame): 输入数据，包含化学成分和能量，
                其中成分列都由elements_list提供命名，并且其单位为物质的量分数，其和为固定值，但是出于凸包数值处理问题，推荐为1。
                vasp_ml_data["endmember"]列，其值类似于CO:NI:CO:NI:TI
                vasp_ml_data["Energy"]列，其值为生成能，单位任意，但推荐为kj/mol
        elements_list (list[str]): 元素名称列表。
        candidate_model (list): 模型名称列表。
        log1 (str): 评估报告文件路径。
        log2 (str): 日志文件路径。
        result_dir (str): 结果文件保存目录。

    返回:
        None
    """
    elements_list = [string for sublist in site_elements for string in sublist]
    elements_list = list(set(elements_list))
    elements_list.sort()
    vasp_ml_data, identity_matrix, raw_points = modify_ml_data_100(vasp_ml_data, elements_list)
    # wyckoff_site = len((vasp_ml_data["endmember"].iloc[0]).split(":"))
    with open(log1,"w", encoding="utf-8") as f1:
        with open(log2,"w", encoding="utf-8") as f2:

            # sourcery skip: replace-interpolation-with-fstring
            print("亚点阵数目, 亚点阵模型, 凸包包络概率,",file=f1)

            # 对每个待选模型进行处理
            for item in candidate_model:
                print(item,file=f2)
                print(site_elements)
                M, inside = model_get_hull(raw_points,identity_matrix,site_elements,item)
                print(site_elements)
                hull = M.convex_hull
                print("顶点索引:", hull.vertices,file=f2)
                # # -------------------------------------------------------------------------
                # # 对凸包外的数据点进行误差评估
                # # 获得非端际组元点
                print(f"true_ratio = {inside.mean()}",file=f2)
                print(f"{item[0]},\"{item[1]}\",{inside.mean()},",file=f1)
                M.points_outer.to_csv(Path("%s/%s_%s.csv"%(result_dir,item[0],item[1].replace(":","_"))))
                


def model_assess_with_elements(
    vasp_ml_data: pd.DataFrame,
    site_elements_list: list,
    model: list,
    log1: str = "report.csv",
    log2: str = "log.txt",
    result_dir: str = "result/",
    pt_outer_output:bool = False
) -> None:
    """
    评估机器学习模型的性能。

    参数:
        vasp_ml_data (pd.DataFrame): 输入数据，包含化学成分和能量，
                其中成分列都由elements_list提供命名，并且其单位为物质的量分数，其和为固定值，但是出于凸包数值处理问题，推荐为1。
                vasp_ml_data["endmember"]列，其值类似于CO:NI:CO:NI:TI
                vasp_ml_data["Energy"]列，其值为生成能，单位任意，但推荐为kj/mol
        elements_list (list[str]): 元素名称列表。
        model (list): 模型名称列表。
        log1 (str): 评估报告文件路径。
        log2 (str): 日志文件路径。
        result_dir (str): 结果文件保存目录。

    返回:
        None
    """
    # wyckoff_site = len((vasp_ml_data["endmember"].iloc[0]).split(":"))
    with open(log1,"w", encoding="utf-8") as f1:
        with open(log2,"w", encoding="utf-8") as f2:
            # sourcery skip: replace-interpolation-with-fstring
            print("site_number,sublattice_symplify_model,site_elements,Probably_in_hull,",file=f1)
            # 对每个待选模型进行处理
            for site_elements in site_elements_list:
                elements_list = [string for sublist in site_elements for string in sublist]
                elements_list = list(set(elements_list))
                elements_list.sort()
                wait, identity_matrix, raw_points = modify_ml_data_100(vasp_ml_data, elements_list)
                print(site_elements,file=f2)
                M, inside = model_get_hull_ele(raw_points,identity_matrix,site_elements,model)
                hull = M.convex_hull
                print("顶点索引:", hull.vertices,file=f2)
                # # -------------------------------------------------------------------------
                # # 对凸包外的数据点进行误差评估
                # # 获得非端际组元点
                sentence = []
                for i in range(len(site_elements)):
                    sentence.append(','.join(site_elements[i]))
                sentence = ':'.join(sentence)
                print(f"true_ratio = {inside.mean()}",file=f2)
                print(f"{model[0]},\"{model[1]}\",\"{sentence}\",{inside.mean()},",file=f1)
                if pt_outer_output:
                    M.points_outer.to_csv(Path("%s/%s_%s_%s.csv"%(result_dir,model[0],model[1].replace(":","_"),sentence)))

def model_get_hull(
    raw_points: pd.DataFrame,
    identity_matrix: np.ndarray,
    site_elements: list,
    model: list,
) -> tuple[Sublattice_model, np.ndarray]:
    elements_list = [string for sublist in site_elements for string in sublist]
    elements_list = list(set(elements_list))
    elements_list.sort()
    print(elements_list)
    # 对于当前的 sublattice model 有 site_elements 应该为：
    new_site_elements = generate.get_model_site_elements(model,site_elements)
    # 生成待选模型所包含的所有端机组元的名称
    model_endmembers = generate.replace_groups(model,new_site_elements)
    print(model_endmembers)
    # 根据名称输出成分点
    model_endmem_points = raw_points[raw_points['endmember'].isin(model_endmembers)] # model_endmem_points:只包含当前候选模型的所有端际组元的抽取
    print(model_endmem_points)
    # 获得成分点的数据
    points = model_endmem_points[ elements_list[1:] + ['Energy'] ].values
    print(len(model_endmem_points),points.shape)
    # TODO:This wait matrix maybe 欠考虑了
    if (len(model_endmem_points)==len(elements_list)):
        wait_matrix = np.eye(len(elements_list)+1)[:-1,1:]*100
        points = np.concatenate((wait_matrix,points),axis=0)
    points = np.concatenate((identity_matrix,points),axis=0)
    sub = Sublattice_model(model[1],model[0],elements_list,model_endmem_points,points)
    sub.update_convex_hull()
    print(points)
    # 获得凸包
    # hull = sub.convex_hull
    unique_equations = sub.uniq_equations
    print(unique_equations)
    # 检查凸包的数值精度问题，测试当前的
    inside = pts_and_hull.is_inside_convex_hull(points, unique_equations)
    outside = ~inside
    outer_points = points[np.where(outside)[0]]
    if len(outer_points) != 0:
        raise ValueError("The convex hull has numerical precision issues. Please check the input data.")
    # -------------------------------------------------------------------------
    # 对凸包外的数据点进行误差评估
    # 获得非端际组元点
    outer_points_head = raw_points[~raw_points['endmember'].isin(model_endmembers)]
    outer_points = outer_points_head[ elements_list[1:] + ['Energy'] ].values
    sub.points_outer = outer_points_head
    inside = sub.update_outer_points()
    return sub, inside


def model_get_hull_ele(
    raw_points: pd.DataFrame,
    identity_matrix: np.ndarray,
    site_elements: list,
    model: list,
) -> tuple[Sublattice_model, np.ndarray]:
    elements_list = [string for sublist in site_elements for string in sublist]
    elements_list = list(set(elements_list))
    elements_list.sort()
    print(elements_list)
    # 生成待选模型所包含的所有端机组元的名称
    model_endmembers = generate.replace_groups(model,site_elements)
    print(model_endmembers)
    # 根据名称输出成分点
    model_endmem_points = raw_points[raw_points['endmember'].isin(model_endmembers)] # model_endmem_points:只包含当前候选模型的所有端际组元的抽取
    print(model_endmem_points)
    # 获得成分点的数据
    points = model_endmem_points[ elements_list[1:] + ['Energy'] ].values
    print(len(model_endmem_points),points.shape)
    # TODO:This wait matrix maybe 欠考虑了
    if (len(model_endmem_points)==len(elements_list)):
        wait_matrix = np.eye(len(elements_list)+1)[:-1,1:]*100
        points = np.concatenate((wait_matrix,points),axis=0)
    points = np.concatenate((identity_matrix,points),axis=0)
    sub = Sublattice_model(model[1],model[0],elements_list,model_endmem_points,points)
    sub.update_convex_hull()
    print(points)
    # 获得凸包
    # hull = sub.convex_hull
    unique_equations = sub.uniq_equations
    print(unique_equations)
    # 检查凸包的数值精度问题，测试当前的
    inside = pts_and_hull.is_inside_convex_hull(points, unique_equations)
    outside = ~inside
    outer_points = points[np.where(outside)[0]]
    if len(outer_points) != 0:
        raise ValueError("The convex hull has numerical precision issues. Please check the input data.")
    # -------------------------------------------------------------------------
    # 对凸包外的数据点进行误差评估
    # 获得非端际组元点
    outer_points_head = raw_points[~raw_points['endmember'].isin(model_endmembers)]
    outer_points = outer_points_head[ elements_list[1:] + ['Energy'] ].values
    sub.points_outer = outer_points_head
    inside = sub.update_outer_points()
    sub.get_inside_pts_distance(~outside)
    return sub, inside

def model_get_hull_ele_gene_tdb(
    raw_points: pd.DataFrame,
    identity_matrix: np.ndarray,
    site_elements: list,
    model: list,
) -> tuple[Sublattice_model, np.ndarray]:
    elements_list = [string for sublist in site_elements for string in sublist]
    elements_list = list(set(elements_list))
    elements_list.sort()
    print(elements_list)
    # 生成待选模型所包含的所有端机组元的名称
    model_endmembers = generate.replace_groups(model,site_elements)
    print(model_endmembers)
    # 根据名称输出成分点
    model_endmem_points = raw_points[raw_points['endmember'].isin(model_endmembers)] # model_endmem_points:只包含当前候选模型的所有端际组元的抽取
    print(model_endmem_points)
    # 获得成分点的数据
    points = model_endmem_points[ elements_list[1:] + ['Energy'] ].values
    print(len(model_endmem_points),points.shape)
    # TODO:This wait matrix maybe 欠考虑了
    if (len(model_endmem_points)==len(elements_list)):
        wait_matrix = np.eye(len(elements_list)+1)[:-1,1:]*100
        points = np.concatenate((wait_matrix,points),axis=0)
    points = np.concatenate((identity_matrix,points),axis=0)
    sub = Sublattice_model(model[1],model[0],elements_list,model_endmem_points,points)
    sub.update_convex_hull()
    print(points)
    # 获得凸包
    # hull = sub.convex_hull
    unique_equations = sub.uniq_equations
    print(unique_equations)
    # 检查凸包的数值精度问题，测试当前的
    inside = pts_and_hull.is_inside_convex_hull(points, unique_equations)
    outside = ~inside
    outer_points = points[np.where(outside)[0]]
    if len(outer_points) != 0:
        raise ValueError("The convex hull has numerical precision issues. Please check the input data.")
    # -------------------------------------------------------------------------
    # 对凸包外的数据点进行误差评估
    # 获得非端际组元点
    sub.get_inside_pts_distance(inside_bool=inside)
    return sub, inside