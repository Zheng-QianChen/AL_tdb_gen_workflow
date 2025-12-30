import pandas as pd
import numpy as np
from lib.class_def import Phase
import os
from pathlib import Path


def process_element(s):
    # 分割字符串并去重（网页4的split方法）
    elements = s.split(':')
    unique_elements = sorted(list(set(elements)))  # 去重后排序（网页1的集合用法）
    # 统计元素个数（网页2的len函数）
    return {
        'sys_num': len(unique_elements),
        'sys_type': sorted(unique_elements, key=lambda x: x.upper())  # 按字母顺序排序
    }

def pre_for_model_assess(phase:Phase, file_path):
    # print(phase.subl_energy)
    # print(phase.pt_to_hull)
    # print(phase.all_points)

    # 合并操作
    tdb_gen_pad = phase.pt_to_hull.merge(
        phase.all_points,
        on='endmember',
        how='inner'  # 保留两边都存在的endmember
    )
    tdb_gen_pad = tdb_gen_pad.merge(
        phase.subl_energy,
        on='endmember',
        how='inner'  # 保留两边都存在的endmember
    )

    # 结果排序（可选）
    tdb_gen_pad.sort_values(by='above_hull', inplace=True)
    print(tdb_gen_pad.head())

    # 生成新列（网页5的pandas处理技巧）
    tdb_gen_pad[['sys_num', 'sys_type']] = tdb_gen_pad['endmember'].apply(
        lambda x: pd.Series(process_element(x))
    )
    sys_spe = phase.tdb_model["sys_species".upper()]
    print(sys_spe,tdb_gen_pad.columns)
    flag = 0
    for i in range(len(sys_spe)):
        # print(sys_spe[i],tdb_gen_pad.columns)
        if sys_spe[i] not in tdb_gen_pad.columns:
            if flag == 1:
                raise ValueError("More than one species has been ignored in hull!")
            tdb_gen_pad[sys_spe[i]] = 1-(tdb_gen_pad[sys_spe[:i]+sys_spe[i+1:]].sum(axis=1))
            flag = 1
    tdb_gen_pad['from'] = np.where(tdb_gen_pad['in_iter'].notna(), 'VASP', 'ML')
    tdb_gen_pad.to_csv(f'{file_path}/{phase.name}_tdb_gen.csv')
    return tdb_gen_pad, sys_spe

def normalize_ratio(s, decimal_places=4):
    """
    将用冒号分隔的数值字符串归一化为各元素占总和比例的格式
    
    参数:
        s: 输入字符串，如"1:1:1:1:1"
        decimal_places: 保留的小数位数，默认4位
    
    返回:
        归一化后的字符串，如"0.2:0.2:0.2:0.2:0.2"
    """
    if type(s) == str:
        # 1. 按冒号分割字符串为列表
        parts = s.split(':')
        # 2. 转换为数值类型（处理可能的空字符串或非数字情况）
        try:
            numbers = [float(part) for part in parts if part.strip()]
        except ValueError:
            raise ValueError("输入字符串包含非数值内容，请确保格式正确（如'1:1:1'）")
    else:
        numbers = s
    
    
    # 3. 计算总和（处理总和为0的特殊情况）
    total = sum(numbers)
    if total == 0:
        return [f"0.0{'0'*(decimal_places-1)}" for _ in numbers]
    
    # 4. 计算每个元素占总和的比例并格式化
    normalized = [num / total for num in numbers]
    formatted_parts = [f"{num:.{decimal_places}f}" for num in normalized]
    
    # 5. 用冒号拼接回字符串
    return formatted_parts

