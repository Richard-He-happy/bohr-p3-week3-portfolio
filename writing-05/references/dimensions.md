# 维度边界、规则字典与定位约定

这份文档有两个读者：一是复核人，需要知道每条判断在查什么；二是后续维护者，需要知道改
阈值、改文案该去动哪里。正则、阈值、全部中文措辞都集中在 `references/ruleset.json`，
`scripts/gates.py` 只做读取与执行，因此调整判定口径不必碰代码。

---

## 一、六个维度：各自管什么，明确不管什么

结构审读最容易犯的错，是把「我更喜欢这样写」当成「这里结构有问题」。所以每个维度都配一
条排除项：一旦落在排除项里，即使读起来别扭，也不进 finding。

| 维度 key | 管辖范围 | 明确排除 |
|---|---|---|
| `research_question_alignment` | 研究问题有没有被摆明、有没有贯穿到方法与结果；贡献主张与实际完成的工作是否同宽 | 选题新不新、问题有没有意思 |
| `section_structure` | 章节齐不齐、先后是否服务论证、篇幅是否失衡、参考文献章能不能用 | 标题好不好看、编号用哪种样式 |
| `argument_chain` | 判断性句子背后有没有可指认的凭据（引用、数值、图表），引用与图表能否回查 | 凭据是否足以说服整个领域 |
| `paragraph_relations` | 相邻段落的关系是否被写出来（承接、对照、递进）；是否一段里塞了两种功能 | 句子长短、是否单句成段、用词偏好 |
| `duplication` | 同一内容在段内或跨章重复出现，导致主论述位置失焦 | 术语与缩写的必要回指 |
| `conclusion_boundary` | 结论有没有越过数据与设计给出的活动范围（因果化、绝对化） | 结论是否亮眼、是否够有冲击力 |

维度 key 是固定枚举，输出时必须按这六个字符串写，不得自造第七个。

## 二、覆盖状态：为什么是四个而不是两个

只区分「有问题 / 没问题」会掩盖两类真实情况，所以状态取四值：

- `findings`——该维度产出了至少一条带定位的发现。
- `no_issue_with_evidence`——确实检查过但没有命中，`checked` 字段必须写清检查规模（例如覆盖了几组相邻段落、几个正文段落），否则等同于没有检查。
- `degraded_by_error`——该维度的规则执行时抛了异常。这种情况绝不能记为「无问题」，异常本身会进入 `degradations`。
- `not_assessable`——输入里没有可解析的正文（例如纯扫描件、只有图表的材料），检查未执行。

## 三、规则字典

规则 ID 前两位标出所属维度，便于与 finding 对齐。每条规则都能在原文上复核：触发条件写的是可数、可查的事实，不是印象。

### 3.1 章节骨架（SEC）

| ID | 触发事实 | 默认严重度 | 动作 |
|---|---|---|---|
| `SEC1` | 全篇解析出的章节块 ≤1 个，即没有任何可识别的标题行 | high | insert |
| `SEC2` | introduction / method / result / conclusion 四者缺一；若已有 discussion 章，conclusion 可免 | high | insert |
| `SEC3` | 角色序列里 method 出现在 result 之后，或 result 出现在 discussion / conclusion 之后 | high | move |
| `SEC5` | 确有参考文献章，但该章内匹配「行首编号条目」的行数为 0 | medium | insert |

### 3.2 研究问题对齐（RQ）

| ID | 触发事实 | 默认严重度 | 动作 |
|---|---|---|---|
| `RQ1` | 摘要、引言、开头段合计前 8 段内，研究问题句式命中 0 次 | high | insert |
| `RQ2` | 研究问题里长度 >4 的关键词，有一半以上（且至少 3 项）没有出现在结果 / 讨论 / 结论 | high | narrow |
| `RQ3` | 贡献句里超过六成（且至少 3 项）关键词在结果章缺席 | medium | narrow |

### 3.3 论断—论据链（ARG）

| ID | 触发事实 | 默认严重度 | 动作 |
|---|---|---|---|
| `ARG1` | 段落 ≥30 词，段内有主张标记句，但引用 / 数值 / 图表指向为 0 | high（结果、讨论、结论）／medium（其他章） | insert |
| `ARG2` | 正文引用编号在参考文献列表里找不到（一次最多报 3 个编号） | high | insert |
| `ARG3` | 正文指向 Figure / Table N，全篇检不到对应的图题或表题 | medium | insert |

### 3.4 段落衔接（PAR）

| ID | 触发事实 | 默认严重度 | 动作 |
|---|---|---|---|
| `PAR1` | 同章相邻两段各 ≥55 词，词项 Jaccard <0.05，且后段首句不含过渡词（每篇最多 2 条） | low | insert |
| `PAR2` | 单段 ≥120 词，数值句 ≥2 且主张句 ≥1，观测与解释混在一段（每篇最多 2 条） | medium | split |

### 3.5 重复表述（DUP）

