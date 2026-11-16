# 交付审单、错误修法与复核模板

## 1. 交付前八项审单

| # | 检查 | 通过判据 | 不通过怎么办 |
|---|---|---|---|
| 1 | 契约完整 | `result.json` 含 `output_contract` 全部键，`unfilled contract:` 为 `none` | 缺键写 `pending_human` 并记录缺口计数 |
| 2 | 矩阵完整 | CSV 行数 = 文档数 × 字段数 | 重跑 `build`，缺格会自动补 `unreported` 占位 |
| 3 | 引文真实 | `reported` 行全部逐字命中，`quote_pass_rate = 1.0` | 回原文重新复制；无法命中改判 `unreported` |
| 4 | 定位可回 | 每格有 locator，`show` 能找到原句 | 用 `show` 重取 locator |
| 5 | 口径随值 | 数值格有 `unit`；跨数据集/口径时补 `dataset`/`metric_scope` | 补元数据 |
| 6 | 可比性成对 | workorder 每个维度都有判定 + basis | 补 `comparability` |
| 7 | 冲突有归因 | 每条 `conflicting` 都有 sample/method/metric/condition | 补归因；实在不能写 `unresolved` + `pending_human` |
| 8 | 诚实降级 | 扫描件/解析失败/未报告项进 `degradations`/`pending_human` | 补记录，不把猜测写成事实 |

命令入口：`check` 看 `coverage`/`quote_pass`/`errors`；`build` 看 `status`/`unfilled contract`。

## 2. 状态判档

- `ok`：契约齐全、check 零错误、无降级、覆盖率 > 0。
- `partial`：有缺格或降级，但矩阵可读（最常见，可接受）。
- `insufficient_evidence`：没有可用文本，或所有格均未报告。
- `input_error`：`/input` 缺失或没有可读材料。

## 3. 常见错误码与修法

| 错误码 | 根因 | 修法 |
|---|---|---|
| `quote_not_found` | 引文被改写、跨段拼接或全半角混用 | 从 `show` 原文重取，缩到单句 |
| `cell_unknown_doc` | `doc_id` 与索引不一致 | 先 `show`（不带 `--doc`）确认 id |
| `duplicate_cell` | 同文档同字段出现两行 | 合并成一行，差异写 `note` |
| `reported_without_value` | 标了 reported 但值为空 | 补值或改 `unreported` |
| `conflict_without_attribution` | 冲突未归因 | 补 attribution，或降为 `partially_consistent` |
| `no_fields` / `no_matrix` | 工作稿缺字段表或矩阵 | 按 schema 补全后重跑 `check` |

## 4. 最小工作稿（示例，非正式案例结果）

```json
{
  "question": "催化剂投加量对染料去除率的影响方向是否一致？",
  "papers": [{"doc_id": "D1", "citation": "示例 2022"}, {"doc_id": "D2", "citation": "示例 2024"}],
  "fields": [
    {"field_id": "dosage", "name": "投加量", "definition": "单位体积催化剂质量", "unit": "g/L", "value_rule": "取报告的最优条件"},
    {"field_id": "removal", "name": "去除率", "definition": "平衡去除率", "unit": "%", "value_rule": "取作者报告值"}
  ],
  "matrix": [
    {"doc_id": "D1", "field_id": "removal", "value": "95", "unit": "%", "status": "reported",
     "quote": "After 120 min at pH 3, the removal efficiency reached 95%.", "locator": "p2#para1", "note": ""},
    {"doc_id": "D2", "field_id": "dosage", "value": null, "unit": "g/L", "status": "unreported",
     "quote": null, "locator": null, "note": "Methods 未给出投加量"}
  ],
  "comparability": [{"dimension": "material", "doc_ids": ["D1", "D2"], "comparable": false,
                     "basis": "D1 TiO2，D2 ZnO；材料不同，去除率不合并", "doc_id": "D1"}],
  "conclusions": [{"doc_id": "D1", "direction": "increase", "strength": "significant",
                   "claim": "投加量升高去除率上升", "quote": "…", "locator": "p3#para2"}],
  "agreement": {"overall": "conflicting", "items": [{"topic": "投加量方向", "verdict": "conflicting",
                "attribution": "material", "explanation": "两篇催化剂不同，最优投加量不可比",
                "evidence": [{"doc_id": "D1", "locator": "p3#para2"}]}]}
}
```