def tdb_gene(model, site_elements, phase_atom_state, file_dir, phase_data_df, normlizesites:bool=True, file_flag='w'):
    """根据输入的热力学相数据（DataFrame）和原子状态参数，生成TDB（Thermodynamic Database）文件
    
    TDB文件是热力学计算常用的数据库格式，本函数主要生成相的Gibbs自由能参数（PARAMETER G）相关内容，
    包含子系统划分、元素标准焓引用、相能量修正项等核心热力学数据，便于后续热力学计算软件（如Thermo-Calc）调用。

    Args:
        phase_atom_state (list[int/float]): 相的亚点阵原子状态列表，通常表示每个亚点阵的原子占位数量或配比
                                           示例：[1, 1] 表示某相包含2个亚点阵，每个亚点阵各1个原子位点
        file_dir (str): 生成的TDB文件保存路径（含文件名）
                       示例：'./thermo_data/phase_tdb.tdb'
        phase_data_df (pandas.DataFrame): 相的热力学参数DataFrame，需包含以下关键字段：
                                          - 'sub_symb': 子系统标识（如'FE_NI'、'FE_W_TA' 方便后期在子系统中调优）
                                          - 'name': 相名称（如'FCC_A1, BCC_A2'，对应TDB中相的唯一标识）
                                          - 'sub_name': 亚点阵名称组合（用冒号分隔，如'FE:NI'，表示2个亚点阵分别为Fe和Ni）
                                          - 'energy': 相的能量修正值（单位：kJ/mol，需转换为J/mol写入TDB）
                                          - 'Ref': 数据引用标识（如'Ref_2023'，用于标注数据来源）
        file_flag (str, optional): 文件操作模式，默认'w'（覆盖写入）。可选值：
                                   - 'w': 覆盖已有文件（若文件存在则清空重写）
                                   - 'a': 追加写入（在已有文件末尾添加内容，不覆盖原有内容）
                                   注意：若选择'a'模式，需确保新增内容与原有TDB格式兼容，避免子系统重复定义

    Returns:
        None: 无返回值，函数执行成功后直接在指定路径生成TDB文件

    Notes:
        1. TDB格式规范：
           - 子系统块以 `$$ 子系统标识` 开头，用于归类同一类型的相参数（如所有FCC结构的相归为一个子系统）
           - 热力学参数行以 `PARAMETER G(相名, 亚点阵组合; 0) 298.15` 开头，其中：
             - "0" 表示参数类型（此处为Gibbs自由能基础参数）
             - "298.15" 表示参考温度（25℃，热力学计算常用基准温度）
           - 元素标准焓引用格式为 `n*GHSER[元素]`，n为亚点阵原子数（来自phase_atom_state），GHSER是TDB标准关键字（表示元素标准焓）
           - 能量修正项需转换为J/mol（原energy单位为kJ/mol，故乘以1000），且续行时正数需加"+"，负数自带"-"
        
        2. 数据预处理说明：
           - 函数会先重置DataFrame索引（drop=True），避免原索引不连续导致遍历异常
           - 通过 `sub_name.split(':')` 将亚点阵组合字符串拆分为列表，用于匹配phase_atom_state的亚点阵顺序
        
        3. 潜在风险：
           - 若phase_data_df缺失关键字段（如'sub_symb'、'energy'），会导致TDB内容不完整或报错，建议调用前先校验DataFrame结构
           - 若phase_atom_state的长度与sub_name拆分后的亚点阵数量不匹配，会导致元素标准焓引用错误，需确保两者维度一致
    """
    with open(file_dir,file_flag) as file:
        sites_summary_str = [','.join(inner_list) for inner_list in site_elements]
        sites_summary_str = ':'.join(sites_summary_str)
        if normlizesites:
            file.write("$ if not normalized:\n$ Phase %s %% %s %s !\n"%(phase_data_df.iloc[0,:]['name'],
                                                model[0], ' '.join(map(str,phase_atom_state))))
            phase_atom_state = normalize_ratio(phase_atom_state)
            SumSub = 1
        else:
            SumSub=sum(phase_atom_state)
        file.write("Phase %s %% %s %s !\n"%(phase_data_df.iloc[0,:]['name'],
                                            model[0], ' '.join(map(str,phase_atom_state))))
        file.write("CONSTITUENT %s %s !\n"%(phase_data_df.iloc[0,:]['name'],
                                            sites_summary_str))
        sub_sys_flag=0
        phase_data_df = phase_data_df.reset_index(drop=True)
        phase_data_df['sub_lat'] = phase_data_df['sub_name'].apply(lambda x: x.split(':'))
        for i in range(len(phase_data_df)):
            if phase_data_df.loc[i, 'sub_symb'] != sub_sys_flag:
                sub_sys_flag=phase_data_df.loc[i,'sub_symb']
                file.write(f'\n$$ {sub_sys_flag}\n')
            file.write(
                f" PARAMETER G({phase_data_df.loc[i, 'name']},{phase_data_df.loc[i, 'sub_name']};0) 298.15 "
            )
            for j in range(len(phase_atom_state)-1):
                file.write(
                    f'{str(phase_atom_state[j])}*GHSER'
                    + phase_data_df.loc[i, 'sub_lat'][j]
                    + '# +'
                )
            j += 1
            file.write(
                f'{str(phase_atom_state[j])}*GHSER'
                + phase_data_df.loc[i, 'sub_lat'][j]
                + '#'
            )
            if phase_data_df.loc[i,'energy'] > 0:
                file.write('\n   +')
            else:
                file.write('\n   ')
            file.write(str(phase_data_df.loc[i,'energy']*1000*SumSub) + '; 6000 N !')
            file.write('\n$__ref__%s__,__sub_sys__%s__,__above_hull_newM__%.8f__,__above_hull_oriM__%.8f__,\n'
                       %(phase_data_df.loc[i,'Ref'],phase_data_df.loc[i,'sub_symb'],
                         phase_data_df.loc[i,'above_hull_new_model'], phase_data_df.loc[i,'above_hull']))


