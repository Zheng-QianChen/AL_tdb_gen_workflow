# 与 Pandat / Thermo-Calc 单点计算对比

当前支持导入两种软件的单点结果，按相名、温度、压力和所有组元的总体原子分数严格匹配，输出逐点差值、最大绝对误差、RMSE、平均有符号误差及覆盖点数。不会插值或自动平移参考能。对比结果说明导入点的数值一致程度，不等价于所有模型或真实材料预测均已验证。

最新公开材料库验证见 [真实四/五亚点阵文献库记录](gibbs-literature-validation.md)：Al–Ni、Fe–Ni、Al–Fe、Al–Fe–Nb 共 120 点，同占位公式全部通过，独立优化有 19 点超差，保留失败及分支搜索诊断。

## 实际验证

三、四、五亚点阵的 **19 组、150 个 Pandat 单点**包括两类化学有序模型；全部通过，最大绝对差 0.02218515 J/mol-atoms，并对比了外部占位。后续材料、空位/间隙、磁性有序专项增加 **17 组、123 点**：真实材料示例的 75 点全部通过；人工四亚点阵磁性有序模型有 6 个优化结果超差点，同占位能量对比则 123 点全部通过。验证矩阵、复现命令及反例诊断见 [多模型验证记录](gibbs-validation.md) 和 [专项验证记录](gibbs-material-validation.md)。以下保留最初的双亚点阵基准。

在用户本地 **Pandat 2022a Education，文件版本 2022.0.0.0** 中，使用 `examples/gibbs_demo.py` 的人工 `SYNTHETIC_B2` 双亚点阵数据库完成了九个独立单点：

- 温度：600、1000、1400 K；压力：101325 Pa。
- 总体 NI 原子分数：0.1、0.5、0.9；两个亚点阵均允许 AL/NI。
- 单一均匀相，自由优化内部占位，沿用数据库参考态。
- 九点全部通过 1 J/mol-atoms 的绝对容差；最大绝对差约 0.00382137 J/mol-atoms，RMSE 约 0.00234479 J/mol-atoms。

这是实际调用 Pandat 引擎的交叉验证，数据库参数为人工构造，不能作为真实 Al–Ni 材料的预测依据。此次未对比外部占位分数，也未运行 Thermo-Calc。

复现命令（需要用户自己的 Pandat 安装）：

```powershell
python -m examples.pandat_benchmark --executable 'D:\Program Files\CompuTherm LLC\Pandat 2022a Education\bin\Pandat.exe' --version '2022a Education (2022.0.0.0)'
```

该示例仅运行人工数据库的九个测试点，不是任意商业数据库的自动适配器。结果写入 `data/pandat_benchmark_<编号>/`，保留 `synthetic.tdb`、`points.pbfx`、`raw/*.dat`、控制台日志、可执行文件哈希、`reference.csv`、`compare.json` 和汇总。启动时使用英文临时目录、隐藏控制台和保持打开的输入管道，以适配旧版 Pandat；不会修改安装或许可配置。以每点成功日志和可解析的输出为依据；若某些版本完成后仍保留输入线程，记录结束方式并只终止本次启动的进程。

## 准备实际模型的对比

先按 [Gibbs 曲线说明](gibbs.md) 计算本程序的结果。任意单点可用 `mode: "gt"`、一个 `temperatures` 值及固定 `composition` 计算。

```bash
python -m altdb --json gibbs-reference gibbs/curve_<编号>/gibbs.json
```

生成三个文件：

- `reference.csv`：相名、T/P、全部总体原子分数、空白 `G` 和占位列。优化占位不会把本程序的占位抄作外部结果；固定占位时列出作为条件的固定值。
- `conditions.json`：相模型、亚点阵选择、位点数、数据库路径/哈希、原始计算请求及采样条件。
- `compare.json`：对比请求模板；软件版本为空，`conditions_verified` 为 `false`，以防空白模板被误用为已经验证的数据。

在外部软件执行相同条件的计算，把相的摩尔 Gibbs 能填入 `G`。不需要比较全部点时删除其他数据行；不要保留空白 G 的行。

```csv
phase,T_K,P_Pa,X_AL,X_NI,G
MY_PHASE,1000,101325,0.5,0.5,<填入外部计算的数值>
```

CSV 使用 UTF-8、英文逗号、小数点。各成分使用原子分数，不使用质量分数或百分数。Pandat 原始 `.dat` 表含独立单位行，需要转换成以上格式；本功能不会猜测不同版本的原始表头或单位。

