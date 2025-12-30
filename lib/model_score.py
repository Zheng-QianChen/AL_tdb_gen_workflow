
import os
import pandas as pd
import numpy as np

def get_file_names(directory:str):  # sourcery skip: for-append-to-extend
    """
    获取指定文件夹下的所有文件名（包括文件和子文件夹）

    参数:
        directory (str): 文件夹路径

    返回:
        list: 文件名列表
    """
    file_names = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_file():
                    file_names.append(entry.name)
    except Exception as e:
        print(f"Error occurred: {e}")
    return file_names

def get_model_score(
    directory_path: str, 
    col_name: list, 
    log: str, 
) -> pd.DataFrame:
    """
    计算模型的分类成绩并输出到日志文件中,返回整体评价的dataframe。

    参数:
        directory_path (str): 包含模型数据的文件夹路径。
        col_name (List[str]): 期望的列名列表。
        log (str): 日志文件的路径。

    返回:
        pd.DataFrame: 包含模型分类成绩的数据框。
    """
    model_score = pd.DataFrame(columns=["model","max","min","RMSE","segment_count",])
    with open(log,"w", encoding="utf-8") as f1:
        file_names = get_file_names(directory_path)
        for file in file_names:
            print(file, file=f1)
            # 读取文件并且检查是否符合规范
            if file[-4:] != ".csv":
                continue
            candidate_model_Ediff = pd.read_csv(f"{directory_path}/{file}",index_col=0)
            print('1',list(candidate_model_Ediff.columns))
            print('2',col_name)
            if ",".join(candidate_model_Ediff.columns) != ",".join(col_name):
                continue
            # 比较能量值
            # 在当前模型下没有生成焓的成分点
            mask = candidate_model_Ediff["Energy"] >= candidate_model_Ediff["distance_between_pt_hull"]
            wait = candidate_model_Ediff[mask]
            print(wait, file=f1)

            # 取得能量的正数
            candidate_model_Ediff['distance_between_pt_hull'] = -candidate_model_Ediff['distance_between_pt_hull']
            # 最小值
            min_distance = candidate_model_Ediff['distance_between_pt_hull'].min()
            print("最小值:", min_distance, file=f1)

            # 最大值
            max_distance = candidate_model_Ediff['distance_between_pt_hull'].max()
            print("最大值:", max_distance, file=f1)

            # RMSE
            rmse = np.sqrt(((candidate_model_Ediff['distance_between_pt_hull'] - candidate_model_Ediff['distance_between_pt_hull'].mean()) ** 2).mean())
            print("RMSE:", rmse, file=f1)

            # 分段频数
            bins = np.arange(0, max_distance + 2, 2)  # 以 10 为区间长度
            candidate_model_Ediff['distance_segment'] = pd.cut(candidate_model_Ediff['distance_between_pt_hull'], bins=bins)
            segment_counts = candidate_model_Ediff['distance_segment'].value_counts()
            print("分段频数:", file=f1)
            print(segment_counts, file=f1)
            
            
            # 将分段频数转换为字典，方便填充到 DataFrame
            segment_dict = segment_counts.to_dict()
            
            # 创建当前模型的信息
            current_model = {
                "model": file,
                "max": max_distance,
                "min": min_distance,
                "RMSE": rmse,
                "segment_count": len(segment_dict),
            }
            
            # 添加分段频数
            for segment, count in segment_dict.items():
                segment_str = str(segment)
                current_model[segment_str] = count
            
            # 将当前模型的信息添加到 DataFrame
            model_score = pd.concat([model_score, pd.DataFrame([current_model])], ignore_index=True)
            print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++",file=f1)
    return model_score