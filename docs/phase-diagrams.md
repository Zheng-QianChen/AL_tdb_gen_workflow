# 多相平衡与相图

相图模块在同一温度、压力和总成分下最小化体系总 Gibbs 能。候选相可以同时存在，同一相也可以分裂成多个不同成分的组成集。内部占位由平衡求解器同时优化。它与 `gibbs` 的单一均匀相约束不同。

## 入口

安装 `requirements-thermo.txt` 后，网页首页 → **多相平衡与相图**，或访问 `/phase-diagram`。可以上传 TDB、选组元和候选相、设置温度/成分范围、检查单点组成集并下载结果。

```bash
python -m altdb --json phase-diagram request.json
python -m altdb phase-diagram-tui request.json
```

`phase-diagram-tui` 不需要训练检查点；现有工作流 TUI 的 **Phase diagram** 按钮 / `p` 键也可使用。工作流入口自动加入该检查点导出的相，其他竞争相和参考函数必须由请求中的 TDB 提供。

```bash
python -m altdb --json phase-diagram request.json --config data/run/input.json
```

CLI 标准输出是单个 JSON，进度输出到 stderr。返回码 `0` 表示请求的计算及开启的检查完成，`6` 表示已保存部分结果，存在失败点、采样差异或未完成的相界追踪；`2` 表示输入、路径或依赖错误。`0` 不等于证明全局最优。结果文件路径在返回值的 `files` 中。

## 模式与输入

所有成分使用 **原子分数**，相分数使用 **原子摩尔分数**，能量单位 **J/mol-atoms**；不输出质量分数或体积分数。

| mode | 图 / 计算对象 | 附加条件 |
| --- | --- | --- |
| `binary` | 二元 T–x 相图，相界、共存连线、不变反应 | 两个元素，至少两个温度；`x_component`、`composition_range` |
| `ternary` | 三元等温截面，相界、连线、三相三角形 | 三个元素，一个温度 |
| `isopleth` | 多元体系沿指定总成分路径的温度截面 | `composition_start` / `composition_end`；至少两个温度 |
| `property` | 固定总成分的相分数–温度曲线 | `composition`；至少两个温度 |
| `point` | 单点多相平衡 | `composition`；一个温度 |

二元示例：

```json
{
  "tdb_files": ["uploads/system.tdb"],
  "components": ["AL", "ZN"],
  "mode": "binary",
  "temperatures": [300, 400, 500, 600, 700, 800, 900, 1000],
  "x_component": "ZN",
  "composition_range": [0, 1],
  "points": 51,
  "pressure": 101325,
  "sampling_density": 200,
  "verify_sampling": true,
  "map_boundaries": true
}
```

- `tdb_files` 中的路径必须位于应用数据目录；相对路径以 `data/` 为基准，也接受该目录中的绝对路径。`--data-dir` / `AL_TDB_DATA_DIR` 可以改变数据根目录。
- `components` 只填真实元素；存在空位时自动加入 VA。最多 8 个元素。
- `phases: null`（默认）启用所有相容相；`suspended_phases` 可明确排除相。空的 `phases: []` 报错。数据库中不存在的相名报错，不会忽略拼写错误。
- 有序模型包含无序参考部分时，自动以有序模型代表这两种状态，避免重复计算。结果逐相列出所有排除原因。
- `temperatures` 是显式温度列表；网页使用等距温度，CLI 支持非均匀温度。禁止超出所引用 TDB 函数定义区间。
- `points` 是二元/路径上的点数；三元表示每条边点数，总网格数为 `points*(points+1)/2`。请求上限 10,000 个网格点，每相上限 1,024 个活动端元，以控制上游端元配对采样的内存占用。
- `composition_start` 到 `composition_end` 按路径分数线性插值。只限制体系总成分；共存各相的成分不被强制留在截线上。
- `allow_missing_ordered_endmembers` 默认 `false`。只有文献明确使用“未列出的有序修正端元为零”的约定时才开启；无序基相仍须有完整端元及参考函数。

三元/多元/相分数示例可自动生成：

