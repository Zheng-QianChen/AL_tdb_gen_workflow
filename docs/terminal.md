# 终端与第一性原理计算管理

网页、CLI 和 Textual TUI 共用同一个主动学习状态机与检查点。CLI 负责脚本化运行，TUI 负责交互查看和触发同样的操作，不需要启动 HTTP 服务。

## 安装与入口

在仓库目录中使用 Python 3.11/3.12：

```bash
python -m pip install -r requirements-terminal.txt -r requirements-fp.txt
python -m altdb --help
python -m altdb tui data/run/my_phase.json --machine examples/vasp_slurm/machine.json
```

只用 CLI 手工导入能量时，安装 `requirements.txt` 即可。Slurm/VASP 管理需要 `requirements-fp.txt`；TUI 单独需要 `requirements-terminal.txt`。这些依赖分别引入 dpdata、DPDispatcher 和 Textual。

`CONFIG` 可以是 JSON 文件路径，也可以是数据根目录 `run/` 内的配置名。数据根目录默认是仓库的 `data/`；环境变量 `AL_TDB_DATA_DIR` 或命令前置参数 `--data-dir PATH` 可以覆盖。网页与终端必须使用相同数据根目录。

```bash
python -m altdb --data-dir /path/to/data --json status my_phase
```

全局参数 `--json` 和 `--data-dir` 放在子命令之前。业务命令将进度和警告输出到 stderr，stdout 只有一个 JSON 结果；`--json` 选择紧凑格式。`--help` 和命令行参数拼写错误使用标准帮助文本。脚本以退出码判断成功、等待或失败，不要通过日志文字判断。

## 脚本运行

```bash
python -m altdb --json validate CONFIG
python -m altdb --json run CONFIG
python -m altdb --json status CONFIG
python -m altdb --json step CONFIG
python -m altdb --json import-results CONFIG /path/to/complete-calc.txt
python -m altdb --json export CONFIG --user cli --mask 5
```

`run` 连续推进到缺少 DFT 结果或候选耗尽。初次运行生成初始批次，缺少结果时正常退出并返回 **10**，可以交给上层脚本调度。`run --watch` 等待外部结果并继续推进；`run --max-steps N` 最多提交 N 个状态转换。`step` 初次只初始化，此后每次推进一个阶段：读入结果 → 训练 → 分析凸包并选点。

`import-results` 检查原有三列格式 `端元,DFT_1,DFT_2`，要求恰好覆盖当前批次，再原子写入 `calc.txt`。能量单位均为 eV/cell。TDB 导出仍是相片段，需要配套的元素参考数据库。

| 退出码 | 含义 |
| --- | --- |
| 0 | 当前命令成功；完整 `run`/`pipeline` 已完成，有限步数的运行以 JSON 状态为准 |
| 1 | 未分类运行错误 |
| 2 | 配置、输入或依赖错误 |
| 3 | 另一个进程正在操作该运行目录或 FP 批次 |
| 4 | 收集结果不完整或未通过校验；没有发布新的 `calc.txt` |
| 10 | `run` 等待 DFT 结果，不是计算失败 |
| 130 | 用户中断；已提交的远端任务不会因此取消 |

## VASP + Slurm

先复制并修改 [`examples/vasp_slurm/machine.json`](../examples/vasp_slurm/machine.json)。科学配置 `CONFIG` 描述相模型、参考能、描述符和选点；`machine.json` 描述执行环境、资源、VASP 命令和输入模板。

必须按实际环境填写：登录主机、用户名、远端工作目录、分区、节点/核数、模块名称，以及本机已有授权的各元素 POTCAR 路径。SSH 使用已有 SSH agent/默认密钥，或在 `remote_profile` 中设置 `key_filename` 的绝对路径。不要把密码或密钥内容提交到仓库。

`input_files` 和 `potcars` 的相对路径相对于 `machine.json` 所在目录解析。`machine.local_root` 由程序设为当前 FP 目录。直接在集群登录节点运行时，可改用 `context_type: "LocalContext"`，删除 `remote_profile`，保留 `batch_type: "Slurm"` 和集群工作目录。

示例 INCAR 是静态单点模板；晶格弛豫、磁性、截断能和 k 点收敛需要针对体系配置，尤其不能把 Al–Ni 演示的非自旋参数直接当作 Ni 的生产设置。若用弛豫，设置相应 `NSW`/`IBRION`；必须提供 `KPOINTS`，或在 INCAR 中设置 `KSPACING`。程序按每个 POSCAR 的实际元素顺序拼接 POTCAR，并检查 TITEL 的元素身份。仓库不附带 POTCAR 或 VASP 可执行文件。

```bash
# 第一步会在等待结果时返回 10
python -m altdb --json run CONFIG
python -m altdb --json fp prepare CONFIG machine.json

# 仅打印本地计划，不连接 SSH、不上传、不提交
python -m altdb --json fp submit CONFIG machine.json --dry-run

# 提交后返回；再次执行同一命令恢复调度状态
python -m altdb --json fp submit CONFIG machine.json

# 等待完成并取回结果
python -m altdb --json fp submit CONFIG machine.json --wait
python -m altdb --json fp collect CONFIG
python -m altdb --json run CONFIG
```

需整条流程无人值守运行时：

