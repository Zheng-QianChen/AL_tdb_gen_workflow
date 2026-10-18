# 二元相图文献与计算归档

文献记录与数据库计算需要分开判定：导入成功、求解收敛、相区拓扑一致及实验误差合格是不同结论。当前 Co–Cu–Fe–Ni–Ta–Ti–W 的 21 个体系中，18 个通过计算运行审计，10 个完成局部实验对照，没有任何一个被认定为完整相图已通过实验验收。

## 目录和可复现入口

研究数据保存在用户指定的独立数据目录，不随公开代码分发。数据包括原始 TDB、适配副本、原生输入输出、被拒绝的计算、实验记录、来源、下载状态与报告。新建归档不会覆盖已有目标。

```bash
python -m examples.seven_binary_archive \
  --study /path/to/seven_element_validation_20261018 \
  --output /path/to/new_snapshot
python /path/to/new_snapshot/verify_archive.py
```

归档生成器仅整理已有证据，不调用商业软件，不重新求解或自动抓取文献。完整程序要求 Python 3.11+；归档自带校验器只需 Python 3.6+ 标准库。

- `index.html`：21 个体系的可点击目录与局限。
- `binaries/<体系>/index.json`：对应的来源、数据、计算判定及文件索引。
- `catalog.json`、`sources.json`、`records.jsonl`：总索引、来源和结构化证据。
- `search_events.json`：前轮逐体系台账及追加检索记录。
- `study/`：取得的原始文件逐字节快照；`calculated.exp` 是计算曲线。
- `manifest.json`：文件大小和 SHA256；验证时检测缺失、篡改及额外文件。

“全部数据”指本次实际取得的文件和记录，不代表穷尽所有公开文献或已数字化原图中的每个散点。原文受限、缺少不确定度、历史拓扑修订、压力不符、亚稳样品和评估计算图均要单独注明。样品化学分析表也不能当成相界端点。

2026-10-19 追加记录中，Fe–Ti 的 1957 年原始论文提供了样品成分表和退火后相组成。数据库的 Fe–Ti 导入问题仍在，故新增证据保留为待比较。[原始论文](https://doi.org/10.2320/jinstmet1952.21.11_665)。Fe–Ta 的独立二元实验文献也已定位，但完整数表尚待取得。[原始研究](https://doi.org/10.1016/j.intermet.2011.03.018)。

Cu–W 评估图明确属于模型计算，并有压力范围限制，不能用作常压实验真值。[作者保存的评估](https://www.andrew.cmu.edu/user/dl0p/laughlin/pdf/130.pdf)。

## 本机计算环境

七元研究脚本使用 `AL_TDB_STUDY_DIR` 指定研究数据根目录，默认采用仓库下的历史研究目录名。原始 `source_v6.tdb` 必须由用户自行提供，不随程序分发。

Thermo-Calc 研究适配器读取 `TC26B_HOME`，Pandat 读取 `PANDAT_EXE`；仅在实际执行对应计算时要求安装路径存在。其他交叉引擎脚本使用必填的 `--home` 或 `--exe` 参数。需要用户自己的合法安装与许可；Windows 上保持后台运行，Python 启动代码不再无条件调用 Windows 专用 API。此改动不代表已验证商业引擎的 Linux 安装。

公开 `docs/validation/` 中只保留数值、版本、来源与哈希，并用占位符替换本机路径；完整原始记录保存在私有研究快照中。
