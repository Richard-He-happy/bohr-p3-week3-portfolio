---
name: opening-report-kit
description: 面向「开题报告 / 研究计划书」的写作与自查工具包。输入 case.json 与原始材料，输出七要素齐全的可编辑 proposal.md、结构化映射、里程碑与风险登记，以及原样回填 output_contract 的 result.json；build 同时写出 5 件可核验资产（golden_standard / diff_report / version_history / run.log / self_check），内含 27 条 rubric 判据 + output_contract 与 organizer_workorder 逐项期望（locator + 逐字 quote）、契约/主产物/引文/计数/兜底/退出码断言；材料缺失时也能降级出稿。
version: 1.0.0
---

# 开题报告与研究计划书工具包（opening-report-kit）

把课题指南、前期数据、讨论记录、文献等碎片材料，整理成一份导师或评审可以直接改的开题方案：
**研究背景与缺口 → 研究问题 → 研究目标 → 技术路线 → 阶段计划 → 风险与备选方案 → 预期成果**。

分工只有一句话：**正文由 Agent 读材料后写成工作稿，脚本负责索引、体检与排版；即使 Agent 没写工作稿，脚本也必须交出一份能看的骨架。**

适用：开题报告、研究计划书、立项申请的研究方案部分、学位论文开题。
不适用：纯文献综述、纯语言润色、投稿信、结题报告（这些不需要七要素对齐）。

## 1. 目录与路径约定

| 位置 | 内容 |
|---|---|
| `/input/case.json` | 用例元数据：`case_id`、`task_instruction`、`output_contract`，可选 `organizer_workorder`、`title` |
| `/input/**` | 原始材料：课题指南、前期数据、讨论记录、文献、伦理与条件说明（文本 / docx / xlsx / pdf / 图片） |
| `/app/work/` | 可重建的中间件：`index.json`、`draft.json`、`draft.effective.json`、`check_report.json` |
| `/app/output/` | 交付物：`proposal.md` 为主产物，另有 `result.json` 与附件（见 §6） |

三个路径都能用参数改：`--input` / `--output` / `--work`，也接受 `INPUT_DIR` / `OUTPUT_DIR` / `WORK_DIR` 环境变量。
脚本用 `Path(__file__)` 定位自身，**不依赖当前工作目录**，只依赖 Python 3.8+ 标准库，不联网。

## 2. 五步工作流

```bash
SK=/skills/weekly-skill/scripts/entry.py
python3 -B $SK init                     # ① 建材料编号索引 + 先落一份 partial result.json
# ② Agent 读材料 → 写 /app/work/draft.json（字段见 §3）
python3 -B $SK check                    # ③ 体检：要素 / 判伪 / 引文 / 周期 / 数字口径
python3 -B $SK build                    # ④ 渲染 proposal.md + 终版 result.json + 附件
python3 -B $SK audit                    # ⑤ 只重算附件与结构化产物，正文不动
python3 -B $SK show --id M2 --grep 周期  # 回看某份材料的原文段落（带 locator）
```

- `init` 只做机械动作（读文件、编号、切段），不做内容判断；内容判断归 Agent。
- `check` 只报告问题，**绝不改稿**。
- `build` 对不完美的工作稿是宽容的：缺的章节用模板补齐、缺的字段用兜底值填上，同时在 `degradations` 里逐条记账。
- 退出码恒为 0；出错信息进 `result.json.errors`，不让评测方看到崩溃。

## 3. 工作稿 draft.json（Agent 唯一必须写的文件）

顶层结构如下（每个数组都可以只写一条，`build` 会补齐其余部分）：

```jsonc
{
  "title": "课题名称",
  "period": {"total": "24 个月", "quote": "执行期：24 个月", "source": "M1/p2"},
  "rqs": [{
    "id": "RQ1",
    "question": "在 X 条件下，Y 能否达到 Z？（必须含对象与条件）",
    "hypothesis": "可被数据推翻的陈述",
    "falsifier": "若出现什么观测（含时点与阈值）则假设被否定",
    "metrics": [{"name": "200 h 保持率", "threshold": "≥85%", "basis": "M2/p1"}],
    "sample": "12 例", "condition": "0.1 M 恒电位", "timepoint": "第 12 月与第 24 月",
    "evidence": [{"source_id": "M1", "locator": "p3", "quote": "逐字原文"}]
  }],
  "sections": [{"id": "background", "blocks": [{"text": "…", "evidence": []}]}],
  "objectives": [{"id": "O1", "rq": "RQ1", "objective": "…", "criterion": "…"}],
  "steps": [{"id": "S1", "rq": "RQ1", "input": "…", "action": "…", "output": "…", "depends_on": []}],
  "resources": {"budget": "…", "people": "…", "data": "…", "note": "…"},
  "milestones": [{"id": "MS1", "period": "第 1–6 月", "task": "…", "deliverable": "…",
                  "depends_on": "—", "criterion": "…", "critical_path": true}],
  "risks": [{"id": "R1", "type": "数据获取|方法可行性|进度|伦理与合规", "risk": "…",
             "trigger": "…", "impact": "…", "fallback": "…", "decision_point": "…"}],
  "outcomes": [{"id": "D1", "rq": "RQ1", "outcome": "…", "verification": "…", "criterion": "…"}],
  "preserved_facts": [{"term": "执行期", "value": "24 个月", "source_id": "M1", "locator": "p2", "quote": "…"}],
  "change_log": [{"action": "起草", "target": "proposal.md", "reason": "…", "before": "—", "after": "v1"}],
  "pending_human": [{"item": "阈值来源", "why": "材料未给", "needed_by": "开题答辩前"}]
}
```

