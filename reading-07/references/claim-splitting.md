# 论断拆分、证据卡与复核仲裁

## 1. 为什么一定要拆

一条复合句的不同成分，成立状态可能相反：前半句原文有依据，后半句是外推。整句给一个 verdict 会同时制造两类错误：
**误支持**（把局部成立放大成整句成立）与**漏检**（不成立的部分被整体结论掩盖）。因此，每条输入 claim 至少拆出
1 个子判断；带并列、因果、比较或限定的至少拆 2 个。

## 2. 拆分执行规则

脚本入口函数 `split_claim()`；人工复核用同一套规则：

1. 第一刀按 `；` `;` `。` 和换行切大句。
2. 第二刀按并列连接词切：中文 `并且 而且 同时 此外 另外 以及 但是 然而 不过 但 且`；
   英文 `and also`、`, and`、`, but`、`, while`。切出的残片不足 4 个字符的丢弃。
3. 若仍只有一句，但逗号两侧各带一个方向词（"提高 20%，降低 10%"这类），按逗号切成两条比较判断。
4. 因果句不拆成两半：保留为**一条** `causal` 子判断，要求证据句原因侧与结果侧同时出现；只有相关性不算。
5. 去重：空白归一化后前 60 个字符相同的片段只保留一条，避免重复核验。
6. 单条 claim 最多 7 个子判断；多出的并入最后一条，并在 `limitations` 记录 `merged_tail`。

## 3. 子判断类型 → 需要的证据

| 线索词形态 | 归入类型 | 证据要求（拼进 required_evidence_type） |
|---|---|---|
| 没有比较、没有因果、没有限定 | fact | 同一发现被明说，且对象与数值同在 |
| 「高于 / 优于 / 小于 / 相比 / higher than」 | comparison | 两个对象、同一指标、同一方向同时出现 |
| 「导致 / 因此 / 引起 / lead to / due to」 | causal | 因果链或干预结果被明说；仅相关不算 |
| 「所有 / 仅 / 均 / always / only」 | scope | 样本域或边界条件被交代 |

## 4. 四个必须保留的字段

`comparator`、`negation`、`significance`、`conditions` 要落在每个子判断对象上；缺一项，判定就难以复核。
抽取由脚本负责，人工复核对回原文：

- comparator 抽取：`A 高于 B` 记作 `A vs B`；`compared with X` 或 `相比 X` 记作 `X`。
- negation 抽取：不、未、没有、无法、并非、not、without 都算否定；"不同、不断、不仅、不少"是例外搭配，要排除。
- significance 抽取：出现"显著 / 极显著 / significant / p<0.05 / 95% CI"即认为论断声称显著。
- 条件限定看这些形态：「在……条件下」「当……时」「under ... conditions」「for ... samples」。

## 5. 一张证据卡长什么样

`evidence_cards.jsonl` 一行一卡，下面给一张拆开的卡当例子（**示例数据**，不是正式案例结果）：

```json
{
    "card_id": "EV-K1-S2",
    "claim_id": "K1",
    "sub_id": "S2",
    "verdict": "contradicted",
    "verdict_confidence": "medium",
    "type": "comparison",
    "required_evidence_type": "both entities, same metric, same direction",
    "claim_text": "450 °C 焙烧的 Ni/Al2O3 催化剂 CO 转化率高于 350 °C 样品。",
    "sub_text": "450 °C 焙烧的 Ni/Al2O3 催化剂 CO 转化率高于 350 °C 样品。",
    "comparator": "450 °C 焙烧 vs 350 °C 焙烧",
    "negation": false,
    "significance": false,
    "conditions": "450 °C 焙烧",
    "evidence": [{
        "source_id": "catalyst-paper",
        "unit_id": "R2",
        "locator": {"type": "json", "json_pointer": "/paragraphs/1", "unit_id": "R2",
                    "section": "Results", "page": 3},
        "label": "catalyst-paper | sec:Results | p.3 | unit:R2",
        "quote": "CO 转化率由 62% 降到 54%，说明 450 °C 焙烧会导致活性下降。",
        "supports": false,
        "role": "counter"
    }],
    "rationale": "原文方向与论断相反（up/down）；覆盖度 0.67；证据句：……",
    "limitations": [],
    "conflict": false
}
```

卡里还固定带两个检索证明字段：`counter_evidence_searched` 恒为 true（表示已主动找过反证），
`search_scope` 记录 `units_scanned`（扫过多少单元）、`sentence_windows`（句子窗口总数）、
`candidates_kept`（保留候选数）。

