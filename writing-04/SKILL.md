---
name: manuscript-revision-desk
version: 1.1.0
description: Offline revision desk for existing academic manuscripts. Given /input/case.json, task.md and supplied material, it locates the targets named by the organizer workorder, inserts source-grounded editorial annotations one by one, verifies anchors and evidence deterministically, then exports an editable manuscript, per-item accept/reject receipts, rollback evidence and a set of auditable artifacts. Standard library only; no network; no fake remote-client or Word tracked-change claims.
---

# 稿件修订工作台 / Manuscript Revision Desk

一句话：**改指定的地方，其余原样；每处改动可定位、可回查依据、可回退。**

## 1. 适用场景

输入里已经有**成稿**、并且能指出**要改的段落或位置**（工单 target_ids，或 task_instruction 指名的章节）时使用：润色、校对、审稿答复、基金修改、引用整理。

不适合：从零写论文、纯格式转换、没有改动目标的"随便优化"。缺定位依据时，确定性检查没有对象，结果只会退化成一堆保命标注。

## 2. Scope limits

- Reads only files under the input root. Fully offline: no search, no invented references, numbers or conclusions.
- No remote collaboration client, no co-author account, no Word tracked-change XML. Primary deliverable is Markdown plus a self-contained HTML preview; if the outer agent needs docx/pdf it must render it for real — this package never ships a fake preview.
- The scripts are mechanics only: they check whether a quote exists, whether evidence can be traced back, whether coverage is complete, whether structure counts are conserved. **Whether an annotation is scientifically sound is the Agent's judgement**, not the script's job.
- Output is UTF-8 without BOM; JSON input is read with BOM tolerance (`utf-8-sig`).

## 3. Interface

Entry point: `python3 scripts/main.py <init|show|check|build>`.

- `--input DIR` — material root, default `/input`, falling back to `/app/input` when absent.
- `--work DIR` — scratch root, default `/app/work`.
- `--output DIR` — deliverable root, default `/app/output`.
- `--workplan FILE` — for `check` / `build`; otherwise the first existing of `<work>/workplan.json`, `edit_plan.json`, `plan.json`, `edits.json` is used.
- `show` also accepts `--id`, `--grep` (regex), `--limit`.

Requires Python 3.8+ standard library; independent of the current directory (the entry adds its own directory to `sys.path`). **The exit status is always 0.** Problems are reported in `result.json` under `errors` / `degradations`; never via return codes.

## 4. 材料识别

1. 先找 `case.json`，没有就递归找第一个 `case*.json`。字段按语义认，不按拼写：`output_contract`、`case_id`、`organizer_edit_workorder`、`task_instruction` 之类，大小写与前后缀一并忽略。
2. 工单识别：递归搜索"键名含 target、值是字符串数组"的对象；命中多个时，取 target id 前缀与 `case_id` 相符的那个。
3. 稿件候选：扩展名 → 文件魔数（PDF 查 `%PDF`，docx 查 `PK\x03\x04`）→ 命名线索 → 体量评分，取最高分且可解析的一份。文件名只当线索，不当证据。
4. 切块保留顺序，类型为标题 / 正文 / 表格 / 引用 / 代码 / 公式。源文件自带 `XXX-Pnnn` 形式 ID 时沿用，否则按"前缀-P序号"编号。
5. 目标解析三级降级并写进 `resolution`：ID 字面命中（`explicit-label`）→ 源段前 70 字符内出现该 ID → 按序号落到第 N 个段落块（后两种记 `ordinal`）；都不行记 `unresolved`，不猜。

## 5. 操作顺序

```bash
R=<skills>/manuscript-revision-desk/scripts/main.py
python3 $R init                    # index + split + target resolution + partial result.json
python3 $R show --id C01-P002      # read the target block (or open <work>/index.json)
#  ---- Agent step: write <work>/workplan.json, see section 6 ----
python3 $R check                   # verify anchors / evidence / coverage -> check_report.json
python3 $R build                   # inject, publish, receipts, audit assets, final result.json
```