```bash
python -m examples.phase_diagram_demo
python -m altdb --json phase-diagram data/phase_diagram_demo/binary.json
python -m altdb --json phase-diagram data/phase_diagram_demo/ternary.json
python -m altdb --json phase-diagram data/phase_diagram_demo/isopleth.json
python -m altdb --json phase-diagram data/phase_diagram_demo/property.json
```

这些示例使用人工构造的理想液体与纯固相，不能作为实际材料预测。二元共晶温度具有解析解 `10000/(10 + R ln 2)`，约 634.390 K。

## 求解与数值审查

使用 pycalphad 0.11 的自由能采样、下凸包初始状态、多相局部平衡及相稳定性搜索。`ThermodynamicModel` 保持此前磁性有序验证中的计算规则：先分配 TC、BMAGN，再计算 IHJ 磁自由能。没有重新使用上游已知不一致的磁自由能分配方式。

`EquilibriumSystem` 缓存同温度、同采样密度的曲面和编译后的相模型；每个总成分独立建立凸包初始解并求平衡，不把上一个点的局部解作为唯一初始条件。缓存适配器使用与 0.11 `Workspace.recompute` 相同的内部调用，已用公开 `equilibrium()` 接口和解析解核验；升级 pycalphad 时必须重新验证。

每个成功输出点检查：

- 相分数和为 1、非负且有限；按相分数加权的元素成分满足质量守恒。
- 每个亚点阵占位和为 1，所有占位/相成分在范围内。
- 体系 G 等于各组成集能量的加权和。
- 共存相满足 `G_phase = Σ x_i μ_i`，并检查采样曲面中是否还存在低于共切平面的状态。

分数容差为 `1e-7`，能量与共切残差绝对容差为 `0.1 J/mol-atoms`。这些检查不代替完整边界 KKT、Hessian 稳定性证明或全局最优证明。低于 `1e-8` 的相分数不参与相区标签，但其组成集仍保存在原始结果中。

默认以 `sampling_density` 和双倍密度独立求解。如果能量或相组合不一致，保留通过审查的较低能量解，同时标记 `needs_refinement`；只有一档成功也标为需复查。两档一致仅代表对这次加密不敏感，不能排除两次都漏掉狭窄能谷。

纯组元端点、三元边等零组元条件按严格降维系统求解，不混入虚拟杂质。缺失元素的化学势不能由该降维平衡唯一确定，因此不输出其数值，并在 `undefined_chemical_potentials` 中列出。含 VA 的曲面排除纯空位端元；有限、归一化检查仍作用于每个最终状态。

二元和三元开启 pycalphad 的零相分数相界追踪，自动扫描边界，并从网格中发现的新多相组合补充内部起点。`max_mapping_steps` 默认 5,000。`FAILED` 分支、拒绝的点、步数耗尽均保留诊断并标为 `partial`，不会因队列为空就宣称相图完整。相分数曲线与任意多元路径截面目前使用网格计算，没有连续边界追踪，转变温度精度受温度网格限制。

## 输出

每次运行保存到新的 `data/phase_diagrams/diagram_<id>/`，不覆盖已有结果。

| 文件 | 内容 |
| --- | --- |
| `diagram.json` | 请求、引擎/模型哈希、TDB 哈希、排除相、每点平衡状态与检查结果、完整相界数据 |
| `diagram.csv` | 每个总成分点的 G、化学势、相组合、质量守恒残差、采样复查与失败原因 |
| `phases.csv` | 每个组成集的相分数、相成分、G 和亚点阵占位 |
| `boundaries.csv` | 相界与不变点中的组成集、相成分、占位，明确保留拒绝点形成的缺口 |
| `request.json` | 可重复运行的参数 |
| `diagram.png` / `diagram.svg` | 科学绘图，可用于后续排版 |
| `report.html` | 可离线打开的图、范围、候选相及下载链接 |

同相分相使用 `PHASE#1`、`PHASE#2`。编号只在当前点内有效，不承诺跨温度连续追踪某条分支。相分数图按基础相名汇总，组成集细节保留在 CSV/JSON。