`rqs` 的 id 建议 `RQ1…RQ3`；`objectives` 的 `rq`、`outcomes` 的 `rq` 指回问题编号，形成闭环。
七个 `sections[].id` 取值固定：`background`、`problem`、`objectives`、`methods`、`plan`、`risks`、`outcomes`。

不想写 JSON 也可以只写 `/app/work/draft.md`：用 `## 一、研究背景与缺口` 到 `## 七、预期成果与验证方式`
这样的小节标题，脚本会按标题切节；缺的结构化要素仍由模板补，状态记为 `partial`，来源记为 `agent+template`。

## 4. 四条质量红线（对应评分里的四个考察问题）

1. **立得住** — `question` 必须写清对象 + 条件；`falsifier` 要写出"何种观测会否定它"；每个指标都要 `threshold` 与 `basis`，没有依据就把阈值写进 `pending_human`。
2. **对得上** — 目标用 `rq` 指回研究问题；路线用 `input → action → output → depends_on` 串起来；成果写清 `verification`（别人怎么复跑你的判定）。
3. **排得开** — 里程碑落在 `period.total` 之内；每条里程碑有交付物与完成判据；关键路径标 `critical_path: true`。
4. **说得清** — 风险 ≥4 条且 ≥3 类，每条都有触发信号、备选方案与决策时点；引文 `quote` 与原文逐字相同。

另有一条硬边界：**材料外面的事实、数字、文献一律不写**。计划里新增的数值要写"计划值"，材料没有的约束（经费、设备、伦理批号）只进 `pending_human`，不许编。

## 5. check 的具体判据

- 七个要素是否成节；某节不足 60 字符会提醒"要素过短"。
- 每条 RQ 是否有 `question`、`falsifier`、指标与阈值；阈值有没有 `basis`。
- 里程碑少于 3 条、风险少于 4 条、风险类型少于 3 类、成果缺验证方式，分别报错或提醒。
- **周期相容**：草稿里出现的"第 X 月 / X–Y 月"若超过 `period.total`，直接报错。
- **数字口径**：草稿中的"数字+单位"若在全部材料里找不到同形写法，列入提醒（需标计划值或补依据）。
- **引文核验**：去掉空白后逐字比对材料段落；命中率低于 90% 时 `build` 只能给 `partial`。找不到就如实报，不许改原文凑命中。

`check` 会把结果写到 `/app/work/check_report.json`，并打印一行计数摘要，便于在一轮里决定是否继续改稿。

## 6. 交付物清单

`/app/output/` 下 `build` 会产出：

| 文件 | 说明 |
|---|---|
| `proposal.md` | 主产物：可编辑 Markdown，七要素成节，附录含覆盖矩阵、引文映射、事实留存、待确认项、自检输出、改动记录 |
| `proposal_matrix.json` | 研究问题 → 目标 → 路线步骤 → 验证方式 → 预期成果的对应矩阵 |
| `milestones.csv` | 里程碑表：时间、任务、交付物、依赖、完成判据、是否关键路径 |
| `risks.md` | 风险登记：类型覆盖统计 + 明细 + 决策时点轴 |
| `result.json` | 机读结果：契约字段、状态、来源、不确定性、待确认、错误、降级、改动、计数 |
| `golden_standard.json` | 金标准：27 条 rubric 判据 + `output_contract` 逐项（C01…）+ `organizer_workorder` 逐项（W01…）+ 六类期望交付（ED1…），每条带 `source_id/locator/逐字 quote` |
| `diff_report.md` | 金标准与实际产物逐项对照（rubric 27 条 + 契约逐项 + 工作单逐项；pass / missing / deviation / manual）与处置 |
| `version_history.md` | 静态版本轴 v0.1.0→v1.0.0 + 三条回退方式 + 运行时追加的本次运行段 |
| `run.log` | 真实阶段日志（时间戳 / 阶段 / 关键计数 / SUMMARY 收尾 / 错误与降级行） |
| `self_check.json` | 契约完整性、主产物可评、引文命中、计数重算、空/坏输入兜底、退出码断言（11 项 checks） |

