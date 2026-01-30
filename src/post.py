import ast
import copy
import os
import random
import matplotlib
matplotlib.use('Agg')  # 切换至Agg后端（需在导入plt前执行）
import matplotlib.pyplot as plt
from datetime import datetime
import sklearn

import numpy as np
import pandas as pd
from sklearn.metrics import root_mean_squared_error,r2_score, mean_absolute_error

def iter_plot(csv_path,fig_size=(12,8),dpi=300,style=False):
    data = pd.read_csv(f'{csv_path}/iter.csv')

    if style:
        # 设置全局样式，全局字体样式为罗马字体
        plt.style.use(['science','ieee','notebook'])
        plt.rcParams['font.family'] = 'serif'
        plt.rcParams['font.serif'] = ['Times New Roman'] + plt.rcParams['font.serif']

    # 创建一个包含2行3列的画布
    plt.figure(figsize=fig_size, dpi=dpi)
    # 数据生成
    x = data["training_data_amount"]
    y1 = data["RMSE(train)"]
    y2 = data["RMSE(test)"]
    # 绘制主曲线
    plt.plot(x, y1, label='RMSE(train)', color='#2ca02c', linewidth=2, linestyle='--', marker='o', markersize=8)
    plt.plot(x, y2, label='RMSE(test)', color='#d62728', linewidth=2, linestyle='--', marker='o', markersize=8)

    # 标注与样式
    plt.xlabel('traning data amount', fontsize=20)
    plt.ylabel('kJ/mol', fontsize=20)
    plt.legend(
        loc='upper right', 
        bbox_to_anchor=(1.0, 1.0),  # 默认位置是 (0,0)~1,1，此处保持右上角
    )
    plt.tight_layout()
    os.makedirs(f'{csv_path}/fig',exist_ok=True)
    plt.savefig(f'{csv_path}/fig/iter.png', bbox_inches='tight')
    # plt.savefig('static/fig/iter.png', bbox_inches='tight')
    

def pred_calc_fig(pkl_phase_path,iter):
    from src.class_def import Phase
    process = 2

    phase=Phase.load(f'{pkl_phase_path}/model_{iter:06d}_{process}.pd')
    save_dir=phase.record_path
    os.makedirs(save_dir, exist_ok=True)
    print(save_dir)
    # 上一轮的X_train, MLmodel, y_train
    # 本轮的 X_test(上一轮up), y_test(新添加的)
    X_train = phase.X_train
    MLmodel = phase.MLmodel
    # 更新pool数据
    y_train_pred = MLmodel.predict(X_train)
    # 使用当前轮次的MLmodel，预测上一轮次的X_test(也即提交出去的东西)
    phase.y_pred_test_MLmodel = phase.MLmodel.predict(phase.X_test)
    # 从第二轮开始验证上一轮的MLmodel
    MLmodel = phase.MLmodel
    X = phase.X_train
    y = phase.y_train
    y_train = phase.y_train
    y_pred_train_MLmodel = y_train_pred
    y_test = phase.y_test
    y_pred_test_MLmodel = phase.y_pred_test_MLmodel
    if phase.ML_style == 'flat':
        X_col = phase.X_bable.columns.values[1:]
        X_imp = pd.DataFrame(X_train,columns=X_col)
    elif phase.ML_style == 'stack':
        X_col = phase.eigen_table
        X_imp = MLmodel.get_X_imp(X_train)
    
    # 准备绘图数据
    y_true = phase.y_test
    y_pred = phase.y_pred_test_MLmodel
    y_true = np.array(y_true, copy=True)
    y_pred = np.array(y_pred, copy=True)
    
    # 计算核心指标
    r2 = r2_score(y_true, y_pred)
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))  # 手动计算RMSE
    print(y_pred_train_MLmodel)
    print(y_train)

    # 输出文件查异常数据
    print(iter)
    temp = phase.subl_energy.copy()
    valid_mask = temp['in_iter'].notna()  # 或 ~temp['in_iter'].isna()
    temp = temp[valid_mask]
    temp['energy'] = (temp['Atom_ref']*13 - temp['DFT_2'])/13*96.485
    save_path = os.path.join(save_dir, f"whole_calced_points_in_iter_{phase.iter:04d}.csv")
    temp.to_csv(save_path)

    a = pd.DataFrame(np.array([y_train,y_pred_train_MLmodel]).T)
    a.columns = ['train','train_pred']
    b = pd.DataFrame(np.array([y_true,y_pred]).T)
    b.columns = ['test','test_pred']
    os.makedirs(f"{save_dir}/iter_tr_te_points",exist_ok=True)
    save_path = (f"{save_dir}/iter_tr_te_points/y_train_in_iter_{phase.iter:04d}.csv")
    a.to_csv(save_path)
    save_path = (f"{save_dir}/iter_tr_te_points/y_test_in_iter_{phase.iter:04d}.csv")
    b.to_csv(save_path)
    
    # 创建画布
    plt.figure(figsize=(10, 10), dpi=300)
    
    # 绘制散点图
    plt.scatter(y_train, y_pred_train_MLmodel, 
                s=40, 
                alpha=0.5,
                c='blue',
                label='train')
    plt.scatter(y_true, y_pred, 
                s=40, 
                alpha=0.5,
                c='red',
                label='pred')
    
    # 添加参考线（完美预测线）
    min_val = min(y_train.min(), y_pred_train_MLmodel.min())
    max_val = max(y_train.max(), y_pred_train_MLmodel.max())
    plt.plot([min_val, max_val], [min_val, max_val], 
             'r--', 
             lw=2,
             label='y=x')
    
    # 添加统计指标文本
    stats_text = (f'$R^2 = {r2:.4f}$\n'
                f'$MAE = {mae:.4f}$\n'
                f'$RMSE = {rmse:.4f}$')
    
    plt.annotate(stats_text,
                xy=(0.05, 0.85),
                xycoords='axes fraction',
                fontsize=14,
                bbox=dict(boxstyle="round,pad=0.3",
                          fc="ghostwhite",
                          ec="lightgray",
                          alpha=0.8))
    
    # 设置坐标轴
    plt.axis('equal')
    plt.xlim(min_val-0.1*(max_val-min_val), max_val+0.1*(max_val-min_val))
    plt.ylim(min_val-0.1*(max_val-min_val), max_val+0.1*(max_val-min_val))
    
    # 添加标签
    plt.xlabel('vasp', fontsize=14, fontname='SimHei')
    plt.ylabel('pred', fontsize=14, fontname='SimHei')
    plt.title(f'pred-calc (with iter:{phase.iter})', 
             fontsize=16,
             fontname='SimHei',
             pad=15)
    plt.legend(loc='upper right', fontsize=12)
    
    # 添加网格
    plt.grid(True, ls=':', alpha=0.7, color='lightgray')
    
    # 自动创建保存路径并保存
    save_path = (f"{save_dir}/fig/pred_test_{phase.name}_iter{phase.iter:04d}_process{process}.png")
    plt.savefig(save_path, bbox_inches='tight')
    # plt.savefig(f"static/fig/pred_test_{phase.name}_iter{phase.iter:04d}_process{process}.png", bbox_inches='tight')
    plt.close()


