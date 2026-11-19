# Windows 双击启动

先安装 64 位 Python 3.11 或 3.12，将发行 ZIP 完整解压。双击 `Start-AL-TDB.cmd`，首次启动会在用户目录建立虚拟环境并安装工作流、DPDispatcher、dpdata 和 pycalphad，首次安装需要联网。服务就绪后在 Edge 独立窗口打开项目工作台。再次双击可回到正在运行的同一服务。

保留启动窗口即可持续服务。按 Ctrl+C 或运行 `Start-AL-TDB.cmd --stop` 可关闭本次实例。默认监听 127.0.0.1:8003，端口已占用时顺延，可在窗口中看到实际地址。

| 可选环境变量 | 用途 |
|---|---|
| AL_TDB_PYTHON | 指定 Python 解释器。源码模式可直接使用已具备运行依赖的环境。 |
| MP_API_KEY | Materials Project 查询凭据，在启动服务前设置 |
| AL_TDB_PORT | 首选本机端口 |
| AL_TDB_DATA_DIR | 计算和结果目录。安装包默认使用用户目录下的 .altdb/data。 |
| AL_TDB_MACHINE_DIR | 服务管理员维护的 DPDispatcher 机器配置目录 |
| AL_TDB_RUNTIME_DIR | 虚拟环境与启动状态目录。默认使用用户目录下的 .altdb/runtime。 |

从源码启动也可双击仓库根目录的同名脚本。构建 ZIP 时先运行 `python -m build --wheel`，然后运行 `python tools/build_windows_bundle.py --wheel WHEEL_PATH`。产物在 dist 目录。

在项目的参数优化页选择 AL–TDB 即可使用内置有限温 CALPHAD 拟合器。Pandat 和 Thermo-Calc 默认导出请求 JSON。已有本地商业软件适配器时，可分别用 AL_TDB_PANDAT_FIT_ADAPTER 和 AL_TDB_TC_FIT_ADAPTER 指向管理员配置的可执行文件。适配器依次接收请求 JSON 路径和输出 candidate.tdb 路径，成功后返回 0。服务核对输出能否重读及所选相名。
## 超算任务观测

从侧栏的「计算与建模 → 超算任务」打开跨项目作业列表。DPDispatcher 提交回执提供平台、计算轮次、调度编号和任务数。多项端元计算可以合并为一个调度作业。旧回执缺少编号时按批次显示。点击模型名可以回到对应的作业工作台。

服务器可接入调度器或资产管理系统定期写出的 JSON 快照。启动前设置环境变量 `AL_TDB_HPC_OBSERVATIONS` 为快照路径，`AL_TDB_HPC_PROJECTS` 为允许展示的外部项目标识（多个用逗号分隔）。要关联单相模型，使用 `外部项目标识=工作台项目ID`；平台标识应与 DPDispatcher 机器配置文件的文件名主干一致。查询作业使用项目、平台和调度编号三者匹配。建议观测端使用原子替换更新快照。

快照含有带时区的 `observed_at` 和 `jobs` 对象，每项含 `project`、`platform`、`scheduler_id` 和 `raw`，可附 `queue` 和该项自己的 `observed_at`。例如：

```json
{"observed_at":"2026-01-01T12:00:00+00:00","jobs":{"example":{"project":"demo","platform":"slurm","scheduler_id":"123","raw":"PENDING","queue":"batch"}}}
```

页面每 30 秒读取一次。快照或单条观测超过 `AL_TDB_HPC_STALE_SECONDS`（默认 300 秒）时，非终态作业显示上次观测，退出实时排队与运行计数。未配置观测源的安装仍可查看提交回执。

使用 orgkit 的部署可将 `AL_TDB_HPC_CATALOG` 指向其作业目录 SQLite 文件，以只读方式补充已取得调度编号的提交回执。服务端应用相同项目范围。旧式独立运行配置可以用 `外部项目标识=@standalone` 关联。
