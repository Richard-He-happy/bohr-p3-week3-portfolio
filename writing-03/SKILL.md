---
name: citation-grounded-writing
description: >-
  把"需要文献支撑的写作任务"做成可复核的三段交付：先切出论断清单，再为每条论断匹配材料中的逐字原文与定位并给出四因子证据强度，最后生成语气与强度相称、冲突与缺口显式保留的可编辑成稿；并强制产出金标准、对照报告、版本记录、运行日志与机器自检五件可核验资产。适用于补引用、核对论断是否被原文支持、评审证据强度、改写过度推断段落等场景。
version: 1.1.0
license: MIT
---

# 引文有据写作（writing-03）

## 它解决什么

学术写作里最容易失控的不是"写不出来"，而是写出来的句子说不清依据。本工作流把一次写任务拆成可回查的三层：**论断 → 依据 → 成稿**。任何一层都能单独被人拿到原始材料上复核，而不是只看一份读起来通顺的终稿。

适用场景：补引用、改讨论段、核论断、审证据强度、给结论加不确定性。触发条件是输入里有 `case.json` 与若干材料文件。

## 五个不可让步的点

1. **可定位**：论断按句切开，每条都带文件、块句号与字符区间。
2. **可对原文**：证据引文从材料原样复制，脚本重新读材料逐字核对；文献著录只抄不补。
3. **可判断强度**：设计类型、样本量、独立来源数、是否存在冲突四项合成分档，正文语气随分档走。
4. **可重跑**：三份产物用同一个 `claim_id` 串联，复核脚本独立重算，计数写进 JSON。
5. **可核验**：每次成稿同时落五件资产（金标准、对照报告、版本记录、运行日志、机器自检），让第三方不依赖本 Skill 的自述也能复核。

同时在材料允许范围内保持克制：不联网、不凭记忆添文献、不编数字、不把相关性写成因果、不把"没找到"说成"不存在"。

## Agent 必须走的流程（先读材料，再写稿）

**这一步不能省。** 评测 Agent 必须先看材料、亲自判断哪些句子是可判定论断、哪一段原文真正支撑它，把结论写进工作稿，再由脚本校验与成稿。**禁止只运行 `build` 就结束**——那样脚本只能按启发式自动组合，虽然仍有完整交付物，但状态会诚实地记为 `partial`，而且论断与证据的对应质量明显低于亲读材料后的版本。

```bash
# ① 建索引 + 先落 partial result.json（同时打印材料清单）
python3 /skills/weekly-skill/scripts/pipeline.py init

# ② 打印带 locator 的原文；引文必须从屏幕上逐字复制（含标点）
python3 /skills/weekly-skill/scripts/pipeline.py show --limit 80

# ③ Agent 亲自读材料，写 /app/work/draft.json（下一节），用逐字 quote
#    写完再跑 check 看引文是否命中、字段是否齐全
python3 /skills/weekly-skill/scripts/pipeline.py check

# ④ 成稿 + 终版 result.json + 五件可核验资产
python3 /skills/weekly-skill/scripts/pipeline.py build

# ⑤ 独立复核：重读材料再算一遍，写 verification.json
python3 /skills/weekly-skill/scripts/pipeline.py audit
```

路径与解释器兼容约定：

- 若 `/skills/weekly-skill` 不存在，把命令里的脚本路径换成实际安装位置，例如 `cd <skill 目录> && python3 -B scripts/pipeline.py build`。
- 若环境只有 `python` 没有 `python3`，用 `python -B ...`；两种写法语义相同。
- 每条命令都接受 `--input/--output/--work`，默认 `/input`、`/app/output`、`/app/work`；也可用环境变量 `SKILL_INPUT/SKILL_OUTPUT/SKILL_WORK` 覆盖。纯标准库、离线、不依赖当前目录。
- **单命令兜底**：`init/show/check/audit` 发现输出目录还没有完整交付物时，会自动补一次"从材料组合"的兜底成稿并落五件资产。因此即使只跑了一条命令，`/app/output` 也不会是空目录；但要让 `status=ok`，仍需写工作稿后跑 `build`。

## 工作稿 `/app/work/draft.json`（Agent 唯一必写文件）

