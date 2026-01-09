
import itertools
from collections import defaultdict

def partition_balls(m: int, n: int) -> list:
    """
    将 m 个小球分成不重复且不为空的 n 组的所有可能分法。

    参数:
        m (int): 小球的数量。
        n (int): 组的数量。

    返回:
        list: 包含所有分组方式的列表。
    """
    result = []
    
    def backtrack(index: int, current_groups: list) -> None:
        """
        回溯函数，用于生成所有可能的分组方式。

        参数:
            index (int): 当前处理的小球索引。
            current_groups (list): 当前的分组情况。
        """
        if index == m:
            if len(current_groups) == n:
                # 将当前分组加入结果，注意深拷贝避免引用问题
                result.append([group.copy() for group in current_groups])
            return
        
        # 将当前小球分配到已有的组中
        for i in range(len(current_groups)):
            current_groups[i].append(index + 1)  # 小球编号从1开始
            backtrack(index + 1, current_groups)
            current_groups[i].pop()
        
        # 创建新的组，如果当前组数小于n
        if len(current_groups) < n:
            new_group = [index + 1]
            current_groups.append(new_group)
            backtrack(index + 1, current_groups)
            current_groups.pop()
    
    backtrack(0, [])
    return result

def restore_sequence(groups: list, group_names: list) -> list:
    """
    将分组信息恢复为序列格式。

    参数:
        groups (list): 分组信息。
        group_names (list): 组名称列表。

    返回:
        list: 恢复后的序列。
    """
    max_element = max(max(sublist) for sublist in groups)
    result = [''] * max_element
    for i in range(len(groups)):
        current_group = groups[i]
        group_name = group_names[i]
        for pos in current_group:
            # 确保索引是从0还是1开始
            if pos > len(result):
                raise ValueError("Invalid position in group")
            result[pos-1] = group_name  # 假设输入是1-based索引
    return result


def model_list_generator(m: int, name_list: list = None) -> list:
    """
    生成模型列表。

    Args:
    参数:
        m (_int_): _the wyckoff site numbers_
        name_list (_list_) : the namelist to generate the model
        m (int): 亚点阵数目。
        name_list (list): 模型名称列表（默认为 ['A', 'B', 'C', 'D', 'E', 'F']）。

    Returns:
    返回:
        list: 包含模型信息的列表。
        _list_: _[[1, 'A:A:A:A:A'], [2, 'A:A:A:A:B']], the number is the number of new model's sublattice, then it has A B C to generate FE:CO:FE:CO and so on 
    """  
    if name_list is None:
        name_list = ['A', 'B', 'C', 'D', 'E', 'F']
    # 示例：将4个小球分成2组
    model_list = []
    for i in range(2,m):
        n = i
        print(f"{m}种{n}组，所有分法如下：")
        # group = partition_balls(m, n)
        # print(group)
        for groups in partition_balls(m, n):
            print(groups)
            group_names = name_list[:n]
            # 取名字列表的前n列
            # print(restore_sequence(groups, group_names))  # 输出应该是 ['A', 'B', 'A', 'C']
            model_list.append([n,':'.join(restore_sequence(groups, group_names))])
    print(model_list)
    return model_list


def letters_to_int(s):
    """将字母字符串（如AA、AB）转换为对应的数字（如27、28）"""
    result = 0
    for char in s:
        result = result * 26 + (ord(char) - ord('A') + 1)  # 关键逻辑：权重累加
    return result-1

def get_model_site_elements(model,elements):
    '''
    将原始形状的 site_elements 转化为 model 对应的 site_elements 形式。
    不同点阵之间的元素会取并集而非交集。
    如果最初的 site_elements 不完备的话可能会产生新的点
    '''
    temp = model[1].split(':')
    if len(temp) != len(elements):
        if len(set(temp)) == len(elements):
            Warning(f'please check that site_elements list is one-o-one to the model in your mind\nnow we have {model} in ',elements)
            return elements
        else:
            raise ValueError('elements should be a 2D list with N*m, where N is equal to the sites number of model')
    for i in range(len(temp)):
        temp[i] = letters_to_int(temp[i])

    # 统计每个数字的出现次数
    num_frequency = defaultdict(int)
    for num in temp:
        num_frequency[num] += 1

    # 记录需要合并的数字（出现次数≥2）
    merge_numbers = {num for num, freq in num_frequency.items() if freq >= 2}

    # 记录每个数字第一次出现的索引
    first_occurrence = {}
    for idx, num in enumerate(temp):
        if num in merge_numbers and num not in first_occurrence:
            first_occurrence[num] = idx  # 仅记录首次出现的索引

    # 构建结果列表：保留首次出现的合并数字子列表（取并集），其余合并数字位置删除，非合并数字保留原样
    elements_new = []
    for idx, num in enumerate(temp):
        if num in merge_numbers:
            if idx == first_occurrence[num]:  # 仅处理首次出现的位置
                # 收集所有相同数字的子列表元素，取并集（去重）
                merged_elements = list(set().union(*[elements[i] for i, n in enumerate(temp) if n == num]))
                elements_new.append(merged_elements)
        else:
            elements_new.append(elements[idx].copy())  # 非合并数字保留原样

    # 更新elements为合并后的结果
    return elements_new


