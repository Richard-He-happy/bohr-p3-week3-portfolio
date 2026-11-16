---
name: citation-grounded-writing
description: >-
  把"需要文献支撑的写作任务"做成可复核的三段交付：先切出论断清单，再为每条论断匹配材料中的逐字原文与定位并给出四因子证据强度，最后生成语气与强度相称、冲突与缺口显式保留的可编辑成稿。适用于补引用、核对论断是否被原文支持、评审证据强度、改写过度推断段落等场景。
version: 1.0.0
license: MIT
---

# 引文有据写作（writing-03）

## 它解决什么

学术写作里最容易失控的不是"写不出来"，而是写出来的句子说不清依据。本工作流把一次写任务拆成可回查的三层：**论断 → 依据 → 成稿**。任何一层都能单独被人拿到原始材料上复核，而不是只看一份读起来通顺的终稿。

适用场景：补引用、改讨论段、核论断、审证据强度、给结论加不确定性。触发条件是输入里有 `case.json` 与若干材料文件。

## 四个不可让步的点

1. **可定位**：论断按句切开，每条都带文件、块句号与字符区间。
2. **可对原文**：证据引文从材料原样复制，脚本重新读材料逐字核对；文献著录只抄不补。
3. **可判断强度**：设计类型、样本量、独立来源数、是否存在冲突四项合成分档，正文语气随分档走。
4. **可重跑**：三份产物用同一个 `claim_id` 串联，复核脚本独立重算，计数写进 JSON。

同时在材料允许范围内保持克制：不联网、不凭记忆添文献、不编数字、不把相关性写成因果、不把"没找到"说成"不存在"。

## 文件与入口

| 文件 | 用途 |
|---|---|
| `SKILL.md` | 本说明 |
| `scripts/pipeline.py` | 生成三段产物与 `result.json` |
| `scripts/audit.py` | 文本抽取/规则工具 + 产物独立复核 |
| `references/output_contracts.md` | 产物字段与 `result.json` 契约 |
| `references/grading_manual.md` | 强度算法、语气映射、下调规则、异常处置 |
| `references/terms_zh2en.tsv` | 中英概念词表（Tab 分隔，可追加） |

## 两条命令

```bash
python -B scripts/pipeline.py [--input DIR] [--output DIR]   # 默认 /input -> /app/output
python -B scripts/audit.py    [--input DIR] [--output DIR]   # 复核并写 verification.json
```

两条命令都以 0 退出。生成器在开始时就写一份不完整的 `result.json`，运行中任何一步抛异常都会被兜住并在最后补齐字段，因此磁盘上不会出现半截 JSON。复核器不读产物里"自报"的结论，而是重新解析输入目录再比对。

## 输入与输出位置

- 输入：`/input/case.json`（含 `case_id`、`task_instruction`、`output_contract`）、`/input/task.md`、`/input` 下的材料文件。
- 输出：`/app/output`；工作目录 `/app/work`。
- 材料类型识别：文件名带 draft/manuscript/原稿/初稿 的视为待改稿；带 ref/bib/reference/文献 的视为文献表；其余视为来源材料。识别只用于选择流程，不改动文件内容。
- 支持文本、Markdown、JSON、CSV、DOCX 与带文本层的 PDF；图片、扫描件、xlsx/pptx/doc 走降级路径。
- 脚本不依赖启动目录，资源路径由 `__file__` 推出。

## 主流程

1. 扫描输入目录，解析每个文件并记录字节数、sha256、解析方式；单文件解析失败只登记降级。
2. 决定论断来源：有待改稿时逐句切原稿（剥掉句末引用标记得到 `core`）；没有原稿时用任务指令与 `source` 元数据组成主题，从材料里挑与该主题最接近的句子，同一文件最多 2 条以避免来源单一。
3. 给每条论断找依据：术语表归一后比较概念集合重叠，数字相同再加权；若原句自带 `[n]`，先把文献表第 n 条映射到具体文件，优先在该文件内找、阈值放宽。证据只从"来源材料"里取，不从待改稿和文献表里取。
4. 计算强度：设计 + 样本 + 重复来源 − 冲突，再套预印本/小样本/仅摘要三个封顶。
5. 记录冲突：同一论断下主题相近而结论方向相反的来源写入 `conflicts`，成稿另起转折句呈现。
6. 生成成稿：每句 = 与强度匹配的限定语 + 判断 + 引用编号；末尾固定"证据边界"和"参考文献"；有原稿时沿用原小节与段落顺序。
7. 下调过度推断：没有随机化或干预对照时把因果表述改成关联表述，把绝对化量词改成范围限定；只改措辞，数值原样保留，每处改动进 `change_log`。
8. 收尾：逐字校验、join 校验、计数、`pending_human`，覆盖写终版 `result.json`；若 `case.json` 带 `organizer_workorder`，把其中能量化的要求（字数上限、引用条数、引用风格）逐条执行并在 `workorder_receipt` 回报，不能判定的标 `unverifiable`。

