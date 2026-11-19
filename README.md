# AL–TDB 热力学数据库工作台

AL–TDB 把文献原表、实验观测、结构候选、第一性原理结果和 CALPHAD 模型关联到同一个本地项目。可以从元素清单开始建库，比较同一相的多种亚点阵模型，再用留出的实验记录检验候选 TDB。

## 启动工作台

从 [GitHub Releases](https://github.com/Zheng-QianChen/AL_tdb_gen_workflow/releases) 下载桌面启动包，完整解压。预先安装带 `venv` 的 Python 3.11 或 3.12。首次运行时启动器建立独立环境并联网安装依赖。

| 平台 | 在解压目录启动 |
| --- | --- |
| Windows | 双击 `Start-AL-TDB.cmd` |
| Linux | 运行 `sh Start-AL-TDB.sh`；无桌面时加 `--no-browser` |
| macOS | 双击 `Start-AL-TDB.command`，也可运行 `sh Start-AL-TDB.sh` |

启动后使用终端打印的本机地址进入 `/projects`。默认端口为 8003。关闭服务可在启动窗口按 Ctrl+C，或用同一入口加 `--stop`。

## 从空项目到候选数据库

1. **确定范围。** 新建项目，输入元素，例如 Al、Ce、La。按二元、三元和更高阶子体系盘点来源，记录要验证的温区和相区。
2. **整理实验。** 在文献库登记题录或 DOI，挂接 PDF 后可直接阅读。由来源文献进入表格导入，映射 CSV/TSV 的测量项目、相名、位置、单位和温度。对照预览再入库，保留原行、文件摘要与修订。多相试样可先保留文献相名。
3. **选择结构和模型。** 比对原型、点阵重复、对称性与占位，确定本库相名。同一相可建立多个独立模型。可导入 CIF，或查询 Materials Project 和 OQMD；MP 密钥从运行环境的 `MP_API_KEY` 读取。
4. **计算、优化、验证。** 配置第一性原理作业并收集收敛信息，按独立试样划分拟合与留出数据。内置优化器产生候选 TDB；Pandat 和 Thermo-Calc 可通过已配置的适配器或导出的任务交接。使用相图、热化学量和二元限制面复查结果。
5. **保存与移交。** 完整工作台包包含该项目的数据和附件，仅设置模式保存界面配置。安装包默认把可写数据放在 `~/.altdb/data`；源码运行默认使用仓库下的 `data/`。通过 `AL_TDB_DATA_DIR` 可改用独立研究目录。

推荐让本地 AI 助手从证据盘点开始。仓库根目录的 [AGENTS.md](AGENTS.md) 列出了操作顺序、API 路径与验收方法；首页的「协作指南」提供可直接交给助手的首个任务。软件发布只包含通用代码、使用文档和合成示例。完整工作台包可能包含用户的原文和研究数据，请按项目授权分享。

## 从源码运行

```bash
git clone https://github.com/Zheng-QianChen/AL_tdb_gen_workflow.git
cd AL_tdb_gen_workflow
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -c constraints-test.txt -e ".[terminal,fp,thermo]"
altdb-web
```

本地接口说明见服务的 `/docs` 和 `/openapi.json`。用 `python -m altdb --help` 查看终端入口。详细的运行参数见[启动设置](docs/windows-server.md)。

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

Pandat / Thermo-Calc 单点结果可通过 `gibbs-reference` 生成参考表、`gibbs-compare` 导入比较。网页也有对应入口；模型条件与比较方法见 [单点对比说明](docs/gibbs-comparison.md)。

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

## 计算结果与人工修订

网页 `/results` 展示每个运行的计算结果、INCAR/K 点设置、计算耗时、电子与离子收敛信息、原始文件校验值和修订历史。能量与备注可以人工修改，必须填写修改人、原因和所依据的版本；原始记录保留，修订追加。

0.3.0 起训练从每个运行的 SQLite 数据库读取结果，并记录实际使用的条目版本。`calc.txt` 保留为兼容格式；已有数据库记录时，改写该文件不会改变训练输入。已训练模型继续使用原来的版本。CLI 用 `altdb results list/show/amend` 操作同一份记录。详见[计算结果与修订](docs/result-records.md)。

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

数值约定、模块职责、检查点设计及已知边界见 [维护说明](docs/maintenance.md)。GitHub Actions 运行 Windows 和 Linux 的 Python 3.11/3.12 回归。macOS 提供启动入口，尚待原生环境验证。