def replace_groups(model: list, site_elements: list) -> list:
    """
    替换组中的元素。

    参数:
        mdoel (list): 包含组信息和名称的列表。[4,"A:B:C:D:B","1:1:1:1:1"]
        site_elements (list): 元素列表。[['H','He','Li','Be','B'],['Li','Be'],['Li','Be'],['Li','Be']]

    返回:
        list: 替换后的字符串列表。
    """
    temp = model[1].split(':')
    for i in range(len(temp)):
        temp[i] = letters_to_int(temp[i])

    # 生成所有组合
    combinations = list(itertools.product(*site_elements))
    # 按模板填充组合
    result = []
    for combo in combinations:
        new_list = []
        for num in temp:  # 遍历数字序列中的每个数字
            # 检查数字是否为有效索引（非负且小于子列表长度）
            if isinstance(num, int) and 0 <= num < len(combo):
                new_list.append(combo[num])  # 添加对应索引的元素
            else:
                new_list.append(None)  # 若索引无效，用None填充（可根据需求调整）
        new_list = ':'.join(new_list)
        result.append(new_list)  # 将当前组合生成的新列表添加到结果中
    return result

def merge_lists_optimized(del_elements, a):
    """
    优化版：高效处理长三维列表，与二维列表a按位置拼接
    
    特点：
    1. 使用列表推导式提升性能（比显式for循环更快）
    2. 处理子列表长度与a不匹配的情况（避免索引越界）
    3. 减少中间变量，降低内存占用
    """
    # 提前获取a的长度，避免重复计算
    a_len = len(a)
    # 外层列表推导式：遍历每个二维子列表
    return [
        # 内层列表推导式：拼接对应位置的子列表
        [
            # 若子列表索引i在a的范围内，则拼接；否则保持原列表
            sub_list + a[i] if i < a_len else sub_list
            for i, sub_list in enumerate(sub_2d)
        ]
        for sub_2d in del_elements
    ]

def remove_elements(site_elements, delete_count):
    """
    从二维列表中删除指定数量的元素，返回所有可能的删除结果（三维列表）
    :param site_elements: {"analys":[], "need_del":[], "fix":[]}
    :param delete_count: 要删除的元素总数（需满足：每个子列表至少保留1个元素）
    :return: 三维列表（所有符合条件的删除结果）
    """
    del_elements = site_elements['analys']
    # 检查输入合法性
    if any(len(sublist) < 1 for sublist in del_elements):
        raise ValueError("原始二维列表中存在空子列表，无法保证删除后子列表非空")
    if delete_count < 0:
        raise ValueError("删除数量不能为负数")
    
    total_elements = sum(len(row) for row in del_elements)
    min_remaining = len(del_elements)  # 每个子列表至少保留1个元素
    if total_elements - min_remaining < delete_count:
        raise ValueError("删除数量过多，无法保证每个子列表至少保留1个元素")
    if delete_count > total_elements:
        raise ValueError("删除数量超过了总元素数量")
    
    # 为每个子列表计算可能的删除数量范围
    possible_deletions = []
    for sublist in del_elements:
        max_delete = len(sublist) - 1  # 最多删除 len-1 个，保留1个
        possible_deletions.append(range(0, max_delete + 1))
    
    # 递归函数：寻找所有符合条件的删除组合
    def find_valid_deletions(index, remaining):
        if index == len(del_elements):
            return [[]] if remaining == 0 else []
        
        results = []
        # 当前子列表可能的删除数量
        for del_count in possible_deletions[index]:
            if del_count > remaining:
                continue  # 剩余删除数量不足，跳过
            
            # 生成当前子列表删除del_count个元素后的所有可能结果
            current_sublist = del_elements[index]
            if del_count == 0:
                # 不删除元素，只有一种可能
                current_options = [current_sublist.copy()]
            else:
                # 生成所有删除del_count个元素的可能结果
                indices = itertools.combinations(range(len(current_sublist)), del_count)
                current_options = []
                for indices_tuple in indices:
                    new_sublist = current_sublist.copy()
                    # 从大到小删除，避免索引错位
                    for idx in sorted(indices_tuple, reverse=True):
                        del new_sublist[idx]
                    current_options.append(new_sublist)
            
            # 递归处理剩余子列表
            for option in current_options:
                for rest in find_valid_deletions(index + 1, remaining - del_count):
                    results.append([option] + rest)
        
        return results
    
    # 执行递归计算
    results = find_valid_deletions(0, delete_count)
    
    # 去重
    unique_results = []
    seen = set()
    for result in results:
        tuple_result = tuple(tuple(sublist) for sublist in result)
        if tuple_result not in seen:
            seen.add(tuple_result)
            unique_results.append(result)
    
    # 排序
    unique_results.sort(key=lambda x: [tuple(sublist) for sublist in x])
    unique_results = merge_lists_optimized(unique_results, site_elements['fix'])
    
    return unique_results

