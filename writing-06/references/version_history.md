# 版本与回退记录：rd-section-forge

本文件是包内**静态**版本记录，随包分发。每次 `build` 时由 `scripts/rd_assets.py`
复制到 `/app/output/version_history.md`，并在文末追加「本次运行」段；静态部分只读不改，
运行段只追加，因此任何一次运行都能看到“这个包从哪来、改过什么、怎么退回去”。

## 1. 版本轴

| 版本 | 日期（UTC） | 状态 | 内容 |
|---|---|---|---|
| v0 | 2026-11-13 | 云端初版（已提交） | `SKILL.md` + `scripts/rd_material.py` + `scripts/rd_sections.py` + 3 份 `references`，共 7 个文件；`init` / `check` / `build` 三命令；`result.json` 契约回填；产物只有正文与 4 份映射；无金标准、无逐项对照、无机器回执 |
| v1.0.0 | 2026-11-16 | 本次提交 | 原入口、参数、产物字节与报错口径不变；新增 `scripts/rd_assets.py`（5 个运行期核验资产）与 `references/version_history.md`（本文件）；`result.json` 顶层新增 `golden_standard` / `diff_report` / `version_history` / `run_log` / `self_check` 五个字段；`SKILL.md` 增一节说明资产 |

## 2. v1.0.0 改了什么

| 文件 | 动作 | 内容 |
|---|---|---|
| `scripts/rd_assets.py` | 新增 | 5 资产生成器：`golden_standard.json`（按 `output_contract` 逐键 + 材料逐条 locator/quote 的金标准）、`diff_report.md`（实际产物 vs 金标准逐项对照）、`version_history.md`（本文件的运行期副本 + 本次运行段）、`run.log`（阶段/耗时/退出码/降级/异常）、`self_check.json`（契约/主产物/引文/计数/兜底/退出码自检回执） |
| `scripts/rd_sections.py` | 增量钩子 | `main()` 记阶段起止、耗时、退出码；`build` 末调用资产 finalize 并回填 5 个 `result.json` 字段；`safe_fail` 也写最小资产；`build` 无前置 `init` 时补齐 `case_id` 与原始 `output_contract`（v0 该路径会丢，属小 bugfix）。子命令、参数、`--help`、原有产物与检查码表均未改动 |
| `references/version_history.md` | 新增 | 本文件（静态版本记录，供运行期复制） |
| `SKILL.md` | 增一节 | §15.1 说明 5 个资产、生成时机与判据；§4 产物目录、§14 产物清单、§16 包文件清单、§18 打勾清单同步；主体结构与写作规则未改 |
| `scripts/rd_material.py`、`references/{pipeline-contract,section-rules,audit-checklist}.md` | 未改 | 材料层与写作规则字节不变，避免回归 |

## 3. 为什么这样改

- 原包产物只回答“交付了什么”，不回答“**凭什么判定交付达标**”：没有金标准，评审无法逐项对照；
  没有逐项对照，缺失与偏差混在一起；没有运行日志，无法确认“真的跑过”；没有机器自检，
  可核验性只能靠作者自述。
- 5 个资产分别对应可核验性的五个问题：**期望是什么**（golden_standard）、
  **实际差在哪**（diff_report）、**版本怎么演进与回退**（version_history）、
  **这次到底怎么跑的**（run.log）、**机器敢不敢签字**（self_check）。
- 全部在 `build` 内生成、写进 `/app/output`，评审不读脚本也能复核；纯标准库、离线、
  不依赖当前工作目录、退出码恒 0。
- 只增量、不重写：v0 的已知行为（同输入产物字节、契约回填、检查码表、降级口径）保持不变，
  便于对照与回退。

## 4. 如何回退

1. **只撤销本次运行段**：从包内 `references/version_history.md` 重新复制覆盖
   `/app/output/version_history.md`，静态部分即恢复。
2. **回退到 v0 包行为**：删除 `scripts/rd_assets.py` 与 `references/version_history.md`，
   用 v0 的 `scripts/rd_sections.py` 覆盖当前脚本（两处新增 import/钩子随之消失）；
   `result.json` 删掉 `golden_standard` / `diff_report` / `version_history` / `run_log` /
   `self_check` 五个顶层键即可，契约字段与状态字段不受影响。
3. **只回退 result.json 形状**：同上第 2 条的后半句；资产文件留在 `/app/output` 不会影响旧逻辑。
4. **回退后自检**：`python3 scripts/rd_sections.py --help` 退出码 0；最小 case 走
   `init →（写 work/draft.json）→ check → build`，`manuscript.md` 与 v0 同输入逐字节一致，
   `status` / `contract_fields` 一致。

## 5. v1.0.0 文件指纹

sha256 前 16 位，用于回退时确认“确实是这版”。本文件（`references/version_history.md`）
含指纹表，不列自身。

| 文件 | bytes | sha256[:16] |
|---|---:|---|
| `SKILL.md` | 22314 | `7f7a11b648a5e6c3` |
| `scripts/rd_material.py` | 24826 | `4f59a11d04c97aa5` |
| `scripts/rd_sections.py` | 33074 | `7711641e1584454d` |
| `scripts/rd_assets.py` | 52195 | `ac5d2cd9de78291c` |
| `references/pipeline-contract.md` | 7881 | `fef712f55832f117` |
| `references/section-rules.md` | 5141 | `b636602bbd67e969` |
| `references/audit-checklist.md` | 3891 | `a099668fc3e3f9ba` |

## 6. 维护约定

- 改词表：同步 `scripts/rd_sections.py` 的 `CAUSAL/HYPE/BOUNDARY` 与
  `references/section-rules.md`；改契约路由：同步 `rd_material.CONTRACT_ROUTER` 与
  `rd_assets.CONTRACT_TEXT`。
- 新增核验资产必须仍写进 `/app/output`，并在 `result.json` 顶层挂一个同名字段；
  不允许只写进日志。
- 任何改动后重跑最小 case，确认原有 7 个产物与 v0 差异只来自本次改动；
  `self_check.json` 的 7 项检查应全为 true（空/坏输入用例允许 `status` 非 ok，但退出码仍为 0）。