```jsonc
{
  "case_id": "…",
  "claims": [
    {"claim_id": "C01",
     "text": "成稿里的判断句（可含 [n]）",
     "core": "去掉句末引用标记后的判断",
     "type": "事实|推断|因果|比较",
     "location": "原稿/材料位置，如 draft:讨论第2句",
     "source_id": "D03",                         // 材料文件编号，用 init 打印的编号
     "locator": "source_A.md [B3.S2] chars:143-276",
     "quote": "从材料逐字复制的支撑片段（含标点，不得改写/翻译/拼接）",
     "strength": "高|中|低|不足",                 // 可不填，脚本按四因子重算
     "support_scope": "直接支撑/部分支撑（范围不一致）/无直接支撑",
     "conflicts": [{"source_id": "D04", "quote": "相反结论的逐字原文", "locator": "…"}]}
  ],
  "preserved_facts": [{"term": "样本量", "value": "412", "source_id": "D03"}],
  "change_log": [{"action": "add_citation", "before": "…", "after": "…", "reason": "…", "locator": "…"}],
  "notes": "可选：材料缺口、待人工确认项"
}
```

规则：

- `quote` 必须能在材料中**逐字**命中；未命中的行会被丢弃、记入 `degradations` 与 `pending_human`，脚本不会改原文凑通过。
- 也可以只写 `/app/work/draft.md`（成稿草稿），脚本按句切分后逐句补证；此时状态至少为 `partial`。
- 工作稿里每条论断的 `claim_id` 会一路贯穿 `claims.json → evidence_table.json → result.json.evidence_map → 成稿引用锚点`。
- 只观察到关联、无随机化/干预对照时，不要写成因果；单篇小样本不要写成领域共识；冲突来源不要隐藏，写进 `conflicts`。

## 文件与入口

| 文件 | 用途 |
|---|---|
| `SKILL.md` | 本说明 |
| `scripts/pipeline.py` | 五命令入口：索引 / 展示 / 校验工作稿 / 成稿 / 复核，并生成五件资产 |
| `scripts/audit.py` | 文本抽取与规则工具 + 独立复核（写 `verification.json`） |
| `scripts/assets.py` | 五件可核验资产生成层（金标准 / 对照 / 版本 / 日志 / 自检） |
| `references/output_contracts.md` | 产物字段与 `result.json` 契约 |
| `references/grading_manual.md` | 强度算法、语气映射、下调规则、异常处置 |
| `references/terms_zh2en.tsv` | 中英概念词表（Tab 分隔，可追加） |

所有入口退出码恒 0。生成器在开始时就写一份不完整的 `result.json`，运行中任何一步抛异常都会被兜住并在最后补齐字段，因此磁盘上不会出现半截 JSON。复核器不读产物里"自报"的结论，而是重新解析输入目录再比对。

## 输入与输出位置

- 输入：`/input/case.json`（含 `case_id`、`task_instruction`、`output_contract`）、`/input/task.md`、`/input` 下的材料文件。
- 输出：`/app/output`；工作目录 `/app/work`。
- 材料类型识别：文件名带 draft/manuscript/原稿/初稿 的视为待改稿；带 ref/bib/reference/文献 的视为文献表；其余视为来源材料。识别只用于选择流程，不改动文件内容。
- 支持文本、Markdown、JSON、CSV、DOCX 与带文本层的 PDF；图片、扫描件、xlsx/pptx/doc 走降级路径。
- 脚本不依赖启动目录，资源路径由 `__file__` 推出。

## 主流程

1. 扫描输入目录，解析每个文件并记录字节数、sha256、解析方式；单文件解析失败只登记降级。
2. 决定论断来源：有 Agent 工作稿时用工作稿的论断与证据（引文逐字复核）；没有工作稿时逐句切原稿（剥掉句末引用标记得到 `core`）；既无工作稿也无原稿时用任务指令与 `source` 元数据组成主题，从材料里挑与该主题最接近的句子，同一文件最多 2 条以避免来源单一。
3. 给每条论断找依据：术语表归一后比较概念集合重叠，数字相同再加权；若原句自带 `[n]`，先把文献表第 n 条映射到具体文件，优先在该文件内找、阈值放宽。证据只从"来源材料"里取，不从待改稿和文献表里取。
4. 计算强度：设计 + 样本 + 重复来源 − 冲突，再套预印本/小样本/仅摘要三个封顶。
5. 记录冲突：同一论断下主题相近而结论方向相反的来源写入 `conflicts`，成稿另起转折句呈现。
6. 生成成稿：每句 = 与强度匹配的限定语 + 判断 + 引用编号；末尾固定"证据边界"和"参考文献"；有原稿或成稿草稿时沿用原小节与段落顺序。
7. 下调过度推断：没有随机化或干预对照时把因果表述改成关联表述，把绝对化量词改成范围限定；只改措辞，数值原样保留，每处改动进 `change_log`。
8. 收尾：逐字校验、join 校验、计数、`pending_human`，覆盖写终版 `result.json`，再生成五件可核验资产；若 `case.json` 带 `organizer_workorder`，把其中能量化的要求（字数上限、引用条数、引用风格）逐条执行并在 `workorder_receipt` 回报，不能判定的标 `unverifiable`。