def tdb_generate_from_MLmodel(pkl_path:str, iter:int=0, process:int=1, user:str='', mask:int=5, file_path:str='./'):
    os.makedirs(file_path,exist_ok=True)
    phase=Phase.load(f'{pkl_path}/model_{iter:06d}_{process}.pd')

    tdb_gen_pad, sys_spe = pre_for_model_assess(phase, file_path)

    with open(f'{file_path}/{phase.name}_{phase.iter}_raw.tdb','w') as file:
        sumn = sum(phase.tdb_model["occup_atoms_in_tdb".upper()])
        temp = [str(i/sumn) for i in phase.tdb_model["occup_atoms_in_tdb".upper()]]
        phase_summarize = ' '.join(temp)
        phase_compo_summarize = [
            ','.join(phase.tdb_model["comp".upper()][i])
            for i in range(len(phase.tdb_model["comp".upper()]))
        ]
        phase_compo_summarize = ':'.join(phase_compo_summarize)
        file.write(f'''
Phase {phase.name} % {phase.tdb_model["sublattice_number".upper()]} {phase_summarize} !
CONSTITUENT {phase.name} :{phase_compo_summarize}:!
        ''')

        # 按sys_num排序并分组处理
        # tdb_gen_pad = tdb_gen_pad.sort_values('sys_num')
        output = []
        tdb_gen_pad['sys_type'] = tdb_gen_pad['sys_type'].apply(lambda x: '_'.join(sorted(x)))
        print(tdb_gen_pad)

        # 按sys_type分组（转换为元组作为分组键）
        for (sys_num, sys_type), group in tdb_gen_pad.groupby(['sys_num','sys_type']):
            # 添加分组标题
            output.append(f"$$ {sys_type}")

            # 处理每个条目
            for _, row in group.iterrows():
                # 生成元素项
                elements = {i:row[f'{i}'] for i in sys_spe}
                # elements = {
                #     'FE': row['FE'], 'TI': row['TI'], 'CU': row['CU'],
                #     'TA': row['TA'], 'CO': row['CO'], 'W': row['W'], 'NI': row['NI']
                # }
                terms = [f"+{v:.2f}*GHSER{k}" for k, v in elements.items() if v > 0]

                # 组合参数行
                sign = '+' if row['Energy'] >=0 else ''
                param_line = (
                    f"  PARAMETER G({phase.name},{row['endmember']};0) 298.15   \n"
                    f"     {' '.join(terms)} \n     {sign}{row['Energy']*1000}; 6000 N REF:0 !\n"
                    f"$__REF__{row['from']}_{user}__,__sub_sys__{sys_type}__,__energy_above_PHASEhull__{row['above_hull']*1000}__"
                )
                if row['above_hull'] < mask:
                    output.append(param_line)

            output.append("")  # 添加空行分隔分组

        # 打印结果
        file.write('\n'.join(output))
        file.close()
    return {'file_path':Path(file_path),'file_name_tdb':f'{phase.name}_{phase.iter}_raw.tdb','file_name_csv':f'{phase.name}_tdb_gen.csv'}

if __name__=='__main__':
    iter=11
    process=1
    user = 'ZQC'
    # mask的值限制输出的参数点与凸包的距离小于该值,单位为kJ/mol
    # 一些参考：固体升高1000K其能量可以增加20kJ/mol
    mask = 5
    file_path = './'
    pkl_path = './MU/result/pkls'
    tdb_generate_from_MLmodel(pkl_path, iter, process, user, mask, file_path)