# Annotation quality bar and receipt reading guide

## A. 五条质量要求（按重要性排序）

1. **Anchored to a concrete sentence.** Copy one verbatim sentence from the target paragraph as the anchor; the annotation sits right after it so a reader sees exactly which claim is being commented on.
2. **Names a checkable boundary.** Say which material system, process parameters, sample size, measurement conditions, statistical convention or citation coverage is at stake. "This is important" carries no information.
3. **Adds no outside facts.** No numbers, references, experiments or conclusions that the supplied material does not contain. When data is genuinely missing, write "needs author input".
4. **Traceable back.** Attach 1–3 verbatim quotes plus locators (section number, paragraph id, block id with line range).
5. **Respects the boundary.** Insert, never rewrite the original sentence. If the source contradicts itself, put the contradiction in the annotation or in `uncertainty`; do not silently repair it for the author.

脚本的 60 字符下限只是**过滤空话用的门槛**，不是质量线；合格标注一般 200 字符以上。

## B. 历史失分模式对照

| Failure pattern | What it looks like | What this package does instead |
|---|---|---|
| Text-only rewrite | Prose that cannot be placed back into the manuscript | `manuscript.md` is the primary artifact; every note is fenced by `ANN-START/ANN-END` markers |
| Whole-paragraph overwrite | Original wording replaced, facts drift | Injection only appends after the target block; `blocks_rewritten=0` and `byte_identical_to_source=True` |
| Invented quotation | Quote cannot be found in the source | Literal match in `find_in_blocks`; a miss rejects that item and triggers fallback |
| Mechanical checklist | Paragraphs listed without scientific judgement | The workorder `consistency_scope` forces a re-read of definitions/methods/results; notes must land on concrete conditions |
| Untraceable versions | Copies diverge from their origin | v1/v2 endpoints plus a real rollback/reapply hash round-trip |
| Broken layout on export | Headings, tables, formulas or numbering drift | Structure counts are compared after stripping annotations (`format_integrity`) |
| Silently claiming success | Gaps are not reported | `status`, `degradations` and `pending_human` record the truth in three places |

## C. 回执阅读顺序

**第一步：`receipts.json`。**

- `import` — 稿件来源路径、sha256、解析模式（`native` / `reconstructed` / `reconstructed-degraded`）、块数与结构计数、目标定位结果。
- `accept_reject.items[]` — 每个 target 的裁决。先看 `origin`：`fallback` 意味着这条不是 Agent 写的，必须人工复核；再看 `reasons`（被拒原因）以及 `quote_ok`、`ev_ok`、`chars`、`applied` 这些实测值。
- `version_compare` — v1/v2 两端 sha256、增删行数、`rollback_test`（回退后哈希是否变化、重放后是否复原）。
- `invalid_operations` — 五类故意越权调用的拦截记录：越界块（I1）、负索引（I2）、回滚未应用的改动（I3）、重复 change id（I4）、把 `case.json` 当稿件导入（I5）。每条都要求 `raised=true` 且 `state_unchanged=true`。
- `preserved_facts` / `evidence_map` — 逐条 fact/claim 的引文、定位与 `verified` 状态。

**第二步：`result.json`。**

- `status` — 只有"零 errors、零 fallback、零 reject、零未验证 fact，并且有改动落地"时才是 `ok`。
- `preservation` — `annotation_free_sha256` 与 `source_sha256` 并列展示，直接判断原文有没有被动过。
- `format_integrity` — `preserved=true` 表示标题/表格/公式/引用计数与源稿一致。
- `receipts.coverage` — 一屏看完目标覆盖、事实核验、原文保真三件事。

**第三步：五份审计材料。** 先看 `self_check.json` 的 `failed_ids`，再按 id 到 `diff_report.md` 查对应谓词的实测值，最后在 `version_history.md` 确认回退步骤能实际执行。

## D. 交付前 60 秒自查

1. `manuscript.md` 中目标段落原句是否一字未变？
2. 每条标注是否都带引文依据和 locator？
3. `change_log.md` 的 before / after 是否成对，计数是否与回执一致？
4. `pending_human` 里是否只剩真正需要作者决定的事项？
5. 打开 `preview.html`：标题层级、表格、标注高亮是否正常？

## E. 写标注时的三个坏习惯

- **把转述当引文**：用自己的话复述原文再塞进 `original_quote`，必然命中失败；锚点要用复制粘贴。
- **用形容词代替条件**："意义重大 / 数据可靠 / 需要改进"这类判断没有回查价值；换成"未说明层高与喷嘴直径，因此该区间不可直接与 2.1 节试样比较"。
- **一次塞太多**：一条标注只解决一个可验证的问题；多个问题拆成多条，便于逐条接受或拒绝。