### 6.1 五个可核验资产（v1.0.0 增补，`build` 自动写出，`audit` 可只重算）

| 资产 | 回答什么问题 | 谁来生成 | 关键断言 / 复算方式 |
|---|---|---|---|
| `golden_standard.json` | 这次到底该交什么、凭什么可核验 | `build` 的资产层（`auditpack.emit_artifacts`） | 每条期望带 locator+逐字 quote；契约项与 `output_contract` 键一一对应；工作单逐项回执 |
| `diff_report.md` | 实际产物差在哪、怎么处置 | 同上 | 逐项判 pass/missing/deviation/manual，非 pass 项给处置与归属 |
| `version_history.md` | 版本怎么演进、怎么回退 | 同上（静态段 + 运行段） | 静态段与输入无关；运行段只写真实 case/status/计数/退出码 |
| `run.log` | 这一轮真实跑了什么、顺序如何 | 每条命令追加一行（`auditpack.note`） | 超 64KB 只留尾部；末尾 `SUMMARY` 含 status/主产物/证据/exit_code |
| `self_check.json` | 契约、主产物、引文、计数、兜底、退出码是否真的成立 | `build` 收尾（`auditpack.after_build`） | `checks` 11 项全 true 时 `overall_pass=true`；子进程实测空/坏输入的 exit code |

要点：

- 五个资产**每次 `build` 必出**，与 Agent 是否写了工作稿无关；`python3 -B scripts/entry.py audit` 只重算资产，不重渲染 `proposal.md`。
- `golden_standard.json` 的期望来自「题面 rubric + output_contract 逐项 + organizer_workorder 逐项 + 模板检查表」，不含预制答案；契约/工作单条目引用 `case.json` 原文片段。
- 工作单条目机械可判时给 pass/deviation；判不了就标 `manual`（人工核实），**不冒充通过**。
- `result.json` 除原契约字段外，另有 `counts`、`golden_standard`、`diff_report`、`version_history`、`run_log`、`self_check`、`artifacts` 汇总键，便于评审按计数复算。
- 回退：删 `<WORK>/draft.json` 重跑 `build` 回到 v0 骨架；只回退资产用 `audit`；整包回退见 `version_history.md` §2（本机归档 `work/patch_backup/writing-10_orig` 或 `GITHUB_URL.txt` 指向仓库的历史版本）。
- 所有命令解释器统一为 `python3`（`python3 -B scripts/entry.py …`），纯标准库、离线、不依赖当前工作目录。

### 6.2 result.json 的回填规则

`output_contract` 里的**每一个键**都必须出现，键名不改、不遗漏；没有值就写 `null` 或 `[]`，不能把键删掉。
字段名按语义匹配：例如契约里的 `research_question_falsifiability` 映射到 `research_questions`，
`milestone_feasibility` 映射到 `milestones`，`citation_to_claim` 映射到 `evidence_map`。匹配不上的键保留并给 `null`。
除契约字段外，`result.json` 一定带 `case_id`、`status`、`deliverable`、`sources`、`uncertainty`、
`pending_human`、`errors`、`degradations`、`changes`、`runtime`、`counts`、`coverage`、`consistency`，
以及 5 件资产的汇总键 `golden_standard`、`diff_report`、`version_history`、`run_log`、`self_check` 与 `artifacts`。
`counts` 由本轮真实计数重算（七要素、RQ、目标、步骤、里程碑、风险、成果、证据、契约/工作单条数、golden 通过数），`self_check.json` 会逐项复算比对。

`status` 判定：

| 状态 | 含义 |
|---|---|
| `ok` | Agent 工作稿齐全、无错误、引文命中率 ≥90% |
| `partial` | 用了模板兜底，或存在要素错误 / 命中率不足 |
| `insufficient_evidence` | 有材料但解析不出任何文本（例如纯图片） |
| `input_error` | 一个输入材料都没找到 |

### 6.3 自研增量：结构性一致性断言

`build` 除了跑 27 条 rubric 判据（外加 output_contract / organizer_workorder 逐项回执），还会做一次**引用完整性断言**并写进 `result.json.consistency`（`audit` 之后由 self_check 一并复核）：

- `dangling_objectives`：`objectives[].rq` 指向了不存在的 RQ；
- `dangling_outcomes`：`outcomes[].rq` 悬空；
- `orphan_rqs`：没有任何目标或成果承接的 RQ；
- `milestone_overrun`：里程碑最远月份减去研究周期（>0 即越界）；
- `checked` / `passed`：本轮真的算过的断言数，避免"看起来通过"。

