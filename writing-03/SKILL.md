---
name: evidence-driven-writing
description: 文献证据驱动写作。读取 /input 的任务说明、待改稿、来源摘录与文献表，按"论断清单 → 证据表（逐字引文 + locator + 强度）→ 证据支撑成稿"三段交付；每条实质判断可回查材料原文，材料未覆盖处标待核，不编造文献、数字与结论。适用于讨论段补证、引用核对、过度推断下调、证据强度与不确定性表达。
version: 1.0.0
---

# 文献证据驱动写作（writing-03）

## 1. 用途与适用条件

给定一个需要文献支撑的写作任务（补写/改写讨论段、补引用、核对论断、标注证据强度与不确定性），
把任务拆成可复核的三段交付物：

1. **论断清单**：句子级 claim，带编号；
2. **证据表**：每条 claim 对应材料中的来源、`locator`、**逐字引文**、证据强度与支撑范围；
3. **成稿**：可编辑 Markdown，数字编号引用 `[n]`，附证据边界与参考文献。

适用：/input 下为文本材料（`case.json`、`task.md`、`artifacts/*.md|txt`）。PDF/扫描件由 Agent 用平台工具读原文。

## 2. 调用方式（必须按顺序执行）

```bash
python3 -B /skills/weekly-skill/scripts/run.py init      # 1) 建索引，看材料逐字句
# 2) Agent 自己读 /input 材料，把工作稿写到 /app/work/draft.json
python3 -B /skills/weekly-skill/scripts/run.py check     # 3) 机械校验工作稿，报告缺什么
python3 -B /skills/weekly-skill/scripts/run.py build     # 4) 组装成稿与全部核验资产
```

- 没有 `python3` 时用 `python`，命令相同。默认路径 `/input`、`/app/output`、`/app/work`，
  可用 `--input/--output/--work` 覆盖。脚本只用标准库、不依赖 CWD，**退出码恒 0**。

> **必须先读材料再写稿，禁止只跑 build 就结束。**
> `build` 在没有工作稿时会从材料自动组合兜底稿（逐字摘句 + locator + 引文），并在 `result.json`
> 中如实记 `status=partial`、`agent_work.draft_used=false`；那不是真正完成的任务。
> 主路径永远是：读材料 → 写 draft.json → check → build。

## 3. 输入与输出

**输入（只读 /input）**
- `case.json`：`case_id`、`task_instruction`、`output_contract`（必须原样回填的字段）。
- `task.md`：任务说明与硬约束（字数、引用格式、不得改动的事实等）。
- 材料：`artifacts/` 下任意文本文件。`init` 自动识别 `draft`（待改稿）/`references`（文献表）/`source`（来源摘录），
  并在 stdout 打印每个句子的 `locator` 与原文，**写 draft.json 时 quote 必须从此处逐字复制**。

**输出（写到 /app/output）**

| 文件 | 内容 |
|---|---|
| `result.json` | 契约键原样回填 + `status/errors/warnings/metrics/pending_human` 等 |
| `deliverable.md` | 主产物：可编辑 Markdown 成稿（引用编号 + 证据边界 + 参考文献） |
| `evidence.json` | 证据表：claim_id、source、locator、逐字 quote、verified、strength |
| `golden_standard.json` | 逐条期望：契约键、每条 claim 的 locator 与逐字 quote、完整性统计 |
| `diff_report.md` | 期望 vs 实际：契约回填表、逐条证据、剩余缺口 |
| `run.log` | 真实运行日志（init/check/build 累积追加） |

`result.json` 中 `output_contract` 的**每一个键都会存在**（缺值写 `null`），并额外带
`status`（`ok / partial / insufficient_evidence / input_error`）、`errors`、`warnings`、
`degradations`、`pending_human`、`metrics`、`agent_work`、`contract_backfill`。

## 4. `/app/work/draft.json` 结构