if __name__=='__main__':
    # # test replace_groups
    # res = replace_groups([5,"A:B:C:D:B:E","1:1:1:1:1:1"],[['H','He','Li','Be','B'],['Li','Be','C'],['Li','Be'],['Li','Be'],['Li','Be','N'],['Li','Be','B']],)
    # res = replace_groups([5,"A:B:C:D:B:E","1:1:1:1:1:1"],[['H'],['He'],['Li'],['Be'],['B'],['C']])
    # res = replace_groups([3,"A:B:C:A:B:B","1:1:1:1:1:1"],[['H','He','Li','Be','B'],
    #                                                       ['Li','Be','C'],
    #                                                       ['Li','Be'],
    #                                                       ['Li','Be','O'],
    #                                                       ['Li','Be','N'],
    #                                                       ['Li','Be','B']],)
    # # test remove_elements
    # res = remove_elements([['H','He','Li','Be','B','O'],['Li','Be','C','N','B'],['Li','Be'],], 3)
    # res = remove_elements([['H','He','O'],['C','N','B'],['Li','Be'],], 1)
    # res = remove_elements([['H','He','O'],['C','N','B'],['Li','Be'],], 5)
    # res = remove_elements([['TA', 'CO', 'FE', 'TI', 'NI', 'CU', 'W'],
    #                        ['CO', 'CU', 'FE', 'NI', 'TA', 'TI', 'W'], 
    #                        ['CO', 'CU', 'FE', 'NI', 'TA', 'TI', 'W'], 
    #                        ['CO', 'CU', 'FE', 'NI', 'TA', 'TI', 'W']], 2)
    # res = remove_elements([['TA', 'CO', 'FE', 'TI', 'NI', 'CU', 'W'],
    #                        ['CO', 'CU', 'FE', 'NI', 'TA', 'TI', 'W'], 
    #                        ['CO', 'CU', 'FE', 'NI', 'TA', 'TI', 'W'], 
    #                        ['CO', 'CU', 'FE', 'NI', 'TA', 'TI', 'W'],
    #                        ['CO', 'CU', 'FE', 'NI', 'TA', 'TI', 'W'],
    #                        ['CO', 'CU', 'FE', 'NI', 'TA', 'TI', 'W'],], 5)
    site_elements = {"analys":[['CO', 'FE', 'NI', 'TA', 'TI', 'W'],# 6
                               ['TI', 'FE', 'NI', 'CU', 'CO', 'TA', 'W'], #7
                               ['CO', 'CU', 'NI', 'TA', 'TI', 'W'],# 6
                               ['CO', 'FE', 'NI', 'TA', 'TI', 'W']],#6
                    "need_del":[['CU'], [], [], ['CU']],
                    "fix":[[], [], ['FE'], []]}
    res = remove_elements(site_elements=site_elements, delete_count=2)
    for i in res:
        print(i)
    # print(res)
    print(len(res))