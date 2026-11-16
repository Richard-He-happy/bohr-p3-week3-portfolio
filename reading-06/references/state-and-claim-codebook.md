# 状态与结论规则手册

内容：四种允许状态、引文如何判定、结论/限制/推测如何分层、冲突如何保持开放、以及不确定性
与人工接管的分界。

## 1. 只用这四种状态

| 状态 | 触发条件 | 必须附带 |
|---|---|---|
| `reported` | 所引段落或单元格印出了该值 | `value`、逐字 `quote`、`source` 定位 |
| `not_reported` | 查过且确实没有 | `search_scope`：章节、表格、关键词 |
| `source_conflict` | 两处对同一字段同一条件给出不同读数 | 两段引文、两个定位、两个值 |
| `extraction_failed` | 页面/单元格不可读，或引文无法核实 | `notes` 写明具体原因 |

判定流程：先尝试 `reported` 并在定位处核验引文；再检查材料本身是否印出了互相矛盾的读数；
只有在扫完所有章节**和**所有表格之后才允许 `not_reported`；材料本身读不了才用
`extraction_failed`。缺失绝不能写成数字，`notes` 里的解释也不能替代数值。

## 2. 引文判定

1. 引文是所引段落或行内连续的一段原文；省略号、重新拼接、修拼写、补单位都算不合格。
2. 必须包含数字、单位，以及能区分条件的词（`时效 16 h`、`n = 4`、`450 C`）。
3. 值与条件分处相邻两句时给两段引文并标 `quote_join: "adjacent_sentences"`，不得伪造一句。
4. 表格单元格的检索文本是 `work/corpus_index.json` 给出的
   `表题 | 列标题 | 行标题 | 单元格值` 拼接串；同时 `source` 必须逐字带
   `table_id`、`row_header`、`col_header`。
5. 字符一致不等于语义一致：接受前确认引文句子讨论的主体与条件就是本字段的，脚本只能比对
   字符。

闸门会区分 exact、大小写归一、空白归一、模糊与缺失。缺失时该字段降级为
`extraction_failed` 并生成 `pending_human`；模糊命中保留 `reported`，但追加
`quote_not_verbatim` 不确定性。

## 3. 结论分层

结论类字段（`author_conclusion`、`limitation`、`hedged_claim`，或 `expected_type: text`）
必须标明层：

| 层 | 表面标记（示例） | 允许的写法 |
|---|---|---|
| `conclusion` | conclude、show、demonstrate、reveal、confirm、establish、find、report、therefore | 可作为论文自身发现引用 |
| `limitation` | limitation、limited、only、however、cannot exclude、did not test、small sample、further work、under these conditions | 只作为适用范围限制，不并入结论 |
| `speculation` | may、might、could、suggest、appear、seem、likely、probably、possibly、potential、indicate、imply、preliminary、trend | 保留模糊词；`may indicate` 不得改写为 `shows` |

整句只有模糊词而没有强动词时，记 `strength: hedged`，确保读起来仍是不确定的表述。归属信息
放在同一对象里：`source.paragraph_id` 加引文。

`readability` 取值：`directly_read`（引文已逐字核验）、`inferred`（由算式或跨句阅读得到）、
`undetermined`（引文在但语义关联未建立，同时进 `uncertainties`）。

## 4. 冲突保持开放

冲突记录保留每个读数及其定位：

```json
{"field_id":"yield_strength","status":"source_conflict",
 "value":["318","305"],"units":["MPa","MPa"],
 "quote":["... 318 MPa (SD 11 MPa, n = 4)","... 305 MPa for the same alloy ..."],
 "source":{"paragraph_id":"R-004"},
 "conflicts":[{"value":"318","source":{"paragraph_id":"R-004","page":6}},
              {"value":"305","source":{"paragraph_id":"R-017","page":12}}],
 "notes":"摘要与表 3 不一致；未取平均；待人工裁定"}
```

不取平均、不默认信摘要、不丢任何一侧。

## 5. 不确定性与人工接管

- `uncertainties[]`：重读能解决——引文模糊、单位缺失、无误差线、条件槽为空、模糊强度不明、
  引文中找不到条件词。
- `pending_human[]`：需要人决定——引文找不到、值与引文不符、真实冲突、表格区域不可读、
  扫描页。

两个列表都只装对象，至少带 `field_id` 与简短的 `type`/`issue`，不写自由散文。

## 6. 条件绑定检查（本包增量）

每个 `reported` 字段都会把 `condition` 里的词与 `quote` 里的词比对一次。若引文里一个条件词
都没有，`validation.condition_binding.bound` 为 false，并追加
`condition_not_bound_to_quote` 不确定性；状态本身不自动改变，因为这种形态多半意味着数值是
从相邻实验挪过来的，值得人工回读一遍。若命中，则记录命中槽位与重合词，方便以后审计
"值与其条件出自同一句"。该检查只是确定性的初筛，语义正确性仍需人工抽查。