中间那步必须由 Agent 亲自完成。`init` 只负责说明"改哪一段、工单要什么"；写什么内容要 Agent 读完目标段及其上下文后自己判断。跳过这步时 `build` 仍会出成稿，但每条标注退化为 `FALLBACK EDITORIAL NOTE … needs author confirmation`（`origin=fallback`、`needs_human=true`），状态变 `partial`。这是保命路径，不是交付路径。

## 6. 工作稿格式

工作稿是流程里唯一的创造性输入，其余步骤都是机械的。骨架如下（字段字典、别名表、反例见 `references/plan-contract.md`）：

```json
{
  "prepared_by": "agent",
  "case_id": "C01",
  "uncertainty": ["源文未交代的比较基准"],
  "preserved_facts": [
    {"locator": "Section 3", "value": "48.6",
     "fact": "某个关键强度数值",
     "quote": "包含该数值的原文句子，逐字复制"}
  ],
  "pending_human": [],
  "targets": [
    {
      "decision": "accept",
      "evidence": [
        {"locator": "Section 2.1", "source_id": "稿件文件名",
         "quote": "材料里逐字存在的支撑句"}
      ],
      "rationale": "对应工单哪一条、为什么在这里加注",
      "annotation": "≥60 字符的编辑标注：科学条件、局限或需要澄清处，可用 Markdown",
      "original_quote": "目标段中逐字摘录的一句原话，作为锚点",
      "target_id": "C01-P002"
    }
  ]
}
```

脚本硬门槛：锚点引文在源稿里必须字面命中（空白、弯引号、破折号先归一化）；标注只许新增、不许改原句；证据至少一条能对回材料；`decision: reject` 表示"提了但不采纳"。也认字段别名：`quote`/`text`、`note`/`new_text`、`sources`/`citations`。

## 7. 交付内容

跑到 `build` 结束，交付根下应有：

- `manuscript.md` — 主交付：原稿逐字保留，标注以 `<!-- ANN-START … -->` 包成独立块，插在目标段之后。
- `versions/v1_original.md`、`versions/v2_published.md` — 版本链条两端。
- `receipts.json` 与 `edit_receipt.json` — 回执。前者含导入信息、逐条裁决、版本对照、回滚记录、故意无效调用、保留事实、证据索引；后者是结构化视图，另带 `preservation`（未涉及块逐块 sha256 + 首句）、`coverage`、`contract`。
- `change_log.md`、`change_log.json` — 人读/机读两版改动记录（改前引文、改后标注、理由、证据、定位、数字核对、回退方式）。
- `version_diff.md` — v1→v2 unified diff，附逐块状态和增删统计。
- `check_report.json` — `check` 阶段校验明细。
- `preview.html` — 自包含预览，标注高亮、原样式保留。
- `result.json` — 契约回填与状态汇总；`init` / `check` 阶段先落 partial 版。

另有五份**审计材料**，由 `scripts/proof_assets.py` 在 `build` 时生成；`init` 会先给 `golden_standard.json` 落 `status=draft` 草稿和 `run.log` 第一行，中途中断也留痕迹：

1. `golden_standard.json` — 期望清单：每项带 `source.locator` 与逐字引文，写盘前重新回验；只写期望，不写结论。
2. `diff_report.md` — 期望对照实际，逐项"达标 / 偏差 / 缺失"加谓词实测值。
3. `version_history.md` — 稿件级与包级两层谱系、文件哈希、回退步骤。
4. `run.log` — 追加式运行日志：步骤、结果、耗时；降级与异常同样记账。
5. `self_check.json` — 自检结果：契约回填、证据覆盖、数字保真、产物齐备、JSON 可解析、故障注入、`--help` 退出码。

## 8. 结果契约

`output_contract` 里的键必须逐个出现：不改名、不删除、不合并。能对上语义的写进 `case_id` / `deliverable` / `preserved_facts` / `evidence_map` / `change_log` / `receipts` / `version_compare` / `uncertainty`；认不出的键原样保留、值置 `null`，确保契约不缺项。

必备字段分两组：

