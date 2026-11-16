# 产物字段说明（writing-03 · 1.1.0）

这份文件只讲两件事：产物长什么样、字段之间靠什么串起来。缺什么标什么，是贯穿全部字段的总原则。

## 一、对齐关系先讲

一次运行产出三份主文件，它们能互相 join：

```
论断清单 claims.json ──(claim_id)──> 证据表 evidence_table.json
                     ──(claim_id)──> result.json 的 evidence_map
                     ──(source_id→编号)──> 成稿 evidence_driven_draft.md 中的 [n]
```

另外还有六份辅助文件：强度说明、著录核验、不确定性汇总、待人工清单、成稿兼容副本 `deliverable.md`、契约与运行记录 `result.json`；复核后会再多一份 `verification.json`。`build` 末尾还会写五件可核验资产（金标准、对照报告、版本记录、运行日志、机器自检），详见 SKILL.md 的对应小节。

## 二、论断清单

文件结构是 `{"case_id": ..., "language": ..., "count": ..., "claims": [...]}`。数组中每条：

| 字段 | 含义 |
|---|---|
| `claim_id` | 论断编号，`C` 加三位数字 |
| `location` | 原稿模式下是 `draft:文件 [B块.S句] chars:起-止`；取材模式下直接给材料定位 |
| `text` | 原句，保留句末引用标记 |
| `core` | 去掉句末 `[n]` / `（作者, 年份）` 之后的判断句 |
| `type` | 比较 / 因果 / 推断 / 事实 四选一 |

切分要求：一句只能是一个可判定命题，整段直接算一条属于错误；标题行、表格线、纯编号行、文献表条目本身不列为论断；类型判定顺序是比较词 → 因果词 → 情态推测词 → 其余归事实。

## 三、证据表

结构是 `{"case_id": ..., "count": ..., "schema": "以逗号分隔的字段名", "rows": [...]}`。每行包含：

- `claim_id`：指向论断。
- `source_id`：材料文件编号（如 `D03`）；找不到来源时为 `null`。
- `locator`：`相对路径 [B块.S句] chars:起-止`，字符区间基于解析后的纯文本。
- `quote`：从材料逐字复制的连续片段，标点、单位、数字都不能动。改写、翻译、拼接都算未命中。
- `source_type`：材料自述的研究设计，如队列、RCT、系统综述、指南、预印本；没写则"未标明"。
- `strength`：高 / 中 / 低 / 不足。
- `support_scope`：直接支撑 / 部分支撑（范围不一致）/ 无直接支撑，尽量附 `n~样本量` 或适用条件。
- `conflicts`：结论方向相反的来源列表，最多三条；没有就给空数组，不写 null。
- `rationale`：一句话说明为什么落这个强度。
- `verified`：逐字校验是否通过。
- 找不到来源的行同样保留：`source_id`、`locator`、`quote` 为 `null`，强度"不足"，范围"无直接支撑"。

## 四、成稿

`evidence_driven_draft.md` 的顺序是：标题 → 案例来源信息（原样转录）→ 正文 → 证据边界 → 参考文献 →（若有）材料内文献表。

正文每一句由限定语 + 内容 + `[n]` 组成；引用编号按首次出现重排；每个 `[n]` 都必须能在参考文献段解析到条目；材料没给 DOI 就不写 DOI。原稿模式下保留原有小节标题和段落顺序，取材模式下按主题合成短段。

## 五、result.json

顶层必含 `output_contract` 的全部键（键名不改、未知键保留输入值、无值给 `null` 或 `[]`），以及下列固定字段：

| 字段 | 内容 |
|---|---|
| `case_id` | 输入原样回填 |
| `status` | ok / partial / insufficient_evidence / input_error |
| `deliverable` | 成稿全文；另有 `deliverable_path` 给路径 |
| `preserved_facts` | 数字、单位、DOI 的逐条记录：值、出处引文、定位、是否进入成稿 |
| `evidence_map` | 每条论断的强度汇总、全部证据行、是否无来源 |
| `change_log` | 过度推断下调的改前/改后文本、理由、定位、`human_confirm` |
| `sources` | 每个输入文件的路径、大小、sha256、判定类型、解析方式 |
| `metrics` | 可复算计数：论断总数、有来源数、引文命中/失败数、强度分布、冲突数、降级数、支撑率 |
| `pending_human` | 需要人补做的事项：回原文、补文献表、OCR 等 |
| `uncertainty` | 不确定性文字说明 |
| `errors` / `degradations` / `changes` | 异常、降级、变更三本账 |
| `integrity` | 结构自检：契约回填、claims↔evidence join、引文全命中、引用编号可解析 |
| `runtime` | 脚本、版本、Python 版本、耗时、参数、`network: disabled` |
| `agent_work` | 是否使用 Agent 工作稿、工作稿路径、work 目录 |
| `verifiable_assets` / `golden_standard` / `diff_report` / `version_history` / `run_log` / `self_check` | 五件可核验资产的路径与字节（`verifiable_assets` 为汇总对象） |
| `coverage` | 金标准条目数、自检通过与否、对照达标计数 |

契约字段的合并顺序：先按 `output_contract` 赋值，再接固定字段，最后追加资产路径；契约键不会被资产字段覆盖，缺值统一进 `contract_unfilled_keys`。

## 六、复核脚本会质疑什么

`audit.py` 不读自报文字，只重算：契约键齐不齐、`case_id` 一不一致、契约值是否空、quote 是否仍在材料里逐字出现、claim_id 有没有悬空、每条证据行的 locator/strength/support_scope/quote 是否齐、成稿正文的引用编号有没有超出参考文献数量、正文是否出现"证明/确证"类越级词、五件资产是否齐全非空、金标准引文是否全命中、`self_check.pass` 是否为真。结果全部写入 `verification.json` 的 `checks`，`passed` 为所有项的交集。
