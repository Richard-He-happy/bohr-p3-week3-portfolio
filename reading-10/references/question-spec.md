# 草稿格式规范（`work/questions.draft.json`）

这是 `check` 与 `build` 唯一读取的输入文件。本规范只写"推荐写法"；脚本用 `first_of()` 兼容少量
历史别名，那是为迁移旧草稿准备的，不要主动使用。

## 0. 先记四条底线

1. 每道题至少一条 `evidence`，`quote` 必须是**材料原文的连续片段**；
2. 每个 `rubric` 点至少一个能在原文里找到的 `key_terms`；
3. `question` 必须能**只靠材料**回答，材料没写的就出"是否报告"型题；
4. 题号、评分点号在题集内唯一。

## 1. 证据块（最重要，先写这个）

一条证据就是一个对象，三个键：

- `quote`：**逐字**原文片段，≥12 字符；只允许空白差异（多空格、换行），不允许改词、拼接、翻译、
  加省略号。抄写来源是 `show` 的输出，别手打。
- `locator`：`<材料号>#p<段号>` 形式，例如 `M02#p11`；不写时脚本按命中位置反推并记一条 NOTE。
- `material`：材料编号（`M02`）；不写时从 locator 前缀推断。

一道题可以给多条证据：跨段对比给两条、材料内冲突给两条（各自指向冲突的一方）。算分时取覆盖度
最高的那条，所以别用一条弱证据去"凑数"。

## 2. 评分点（rubric 数组）

每个点是一个对象：

- `id`：题内唯一，习惯写 `R1`、`R2`；缺省按出现顺序补。
- `text`：一句话说明"答到什么算过"，直接写进报告给人看。
- `weight`：浮点，所有点相加应≈1.0；偏离 0.02 以上只记 NOTE，不影响算分。
- `key_terms`：1–5 个短串，**用原文的实词**——数字、单位、术语、专名。脚本统计这些串在证据
  引文中的出现比例，作为覆盖度。写"准确""完整""合理"对算分毫无影响；`pH`、`CO2` 这种两三个
  字符的术语要显式写，自动抽取会跳过过短的词。

经验值：两点 0.6/0.4 或三点 0.35/0.35/0.3 能区分"答对一半"，一个点权重 1.0 只有在答案是一个
不可分割的事实时才用。

## 3. 整张题卡

必填：

- `id`（str）：题集内唯一，习惯 `Q01`；重复时脚本加后缀并报 FAIL。
- `type`（enum）：`extraction`、`numeric`、`method`、`definition`、`conflict`、`coverage`、
  `table`、`other` 之一；未知值落到 `other`，只影响报告分组与统计。
- `question`（str）：≥10 字符。
- `rubric`（array）：≥1 个点，见 §2。
- `reference_answer`（str 数组）：≥1 条参考要点，可以带 locator；这是"评分锚点"，不是给
  Agent 的答案模板。
- `evidence`（array）：≥1 条，见 §1。

选填：

- `difficulty`：`easy` / `medium` / `hard`，缺省 `medium`；只用于展示，不参与算分。
- `sources` / `source_refs` / `material_refs`：给复核人看的来源说明，脚本不读，但建议保留。

## 4. 顶层

- `case_id`（str，可缺）：与 `case.json` 对齐便于追溯；缺省时取 case 里的。
- `notes`（str，可缺）：出题思路、覆盖了哪些段落，写给复核人。
- `items`（array，**必需**）：题卡数组；别名 `questions` 也认；给空数组会让 `build` 走确定性兜底。

## 5. `check` 会逐条报什么

报错分两级：`FAIL` 让题不进题集，`NOTE` 只提示。

1. 必备字段缺失或 `question` 过短 → FAIL；
2. `quote` 在材料里找不到 → FAIL（`quote_absent`），要回 `show` 重新复制；
3. 命中位置与声明的 `locator` 不一致 → FAIL（`locator_mismatch`）；
4. `quote` 少于 12 字符 → FAIL；
5. 题号重复 → 自动改名 + FAIL；
6. 整个题一个可核验引文都没有 → 拒收，进 `benchmark.json.rejected` 与 `pending_human`；
7. 权重和偏离 1.0 → NOTE；
8. 某题全部 `key_terms` 缺失 → NOTE，脚本改用 `reference_answer` 自动抽取；
9. `locator` 缺省但命中明确 → 自动补齐 + NOTE。

机器可读结果写在 `work/check_report.json`（`issues` / `warnings` / `rejected` / `n_raw` / `draft_path`）。
`check` 失败不影响继续 `build`：`build` 会保留能用的题、对被拒部分做兜底。

## 6. 一份可运行的示例（**示例数据**，不是任何正式案例的答案）

```json
{
  "case_id": "spec-demo",
  "notes": "M03#p4 数值；M04#p2 方法；M03#p6 未报告",
  "items": [
    {
      "id": "Q07",
      "type": "numeric",
      "difficulty": "medium",
      "question": "催化剂 C-7 在 80 °C 下的转换频率是多少，作者给出的误差范围多大？",
      "rubric": [
        {"id": "R1", "text": "给出 0.42 mmol h-1 g-1", "weight": 0.6,
         "key_terms": ["0.42", "mmol"]},
        {"id": "R2", "text": "给出 ±0.03 的误差", "weight": 0.4, "key_terms": ["0.03"]}
      ],
      "reference_answer": ["0.42 mmol h-1 g-1，误差 ±0.03"],
      "evidence": [{
        "material": "M03",
        "locator": "M03#p4",
        "quote": "the turnover frequency of C-7 at 80 °C reached 0.42 mmol h-1 g-1 (±0.03)"
      }]
    }
  ]
}
```

## 7. 返工高发点（按出现频率排）

1. **引文是手打的**：`d-1` 写成 `d−1`、`µ` 写成 `u`、`±` 漏掉——都会 `quote_absent`。一律复制。
2. **`locator` 猜错了段**：材料切段按空行，标题单独成段是常事；先 `show` 再写 locator。
3. **`key_terms` 写成了评价词**：覆盖度永远是 0，题目白白从 2 分掉到 0/1 分。
4. **一题只有一个证据且被拒**：整题消失；多给一条同题证据能显著降低拒收率。
5. **把"未报告"写成猜测数字**：违反题面要求，且无法核验；写"未报告"反而能拿分。
6. **题目超纲**：问题需要材料外的知识才能答，等于把评分点建在空气上。