修改 `compare.json`：填写 `software`（`pandat` / `thermo-calc` / `other`）、`software_version`、`reference_csv` 路径、`energy_unit`（`J/mol-atoms` 或 `kJ/mol-atoms`）。核对外部配置与 `reference_model` 一致后，设置 `conditions_verified: true`。来源和约束是操作者的声明，导入程序无法从一列 G 独立验证外部求解器设置。

```bash
python -m altdb --json gibbs-compare compare.json
```

退出码：`0` 表示所有导入点的能量在容差内；`5` 表示存在超差点，报告仍会保存；`2` 表示输入或条件无效。结果 CSV/JSON 写入 `gibbs_comparisons/comparison_<编号>/`。只导入部分点时，报告明确列出未比较点数，不将其视为通过。

网页 `/gibbs` 的“单点对比”区可以生成模板，选择填写后的请求 JSON 并显示误差、覆盖率和报告下载链接。请求引用的 CSV/本程序结果须位于应用数据目录内。API 为 `POST /gibbs/reference-template`（`{"result":"…/gibbs.json"}`）和 `POST /gibbs/compare`（完整请求）。

## 必须一致的计算定义

1. **同一 TDB 模型**：端元、相互作用、元素参考函数和参数温区都一致。仅相名相同、数据库不同只能做模型差异比较，不能用来验证求解器。模板记录源 TDB 的 SHA256；若合并文件改变文本，需另行保留合并来源证明。
2. **相同亚点阵组元与位点数**：限制某亚点阵的允许组元时，外部软件也要实施相同限制，不能只在整体元素列表上删除。
3. **单一均匀相**：限制相名后仍须确认没有同相分裂成多个 composition sets，且相成分等于指定总成分。系统平衡自由能可能低于这里的均匀相自由能。
4. **相同参考态及归一化**：比较相的 G，不混用混合自由能、形成自由能、驱动力或系统总 G。以每 mol 原子为基准；每 mol 化学式单位需按实际占据的原子数 `Σ a_s(1-y_VA)` 换算。只有不含空位时才等于位点总数。VA 不列入总体 `X_*`，但应保留在完整的 `Y_*` 占位表中。
5. **相同内部约束**：默认优化占位；固定占位模式要求外部导出所有 `Y_<从0开始的亚点阵序号>_<组元>` 列，并与本程序固定值一致。优化模式可选导出完整占位，差异仅作为诊断，因为对称等价构型可能有相同 G 和不同占位。

匹配容差：T 为 1e-6 K，P 为 0.01 Pa，每个原子分数默认 1e-8。对于外部文本导出精度有限的情况，可在请求中显式指定 `fraction_atol`（大于零、不超过 1e-4）；它同时用于成分匹配、占位归一化/成分一致性和固定占位核对，随报告保存。2022a 的首个输出有时只有六位有效数字，本验证使用 `2e-6`，不改写原始数值。不匹配、匹配到多个点、重复点、非有限数值或声明模型不符时均拒绝生成比较结论。相名及 CSV 列名按模板填写，拆分相如 `PHASE#2` 不自动合并。

能量判据为 `|G_local - G_external| <= atol_J_mol_atoms + rtol * |G_external|`。默认 `atol=1 J/mol-atoms, rtol=0`，是可调整的工程阈值，不是物理不确定度。接近零的 G 也使用同一绝对容差判据。

## 外部软件设置参考

Pandat 使用 **Individual Phases** 条件，取 `G(@相名)`；官方表格定义为每 mol 原子的相 Gibbs 能，未指定参考相时使用数据库默认参考态。单点也应检查相名和 `x(组元@相名)`，确认单一相组成。见 [Pandat 自由能曲线](https://computherm.com/Pandat_Online_Help/CalculationofGibbsEnergyCurves.html) 和 [表格语法及单位](https://computherm.com/Pandat_Online_Help/PandatTableFormatSyntax.html)。本机 2022a 的 PBFX 单点压力输入以 `atm` 配合数值 1 验证通过，导入时乘以 101325 转 Pa；不要仅凭列标签假设所有输入单位都受支持。

Thermo-Calc 可用单点平衡接口配置相状态及参考态；需要逐点确认相组成和 composition sets，不能把“仅一个相名被启用”视为必然满足单一均匀相约束。官方接口还区分相的每 mol 化学式附加能量和其他摩尔量，取值时需核对实际输出定义。见 [TC-Python single equilibrium 文档](https://www2.thermocalc.com/docs/tc-python/latest-version/html/calculation_modules/single_equilibrium.html)。当前提供结果导入；尚未实测 TC-Python 自动执行。