## 6. 定位怎么给

- JSON 材料：`json_pointer`（例如 `/paragraphs/1`），或 `paragraph_id` + `section` + `page` 三件套。
- 纯文本 / Markdown：block 序号；PDF：页序 + 抽取方式（写进 `sources[].format`）。
- 只给"篇名 + 作者"不算定位。跨段证据给两条 quote，每条各自带 locator。
- quote 要与原文逐字一致；脚本按空白归一化后比对，命中不了就拒收。

## 7. 双人复核与仲裁

**A 角色**：运行 `audit_claims.py` 得到机器初判 `evidence_cards.jsonl`（`evidence_path=rule_engine`）。

**B 角色**：另建 `review.csv`，列名固定 `card_id, verdict_A, verdict_B, reason_B, quote_B`。
只复核 A 的 `supported` 与 `contradicted` 卡片——这两类判错的代价最高。

仲裁规则：
1. 两人判断一致 → 直接保留。
2. B 能给出**逐字 quote 且支持相反判定** → 采纳 B；该卡 `verdict_confidence` 降为 `low`，
   两段 quote 写入 `conflict.both_sides`。
3. B 只有口头意见、拿不出 quote → 不采纳，保留 A 的判定，另记 `pending_human`。
4. 分歧只出现在 `partially_supported` 与 `supported` 之间时，按支持度规范第 2 节第 5 步逐项对齐要素，不投票。

一致性指标：`agreement = 一致卡片数 / 复核卡片数`，写进运行说明；低于 0.8 先修规范再扩案例。
仲裁后的最终 verdict 必须能追溯回某条 quote；追溯不回去的一律回退 `insufficient_evidence`。

## 8. 他人复核清单

- 每张卡的 quote 能否在 `sources[].path` 指向的文件中检索到？
- verdict 是否落在四级集合内？`partially_supported` 是否写清哪一项没对齐？
- `contradicted` 是否给出了明确的相反表述，而不是"原文没提"？
- 冲突卡的两侧是否都带 locator 与 quote？
- `coverage` 四类计数之和是否等于 `claims_verified`？`sub_claim_verdicts` 之和是否等于 `split_subclaims`？

## 9. 拆分环节常见的三种错误

**拆得太碎。** 把一条因果句切成"有相关性"与"有因果性"两半，会让两个子判断都缺证据、整体被拖成证据不足。
正确做法是因果句保留一条，要求同一证据句同时给出原因侧和结果侧。

**拆得不够。** 句子里的"并且/同时/以及"被忽略，整句只给一个 verdict，后半句的外推就藏进了前半句的成立里。
遇到并列连接词必须逐个切成子判断，即使切出来的片段很短。

**拆完不复核要素。** 子判断切出来后没有把比较对象、否定词、显著性、条件带过去，导致后续检索拿错锚点。
切分结束后，每个子判断都要单独跑一遍四要素抽取，缺项就在 `limitations` 里留痕。

## 10. 拆分粒度与效率的取舍

### 多语言与特殊句式

中文与英文混合的 claim（例如中文句子里夹带英文术语或型号）按同一套连接词规则切分，但英文子句要额外检查
`, which` / `, while` / `; however` 这类弱连接。引用转述（"as reported by X"、"据 X 报道"）不拆成两个判断，
而是保留为一条并注明转引来源，因为原始出处不在输入材料里，判定只能落到转引段落本身。
带括号补充说明的句子先去掉括号内容再拆，避免括号里的条件被误当成独立判断。

拆得越细，覆盖面越大，但每条子判断都要重新检索，效率会下降。推荐按"可独立判定的最小成分"来切：

- 事实句：一个主语配一个结论即可，同一句里的两个不同指标不要合并；
- 比较句：保留完整的"对象 A + 指标 + 方向 + 对象 B"，不要拆成"有 A"与"有 B"两条；
- 因果句：一条因果链算一个整体，原因侧与结果侧不拆开；
- 范围句：把全称限定单独成条，因为它常常是外推风险的来源。

经验值：单条 claim 拆出 2～4 个子判断时，检索成本与覆盖质量最平衡；超过 5 条时优先合并同义片段，
并把合并动作记进 `limitations`。这样 `coverage.split_subclaims` 能与实际人工复核量对上，
也方便对照"不加载 Skill 时整句重读原文"的成本差异。

合并时保留原句措辞作为 `sub_text`，不要把两个片段改写成一句新话——改写会丢掉否定词和条件，
也会让后续 quote 回查失去依据。