| ID | 触发事实 | 默认严重度 | 动作 |
|---|---|---|---|
| `DUP1` | 两段各 ≥45 词，8 词 shingle 集合 Jaccard ≥0.30；跨章且 ≥0.5 记 high（每篇最多 5 组） | medium / high | merge |
| `DUP2` | 去空白、去标点、转小写后长度 ≥55 字符的同一句出现两次及以上 | medium | delete |

### 3.6 结论边界（BND）

| ID | 触发事实 | 默认严重度 | 动作 |
|---|---|---|---|
| `BND1` | 方法与结果只有相关性表述、没有干预 / 随机化 / 对照设计，结论句却用因果动词且无限定语 | high | narrow |
| `BND2` | 摘要 / 讨论 / 结论句含绝对化措辞，且同句没有任何限定或概率表达 | medium | narrow |

阈值不写在本文件里，统一见 `ruleset.json` 的 `thresholds`。另有三个全局上限：单维结论类发现
最多 6 条（`bound_sentence_cap`）、全篇 finding 最多 40 条、`preserved_facts` 最多 25 条。

规则一次没命中，说明的是「按当前口径没查到」，不是「这一维没看」。此时输出
`no_issue_with_evidence`，并在 `checked` 里写清检查对象与数量。

## 四、定位符与字符锚点

稿件被切成三级坐标，任何一条 finding 都必须落到其中一级：

```
C03              第 3 章
C03-P002         第 3 章第 2 段
C03-P002-S01     第 3 章第 2 段第 1 句
```

动作另有起止两端：`from_locator` 指向要被处置的位置，`to_locator` 指向处置的落点。除
`move` 与 `merge` 之外，两者可以相同，表示原地处理。

在此基础上，每条 finding 还会记录 `start` / `end` 两个字符偏移（针对空白归一化后的全文）。
复核人据此可以直接切出原句，不必自己再搜一遍。偏移与实际引用长度的不一致会被自检拦下。

## 五、字段契约

| 字段 | 取值 | 约束 |
|---|---|---|
| `finding_id` | `F01`、`F02`… | 全篇唯一，action 靠它 join |
| `dimension` | 六类之一 | 固定枚举 |
| `severity` | high / medium / low | 直接决定 priority |
| `locator` | 见上一节三级坐标 | 必须能在稿件里找到 |
| `quote` | 原文片段 | 逐字子串；锚定失败即丢弃该条 |
| `diagnosis` | 结构判断 | 只谈位置与关系，不评判科学对错 |
| `evidence_for_judgment` | 计数与依据 | 需可复算（句数、词项数、Jaccard 值） |
| `confidence` | high / medium / low-medium | 与 severity 分开记，二者不等价 |
| `action_id` | `A01`… | 与 finding 一一对应 |
| `operation` | move / merge / split / narrow / delete / insert | 固定枚举 |
| `from_locator` / `to_locator` | 三级坐标 | 见上节 |
| `expected_effect` / `risk` | 文本 | 均非空；风险要写具体副作用 |

「这段可以更简洁」「建议加强论证」这类条目一律不入库：没有落点、没有可执行动作，作者无从
采纳也无从驳回。

## 六、论点—论据映射的形状

```json
{"method": "把主张句与凭据句逐句配对；配不上对的一律记 unsupported",
 "closure_matrix": {
   "fully_closed": false, "total_links": 4, "closed_links": 2,
   "links": [{"from": "result", "to": "conclusion", "status": "thin",
              "shared": 2, "need": 4, "evidence": "…"}]},
 "unsupported_chains": 1,
 "chains": [
   {"paragraph": "C05-P003", "chapter": "C05", "status": "supported",
    "claim": {"locator": "C05-P003-S01", "quote": "<论断原句>"},
    "evidence": [{"kind": "figure", "locator": "C05-P003-S03", "quote": "<凭据原句>"}]}],
 "research_question": {"locator": "C02-P001-S02", "quote": "<研究问题原句>"}}
```

`status=unsupported` 的链条正是 ARG1 的取证来源；`closure_matrix` 里标 `thin` 的那一环，说明
问题—方法—结果—结论这条线上有一处呼应没接住。

## 七、复核动线

1. 打开 `dimension_coverage`，先分清「有发现」与「查过但没有」；后者括号里的数字是检查规模。
2. 按 `edit_plan.md` 的 P1 → P3 逐条执行，每条都带 `from_locator`，能在稿件里直接跳到位置。
3. `confidence=low-medium` 的条目（`PAR1`、`RQ3`）建议人工过一遍再采纳——这正是作者行使「采纳 / 部分采纳 / 驳回」的空间。
4. `pending_human.json` 里的条目需要作者补材料或补判断，Skill 不替作者下结论。
5. 想从头复现：`python3 -B scripts/audit.py --input <case> --out <dir> --check`，输出 pass 与各项计数。

## 八、不判定清单

以下情形只登记、不下结论：稿件疑似截断而缺章、正文没有研究问题句且篇幅过短、输入里有多份
可解析文本无法确定主稿、正文有引用标记但全篇没有参考文献表。对应的说明写在
`pending_human.json`，`kind` 与 `needed_action` 分别说明「是什么情况」与「作者需要补什么」。
