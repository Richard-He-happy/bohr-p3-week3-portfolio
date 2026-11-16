# 工作稿字段契约

## 0. 放在哪、怎么被找到

工作根下按顺序找：`workplan.json` → `edit_plan.json` → `plan.json` → `edits.json`；也可在 `check` / `build` 时用 `--workplan <文件>` 指定。文件名不重要，能解析出下面这些字段才重要。

## 1. 必须满足的四条

1. **每个工单 target 都要被覆盖**。漏掉的 target 会被自动补成 fallback 标注，并在 `accept_reject` 里留下 `origin=fallback`。
2. **锚点引文逐字存在**。`original_quote` 取自目标段落原句；比较时先归一化空白、全角/半角引号与破折号，但字面必须对得上。
3. **标注够长且有内容**。去空白后至少 60 字符，写的是科学条件、材料边界、测量口径、引用范围之类；"此处很重要"不算。
4. **证据至少一条能回材料**。`evidence[].quote` 必须在稿件或材料文件里字面命中；脚本会把命中位置回填成 locator。

## 2. 字段字典

| 键 | 是否必填 | 说明 |
|---|---|---|
| `target_id` | 必填 | 必须与工单 target 一致；也接受 `target` / `id` |
| `original_quote` | 必填 | 目标段逐字原句；也接受 `quote` / `anchor` / `before` / `original` |
| `annotation` | 必填 | 插入的标注正文，≥60 字符；也接受 `new_text` / `note` / `insert` / `content` |
| `evidence` | 必填 | 证据数组，元素至少含 `quote`（或 `text` / `excerpt`）；也接受 `sources` / `citations` |
| `rationale` | 建议 | 写清对应工单哪条要求；会进 `change_log.md`，缺了不阻断构建 |
| `decision` | 可选 | `accept` 默认；写 `reject` 表示提出但不采纳，回执里记 `rejected` 并留给人工 |
| `preserved_facts` | 建议 | 关键事实的保真记录；每条 `quote` 会被回验，未命中则 `verified:false` 并进 `pending_human` |
| `uncertainty` | 建议 | 材料没说清的问题，原样写进最终 `result.json` |
| `pending_human` | 建议 | 需要作者决定的事项，原样写进最终 `result.json` |

顶层目标列表键也接受 `edits` / `changes` / `annotations` / `items`。额外元信息（`prepared_by`、`operation`、`anchor_block_id` 等）允许存在，脚本不会因此报错。

## 3. 完整骨架（字段顺序随意）

```json
{
  "case_id": "C01",
  "prepared_by": "agent",
  "targets": [
    {"original_quote": "目标段中的一句逐字原话",
     "annotation": "写清条件/边界/需澄清处的标注，长度 ≥60 字符",
     "evidence": [{"quote": "材料中逐字存在的支撑句", "locator": "Section 2.1",
                   "source_id": "稿件文件名"}],
     "rationale": "为什么加在这里，对应工单的哪一条",
     "decision": "accept",
     "anchor_block_id": "C01-P002",
     "operation": "add_editorial_annotation",
     "target_id": "C01-P002"}
  ],
  "preserved_facts": [
    {"fact": "被保留的关键结论", "value": "48.6",
     "quote": "逐字包含该数值的原句", "locator": "Section 3",
     "source_id": "稿件文件名"}
  ],
  "uncertainty": [],
  "pending_human": []
}
```

## 4. 一份写得对的样例（示例数据，非正式案例结果）

```json
{"targets": [{
  "target_id": "C01-P002",
  "original_quote": "Interlayer bonding governs the tensile response of the printed coupons.",
  "annotation": "The quoted 50-80% improvement range is not tied to any polymer, nozzle size or layer height, so it cannot be read as the benchmark for the coupons described later in this manuscript, which were printed with a 0.4 mm nozzle at 0.2 mm layer height and 100% rectilinear infill. The band should therefore be treated as an indicative literature range, not as a prediction for the present build configuration; the manuscript should state which comparator it intends.",
  "rationale": "The workorder asks for a condition-level clarification; the paragraph cites a range without stating the material and process basis behind it.",
  "evidence": [
    {"source_id": "C01_source_chapters.md", "locator": "Section 2.1",
     "quote": "All coupons were conditioned at 23 C and 50 percent relative humidity for 48 h before testing."}],
  "decision": "accept"}]}
```

## 5. 反例与对应结果

- 把原句改写成同义句当锚点 → 字面不命中，`original_quote not found verbatim in the source`，转 fallback。
- 标注写成"该结论意义重大" → 长度或信息量不足，`annotation under 60 chars (not substantive)`，转 fallback。
- 证据来自记忆、材料里没有 → `no evidence quote verified against the source`，转 fallback。
- 标注引入材料没出现的数字 → 不拒收，但回执里出现 `warnings: numbers not found in source`，需要人工确认。
- 想整段替换原段落 → 做不到：注入动作只有"目标块之后插入"，`blocks_rewritten` 恒为 0。