```json
{
  "case_id": "从 case.json 原样复制",
  "sections": [
    {"heading": "## 讨论", "claims": [
      {"claim_id": "C001", "text": "成稿句子（可含 [1]）", "claim_type": "事实|关联|因果|比较|推断",
       "evidence": [
         {"source": "artifacts/source_A.md",
          "locator": "artifacts/source_A.md [B1.S2] chars:121-254",
          "quote": "从 init 输出逐字复制的原文",
          "strength": "高|中|低|不足",
          "support": "直接支撑|部分支撑|冲突"}]}
    ]}
  ],
  "preserved_facts": [{"value": "0.78", "quote": "逐字原文", "locator": "..."}],
  "change_log": [{"claim_id": "C001", "before": "原句", "after": "改后", "reason": "为何改", "locator": "..."}],
  "references": ["可选；材料未提供参考文献表时不要编造"]
}
```

容错：`claims` 也可放顶层；`deliverable`/`draft` 可放完整 Markdown；evidence 接受
`locator/quote/source` 常见别名。`check` 会逐条打印问题。

## 5. 证据与定位规范

- `locator` 形如 `<相对路径> [B<块>.S<句>] chars:<start>-<end>`；**quote 必须与材料逐字一致**（含标点、数字、单位）。
- 引文未逐字命中的证据不会作为支撑：`build` 记入 `pending_human` 并把状态降为 `partial`；
  **禁止改写原文凑通过**，宁可标缺口。
- 证据强度按研究设计与样本量分级（系统综述/荟萃 > 随机试验 > 队列 > 病例对照 > 横断面 > 病例报告/体外/预印本）。
- 相关不写成因果、单篇小样本不写成领域共识、冲突证据必须显式保留（`support=冲突` + `change_log`）。
- 材料没有覆盖的内容标"待核"，不补造；未联网核验要在证据边界中说明。

更细规则与失败处置见 `references/evidence_rules.md`。

## 6. 异常与降级（全部退出码 0）

| 情况 | 处置 |
|---|---|
| 空 /input | `init` 写 partial `result.json` + `deliverable.md` 占位；`build` 记 `status=input_error` |
| `case.json` 坏 JSON | `input_error`，`errors` 记录原因；仍产出合法最小产物 |
| 无 `draft.json` | `build` 自动兜底成稿（逐字摘句），`status=partial`、`degradations` 记录 |
| `draft.json` 坏 JSON | `check` 报告 FAIL；`build` 回退自动兜底并记录 warning |
| 引文不命中 | 该证据 `verified=false`，进 `pending_human`，状态降为 `partial` |
| PDF / 不支持格式 | 记录 `unsupported` / `pdf_text_unsupported`，由 Agent 用平台工具读原文后写 draft |

## 7. 自检清单

- [ ] `init` 退出码 0，`/app/work/index.json` 已生成且 `units` 非空。
- [ ] 逐条核对 `draft.json` 里每个 quote 都能在 `/input` 材料中逐字找到。
- [ ] `check` 输出 `passed=True`（claims / quote / contract 三项）。
- [ ] `build` 退出码 0，`/app/output` 六个文件齐全且非空。
- [ ] `result.json` 契约键无缺失；`degradations` 与 `pending_human` 是真实缺口。

## 8. 最小调用示例（示例，非正式案例结果）

输入：`case.json` 含 5 键契约（case_id/deliverable/preserved_facts/evidence_map/change_log）、
`task.md`、`artifacts/discussion_draft.md` + 2 篇来源摘录 + `references.md`。

```bash
python3 -B /skills/weekly-skill/scripts/run.py init
# Agent 写 draft.json（每条 claim 带 source/locator/quote）
python3 -B /skills/weekly-skill/scripts/run.py check   # passed=True
python3 -B /skills/weekly-skill/scripts/run.py build   # status=ok contract_filled=5/5
```

以上为示例说明接口，不是正式案例结果。

## 9. 文件与维护

| 文件 | 作用 |
|---|---|
| `SKILL.md` | 本说明（入口） |
| `scripts/run.py` | 主流程：init/check/build，含契约回填、引文校验、兜底与日志 |
| `references/evidence_rules.md` | 证据/引文/定位/状态/失败处置规则 |
| `references/lexicon.json` | 可选数据：中英术语表与契约键启发式（缺失时自动降级） |

维护：调整契约键匹配在 `scripts/run.py` 的 `HEUR`（数据在 lexicon.json）；修改后重跑
`--help`、主流程、空输入、坏 JSON、无 draft 五种场景，要求全部退出码 0。