- 运行与状态：`runtime`、`case_id`、`status`（`ok` / `partial` / `insufficient_evidence` / `input_error`）、`sources`（每份材料 sha256）、`errors`、`degradations`、`uncertainty`、`pending_human`、`changes`。
- 佐证与审计：`preservation`、`format_integrity`、`rollback`、`receipts.coverage`；外加 `self_check`、`diff_report`、`golden_standard`、`version_history`、`run_log`（各带 `file` 与计数；`init` 阶段留空或 `status=draft`）、`verifiable_assets`（5 资产字节+sha256 实测）与 `evidence_coverage`（金标准/契约/引文/事实计数）与 `exceptions`。

`status=ok` 的门槛是硬的：零 errors、零 fallback、零 reject、零未验证 fact、targets 非空、至少一条改动落地。任一不满足就按实情降级，不许把 partial 说成 ok。

## 9. 溯源规范

每条改动记录三件事：改前引文（`original_quote`，逐字）、改后文本（`revised_quote`，即插入的标注）、定位（`anchor.locator`，形如 `block#N id=… lines a-b`），再加证据条目（`evidence[].quote` + `locator`）。

- Quote missing from the source → reject that single item, switch it to fallback, record the reason under `reasons`. Never edit the source to make a quote fit.
- Numbers appearing in an annotation but absent from the source → attach `warnings: numbers not found in source`; treat them as possible new facts.
- Preservation proof: strip the annotation blocks and byte-compare the remainder against the source; write the result into `preservation.byte_identical_to_source`. Byte evidence, not prose.

## 10. 异常处理表

| 情形 | 动作 | Exit |
|---|---|---|
| `case.json` 缺失或 JSON 损坏 | 记 `errors`，用默认契约继续，仍写 partial `result.json` | 0 |
| 输入根不存在 | `status=input_error`，交付 `deliverable.md` 作缺口报告 | 0 |
| 找不到稿件 | 同上：出缺口报告，不编内容 | 0 |
| docx / pdf 解析 | 走 `reconstructed` 模式（pdf 属降级），记 `degradations`，可信度看 `mode` | 0 |
| 工作稿缺失或坏 JSON | 每个目标生成带标签的 fallback 标注，`status=partial` | 0 |
| 锚点或证据未命中 | 只拒收该条并 fallback，其他条目继续，不牵连全局 | 0 |
| 没有 PDF 渲染器 | 保留 `preview.html`，记 `degradations`，不伪造导出件 | 0 |
| 未捕获异常 | 兜底写最小合法 `result.json`（`errors`/`exceptions` 齐全，四个审计字段置 `null`），日志记 `outcome=exception` | 0 |
| 某个审计材料生成失败 | 只降级该材料并记 `degradations`；主产物与其他材料照常落盘 | 0 |
| 自检的故障注入 | `self_check.json` 的 SC-09..SC-11 在临时目录真实重跑 `init`/`build`，不污染当前产物 | 0 |

## 11. 收尾自检

`build` 结束后看 stdout，逐项确认：

- `status` 是否为 `ok`；不是就按 `degradations` 逐条追。
- `changes` 数量 = 工单目标数，或 = 目标数 − 已解释的 reject。
- `preserved : byte_identical_to_source=True` 且 `integrity=True`。
- `rollback` 行显示 `byte-identical restore`。
- `invalid: n/n raised, state unchanged`（故意越权调用全部被拦）。
- `receipts.coverage.original_text_preserved=true`。
- `pending_human` 只剩真正要作者拍板的事项；没做的缺口必须出现在 `degradations` 或 `pending_human` 里。

## 12. 一次最小调用（示例，非正式评测结果）

假设 `/input/case.json` 的 `case_id` 是 `C07`，工单只点名 `C07-P004`，材料是一份分节 markdown 稿件。

