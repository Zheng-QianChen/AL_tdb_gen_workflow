#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@文件        :POSCAR_generate.py
@说明        :AL4tdb_v1.1
@时间        :2025/03/23 17:40:57 recode
@作者        :郑芊宸 gz1999zqc@163.com
@版本        :2.0
'''

import os
import pandas as pd
from pymatgen.core import Element, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
from pathlib import Path


def whole_pool_generate(
    chemical_space:list=["FE","CO"],
    sulattice_number:int=2,
):
    return 0

def replace_wyckoff(input_file:str,
                    replacement_sequence:tuple=tuple([chr(i + 65) for i in range(26)]),
                    convert_to_primatice:bool=False,
                    output_file:str="substituted.vasp"):
    """
    基于Wyckoff等效位点的元素替换工具
    
    功能说明:
    - 自动识别晶体结构的对称等效Wyckoff位点
    - 将每个等效位点组替换为指定序列中的元素符号
    - 输出替换后的VASP格式结构文件

    参数:
    :param input_file: 输入结构文件路径 (支持CIF/POSCAR等pymatgen可解析格式)
    :param replacement_sequence: 元素符号替换序列，默认使用大写字母表(A,B,C...Z)
                                (示例: ("Fe", "Co") 将交替替换Wyckoff位点)
    :param output_file: 输出文件路径，默认生成substituted.vasp

    返回:
    Structure: 替换后的pymatgen Structure对象

    工作原理:
    1. 通过空间群分析器(SpacegroupAnalyzer)识别对称等效原子位点
    2. 对每个等效位点组按顺序分配替换序列中的元素符号,
        对于下载自Material Project上带symmetry的cif文件,其等效点位顺序即cif文件中的顺序。
    3. 元素分配逻辑：第n个等效位点组使用 replacement_sequence[n % 序列长度]
    
    注意事项:
    ■ 替换序列长度不足时会循环使用元素符号
       (例如用默认26字母处理30个Wyckoff位点组时，第27组将使用A)
    ■ 输出文件元素行会保留所有替换后的元素符号
       (例如输入结构含3个Wyckoff组，替换序列为["Fe","Co"]，则元素行为Fe Co Fe)
    ■ 原子坐标顺序会保持与原结构一致，仅修改元素符号

    示例:
    >>> # 将MgO结构中的O位点替换为S，Mg位点保持不动
    >>> modified = replace_wyckoff("MgO.cif", ("Mg", "S"))
    >>> # 交替替换三个Wyckoff位点为Fe/Co
    >>> replace_wyckoff("POSCAR", ("Fe", "Co"), "FeCo.vasp")
    """
    # 读取结构并对称性分析
    structure = Structure.from_file(input_file)
    analyzer = SpacegroupAnalyzer(structure)
    symmetrized_struc = analyzer.get_symmetrized_structure()

        # 初始化Wyckoff信息统计
    wyckoff_data = []
    seen_groups = set()
    replace_pattern = []
    
    # 收集原始Wyckoff信息（替换前）
    for idx, group in enumerate(symmetrized_struc.equivalent_sites):
        # print(idx)
        # print(replacement_sequence[idx % len(replacement_sequence)])
        # 获取Wyckoff符号（需API版本>=2022.0.8）
        wyckoff_symbol = symmetrized_struc.wyckoff_symbols[idx]
        original_element = group[0].species.elements[0].symbol
        
        # 生成唯一标识符避免重复统计
        group_signature = f"{wyckoff_symbol}-{original_element}"
        wyckoff_data.append({
            # "idx":idx,
            "Wyckoff Symbol": wyckoff_symbol,
            "Original Element": original_element,
            "Sites Count": len(group),
            # "Replaced Element": replacement_sequence[idx % len(replacement_sequence)]
        })
        replace_pattern.append(replacement_sequence[idx % len(replacement_sequence)])
        seen_groups.add(group_signature)
    # print(idx)
    # print(replace_pattern)
    
    # 创建统计表格
    wyckoff_df = pd.DataFrame(wyckoff_data).sort_values(
        by=["Wyckoff Symbol", "Original Element"]
    )
    print(wyckoff_df)
    output_file = str(output_file)
    os.makedirs("/".join("/".join(output_file.split("\\")).split("/")[:-1]), exist_ok=True)
    wyckoff_df.to_csv(f'{output_file}_wyckoff_summary.csv')
    
    # 创建新结构副本
    new_structure = structure.copy()
    
    for idx, group in enumerate(symmetrized_struc.equivalent_sites):
        element = replacement_sequence[idx % len(replacement_sequence)]
        
        # 替换当前组所有原子
        for site in group:
            site_index = new_structure.index(site)
            new_structure[site_index] = element
    os.makedirs("/".join("/".join(output_file.split("\\")).split("/")[:-1]), exist_ok=True)
    new_structure.to(filename=f'{output_file}_sub.cif', fmt="cif")
    
    # 保存替换后的结构
    if convert_to_primatice:
        new_structure = new_structure.get_primitive_structure()  # 直接获取原胞[6](@ref)
    os.makedirs("/".join("/".join(output_file.split("\\")).split("/")[:-1]), exist_ok=True)
    new_structure.to(filename=output_file, fmt="poscar")
    print(f"替换完成，结果已保存至 {output_file}")
    return new_structure,replace_pattern

def POSCAR_generate(in_poscar:Structure,
                    replace_map:dict,
                    out_poscar_path:str="POSCAR_NEW"):
    """
    生成替换元素后的VASP格式POSCAR文件
    
    功能说明:
    - 根据元素替换规则修改晶体结构
    - 自动合并同类元素并排序原子（按元素符号字母序）
    - 输出符合VASP格式要求的POSCAR文件
    
    参数:
    :param in_poscar: pymatgen Structure对象，原始晶体结构
    :param replace_map: 元素替换映射字典，格式 {旧元素: 新元素}
                       示例: {"Li": "Na", "Fe": "Co"} 表示将Li替换为Na，Fe替换为Co
    :param out_poscar_path: 输出文件路径，默认生成POSCAR_NEW
    
    返回:
    int: 固定返回0表示执行完成(不表示成功与否，需结合输出文件验证)
    
    注意事项:
    1. 替换后会合并同类元素，如原始结构含2个Fe和3个Fe，替换后将合并为5个Fe
    2. 原子排序规则：先按元素符号字母序排列，同类元素按坐标位置排序
    3. 若替换元素在原始结构中不存在，该映射项将被忽略
    4. 输出文件元素行自动去除重复，如替换产生[Fe, Co, Fe]将被合并为[Fe, Co]
    
    示例:
    >>> struct = Structure.from_file("POSCAR")
    >>> POSCAR_generate(struct, {"Li": "Na", "O": "S"}, "POSCAR_modified")
    """
    # 执行元素替换（自动合并重复元素）
    # print(in_poscar)
    temp = in_poscar.copy()
    temp.replace_species(replace_map)
    temp.sort()
    # 保存新文件（符合 VASP 元素唯一性要求）
    os.makedirs(os.path.dirname(out_poscar_path), exist_ok=True)
    temp.to(filename=out_poscar_path, fmt="POSCAR")
    return temp


if __name__=='__main__':
    table_elements = [Element.from_Z(i).symbol for i in range(1, 119)]
    # 示例调用：
    re = [chr(i + 65) for i in range(26)]
    re = tuple(re)
    print(re)
    # re = tuple(["CO","CU","FE","NI","TA","TI","W"])
    # print(re)
    replace_wyckoff("uploads/Fe7W6.cif", replacement_sequence=tuple(re), output_file='POSCAR')
    element_map = {
    re[0]: "Fe",  # 将 A 替换为 Fe
    re[1]: "Fe",  # 将 B 替换为 Fe
    re[2]: "Cu",  # 将 C 替换为 Cu
    re[3]: "Fe",  # 将 H 替换为 Fe (需与 A 合并）
    re[4]: "Fe",  # 将 E 替换为 Fe
    re[5]: "Ta"   # 将 F 替换为 Ta
    }
    # 读取 POSCAR 文件
    structure = Structure.from_file("POSCAR")
    POSCAR_generate(in_poscar=structure, replace_map=element_map, out_poscar_path='NEW_POSCAR')