## API

- `GET /phase-diagram`：网页。
- `POST /phase-diagram/options`：`{"tdb_files": [...], "config": null}` 返回元素、相和亚点阵定义。
- `POST /phase-diagram/calculate`：接受完整请求，在线程执行器运行，返回结果和 `urls`。

计算接口当前会等待整个请求完成。耗时较长的任务建议使用 CLI，并保存标准输出；关网页不等于取消服务器计算。

## 适用边界

当前支持中性元素 / VA 的固定点阵比 CEF、化学计量相、常规 IHJ 磁性、有序–无序耦合和可变间隙/空位。离子、带电物种、MQMQA、非标准磁性模型等不在本版支持范围，遇到会报错。没有包含 Scheil 凝固、扩散动力学或自动热力学参数评估。

“完整相图”还需要数据库含有完整的竞争相及足够可信的参数。加入某个 DFT/ML 相片段不会自动生成其液相、其他晶体结构或欠缺的温度贡献。相图数值审查通过，也不证明数据库与实验相符。

算法参考：[pycalphad Mapping 官方说明](https://pycalphad.org/docs/latest/examples/Mapping.html)。

## 本次验证（2026-10-18）

57 项相图、Gibbs 和终端相关测试全部通过，覆盖解析共晶、共切线与杠杆定则、封闭分相区的内部起点、三相三角形、严格零组元边界、三/四/五亚点阵磁性有序、可变间隙、CLI/API 和无训练检查点的 TUI。相图模块新增 32 项测试。网页 HTTP 入口、实际计算和 8 类文件下载均通过；浏览器自动操作环境未能启动，因此没有完成浏览器点击流程的自动化验证。

| 文献数据库 | 网格点通过 / 总数 | 双密度检查通过 | 相界追踪 |
| --- | --- | --- | --- |
| Al–Zn，an Mey 模型 / NIMS 文件 | 1476 / 1476 | 1476 | 部分完成，2 条分支失败，8 个追踪点被拒绝 |
| Cr–Ti–V，Ghosh 模型 / NIMS 文件 | 136 / 136 | 136 | 部分完成，1 条分支失败 |
| Al–Cr–Ni，含有序与磁性模型 | 135 / 136 | 135 | 部分完成，10 条分支失败 |

Al–Cr–Ni 在 1273.15 K、总成分 Al=0.133333、Cr=0.2、Ni=0.666667 的点未通过稳定性检查：采样中仍有约 19.708 J/mol-atoms 低于所得共切平面的状态。该点保留为失败，不提供伪造的稳定平衡结果。上述网格检查通过不表示整个相界拓扑已经验证。

人工数据库的三元截面（231 点）、四元路径截面（651 点）和相分数曲线（76 点）均完成，并通过双密度检查。三元人工算例的相界追踪完成。

Thermo-Calc Education 2026b 对 Al–Zn 的 4 个代表点进行了全相平衡总 G 复核，覆盖 FCC 同相分裂、FCC+液相、FCC+HCP 和液相。最大绝对差为 **0.005429 J/mol-atoms**。这是总 G 的交叉验证，尚未自动核验全部相分数、占位和相图拓扑。为兼容其 TDB 导入器，仅在临时副本中删除了 38 行完整注释，所有非注释行保持一致；原数据库未改动。数据库哈希、求解状态和核对结果见 [验证记录](validation/phase-diagram-validation.json)。

本机有可用 Thermo-Calc Education 安装时，可用以下脚本重复核对已有结果中的内部点：

```bash
python -m examples.phase_diagram_tc_check data/phase_diagrams/diagram_ID/diagram.json data/tc_check --points 594 1004 512 1045 --home "PATH_TO_THERMO_CALC_2026b"
```

点编号来自该次运行的 `rows[].point_id`，不能直接用于其他网格。脚本要求源文件哈希一致、全相候选集、TDB 导入成功、平衡收敛标记和实际结果文件，缺一项不会判为验证通过。