## 三段产物

`claims.json` 的每条：`claim_id`、`location`（原稿位置或材料定位）、`text`（原句）、`core`（去掉引用标记的判断句）、`type`（事实/推断/因果/比较）。

`evidence_table.json` 的每行：`claim_id`、`source_id`、`locator`、`quote`、`source_type`、`strength`、`support_scope`、`conflicts`、`rationale`、`verified`。定位统一写成"相对路径 + `[B块.S句]` + `chars:起-止`"，便于回到原文。

成稿 `evidence_driven_draft.md` 里每个 `[n]` 都要能在参考文献段找到对应条目；材料没给 DOI 就不写 DOI。同目录另留 `deliverable.md` 作为文件名兼容副本，并生成 `evidence_strength.md`、`reference_check.md`、`uncertainty_notes.md`、`pending_human.json` 四份辅助记录。

join 关系：`claims.claim_id` 同时出现在证据表、`result.json` 的 `evidence_map` 与成稿引用编号链路上。

## 五件可核验资产（`build` 自动写 `/app/output`）

| 文件 | 内容 | 复核方式 |
|---|---|---|
| `golden_standard.json` | 金标准：契约键、任务书句子、每条论断对应的材料 `locator` 与**逐字 quote**、成稿 join 期望、运行契约，共五类条目；构建时逐条回查原文并给出 `quote_hit_rate` | 打开文件，把 `basis=material` 的 `quote` 贴回材料应逐字命中；无来源条目 `quote` 为空且 `basis` 为 contract/skill |
| `diff_report.md` | 实际产物 vs 金标准逐项判定 `met / partial / missing / pending`，含契约回填表、产物字节表、可复算指标、偏差处置与复核方法 | 每行对应一个金标准条目；非 met 项都有理由与处置归属 |
| `version_history.md` | 静态版本历史（v0 → v0.5 → v1.0.0 → v1.1.0，改了什么/为什么/如何回退）+ 本次运行溯源（命令、case、输入字节、论断/证据计数、阶段摘要、回退方法） | 回退命令可直接执行；本次运行段与实际 `run.log` 对得上 |
| `run.log` | 真实阶段时间线：startup / input / case / discover / claims / evidence / compose / result / asset_* / assets / summary，跨命令追加，含耗时与降级 | 用时间线核对本次运行真的扫描、匹配、成稿、写资产 |
| `self_check.json` | 机器断言：契约键完整、result 合法、主产物存在、资产齐全、引文逐字、claim join、计数一致、正文引用可解析、**空输入与坏 JSON 子进程兜底**、退出码恒 0、自身可解析 | `pass` 为全部检查的汇总；`checks[].detail` 给出断言值与证据 |

资产生成失败只记降级并写诚实占位，不会让主流程或退出码失败；`audit` 会复检这五件资产并把结论并入 `verification.json`。

## `result.json` 契约

必须原样带上 `output_contract` 里每个键，键名不改；未知键保留输入原值；无内容给 `null` 或 `[]`。另外固定包含 `case_id`、`status`、`sources`、`uncertainty`、`pending_human`、`errors`、`degradations`、`changes`、`integrity`、`runtime`、`metrics`、`agent_work`、`coverage`、`verifiable_assets` 与五个资产路径字段（`golden_standard`、`diff_report`、`version_history`、`run_log`、`self_check`）。

`status` 四选一：`ok`、`partial`、`insufficient_evidence`、`input_error`，取值必须与真实缺口一致。工作稿缺失时即使交付物完整，也记 `partial` 并在 `degradations` 说明。

