# 按亚点阵组元计算 Gibbs 自由能曲线

支持固定温度的 G–成分曲线和固定总成分的 G–温度曲线。两种模式默认在总成分约束下优化各亚点阵占位，计算**单一均匀相**的自由能；不做多相平衡或同一相的两相分解。支持中性元素及 VA 的 CEF 亚点阵模型，含部分间隙和磁性有序耦合模型；实际验证与已知反例见 [专项验证记录](gibbs-material-validation.md)。

公开材料库的四/五亚点阵模型另完成 120 点 Pandat 对比：公式一致性全部通过，独立占位优化保留 19 个差异点。来源、适用边界及复现脚本见 [文献库验证记录](gibbs-literature-validation.md)。

## 安装与操作

```bash
python -m pip install -r requirements-thermo.txt
python app.py
```

网页访问 `/gibbs`，或从模型分析页的“Gibbs 自由能曲线”进入。模型分析页导出选定模型后，会带入实际导出的 TDB 路径和相名，保留已选亚点阵组元。补入相容的参考 TDB，点击“读取亚点阵”，即可调整各亚点阵的允许组元和曲线条件。

支持两种数据来源：

- **已训练的运行配置**：填写配置名或数据目录内的 JSON 路径，程序读取一个已提交的检查点，生成相片段并合并参考 TDB。
- **现有 TDB**：不填运行配置，提供相 TDB 和参考 TDB（也可以是单个完整数据库），指定相名。适用于原始或简化后的亚点阵模型。

TDB 文件路径相对于数据根目录解析，也接受位于该目录内的绝对路径。数据根目录由 `AL_TDB_DATA_DIR` / CLI `--data-dir` 控制。需要先把外部数据库放入数据目录（例如 `data/uploads/`）。TDB 使用 UTF-8；Windows 换行会正确处理。

脚本入口：

```bash
python -m altdb --json gibbs gx.json
python -m altdb --json gibbs gt.json
# 使用当前运行的检查点；请求中的 TDB 文件作为参考数据库
python -m altdb --json gibbs gx.json --config my_phase
```

TUI 中点击 **Gibbs curves**（快捷键 `g`），输入曲线请求 JSON 路径，计算当前运行的相。TUI 会显示生成的 CSV、JSON、PNG、SVG 路径。若使用独立 TDB（包括已经简化的相），请使用网页或 CLI，不添加 `--config`。网页可下载请求 JSON，直接复用于相同数据根目录下的 CLI。

## G–成分请求

```json
{
  "tdb_files": ["uploads/reference.tdb", "output/models/selected_phase.tdb"],
  "phase": "MY_PHASE",
  "sublattices": [["MO", "NB"], ["NB", "TA"]],
  "mode": "gx",
  "temperatures": [600, 1000, 1400],
  "pressure": 101325,
  "composition_start": {"MO": 0.5, "NB": 0.5},
  "composition_end": {"NB": 0.5, "TA": 0.5},
  "x_axis": "TA",
  "points": 101,
  "starts": 8
}
```

示例端点适用于两个等权亚点阵；真实输入要匹配所选模型。`sublattices` 可省略以使用数据库的全部组元。每组至少保留一个组元，可以不同亚点阵选择不同的元素。成分是**总体原子分数**，每个端点合计为 1；未列出的元素按零处理。

两个成分端点定义多元空间中的直线截面。`x_axis` 选择其中一个变化组元作为横坐标；省略时自动选一个变化组元。单条曲线不是多元体系的整个自由能超曲面，多个温度各生成一条曲线。若固定亚点阵使某些总成分不可实现，程序会报出不可行成分，不将占位强行归一化。

## G–温度请求

```json
{
  "config": "run/my_phase.json",
  "tdb_files": ["uploads/reference.tdb"],
  "sublattices": [["MO", "NB"], ["NB", "TA"]],
  "mode": "gt",
  "temperatures": [300, 500, 700, 900, 1100, 1300, 1500],
  "composition": {"MO": 0.25, "NB": 0.5, "TA": 0.25},
  "pressure": 101325,
  "starts": 8
}
```

`temperatures` 为明确的 Kelvin 采样点；网页根据起止温度和点数生成。固定总成分下，每个温度会重新优化占位，因此可表现当前模型内的占位变化。

