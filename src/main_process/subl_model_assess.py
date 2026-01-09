import src.model_assess as mAssess
import src.model_score as mScore
from src.MODEL import *
import src.generate as generate
import src.tdb_generator as Tdbgene
import src.model_post as mPost
import pandas as pd
import numpy as np
import os, json
from pathlib import Path

class subl_assess:
    def __init__(self,
                 input_data_file:Path=Path("./"),
                 vasp_ml_data_path:Path = Path("data/CU4TI_tdb_gen.csv"),
                 record_path:Path = Path("./")):
        self.name_list = []
        with open(input_data_file, 'r', encoding='utf-8') as f:
            # data = json.load(f, object_hook=lambda d: {k.upper(): v for k, v in d.items()})
            data = json.load(f)
        self.input_data = data
        self.site_elements = []
        self.elements_list = []
        self.site_weight = []
        self.vasp_ml_data_path = vasp_ml_data_path
        self.working_path = Path(f"{record_path}/TDBmodel_assess")
        self.directory_path = Path(f"{self.working_path}/00_all_model_points_result")
        os.makedirs(self.working_path,exist_ok=True)
        os.makedirs(self.directory_path,exist_ok=True)
        self.candidate_model = []
        self.init_this()

    def init_this(self):
        # 体系包含的所有元素
        site_elements = self.input_data['tdb_model'.upper()]['comp'.upper()]
        self.site_elements = site_elements
        elements_list = [string for sublist in self.site_elements for string in sublist]
        elements_list = list(set(elements_list))
        elements_list.sort()
        self.elements_list = elements_list
        # 表示亚点阵模型的占位码(以字母表示)
        name_list_number = self.input_data['tdb_model'.upper()]['sublattice_number'.upper()]
        letters = []
        name_list = []
        for letter in range(1,name_list_number+1):
            while letter > 0:
                letter -= 1  # 调整数字范围（1-26 -> 0-25）
                remainder = letter % 26  # 当前位的字母索引
                letters.append(chr(ord('A') + remainder))  # 转换为字母
                letter = letter // 26  # 进位处理
            name_list.append(''.join(reversed(letters)))  # 逆序拼接结果
            letters = []
        self.name_list = name_list
        # site_weight 是最后生成tdb的点阵上占位的原子比例
        self.site_weight = self.input_data['tdb_model'.upper()]['occup_atoms_in_tdb'.upper()]
        # 初始化分析表格
        print(self.vasp_ml_data_path)
        self.vasp_ml_data = self.reset_vasp_ml_data()
        print(self.vasp_ml_data)


    def reset_vasp_ml_data(self):
        self.vasp_ml_data = pd.read_csv(self.vasp_ml_data_path, index_col=0)
    
    def get_model_result_raw(self, choosen:list=None):
        print('im in get_model_result_raw')
        if not choosen:
            # choosen = range(2,len(self.site_weight))
            return True
        # 生成待选模型
        print(choosen)
        candidate_model = generate.model_list_generator(m=len(self.site_weight), name_list=self.name_list)
        for i in range(len(candidate_model)-1, -1, -1):  # 反向遍历索引
            if candidate_model[i][0] not in choosen:      # 若模型标识不在choosen中
                del candidate_model[i]                     # 删除原始列表中的元素
        # 获取result的data文件
        print(candidate_model)
        print(self.vasp_ml_data_path)
        self.reset_vasp_ml_data()
        print(self.vasp_ml_data)
        mAssess.model_assess(self.vasp_ml_data, self.site_elements, candidate_model,
                             log1=f"{self.working_path}/pre_report.csv",
                             log2=f"{self.working_path}/pre_log.txt",
                             result_dir=self.directory_path)
        # 对获得的候选模型的超出凸包部分进行统计，生成报告
        col_name = ["index","endmember","from"] + self.elements_list + ["Energy","distance_between_pt_hull"]
        log = f"{self.working_path}/log_model_score.txt"
        model_score_file = Path(f"{self.working_path}/model_score.csv")
        print('im in get_model_result_report')
        model_score = mScore.get_model_score(self.directory_path, col_name, log)
        model_score_sort = model_score.sort_values(by='RMSE')

        # 2. 调整区间列顺序（使y轴标签连续）
        # 提取所有区间列的名称（排除非区间列）
        interval_cols = [col for col in model_score_sort.columns if '(' in col and ')' in col]
        # 按区间上限排序（如(0.0,2.0] < (2.0,4.0]）
        interval_cols_sorted = sorted(interval_cols, key=lambda x: float(x.strip('()').split(',')[0]))

        # 重新排列DataFrame的列：非区间列在前，区间列按排序后的顺序在后
        non_interval_cols = [col for col in model_score_sort.columns if col not in interval_cols]
        model_score_sort = model_score_sort[non_interval_cols + interval_cols_sorted]
        model_score_sort.to_csv(model_score_file)
        return True
    
    
    def get_model_result_elements(self, candidate_model:list, site_elements:dict=None, delet_ele_num_list:int=[1]):
        '''
        candidate_model = [4,'A:B:C:D:A']
        site_elements = {"analys":[], "need_del":[], "fix":[]}
        '''
        init_site_for_model = generate.get_model_site_elements(model=candidate_model, elements=self.site_elements)
        if site_elements == None:
            site_elements = {"analys":init_site_for_model, "need_del":[[]], "fix":[[]]}
        print('im in get_model_result_elements')
        print(self.vasp_ml_data_path)
        self.reset_vasp_ml_data()
        print(self.vasp_ml_data)
        site_elements_list = self.delete_some_elements_in_sites(candidate_model,delet_ele_num_list,site_elements=site_elements)
        sum_of_del_elemets = sum(len(row) for row in init_site_for_model)\
                            - sum(len(row) for row in site_elements['analys'])\
                            - sum(len(row) for row in site_elements['fix'])
        print(sum_of_del_elemets)
        os.makedirs(f"{self.working_path}/01_elements_delete_model/",exist_ok=True)
        mAssess.model_assess_with_elements(self.vasp_ml_data, site_elements_list, candidate_model,
                             log1=f"{self.working_path}/01_elements_delete_model/pre_ele_report_{sum_of_del_elemets}.csv",
                             log2=f"{self.working_path}/01_elements_delete_model/pre_ele_log_{sum_of_del_elemets}.txt",
                             result_dir=self.directory_path)
        # 对获得的候选模型的超出凸包部分进行统计，生成报告
        # col_name = ["index","endmember","from"] + self.elements_list + ["Energy","distance_between_pt_hull"]
        # log = f"{self.working_path}/log_model_score.txt"
        # model_score_file = Path(f"{self.working_path}/model_ele_score.csv")
        # print('im in get_model_result_report')
        # model_ele_score = mScore.get_model_score(self.directory_path, col_name, log)
        # model_score_sort.to_csv(model_score_file)
        return True
    
    def plot_model_result_raw(self):
        model_score_file = Path(f"{self.working_path}/model_score.csv")
        plot_file = Path(f"{self.working_path}/summary_fig.png")
        mPost.subl_model_summary_plot(csv_file_path=model_score_file,save_fig_file=plot_file)
        return {"state":True, "plot_file":plot_file}

    def output_all_tdb_file_assessed(self, candidate_model:list, site_elements:list[list[str]]=None, tor:float= 1e-10, save_path:Path=None):
        '''
        candidate_model = [[4,"A:B:A:C:D"],[4,"A:B:C:C:D"],[4,"A:B:C:A:D"],[3,"A:B:C:C:A"],[3,"A:B:A:A:C"]]
        '''
        # ==============================================================================
        # 选择较为满意的模型，进一步完善能量模型设置
        # TODO: 输入为模型的设置，基础输出：1-凸包端点 2-按照能量依次将端际组元置入凸包，考察凸包的变化，可以移动凸包的平面？可以将点置入凸包之中？ 3-如果置入后，模型的提升非常大，则调整模型端际组元的能量以包括该点。
        # 如何调整端际组元？首先要找投影点所在的平面，然后通过平面找到构成端际组元，以每次移动一半能量差值的方式，调整至将该端际组元的能量差值在2以内。 
        if save_path == None:
            save_path = self.working_path
        else:
            save_path = Path(save_path)

        # 后续还需要处理 above_hull 数据，因此这里删掉
        # 虽然这样可以简化一些操作
        # vasp_ml_data = self.vasp_ml_data[self.vasp_ml_data['above_hull'] <= tor]
        self.reset_vasp_ml_data()
        vasp_ml_data, identity_matrix, raw_points = mAssess.modify_ml_data_100(self.vasp_ml_data, self.elements_list)

        for item in candidate_model:
            if site_elements == None:
                site_elements = self.site_elements
                site_elements = generate.get_model_site_elements(item, site_elements)
                
            # M, inside = mAssess.model_get_hull(raw_points,identity_matrix,self.site_elements,item)
            M, inside = mAssess.model_get_hull_ele_gene_tdb(raw_points,identity_matrix,
                                                   site_elements=site_elements,
                                                   model=item)
            ver = M.convex_hull.vertices
            temp = identity_matrix.shape[0]
            end = M.endmembers_name.iloc[ver-identity_matrix.shape[0],:]
            print(M.convex_hull.vertices)
            new_table = self.output_all_tdbs(M, tor)
            self.output_tdb_file(model=item, new_table=new_table,
                                 site_elements=site_elements,
                                 tdb_output_path=save_path)

    def delete_some_elements_in_sites(self, model, choosen:list, site_elements:list=None):
        '''
        model = [4,"A:B:A:C:D"]
        site_elements = {"analys":[], "need_del":[], "fix":[]}
        '''
        if site_elements == None:
            site_elements = self.site_elements
            site_elements = generate.get_model_site_elements(model, site_elements)
        # max_delete_number = sum(len(row) for row in self.site_elements) - len(self.site_elements)
        elements_site_del = []
        for i in choosen:
            print(i)
            elements_site_del.extend(generate.remove_elements(site_elements, i))
        return elements_site_del

    def output_all_tdbs(self, M:Sublattice_model, tor:float):
        # ==============================================================================
        # 总而言之，先把它们输出来。
        # M, inside = mAssess.model_get_hull(raw_points,identity_matrix, site_elements, one_candidate_model)
        # ver = M.convex_hull.vertices
        # end = M.endmembers_name.iloc[ver,:]
        end = M.points_insider
        # temp_string = "_".join(one_candidate_model[1].split(":"))
        # end.to_csv(f"{self.directory_path}/{temp_string}end.csv")

        self.reset_vasp_ml_data()
        vasp_ml_data = self.vasp_ml_data
        # vasp_ml_data["index"] = vasp_ml_data.index
        # # 获取 end 表中的 index 值
        # end_indexes = end['index']

        # # 根据这些 index 值筛选 vasp_ml_data
        # new_table = vasp_ml_data[vasp_ml_data['index'].isin(end_indexes)]
        # new_table.to_csv("end_prepare_for_generate.csv")

        end_indexes = M.points_insider['endmember']
        new_table = vasp_ml_data[vasp_ml_data['endmember'].isin(end_indexes)]
        new_table['distance_between_pt_hull'] = M.points_insider['distance_between_pt_hull']
        new_table = new_table[new_table['distance_between_pt_hull'] <= tor]
        
        return new_table

    def extract_and_rejoin(self, s, indices):
        parts = s.split(":")
        selected = [parts[i] for i in indices if i < len(parts)]
        return ":".join(selected)
    
    def create_index_dict(self, list1, list2):
        # 记录列表2中每个元素第一次出现的索引
        index_map = {}
        for idx, element in enumerate(list2):
            if element not in index_map:
                index_map[element] = idx
        
        # 根据列表1中的元素生成结果字典
        result_list = [index_map.get(key, -1) for key in list1]
        return result_list

    def sum_elements(self, model, reference_list):
        # 分割字符串
        keys = model[1].split(":")
        values = list(map(int, model[2].split(":")))
        
        # 创建一个字典来存储总和
        sum_dict = {key: 0 for key in reference_list}
        
        # 遍历 keys 和 values
        for key, value in zip(keys, values):
            if key in sum_dict:
                sum_dict[key] += value
        
        # 根据 reference_list 的顺序生成结果列表
        result = [sum_dict[key] for key in reference_list]
        
        return result

    def output_tdb_file(self, model:list, new_table:pd.DataFrame, site_elements:list[list[str]], tdb_output_path:Path):
        '''
        model = [4,"A:B:C:D:B","1:1:1:1:1"]
        '''
        temp = ':'.join(map(str, self.site_weight))
        model.append(temp)
        # model.append(self.site_weight)
        # 目标字符串用于检查
        print(model)
        model_name_list = self.name_list[:model[0]]

        indices = self.create_index_dict(model_name_list,model[1].split(":"))

        result = self.sum_elements(model, model_name_list)
        print(result)

        # 应用函数到 DataFrame 的列 '0'
        new_table['sub_name'] = new_table['endmember'].apply(lambda x: self.extract_and_rejoin(x, indices))
        new_table = new_table.rename(columns={"Energy": "energy", "from":"Ref",
                                              "distance_between_pt_hull":"above_hull_new_model"})
        new_table['sub_symb'] = new_table['endmember'].apply(lambda x: '_'.join(sorted(list(set(x.split(':'))))))
        new_table['sub_num'] = new_table['endmember'].apply(lambda x: len((set(x.split(':')))))
        new_table = new_table.sort_values(by=['sub_num','sub_symb'])
        new_table['name'] = self.input_data["phase_name".upper()]
        indices = '_'.join(map(str,indices))

        os.makedirs(tdb_output_path, exist_ok=True)
        temp = str(site_elements).replace('], [','__').replace('\'','')
        temp = temp.replace('[','').replace(']','').replace(', ','_')
        temp1 = model[1].replace(':','_')
        temp2 = model[2].replace(':','_')
        tdb_output_path = tdb_output_path / Path(f"model_{model[0]}__{temp1}__{temp2}__{temp}.tdb")
        Tdbgene.tdb_gene(model, site_elements, result,tdb_output_path,new_table)

    def output_tdb_file_entire(self, model:list=None, site_elements:list=None, tdb_output_path:Path='./'):
        '''
        model = [4,"A:B:C:D:B","1:1:1:1:1"]
        '''
        if model == None:
            model = [len(self.name_list),":".join(self.name_list)]
        if site_elements == None:
            site_elements = self.site_elements
        self.reset_vasp_ml_data()
        vasp_ml_data_temp = self.vasp_ml_data
        vasp_ml_data_temp["index"] = vasp_ml_data_temp['endmember']

        # 生成 点 的列表
        end_indexes = generate.replace_groups(model=model, site_elements=site_elements)
        
        # 根据这些 index 值筛选 vasp_ml_data
        new_table = vasp_ml_data_temp[vasp_ml_data_temp['index'].isin(end_indexes)]
        # new_table.to_csv("end_prepare_for_generate.csv")

        print(type(model))
        temp = ':'.join(map(str, self.site_weight))
        model.append(temp)
        print(model)
        # 目标字符串用于检查
        model_name_list = self.name_list[:model[0]]
        indices = self.create_index_dict(model_name_list,model[1].split(":"))
        result = self.sum_elements(model, model_name_list)
        print(result)

        # 应用函数到 DataFrame 的列 'endmember'
        new_table['sub_name'] = new_table['endmember'].apply(lambda x: self.extract_and_rejoin(x, indices))
        new_table = new_table.rename(columns={"4": "energy", "5":"Ref", })
        new_table['sub_symb'] = new_table['endmember'].apply(lambda x: '_'.join(sorted(list(set(x.split(':'))))))
        new_table['name'] = self.input_data["phase_name".upper()]
        new_table['energy'] = new_table['Energy']
        new_table['Ref'] = new_table['from']
        new_table['above_hull_new_model'] = new_table['above_hull']
        # indices = '_'.join(indices)

        os.makedirs(tdb_output_path,exist_ok=True)
        temp = str(site_elements).replace('], [','__').replace('\'','')
        temp = temp.replace('[','').replace(']','').replace(', ','_')
        temp1 = model[1].replace(':','_')
        temp2 = model[2].replace(':','_')
        tdb_output_path = tdb_output_path / Path(f"model_{model[0]}__{temp1}__{temp2}__{temp}.tdb")
        Tdbgene.tdb_gene(model, site_elements, result, tdb_output_path ,new_table)