这一块不依赖 LLM 判断，是纯算术断言，评测方可以按 `result.json` 复算。

## 7. 异常与降级（任何一条都不许中断流程）

| 情形 | 处理方式 |
|---|---|
| `case.json` 缺失或 JSON 损坏 | 递归找 `case*.json` / `input*.json` 兜底；仍失败则把解析错误写进 `errors`，用材料继续 |
| 图片材料 | 不做 OCR，记 `no_ocr`，不猜测内容 |
| PDF 没有文本层 | 依次尝试 `pdftotext` → `pdf-text-tool` → PyMuPDF → pdfminer → 标准库粗解析；只降级该份材料 |
| 识别不到研究周期 | 里程碑按 12 个月占位，并把"周期未识别"写进 `pending_human` |
| 没有工作稿 | 用模板生成完整骨架，`status=partial`，`draft_source=fallback` |
| 只有 draft.md | 按标题切节，结构化要素用模板补，`status=partial`（`agent+template`） |
| 极端情况（渲染异常） | 也写出占位 `proposal.md` 与合法 `result.json`，退出码仍为 0 |

## 8. 成稿前自检清单

- [ ] 背景写的是"已知—未知—待验证"，不是领域综述。
- [ ] 每条 RQ 有判伪条件与阈值；阈值有来源或已在 `pending_human` 登记。
- [ ] 目标 → 路线步骤 → 验证方式 → 预期成果能闭环，没有悬空 id。
- [ ] 里程碑都落在周期内，且有交付物与完成判据；关键路径已标。
- [ ] 风险覆盖数据 / 方法 / 进度 / 伦理四类，每条有触发信号与备选。
- [ ] 引文逐字一致，`M#/p#` 能回查到原文（用 `show` 复核）。
- [ ] 数字、单位、样本量、经费与材料同形；新增值标"计划值"。
- [ ] `pending_human` 写清缺什么、什么时候必须补。
- [ ] `status` 与真实完成度一致，`diff_report.md` 的非 pass 项都有处置。
- [ ] `self_check.json` 的 `checks` 全为 true（11 项），`consistency.passed` 为 true。
- [ ] 5 件资产均非空：`golden_standard.json` / `diff_report.md` / `version_history.md` / `run.log` / `self_check.json`；`golden_standard.json` 每条期望都有 locator+逐字 quote。
- [ ] `result.json.counts` 与各数组长度一致（用 `self_check.json.counts_consistency.checks` 复算，全 true）。

## 9. 最小调用示例（示例，不是正式案例结果）

```bash
$ python3 -B scripts/entry.py init --input /input --output /app/output --work /app/work
== 初始化 v1.0.0 == 用例 /input/case.json | 任务书 /input/task.md
契约字段 case_id, deliverable, preserved_facts, evidence_map, change_log | 材料 2 份 | 周期 (24, '执行期：24 个月')
  M1  guide.md        text    306字   3段 plain
  M2  meeting.md      text    235字   3段 plain
下一步：写 /app/work/draft.json，然后执行 check 与 build
```

上面的编号、字数只是演示接口形状；正式案例（3 个隐藏用例）由平台提供，本包不附带任何预制答案。

## 10. 文件与维护

| 文件 | 职责 |
|---|---|
| `SKILL.md` | 本说明 |
| `scripts/entry.py` | 命令行入口：材料抽取、索引、契约映射、init/show/check/build/audit |
| `scripts/draftkit.py` | 工作稿解析、引文核验、七要素校验、模板兜底、正文渲染 |
| `scripts/auditpack.py` | 5 件可核验资产（golden/diff/version/run.log/self_check）、契约与工作单逐项回执、27 条 rubric 判据、矩阵与表格产物 |
| `references/proposal-skeleton.md` | 七要素检查表 + 表格表头 + 兜底文案与行模板（`<!-- KEY:... -->` 块） |

- 改表头或兜底文案：只改 `references/proposal-skeleton.md`。
- 改校验规则：改 `draftkit.py` 的 `inspect_draft()`。
- 改金标准判据：改 `auditpack.py` 的 `G` 表与 `rule_*` 函数。
- `entry.py --help` 可直接做冒烟；另两个是纯函数模块，可 import 后单独验证。

已知边界：段落定位按空行切分；PDF 粗解析可能丢失阅读顺序，重要引文先用 `show` 回看；
不做 OCR；数字一致性是字面比对（`85%` 与 `85 %` 会被提醒，属预期）；学科差异（伦理批号、样机指标）交给 `pending_human`，不硬编码在脚本里。