def assess(file,MLmodel,X_imp,X,X_train,X_col,y,y_train,y_pred_train_MLmodel,y_test,y_pred_test_MLmodel):
    model_log=open(f'{file}/log.txt','a')
    model_log.write('\n\n%s\n'%(datetime.now()))
    model_log.write('data_amount is %d\n'%(len(X)))
    # print(MLmodel)
    # model_log.write(MLmodel)

    # # 模型参数重要性评价
    # X_imp=pd.DataFrame(X_train,columns=X_col)
    # 提取训练后的特征重要性
    feature_importances = MLmodel.feature_importances_
    # 创建一个数据框来存储特征名称和它们的重要性
    feature_importances_df = pd.DataFrame({'Feature': X_imp.columns, 'Importance': feature_importances})
    # 按重要性降序排列
    feature_importances_df = feature_importances_df.sort_values('Importance', ascending=False)
    # 打印特征及其重要性
    model_log.write(feature_importances_df.to_string(index=False))

    # 评价之偏离真实值
    rmse_tr_MLmodel = root_mean_squared_error(y_train, y_pred_train_MLmodel)
    rmse_te_MLmodel = root_mean_squared_error(y_test, y_pred_test_MLmodel)
    model_log.write('\n\nRMSE(training) = %.3f\n' % rmse_tr_MLmodel)
    model_log.write('RMSE(test) = %.3f\n' % rmse_te_MLmodel)

    # 评价之交叉验证法
    from sklearn.model_selection import KFold, cross_val_score

    crossvalidation = KFold(n_splits=10, shuffle=True)
    r2_scores_MLmodel = cross_val_score(MLmodel,X,y,scoring='r2',cv=crossvalidation)
    rmse_scores_MLmodel = cross_val_score(MLmodel,X,y,scoring='neg_root_mean_squared_error',
                                    cv = crossvalidation)
    model_log.write('Cross-validation results:\n')
    model_log.write('Folds: %i, mean R2: %.3f\n' %(len(r2_scores_MLmodel),r2_scores_MLmodel.mean()))
    model_log.write('Folds: %i, mean RMSE: %.3f\n' %(len(rmse_scores_MLmodel),-rmse_scores_MLmodel.mean()))
    model_log.close()

    # 方便画图
    iter_csv = open(f'{file}/iter.csv','a')
    iter_csv.write(f"{len(X)},{rmse_tr_MLmodel},{rmse_te_MLmodel},{len(r2_scores_MLmodel)},{r2_scores_MLmodel.mean()},{len(rmse_scores_MLmodel)},{abs(rmse_scores_MLmodel.mean())}\n")
    iter_csv.close()

    iter_plot(csv_path = file,fig_size=(12,8),dpi=300)
