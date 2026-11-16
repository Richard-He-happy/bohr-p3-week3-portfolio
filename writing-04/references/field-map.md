# 契约字段速查与降级判定（本包新增）

本页把 `case.json` 的契约字段、`result.json` 的输出字段、以及常见降级判定放在一起，供 Agent 在写工作稿和收尾核对时快速对照。

## 1. `output_contract` → `result.json` 的语义映射

| 契约键（语义识别，大小写/前后缀不敏感） | 回填到 `result.json` 的位置 | 说明 |
|---|---|---|
| `case_id` | 顶层 `case_id` | 原样回填，不做大小写或格式改写 |
| `deliverable` | 顶层 `deliverable` | 主交付文件名或路径；缺稿件时指向缺口报告 |
| `preserved_facts` | 顶层 `preserved_facts` | 每条含 fact/value/quote/locator/verified |
| `evidence_map` | 顶层 `evidence_map` | 改动 → 证据 → locator 的映射 |
| `change_log` | 顶层 `change_log` | 与 `change_log.json` 同源的机读改动记录 |
| `receipts` | 顶层 `receipts` + `edit_receipt.json` | 导入 / 逐条裁决 / 版本对照 / 无效操作 |
| `version_compare` | 顶层 `version_compare` | v1/v2 哈希、行增删、回滚测试 |
| `uncertainty` | 顶层 `uncertainty` | 未定项列表 |
| 其他未知键 | 同名键，值置 `null` | 不删键、不改名，避免契约缺字段 |

## 2. `status` 取值与含义

| 取值 | 什么时候用 |
|---|---|
| `ok` | 无 errors、无 fallback、无 reject、无未验证 fact、targets 非空、至少 1 条改动落地 |
| `partial` | 主产物已产出，但有 fallback/reject/未验证 fact 或缺失素材 |
| `insufficient_evidence` | 材料不足以支撑任何有依据的改动（例如找不到稿件或引文全不命中） |
| `input_error` | 输入根缺失、`case.json` 不可读、工单不可解析等入口级问题 |

降级只改 `status` 与 `errors`/`degradations`，**不改退出码**；任何分支退出码都是 0。

## 3. 快速判定表

| 现象 | 先看哪里 | 处理 |
|---|---|---|
| `status=partial` 且 `origin=fallback` | `receipts.json → accept_reject.items[]` | 按 `reasons` 修工作稿（引文不逐字 / 标注太短 / 证据未命中），重跑 `check` |
| `status=insufficient_evidence` | `result.json → errors`、`deliverable.md` | 确认输入材料是否真的缺失，不要自行补造 |
| `format_integrity.preserved=false` | `receipts.json → import` 的结构计数对比 | 检查是否误改了标题/表格/公式，必要时 `versions/v1_original.md` 回退 |
| `warnings: numbers not found in source` | `change_log.json → items[]` | 标注里的数值必须有原文出处，否则删掉或改成"需作者补充" |
| `pending_human` 偏多 | `result.json → pending_human` | 只保留真正需要作者决策的条目，其余应自行闭环 |
| `self_check` 有 `ok=false` | `self_check.json → failed_ids` | 失败项是结论不是崩溃；按 id 对应到产物再修 |

## 4. 与上游工单的对应关系

`organizer_edit_workorder` 里的每条 requirement 都应在 `golden_standard.json` 有一个 `GS-xx` 期望项，并在 `diff_report.md` 有一行"达标/偏差/缺失"。若某个 requirement 没有对应期望项，说明工单解析不完整，应在 `uncertainty` 里写明，而不是假装覆盖。