```bash
python -m altdb --json pipeline CONFIG machine.json
python -m altdb --json export CONFIG
```

`pipeline` 循环执行主动学习、prepare、submit/wait、collect，直到候选耗尽，或遇到输入/调度/结果错误。它会实际提交计算，请先检查本地计划。终端中断后，保持配置和输入不变，重复 `pipeline` 或相同 `fp submit` 命令恢复。远端作业不会自动取消；需要取消时在集群使用 Slurm 的 `scancel`。`fp submit --iteration N` 可同步此前某一轮；只有当前等待批次允许收集并发布训练数据。

## 文件、能量与可追溯性

```text
generated/0/tasks.json                   # 端元、POSCAR、原子数、校验值
calculated/iter.000000/
  calc.txt                              # 整批通过后才原子发布
  02.fp/
    manifest.json                       # 科学配置、环境配置与输入 SHA256
    dispatch.json                       # 提交状态、DPDispatcher submission hash
    collection.json                     # 来源校验值、最终帧、收敛与失败原因
    task.000000/                        # INCAR/POSCAR/POTCAR/OUTCAR 等
    task.000001/
    datasets/task.000000/                # 最终有效帧的 DeePMD/npy 数据
```

DPDispatcher 自身的恢复记录也会写在 `02.fp/` 中；请保留整个目录与远端工作目录。程序使用 `clean=False`，不自动清理远端结果。同一批次的准备和提交参数必须保持不变，避免重新提交时混用输入；改变科学输入或计算环境时另建运行目录。失败作业的重试由 DPDispatcher 管理。

默认用 dpdata 解析 `vasp/outcar` 的最后一帧，其 `energies` 是 VASP 的 **free energy TOTEN（eV/cell）**；不是自动选择的 `energy(sigma→0)`。参考能应采用一致的能量定义、赝势和数值设置，有限展宽的差异需要在科学计算方案中处理。当前适配器把同一个最终总能量写入旧格式的 `DFT_1` 和 `DFT_2`，模型仍读取 `DFT_2`。它尚不编排“先弛豫，再静态单点”的两段 VASP 作业，需这种流程时可通过明确的命令脚本提供最终 OUTCAR。

OUTCAR 必须完整结束、最终电子步收敛；弛豫任务还要求离子收敛标记。缺损帧不会被前一有效帧替代。收集同时检查元素计数、原子总数、能量/坐标/晶胞/力的有限性，并记录结果 SHA256。全部端元通过后才输出 `calc.txt`；部分完成或错误时保持等待，失败原因见 `collection.json`。

也可配置 `result_format: "vasp/xml"`、`result_file: "vasprun.xml"`，或导入 `deepmd/npy` 目录。`backward_files` 必须包含对应结果文件/目录。外部 DeePMD 数据标记为 `external_dataset`，表示只检查数据结构和数值，无法从该格式重新证明 VASP 收敛。每个端元导出独立的最终帧数据集，供后续 dpdata/势函数训练使用；当前实现不训练 Deep Potential 势。

## TUI 操作与并发

TUI 显示当前相、轮次、已保存阶段、写入占用状态、每个端元的准备/校验状态以及命令结果。支持推进到下一批、单步、准备、提交/同步、收集和导出。快捷键 `r` 运行、`s` 单步、`F5` 刷新、`q` 退出；路径输入框获得焦点时可正常输入字符。

“Submit / Sync FP” 是非阻塞提交：点击后通过相同入口再次同步，完成取回后点击收集。长时间等候与全自动批量运行请使用 CLI 的 `--wait`/`pipeline`。TUI 操作通过子进程调用相同 CLI，计算期间保持界面响应；当前操作结束后再退出，避免遗留子进程。

本机的网页、CLI 与 TUI 共享文件锁，阻止两个进程同时修改同一组或相互嵌套的工作输出目录。每轮 FP 操作另有锁，防止重复提交和同时收集。Web/`run --watch` 可等待 FP 收集的原子结果。锁是本机文件系统级协调，不代替跨主机的分布式调度；建议一个控制端管理一个数据根目录。

此前版本的生成目录如果没有 `tasks.json`，仍可用原有 `calc.txt` 流程恢复，但 FP 管理需要当前版本生成的任务清单。不要仅为使用新界面修改已有检查点内的配置。

## 参考与验证范围

分步操作借鉴 [DP-GEN 的 make/run/post 流程](https://docs.deepmodeling.com/projects/dpgen/en/latest/run/overview-of-the-run-process.html)，科学配置与计算资源分离参考其 [machine 配置](https://docs.deepmodeling.com/projects/dpgen/en/latest/run/example-of-machine.html)。调度直接使用 [DPDispatcher](https://docs.deepmodeling.com/projects/dpdispatcher/en/latest/)，数据解析与导出直接使用 [dpdata](https://github.com/deepmodeling/dpdata)。

测试包括真实 CLI 子进程、多轮人工能量闭环、Textual 无窗口交互、跨进程锁、真实 dpdata OUTCAR/DeePMD 解析、坏帧拒绝，以及真实 DPDispatcher Slurm 对象的参数/恢复标识校验。测试替换了远端提交边界，不会执行 `sbatch`。实际集群上的模块加载、SSH、分区权限、MPI 启动和 VASP 性能仍需用用户环境进行首批验收。
