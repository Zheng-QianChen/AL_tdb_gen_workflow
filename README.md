# AL_tdb_gen_workflow

用主动学习连接第一性原理计算与 CALPHAD 相模型：生成端元结构、导入 DFT 总能量、训练回归模型、计算下凸包、选择下一批计算，并导出 TDB 相片段。

## 安装

推荐 Python 3.11 或 3.12。基础流程支持 Windows/Linux，不要求 CUDA 或 WSL。

```bash
git clone https://github.com/Zheng-QianChen/AL_tdb_gen_workflow.git
cd AL_tdb_gen_workflow
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
```

也支持安装为程序包并从其他工作目录调用：

```bash
python -m pip install -e ".[terminal,fp,thermo]"
altdb --help
altdb-web
```

用 `python -m pip wheel --no-deps .` 可构建包含网页资源的 wheel。wheel 安装后的默认可写数据目录是 `~/.altdb/data`，也可设置 `AL_TDB_DATA_DIR`。源码运行仍默认使用仓库下的 `data/`。

也可以运行 `conda env create -f environment.yml`，然后 `conda activate AL_process`。

可选模型分别安装 `xgboost` 或 `catboost`；桌面窗口需要 `pywebview`。这些不影响默认浏览器模式。

## 启动

```bash
python app.py
```