## 三段产物

`claims.json` 的每条：`claim_id`、`location`（原稿位置或材料定位）、`text`（原句）、`core`（去掉引用标记的判断句）、`type`（事实/推断/因果/比较）。

`evidence_table.json` 的每行：`claim_id`、`source_id`、`locator`、`quote`、`source_type`、`strength`、`support_scope`、`conflicts`、`rationale`、`verified`。定位统一写成"相对路径 + `[B块.S句]` + `chars:起-止`"，便于回到原文。

成稿 `evidence_driven_draft.md` 里每个 `[n]` 都要能在参考文献段找到对应条目；材料没给 DOI 就不写 DOI。同目录另留 `deliverable.md` 作为文件名兼容副本，并生成 `evidence_strength.md`、`reference_check.md`、`uncertainty_notes.md`、`pending_human.json` 四份辅助记录。

join 关系：`claims.claim_id` 同时出现在证据表、`result.json` 的 `evidence_map` 与成稿引用编号链路上。

## `result.json` 契约

必须原样带上 `output_contract` 里每个键，键名不改；未知键保留输入原值；无内容给 `null` 或 `[]`。另外固定包含 `case_id`、`status`、`sources`、`uncertainty`、`pending_human`、`errors`、`degradations`、`changes`、`integrity`、`runtime`。

`status` 四选一：`ok`、`partial`、`insufficient_evidence`、`input_error`，取值必须与真实缺口一致。

## 强度与语气

分档只看四因子合计：≥5.5 高，3.5–5.4 中，1.5–3.4 低，<1.5 不足；预印本总分封顶 4.0，样本不足 100 封顶 3.4，只能看到摘要的来源最高记"中"。写成文字时，高用"多项证据一致"，中用"研究提示"，低用"初步线索"，不足写"材料不足以判断"；原句已有弱化词则不重复加。完整算法和改写对照见 `references/grading_manual.md`。

## 异常与降级

- 只有摘要：标 `abstract_only`，强度封顶"中"，不确定性说明中提示未回原文。
- 没有文献表：成稿照写，引用只映射到材料文件，`reference_check.md` 记缺口。
- 著录缺项：DOI/年份/期刊缺哪补哪列，不联网、不虚构。
- 摘要与原文矛盾、或来源之间结论冲突：两条都保留，互标冲突，强度下调，不取平均。
- 扫描件 PDF、图片、xlsx/pptx/doc：记 `degradations` 并给出需人工处理的提示。
- 输出目录不可写：退回当前工作目录，`errors` 留痕。
- 空目录、坏 JSON、缺 `case.json`：仍写合法 partial `result.json`，`status` 为 `input_error` 或 `partial`，退出码 0。
- 论断找不到来源：保留句子但改为待核表述，进 `pending_human`，不硬塞引用。

## 复核脚本查什么

`audit.py` 把结论写进 `verification.json`：契约键是否齐全、`case_id` 是否原样、契约值是否有空、引文是否逐字命中、claims 与证据表是否双向 join、证据行四要素是否齐、成稿引用编号是否越界、正文是否残留"证明/确证"式越级表述。任一项 False 都需要回改产物。

## 示例（示意数据，非评测结果）

输入目录放一个 `case.json`：`case_id` 为 `DEMO-G7`，`task_instruction` 为"给方法小节补 3 条引用"，`output_contract` 含五个键（`case_id`、`deliverable`、`preserved_facts`、`evidence_map`、`change_log`），`source` 给一篇论文的标题与 DOI；再放待改稿、两条摘要与一份文献表。

```bash
python -B scripts/pipeline.py --input demo/input --output demo/output
python -B scripts/audit.py --input demo/input --output demo/output
```

示意输出（**非评测结果**）：生成器打印 `done partial claims=4 rows=5 quote=4/4 pending=1`；复核器打印 `verify PASS` 并在 `verification.json` 中给出逐项 True；`result.json` 示意的 `status` 为 `partial`，`support_rate` 约 0.75，`overclaim_downgrades` 为 1。

## 版本与维护

当前 1.0.0，要求 Python 3.8 以上，无第三方依赖。改强度阈值时同步 `scripts/audit.py` 的函数与 `references/grading_manual.md` 的口径；扩词只往 `terms_zh2en.tsv` 加确认同义的条目。回归方式：先跑生成器再跑复核器，要求逐字命中、join、四要素、引用编号四项全 True。