## 5. 三验抽样记录模板（本包增量）

抽 3 格（数值格、未报告格、冲突格各一），把结果记在 `work/sample_audit.md`：

| 抽样格 (doc×field) | value | quote 命中 | locator 可回 | unit/dataset/口径 | 结论 |
|---|---|---|---|---|---|
| D1×removal | 95 | 是 | p2#para1 | % / 批次实验 / 平衡值 | 通过 |
| D2×dosage | null | 不适用 | 不适用 | note 写清检索范围 | 通过 |
| D1×pH 冲突 | — | 双方引文均在 | 两条 locator 均可用 | 归因 condition | 通过 |

任一列为"否"：先修工作稿，再重跑 `check` 与 `build`；不得把未通过项留到交付。

## 6. 引文抽查命令

```bash
python3 -B scripts/evidence_check.py quote --index /app/work/index.json --doc D1 --quote "<某格引文>"
```

返回 `found: true` 即命中；`mode: loose` 说明原文与引文只差空白/标点，评审前建议改成逐字一致。

## 7. 复跑一致性与增量检查

同一份输入连跑两次，比较三样东西：`comparison_matrix.csv` 是否逐字节相同、`evidence_cards.jsonl` 是否逐字节相同、`result.json` 的 `matrix`/`comparability`/`coverage` 三个键是否相等。任何一项不同，先查是不是工作稿被改动过（时间戳、人工编辑），再查脚本是否读了时间/随机数/当前目录。复跑不稳定意味着他人无法按记录复现，属于可核验性硬伤。

另外做一次"缺工作稿"的保底演练：把 `draft.json` 临时改名后跑 `build`，确认仍能产出四件产物、契约键齐全、`status=partial`，再把 draft 改回来。这个演练能保证评测时 Agent 超时或漏写工作稿也不会空手而归；但演练产出的空表**不得**当作正式交付，交付前必须重新跑一次带工作稿的 `build`。

## 8. 结果自述的边界

对外说明时只主张三件可验证的事：每个非空单元格都能用记录的锚点回到原文；空单元格的原因已被记录；数值综合只发生在可比子集内。不要写"已完整覆盖全部文献"除非矩阵确实满行满列且无降级，也不要把 `partial` 包装成 `ok`。若用了自动兜底（如可比性由字段值推导），在 `method` 与 `degradations` 里明说是推导结果、需要人工确认。

## 9. 提交前六十秒口头复核

不看文件，先把三件事说清：这张表回答的问题是什么、矩阵有几行几列、哪几格是空的以及为什么。能顺口说清，说明工作稿与产物一致；说不清就先回到 `check` 的 counts 重新核对。随后随机挑一个字段，把它的 `definition`、`unit`、`value_rule` 复述一遍，再对照 `comparison_table.md` 里该字段那一行——若复述时才发现定义模糊，说明字典没写到位，先修字典再交付。最后确认包内没有 `__pycache__`、没有把演示目录或历史产物混进来、SKILL.md 里引用的每个相对路径都真实存在。这些动作加起来不到一分钟，但能挡住大部分低级失分点。

如果时间只剩一两分钟，按这个优先级收尾：先保证 `result.json` 合法且契约键齐全，再保证 CSV 行数正确，最后才去润色 `comparison_table.md` 的措辞。原因是前两者属于"有没有交付"的问题，措辞只影响"读起来好不好"。反过来，为了一句总结文案而把已生成的产物覆盖掉，是最不划算的失误。

另一个常被忽略的点是样本量口径：workorder 若要求"最终分析样本量"，就绝不能填筛选前的入组人数；两者混填会让所有下游比值失真。遇到论文同时报告筛查数、入组数、完成数和分析数时，把另外三个数字放进 `note` 供核对，主值只保留分析数。类似地，报告"均值±标准差"还是"中位数(四分位距)"要写进 `metric_scope`，否则同名为"水平"的两格其实不可比。这些细节单独看很小，合起来决定这张表能不能被别人放心引用。

最后一条纪律：`check` 报出的每一个 `FIX` 都要有对应的修改动作，不允许"知道但先这样交"。若确实无法修（例如原文就没有该数据），就把该格改成 `unreported` 并在 `note` 写清检索范围，再重跑一次 `build` 让产物与工作稿一致。交付时 `unfilled contract` 与 `errors` 都应处于可解释状态，这是评审可以现场复核的硬信息。
