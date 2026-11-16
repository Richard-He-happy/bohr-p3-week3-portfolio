# result.json 字段字典与可追溯映射

本文件回答三件事：`result.json` 里都有什么、每个分数的三指针怎么落、以及"输入坏了"时状态与字段
怎么对应。实现细节在 `scripts/reading_core.py` 的 `result_skeleton()` / `fulfill_contract()`。

## 1. 顶层字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | str / null | 取自 `case.json` 的语义识别结果（`case_id`/`caseId`/`id`） |
| `status` | str | `ok` / `partial` / `insufficient_evidence` / `input_error`，含义见 §4 |
| `stage` | str | 最后一次落盘的阶段（`init` / `show` / `check` / `build` / `<verb>/error`） |
| `skill` | obj | `{name, version}`，便于版本追溯 |
| `outputs` | obj | 五件产物与 `index` / `draft` 的绝对路径 |
| `benchmark` | obj / null | 题集摘要：`mode`、`n_items`、`n_rubric_points`、`n_rejected`、逐题分数映射 |
| `anchors` | obj / null | `{n_anchors, verified}` 引文核验计数 |
| `scoring` | obj / null | `{aggregate: {...}}`，完整逐点明细在 `scoring.json` |
| `sources` | array | 材料清单：`id/name/path/kind/bytes/sha1/paragraphs/status/method` |
| `uncertainty` | str[] | 明确的不确定性（降级、无锚点、兜底题覆盖不足…） |
| `pending_human` | str[] | 需要人工接管的条目（分数 <2 的点、被拒题、缺契约…） |
| `errors` | obj[] | `{stage, item?, material?, error, traceback?}` |
| `degradations` | obj[] | `{material/file/item, issue, action}`：降级与兜底动作 |
| `changes` | obj[] | `{what, mode?, why}`：本次运行做了什么变更 |
| `technical_synthetic` | obj | `{present, not_a_dsh_score, sources, scored, note}`：checker/候选输出只登记不评分 |
| `runtime` | obj | `{skill_version, python, started_at, elapsed_s, input_root, output_root, stage, written_at, argv, self_audit}` |
| `contract_fields_present` | str[] | `output_contract` 声明的字段名（原样、原顺序） |
| `contract_echo` | obj | 契约原文，便于审计"我们回填了哪些键" |

此外，`output_contract` 里的**每个字段**都会在顶层出现：算得出就填真值，算不出就 `null`/`[]`/
同形空结构。`fill_contract` 的匹配顺序是"精确名 → 近精确名 → 关键词提示（scoring/anchor/items/
stats/report/status/sources/uncertainty/outputs/changes/result/claims/uncertainties）→ 契约空镜像"，
所以不会出现某个键整个消失的情况。

## 2. 一个分数的三指针

平台若要求 `raw_output_ref` / `config_ref` / `scoring_record_ref`，按下面这张表落：

| 指针 | 指向什么 | 本包里的落点 |
|---|---|---|
| `raw_output_ref` | 被评测对象的原始输出 | `outputs/<agent>/<item_id>.json`（外部提供时）；本包内是 `benchmark.json` 的该题 + `anchors.json` 的 quote |
| `config_ref` | 本次运行配置 | `result.json.runtime`（模型/权限/预算/prompt 版本由运行方写入；本包记录 python 版本、输入/输出根、argv、时间） |
| `scoring_record_ref` | 本包评分记录 | `scoring.json` → `items[i].points[j]`（含 `rubric_id` / `score` / `locator` / `coverage` / `basis`） |

题集内的追溯链（不依赖外部）：

```
scoring.json items[i].points[j]
   └─ item_id → anchors.json anchors[k].{material, locator, quote, verified, match}
   └─ item_id → benchmark.json items[i].{question, rubric, reference_answer, evidence}
   └─ locator → /input 中该段原文（`show` 可重放）
```

`runtime.self_audit` 是 build 结束时跑的 6 项结构断言，结果为
`{ok, passed, total, failed[], checks[]}`：

1. `point_counts_add_up`：`n2+n1+n0 == n_points`；
2. `anchor_locators_resolve`：每条 verified 锚点的 locator 能解析到索引里真实存在的段；
3. `scoring_ids_match_benchmark`：评分题号集合与题集题号集合一致；
4. `scored_points_have_locator`：任何 ≥1 分的点都带 locator；
5. `contract_keys_on_top`：契约字段全部出现在 `result.json` 顶层；
6. `aggregate_recomputable`：`mean_score` 可从逐题分数复算（±0.002）。

任一项不通过 → `runtime.self_audit.ok=false`，`failed` 列出名字，stdout 打印 `ATTENTION <names>`。

## 3. 文件 ↔ 字段对照

| 产物 | 对应 result.json 字段 | 备注 |
|---|---|---|
| `benchmark.json` | `benchmark`、`outputs.benchmark` | `schema=reading-bench-forge/benchmark@1` |
| `anchors.json` | `anchors`、`outputs.anchors` | 引文核验表，`quote_policy` 写明逐字 |
| `scoring.json` | `scoring.aggregate`、`outputs.scoring` | 逐点明细与 `pending_human` 全量 |
| `report.md` | `outputs.report` | 供人读的凭证 |
| `result.json` | 自身 | `outputs.result` 指向自己 |

## 4. 状态语义

| status | 触发条件 | 下游应该怎么用 |
|---|---|---|
| `ok` | 有题、无校验 FAIL、mode 为 `agent_authored` | 正常进入人工抽检 |
| `partial` | 有产物但存在降级/兜底/未决问题 | 可用，但必须读 `pending_human` 与 `uncertainty` |
| `insufficient_evidence` | 有材料但没有可用段落或题 | 结算前人工决定是否补材料 |
| `input_error` | 没有材料或输入根不可用 | 当作运行失败但保留产物 |

## 5. 降级动作 → 字段映射

| 触发 | `degradations[].action` | 同时写入 |
|---|---|---|
| 草稿缺失或无效 | `fallback_generated_items` | `mode=fallback_minimal`、`status=partial` |
| 题被拒后补题 | `added deterministic minimal items from real paragraphs` | `mode=agent_authored_with_fallback` |
| 材料无文本 | 该材料 `status=no_text` | `sources[].status`、`errors[]` |
| PDF 文本质量低 | `pdf_text_quality_low=…` | `degradations[]`、`uncertainty[]` |
| 未捕获异常 | `wrote a legal partial result` | `errors[].traceback`、`pending_human[]` |
| 检测到 checker/候选输出 | 登记 | `technical_synthetic.{present,not_a_dsh_score}` |

**合成日志声明**：`technical_synthetic` 只表示"输入里存在 checker/候选文件"，其内容不是 DSH 分数，
也不是独立语义验证；`scored=false` 永远成立。任何把该字段解读成分数的做法都违背本包设计。
