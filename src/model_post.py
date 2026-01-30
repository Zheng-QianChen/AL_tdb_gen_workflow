import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scienceplots
from matplotlib.colors import LinearSegmentedColormap
from pathlib import Path
import matplotlib.patches as mpatches

def subl_model_summary_plot(csv_file_path:Path=Path("CU4TI_model_score.csv"),save_fig_file:Path=Path("./subl_summary.png")):
    # 数据预处理
    df = pd.read_csv(csv_file_path, index_col=0)
    bins_cols = [col for col in df.columns if '(' in col and ']' in col]  # 提取所有区间列
    df[bins_cols] = df[bins_cols].fillna(0)  # 填充NaN为0

    # 提取模型前缀并排序
    df['prefix'] = df['model'].apply(lambda x: x.split('_')[0])
    df = df.sort_values(by='RMSE').reset_index(drop=True)

    # 获取所有唯一前缀并生成对应的颜色映射
    unique_prefixes = sorted(df['prefix'].unique())
    prefix_cmaps = {}

    # 定义基础颜色用于生成不同色系
    base_colors = [
        ['#8ECAE6', '#023047'],   # 蓝调色系
        ['#FFB703', '#8B4513'],   # 橙调色系
        ['#80ED99', '#2D6A4F'],   # 绿调色系
        ['#E0C3FC', '#8E2DE2'],   # 紫调色系
        ['#FFCAD4', '#D88373'],   # 粉调色系
        ['#C7E9C0', '#31A9B8']    # 青调色系
    ]

    # 为每个唯一前缀创建颜色映射
    for i, prefix in enumerate(unique_prefixes):
        # 循环使用基础颜色组合
        color_pair = base_colors[i % len(base_colors)]
        prefix_cmaps[prefix] = LinearSegmentedColormap.from_list(
            f'prefix{prefix}', color_pair
        )

    # 创建画布和双坐标轴
    fig, ax1 = plt.subplots(figsize=(10, 6), dpi=300)
    ax2 = ax1.twinx()  # 创建次Y轴用于RMSE

    # 绘制堆叠柱状图
    bottom = np.zeros(len(df))
    for i, bin_col in enumerate(bins_cols):
        colors_list = []
        for idx in range(len(df)):
            prefix = df['prefix'].iloc[idx]
            cmap = prefix_cmaps.get(prefix, plt.cm.viridis)
            colors_list.append(cmap(i / len(bins_cols)))
        
        ax1.bar(
            range(len(df)), 
            df[bin_col], 
            bottom=bottom,
            color=colors_list,
            edgecolor='white',
            linewidth=0.5
        )
        bottom += df[bin_col].values

    # 添加RMSE折线图
    rmse_line = ax2.plot(
        df.index, 
        df['RMSE'], 
        'ro--', 
        markersize=6, 
        linewidth=2,
        label='RMSE'
    )

    # 图表基本设置
    ax1.set_xlabel('Model Summary', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Outerpoints Count', fontsize=12, fontweight='bold')
    ax2.set_ylabel('RMSE Value', fontsize=12, fontweight='bold', color='red')
    ax1.set_title('Error Distribution Segments with RMSE Comparison', fontsize=14, pad=20)

    # 坐标轴刻度调整
    ax1.set_xticks(df.index)
    ax1.set_xticklabels(df['model'].str.replace('.csv', ''), rotation=90, ha='right')
    ax2.tick_params(axis='y', labelcolor='red')

    # 添加图例
    ax2.legend(loc='upper right', fontsize=10, bbox_to_anchor=(0.80, 1))

    # 添加数据标签（在柱状图顶部显示总频数）
    for i, total in enumerate(bottom):
        ax1.text(i, total+50, f"{int(total)}", ha='center', va='bottom', fontsize=9)

    # 处理区间标签 - 提取最小、最大和中间的区间
    if bins_cols:
        # 对区间进行排序
        def parse_bin(bin_str):
            # 从区间字符串中提取数值
            start = float(bin_str.strip('()[]').split(',')[0])
            end = float(bin_str.strip('()[]').split(',')[1])
            return (start + end) / 2  # 返回区间中点
        
        # 按区间中点排序
        sorted_bins = sorted(bins_cols, key=lambda x: parse_bin(x))
        bin_count = len(sorted_bins)
        
        # 选择要显示的三个区间
        if bin_count >= 3:
            selected_bins = [
                sorted_bins[0],          # 最小区间
                sorted_bins[bin_count//2],  # 中间区间
                sorted_bins[-1]          # 最大区间
            ]
        else:
            # 如果区间少于3个，显示所有可用区间
            selected_bins = sorted_bins
            # 不足3个时用空字符串填充
            while len(selected_bins) < 3:
                selected_bins.append('')

    # 为每个前缀创建颜色条带
    for i, (prefix, cmap) in enumerate(prefix_cmaps.items()):
        # 创建一个小轴用于绘制颜色条带
        cax = fig.add_axes([0.33, 0.85 - i * 0.08, 0.13, 0.03])  # [left, bottom, width, height]
        # 绘制颜色条带
        cbar = plt.colorbar(plt.cm.ScalarMappable(cmap=cmap), cax=cax, orientation='horizontal')
        cbar.set_ticks([0.0, 0.5, 1.0])  # 中间点
        
        # 设置颜色条标签为选择的区间
        if selected_bins:
            cbar.set_ticklabels(selected_bins)
        
        cax.yaxis.set_ticks_position('left')
        cax.yaxis.set_label_position('left')
        fig.text(
            0.25,  # 左侧偏移量
            cax.get_position().y0 + cax.get_position().height / 2,  # 居中垂直位置
            f'LatticeNum={prefix}\npred_error vs color',
            fontsize=10,
            ha='center',
            va='center'
        )

    # 网格线和样式优化
    ax1.grid(axis='y', linestyle='--', alpha=0.7)
    ax1.set_axisbelow(True)
    plt.tight_layout()
    plt.savefig(save_fig_file, bbox_inches='tight', dpi=300, 
            transparent=False, facecolor='white')
    # plt.savefig(f'./static/fig/{save_fig_file.name}', bbox_inches='tight', dpi=300, 
    #         transparent=False, facecolor='white')
    # plt.show()

if __name__=='__main__':
    csvpath=Path("E:/ZQC/code/CU4TI/stack_result/tdb_file/TDBmodel_assess/model_score.csv")
    savefile=Path("./whole_2_RMSE-outerstack.png")
    subl_model_summary_plot(csvpath,savefile)