访问 [主界面](http://127.0.0.1:8003) 或 [API 文档](http://127.0.0.1:8003/docs)。
`python main.py` 与 `python local_server.py` 启动同一个应用；`python main.py --desktop` 打开可选桌面窗口。

默认只监听本机。环境变量 `AL_TDB_HOST`、`AL_TDB_PORT` 可调整地址，`AL_TDB_DATA_DIR` 可指定数据根目录。默认数据目录为仓库下的 `data/`，不依赖启动时的工作目录。服务是本地工具，未实现多用户认证；任务使用一个服务进程管理。

## CLI、TUI 与 VASP/Slurm

逐体系文献、实验条件、计算日志与文件校验的整理方法见 [研究归档](docs/research-archives.md)。私有数据库和研究原始文件不随公开程序包分发。

```bash
python -m pip install -r requirements-terminal.txt -r requirements-fp.txt
python -m altdb --json run data/run/my_phase.json
python -m altdb tui data/run/my_phase.json --machine examples/vasp_slurm/machine.json
```

CLI 支持配置检查、状态查询、单步/连续运行、结果导入和 TDB 导出；`run` 等待 DFT 结果时返回退出码 10。TUI 提供同一套操作的交互界面。网页与终端共用检查点和跨进程锁。

填写集群与 VASP 输入配置后，`python -m altdb --json pipeline CONFIG machine.json` 可循环选点、准备、通过 DPDispatcher 提交/恢复 Slurm 作业、用 dpdata 收集最终帧，再训练下一轮。也可独立调用 `fp prepare`、`fp submit --dry-run`、`fp submit --wait` 和 `fp collect`。

配置模板、退出码、能量定义与恢复方法见 [终端使用说明](docs/terminal.md)。示例不包含 POTCAR，实际提交前需填写自己的集群参数与授权赝势。

## Gibbs 自由能曲线

```bash
python -m pip install -r requirements-thermo.txt
python -m altdb --json gibbs curve.json
python -m examples.gibbs_demo
```

网页 `/gibbs` 或 TUI 的 **Gibbs curves** 可按所选亚点阵组元计算 G–成分和 G–温度曲线，支持约束占位优化、能量分项和 CSV/JSON/PNG/SVG 导出。完整 Gibbs 能量需要相容的参考 TDB；现有 DFT 相片段本身不提供全部温度依赖。计算对象为单一均匀相，不允许两相分解。配置、参考态和优化范围见 [Gibbs 曲线说明](docs/gibbs.md)。

Pandat / Thermo-Calc 单点结果可通过 `gibbs-reference` 生成参考表、`gibbs-compare` 导入比较。网页也有对应入口；模型条件和实际 Pandat 验证见 [单点对比说明](docs/gibbs-comparison.md)。

三、四、五亚点阵及化学有序/无序耦合模型已完成 **19 组、150 个 Pandat 实际单点验证**，最大自由能差约 0.0222 J/mol-atoms。覆盖范围、占位对比和脚本入口见 [多模型验证记录](docs/gibbs-validation.md)。

材料数据库、空位/间隙和磁性有序专项新增 **17 组、123 点**：9 组真实材料示例的 75 点全部通过；人工四亚点阵磁性有序模型保留 6 个优化结果超差点。同占位自由能表达式的 123 点对比全部通过。代码修正、误差图与可复现反例见 [专项验证记录](docs/gibbs-material-validation.md)。

公开文献/作者库新增 Al–Ni 四亚点阵及 Fe–Ni、Al–Fe、Al–Fe–Nb 五亚点阵的 **14 组、120 点**：同占位公式 120 点通过，独立占位优化保留 19 个差异点。数据库来源、导入等价性、独立搜索诊断与复现入口见 [真实材料四/五亚点阵验证](docs/gibbs-literature-validation.md)。

## 无 DFT 环境的完整示例

```bash
python -m examples.demo
```

示例建立 Al–Ni B2 两亚点阵模型，使用明确标记的人工能量，运行多轮选点、训练、保存和导出。每次在 `data/demo_<随机后缀>/` 新建独立目录，最后打印配置与 TDB 路径。它只验证软件流程，不能作为材料数据使用。

只生成配置和输入文件：`python -m examples.demo --prepare-only`。然后可在主界面输入生成的 `demo_*.json` 文件名启动任务。

## 真实计算流程

1. 在数据准备页面上传结构、元素参考能 CSV、描述符 CSV，并设置每个 Wyckoff 位点组对应的亚点阵。元素符号使用大写，位点比必须与输入结构一致。
2. 保存配置至 `data/run/<配置名>.json`。参考完整结构见 `examples/demo.py`。
3. 主界面启动配置。默认用户标识为 `guest`。HTTP 接口为 `POST /start`，内容为 `{"user_id":"guest","configname":"配置名"}`；也支持向 `POST /api/start_task` 提交完整配置。
4. 从 `generate_DFT_path/<轮次>/<端元>/POSCAR` 取出结构，使用自己的 VASP/DFT 环境计算。
5. 将完整结果写入 `calced_DFT_path/iter.000000/calc.txt`。下一轮目录递增，文件无表头，每行格式为 `AL_NI,DFT_1,DFT_2`，冒号分隔端元也可接受。两列能量均为整个晶胞的 eV 总能量，模型采用 `DFT_2`。
6. 先写临时结果文件，再重命名为 `calc.txt`，避免任务读到尚未写完的内容。程序读取结果、训练并生成下一批结构，候选耗尽后结束。
7. 模型分析页面读取已保存的检查点导出数据库；导出不会启动计算任务。凸包容差单位为 kJ/mol-atoms，标记近凸包端元，TDB 保留完整的端元参数。

参考能 CSV 存储 eV/atom；成分内部为原子分数；预测与凸包距离为 kJ/mol-atoms。超参数必须为合法 JSON 对象，不能填写 Python 表达式。所有配置路径必须位于数据根目录内。

## 恢复与兼容性

停止时会等待当前计算步骤完成。保持配置、结构、参考能和描述符不变，再次启动即可从已完成的阶段恢复。更改这些输入或重做计算时应使用新的输出目录。

旧版检查点无法保证能量和成分单位正确，本版不会自动恢复它们。可保留原始结构与 DFT 结果，在新目录重新运行。TDB 导出是相片段，需要与相容的元素参考数据库合并。

## 多相平衡与相图

网页首页的“多相平衡与相图”支持二元 T–x 相图、三元等温截面、多元成分路径截面、相分数–温度曲线和单点平衡。结果包含相分数、相成分、内部占位、元素化学势，以及二元/三元相界与共存连线，可导出 JSON、CSV、PNG 和 SVG。

```bash
python -m pip install -r requirements-thermo.txt
python -m examples.phase_diagram_demo
python -m altdb --json phase-diagram data/phase_diagram_demo/binary.json
python -m altdb phase-diagram-tui data/phase_diagram_demo/binary.json
```

同相分相、磁性有序、质量守恒及采样加密检查均进入计算流程；未收敛的点和提前终止的相界明确标记。竞争相数据库必须完整，数值搜索不构成全局最优证明。输入模式、适用范围及返回码见[相图计算说明](docs/phase-diagrams.md)。

## 开发与验证

```bash
python -m pip install -r requirements-dev.txt -c constraints-test.txt
python -m pytest -q
```

数值约定、模块职责、检查点设计及已知边界见 [维护说明](docs/maintenance.md)。GitHub Actions 配置了 Windows/Linux、Python 3.11/3.12 回归测试。