```bash
python3 scripts/main.py init
# 读入 2 份材料；X7_chapters.md 切出 22 块；C07-P004 落到第 5 块（explicit-label）
# 已写出 partial result.json，可安全中断
python3 scripts/main.py show --id C07-P004
# 打印该块文本与 locator，供 Agent 阅读后撰写标注
# Agent 写工作稿：1 个 target（1 条标注 + 1 条证据）+ 1 条 preserved_fact
python3 scripts/main.py check
# targets=1 · agent=1 · fallback=0 · rejected=0 · facts 1/1 verified · ready=True
python3 scripts/main.py build
# status=ok；1 条改动落地；剥离标注后逐字节一致；结构计数守恒
# 5/5 故意无效调用被拦且状态未变；manuscript.md、回执、preview.html、result.json 齐备
```

上面只是接口示意，**不是**任何正式案例的分数或产物。

## 13. 包内文件

```
SKILL.md                          本说明
scripts/main.py                   四阶段入口：索引/定位/校验/注入/契约回填
scripts/doc_parse.py              文档模型：切块、字面命中、结构计数、预览与日志渲染
scripts/proof_assets.py           审计材料：金标准、对照报告、版本史、运行日志、自检
references/plan-contract.md       工作稿字段契约、别名表、正反例
references/annotation-rubric.md   标注质量标尺、历史失分模式、回执阅读路线
references/field-map.md           契约字段映射与降级判定速查（本包新增）
```

维护线索：标注下限（60 字符）与证据条数在 `scripts/main.py` 的 `score_plan`；解析与渲染在 `scripts/doc_parse.py`；金标准条目和判定谓词在 `scripts/proof_assets.py`——`golden` 定义期望项、`CHECKERS` 注册谓词，加一项只需加一个 `add(...)` 和一个谓词函数。任一审计材料失败只影响它自己：`finish` 抛异常时主流程记 `degradations` 并继续写 `result.json`。回归方式：造最小 case + 稿件，跑 `init → 写工作稿 → check → build`；再删掉工作稿重跑，应得 `status=partial` 与 fallback 标记。

## 14. 常见问题（FAQ）

**问：工单没给出 target_ids 怎么办？**
回退到 task_instruction：按其中点名的章节/段落/句子自己定位，把定位方式写进工作稿 `rationale` 与 `result.json` 的 `uncertainty`。定位不到的不要硬凑，留 `unresolved` 并进 `pending_human`。

**问：材料里同一段有中文版和英文版，改哪个？**
以工单或 task_instruction 指定的目标文件为准；为指定版本时，优先与稿件主语言一致的那份，并在 `uncertainty` 说明选择口径。

**问：一条标注引用了多段证据，怎么给？**
`evidence` 数组按 1–3 条组织，每条各自带 `quote` 和 locator；能对应同一 locator 的不要重复堆砌。

**问：作者要求"顺手改掉明显的单位笔误"，但 source_fidelity 说不得静默纠正怎么办？**
不改原文；把可疑单位写进标注并注明"疑似笔误，建议作者确认"，同时进 `uncertainty`。

**问：`status=partial` 还能交付吗？**
能，但必须在回复里说明 partial 原因（看 `degradations` / `pending_human`）；把 fallback 条目当作"待人工复核"，不要描述成已完成。

**问：稿件很长（几十节、上百块），怎么控制成本？**
`init` 一次建好索引，`show --id` 只取目标块，不必通读全文；但撰写标注前至少要读目标块前后的定义、方法或结果段落——只看目标块本身容易误解上下文。多目标时可以分批写工作稿、反复 `check`，最后统一 `build`。

**问：运行途中被杀掉，产物会怎样？**
`init` 和 `check` 都会先写 partial 版 `result.json`，`run.log` 逐行追加；重跑同一命令即可续上，已存在的输出会被覆盖为最新一致状态。若上一次 `build` 只写了一半，重跑 `build` 会重新生成全部产物，不需要手工清理。

**问：`self_check.json` 里有 `ok=false` 但 `status=ok`，信哪个？**
两者不冲突：`self_check` 是包自身健康度（含在临时目录跑的故障注入），其中某项失败说明该审计点没通过，`failed_ids` 会指出是哪一项；`status` 只描述本次交付。先按 `failed_ids` 修问题，再决定是否声称完成。