## 强度与语气

分档只看四因子合计：≥5.5 高，3.5–5.4 中，1.5–3.4 低，<1.5 不足；预印本总分封顶 4.0，样本不足 100 封顶 3.4，只能看到摘要的来源最高记"中"。写成文字时，高用"多项证据一致"，中用"研究提示"，低用"初步线索"，不足写"材料不足以判断"；原句已有弱化词则不重复加。完整算法和改写对照见 `references/grading_manual.md`。

## 异常与降级

- **没有工作稿**：仍从材料自动组合完整交付物（论断清单 + 证据表 + 成稿 + 覆盖报告 + 五资产），状态记 `partial`，并在 `degradations` 说明"未收到 Agent 工作稿"。
- **工作稿引文不逐字**：丢弃该行，进 `pending_human` 与 `degradations`，改用材料自动匹配结果；禁止改原文凑命中。
- 只有摘要：标 `abstract_only`，强度封顶"中"，不确定性说明中提示未回原文。
- 没有文献表：成稿照写，引用只映射到材料文件，`reference_check.md` 记缺口。
- 著录缺项：DOI/年份/期刊缺哪补哪列，不联网、不虚构。
- 摘要与原文矛盾、或来源之间结论冲突：两条都保留，互标冲突，强度下调，不取平均。
- 扫描件 PDF、图片、xlsx/pptx/doc：记 `degradations` 并给出需人工处理的提示。
- 输出目录不可写：退回当前工作目录，`errors` 留痕。
- 空目录、坏 JSON、缺 `case.json`：仍写合法 partial `result.json` 与完整占位交付物，`status` 为 `input_error` 或 `partial`，退出码 0。
- 论断找不到来源：保留句子但改为待核表述，进 `pending_human`，不硬塞引用。

## 复核脚本查什么

`audit.py` 把结论写进 `verification.json`：契约键是否齐全、`case_id` 是否原样、契约值是否有空、引文是否逐字命中、claims 与证据表是否双向 join、证据行四要素是否齐、成稿正文引用编号是否越界、正文是否残留"证明/确证"式越级表述，以及五件可核验资产是否齐全、金标准逐字命中、`self_check.pass` 是否为真。任一项 False 都需要回改产物。

## 示例（示意数据，非评测结果）

输入目录放一个 `case.json`：`case_id` 为 `DEMO-G7`，`task_instruction` 为"给方法小节补 3 条引用"，`output_contract` 含五个键（`case_id`、`deliverable`、`preserved_facts`、`evidence_map`、`change_log`），`source` 给一篇论文的标题与 DOI；再放待改稿、两条摘要与一份文献表。

```bash
python3 scripts/pipeline.py init      --input demo/input --output demo/output --work demo/work
python3 scripts/pipeline.py show      --limit 40 --input demo/input --output demo/output --work demo/work
# Agent 写 demo/work/draft.json（论断 + source_id/locator/逐字 quote）
python3 scripts/pipeline.py check     --input demo/input --output demo/output --work demo/work
python3 scripts/pipeline.py build     --input demo/input --output demo/output --work demo/work
python3 scripts/pipeline.py audit     --input demo/input --output demo/output --work demo/work
```

示意输出（**非评测结果**）：`check` 打印 `claims=4 evidence=5 quote_hit=4/5 missing_fields=0 unsupported=1`；`build` 打印 `done partial claims=4 rows=5 quote=4/4 pending=1 assets=5/5`，并在 `/app/output` 落 15 个文件（三件主产物 + 成稿副本 + 四份辅助记录 + `result.json` + 五件资产）；`self_check.json` 的 `pass` 为 `true`，`support_rate` 约 0.75，`overclaim_downgrades` 为 1。

## 版本与维护

当前 1.1.0，要求 Python 3.8 以上，无第三方依赖。改强度阈值时同步 `scripts/audit.py` 的 `grade_row()` 与 `references/grading_manual.md` 的口径；扩词只往 `terms_zh2en.tsv` 加确认同义的条目；改金标准判据只改 `scripts/assets.py` 的条目构造与 `diff` 判定函数。回归方式：先跑 `init → 写工作稿 → check → build → audit`，要求逐字命中、join、四要素、引用编号、五资产五项全 True，再用空/坏输入各跑一次确认退出码 0 且五资产非空。