如果希望考察固定构型而非优化占位，可在 **G–温度** 请求中加入：

```json
"site_fractions": [{"MO": 0.5, "NB": 0.5}, {"NB": 0.5, "TA": 0.5}]
```

每个亚点阵内的占位分数之和须为 1，按位点权重换算后还必须等于 `composition`。这时结果的 `method` 为 `fixed_site_fractions`。

## 模型和能量定义

对中性元素、固定亚点阵位点数的 CEF，相的摩尔 Gibbs 自由能包含：

\[
G_m = \frac{\sum_{\text{端元 }I}(\prod_s y_{I_s}^{(s)})G_I^0(T)
+ RT\sum_s a_s\sum_i y_i^{(s)}\ln y_i^{(s)}
+ G^{\rm excess}+G^{\rm magnetic}+\cdots}{N_{\rm atoms}(y)}.
\]

`a_s` 是位点数，`y` 是亚点阵占位，`N_atoms(y) = Σ_s a_s (1-y_VA^(s))` 是每化学式单位的实际原子数；不含 VA 时等于总位点数。总体原子分数 `x_i = Σ_s a_s y_i^(s) / N_atoms(y)`，**VA 不属于总体成分**。VA 保留在占位和构型熵中。实际表达式基于 [pycalphad Model](https://pycalphad.org/docs/latest/api/pycalphad.html)，本项目补充了常规 IHJ 磁性参数分拆和居里温度边界处理。图中使用 kJ/mol-atoms；CSV/JSON 使用 J/mol-atoms，温度 K，压力 Pa。

**完整曲线指完整计算所给模型，并不代表原始 DFT 能量已经包含全部热力学贡献。** 本程序现有 DFT/ML 相片段把形成能作为温度无关常数，并引用 GHSER 元素函数。只用这些片段与元素参考库时，温度依赖主要来自元素参考函数和构型熵；未提供的振动、电子、磁性以及非理想相互作用贡献不会自动补齐。定量预测这些效应需要适当的 TDB 参数和物理模型。

程序默认拒绝缺失的端元 G 参数、未定义或循环引用的函数，以及超出相关参数/函数温区的请求。温区遵从 TDB 区间（通常下界包含、上界不包含）。不会将未知参考函数置零，也不会默认进行温区外推。输入数据库之间存在重复定义或不兼容时应先整理数据库，而不是自动覆盖。扩散迁移率 `MF/MQ` 不进入 Gibbs 参数校验。

## 多亚点阵与化学有序化

三、四、五亚点阵使用相同的计算接口，可使用相等或不等位点权重，以及每个亚点阵不同的允许组元。已实际验证的范围见 [多模型 Pandat 验证记录](gibbs-validation.md)。

支持两种化学有序描述：独立 CEF 中由不同端元/相互作用产生的有序占位，以及含无序参考相的分拆模型：

\[
G_m(y)=G_{\mathrm{dis}}(x)+G_{\mathrm{ord}}(y)-G_{\mathrm{ord}}(y=x).
\]

随机占位 `y=x` 时，有序修正应为零，返回无序参考相的自由能。TDB 必须同时提供有序相和无序相。支持 `TYPE_DEFINITION … GES AMEND_PHASE_DESCRIPTION … DISORDERED_PART …`，也接受 Pandat 的 `DISORDER_PART` 拼写；只在解析时转换该关键字，原文件及 SHA256 不变，转换记录保存在 `sources[].parser_normalizations`。结果中的 `ordering_model` 标明是否使用耦合模型。

当前耦合映射要求有序相前部为组元集合相同的等价置换亚点阵，对应无序参考相的第一个亚点阵；允许后部存在逐一对应的间隙/空位亚点阵，位点数须保持相容比例。选定组元后仍保留计算随机占位扣除项所需的完整端元和函数，不会先删除它们而改变有序模型。

耦合模型有序侧支持 `G/L` 和常规 IHJ 的 `TC/BMAGN`。上述能量分拆式用于化学项；磁性采用 `TC = TC_dis + TC_ord(y) - TC_ord(y_random)`，`BMAGN` 同样处理，然后对合成参数应用反铁磁符号约定并计算一次非线性磁性能量。不能把三个各自算好的磁性能量直接相减。含有序磁性修正时，两相的化学式单位须匹配；若有序侧另有 IHJ 设置，须与无序侧一致。后部间隙占位在随机态扣除时保持不变。实现基于 [pycalphad 有序相映射](https://pycalphad.org/docs/latest/_modules/pycalphad/model.html)，修正了所用 0.11.1 版本对分拆后磁性参数未重新计算能量的限制。

少数数据库省略数值为零的**有序修正**端元。确认该约定后，可在 CLI/API 请求中显式设置 `"allow_missing_ordered_endmembers": true`；默认关闭，并记录在结果中。此选项不放宽无序参考相或独立 CEF 的绝对端元完整性校验，未知函数仍报错。Al–Fe B2 专项验证采用了该声明。

例如 `(FE)1:(C,VA)3`，若总体 `X_C=0.1`，间隙占位为 `Y_C=0.1/(3×0.9)`，而不是 0.1。请求中的 `composition` 只填写 `FE/C`；固定构型时 `site_fractions` 则须包含 `VA`。

## 优化、导出与限制

每个总成分先通过线性规划检查占位可行性并确定固定自由度，再用多个可行起点的 SLSQP 优化内部占位，选择成功收敛解中自由能最低者。G–温度还使用前一个温度的解作为起点。**这不是全局最优证明**；复杂的多阱模型建议增加 `starts`，比较不同设置和独立 CALPHAD 软件。所有起点均失败时不发布曲线。

当前支持独立的元素/VA CEF 相及上述映射范围内的化学、常规 IHJ 磁性有序/无序耦合模型。至少一个选定亚点阵必须不含 VA，以排除零原子数奇点；因此所有亚点阵都允许空位的模型仍会拒绝。带电或分子组元、可变位点比例、离子或 MQMQA 模型，以及超出上述范围的有序侧物理参数仍不支持。Xiong 磁性有序耦合不在支持范围。单相曲线可以非凸；例如存在混溶间隙时，不会自动替换为两相包络。

结果写入数据目录的 `gibbs/curve_<唯一编号>/`：

- `gibbs.csv`：G、各物理项、T/P、总体成分 `X_*`、亚点阵占位 `Y_<从0开始的序号>_*`，以及 `atoms_per_formula_unit`、`TC_K`、`BMAG`。未启用磁性时后两项为零。
- `gibbs.json`：同样的数据，加上请求、源文件 SHA256、检查点来源与计算范围说明。
- `gibbs.png` / `gibbs.svg`：可导出和分享的科学曲线图。

`successful_starts` 为收敛起点数，`energy_spread` 是收敛解间自由能差（J/mol-atoms），可提示存在多个局部解。`unique_constitution` 表示约束已唯一确定占位。所有输出均保留模型参考态，不自动转成混合自由能或凸包距离。

## 无真实数据库的演示

```bash
python -m examples.gibbs_demo
```

会建立一个明确标记为 **SYNTHETIC_B2** 的人工数据库，计算 G–成分和 G–温度曲线，并输出可直接复用的 `gx.json`、`gt.json` 路径。它用于检查界面与计算流程，不能用于真实 Al–Ni 相稳定性预测。

HTTP 接口为 `POST /gibbs/options` 和 `POST /gibbs/calculate`，分别接受来源配置和完整曲线请求。新功能使用相同的数据根目录访问限制，读取检查点快照，不推进主动学习或修改计算任务。

## 与外部软件交叉验证

可生成空白单点参考表，再导入 Pandat / Thermo-Calc 结果进行严格条件匹配和误差统计。已用本地 Pandat 2022a Education 完成双亚点阵的九点验证，以及三、四、五亚点阵的 19 组、150 点验证，后者包含占位和化学有序化对比。新增材料/空位/磁性专项 17 组、123 点：真实材料示例 75 点全部通过，人工磁性有序模型保留 6 个求解分支不一致点。命令、外部软件设置、数据格式见 [单点对比说明](gibbs-comparison.md)，覆盖范围与误差见 [多模型验证记录](gibbs-validation.md) 和 [专项验证记录](gibbs-material-validation.md)。
