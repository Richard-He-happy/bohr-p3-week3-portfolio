# 节点与关系规范（node-edge-spec）

本文件是 `mindmap.json`、`node_evidence.csv`、`result.json` 三份产物共用的字段契约，
也是与他人交换导图时的最小互操作说明。所有条目均为可执行规则，不是风格建议。

## 1. 结构真源 schema

```json
{
  "schema": "mindmap/1.0",
  "case_id": "案例标识，原样取自 case.json",
  "generator": "mindmap-evidence-forge/1.0.0",
  "source_mode": "agent | fallback",
  "generated": "2026-01-01T00:00:00",
  "theme": {"id": "root", "label": "中心主题", "evidence": [EVIDENCE]},
  "nodes": [NODE],
  "edges": [EDGE],
  "dropped_edges": [{"from": "id", "to": "id", "type": "cause", "reason": "为何不画"}],
  "layout": {"canvas": [宽, 高], "boxes": {"节点 id": [x, y, w, h]}, "columns": 4, "collisions": []},
  "stats": {"nodes": 0, "edges": 0, "verified_evidence": 0, "depth": 0}
}
```

`NODE`：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 图内唯一；与 `root` 冲突时自动加后缀，不丢节点 |
| `label` | string | 是 | 名词短语 ≤ 20 字；不带「综上所述」类装饰语 |
| `parent` / `parent_id` | string | 是 | 同一值的两个名字；`root` 表示直挂中心主题 |
| `level` | int | 脚本填 | 由 parent 链推导，root 为 0 |
| `role` / `type` | string | 是 | `role` 为英文词表，`type` 为对应中文，二者等价 |
| `status` | `fact` / `summary` / `inference` | 是 | 区分原文直述、材料内概括、你的推断 |
| `summary` | string | inference 必填 | 一句依据说明；缺失触发 `inference_bare` 告警 |
| `evidence` | [EVIDENCE] | 是 | 至少一条；全部未命中则该节点进 `unverified` |
| `evidence_ids` | [string] | 脚本填 | 每条证据的 `EV01` 编号，供边引用 |
| `verified` | bool | 脚本填 | 是否至少一条证据逐字命中 |

`EDGE`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `from` / `source` | string | 起点 id，同值两名 |
| `to` / `target` | string | 终点 id，同值两名 |
| `type` / `relation` | string | `cause` / 因果，`depends` / 依赖，`contrast` / 对比，`sequence` / 时间，`cite` / 引用，`support` / 支持，`conflict` / 冲突 |
| `evidence` | [EVIDENCE] | 空则整条边被丢弃（`dropped_edges`），因为无证据的关系不画 |
| `grounded` | bool | 脚本填：引文是否命中材料 |

`EVIDENCE`：

```json
{"id": "EV03", "material": "M1", "locator": "p.4¶3", "quote": "原文连续片段", "verified": true}
```

## 2. 词表与降级映射

- 角色词表（英文）：`question` `method` `evidence` `finding` `conclusion` `limitation` `gap` `task` `risk` `concept` `subtopic`。
- 中文别名：问题 / 方法 / 证据 / 结果 / 结论 / 局限 / 空白 / 任务 / 风险 / 概念 / 子题；`result`→`finding`、`发现`→`finding`、`recommendation`→`task`、`topic`→`concept`。
- 词表外的角色不报错，一律降级为 `subtopic` 并留痕，避免整张图因一个拼写失效。
- 关系别名同样宽松：`causal`→`cause`、`depend`/`dep`/`依赖关系`→`depends`、`对照`/`compare`→`contrast`、`time`/`order`/`时序`→`sequence`、`citation`/`ref`→`cite`、`supports`/`证据支持`→`support`、`矛盾`→`conflict`。
- 无法识别的类型直接丢弃该边并写 `dropped_edges`，不做静默猜测。

## 3. 定位与引文口径

| 材料类型 | locator 形如 | quote 要求 |
|---|---|---|
| PDF | `p.3¶2`；无文本层兜底为 `stream7` | 必填，逐字，10–200 字 |
| DOCX | `¶7` | 必填 |
| Markdown / TXT | `¶12` | 必填 |
| CSV / TSV | `row5` | 必填 |
| JSON | `json:/results/0/value` | 必填 |
| 幻灯片 | `slide3` | 必填 |
| 图片 / 图表 | `figure2` / `table1` | 可空，但 locator 必须以 figure/table/图/表 开头 |

比对算法：NFKC → 破折号与引号折叠 → 空白压缩 → 小写；先整体检索，再逐单元定位；不中则做「去空白去连字符」的二次比对；仍不中即 `verified: false`。这条口径只许收紧。

## 4. 布局与可读性约束

- 布局算法：缩进树。一行一节点、一列一层，列宽取该层最宽标签，因此节点框两两不相交；`layout.collisions` 应恒为 `[]`，非空即布局 bug。
- 节点框最小宽 84px、最小高 32px；标签按 250/205px 折行，最多 3 行，超出以 `…` 截断。
- 画布四周留白 ≥ 36px；关系线走右侧走廊（`x > 最右节点框`），不压节点；底部预留 138px 给图例与署名。
- SVG 中每个节点一个 `<g id="node-<id>">`，携带 `data-node-id`、`data-level`、`data-role`、`data-parent`、`data-locator`、`data-quote`、`data-material`、`data-evidence`、`data-verified`；文字放在 `<text><tspan>` 内，可被任意编辑器改写。
- 不引用外部字体、图片或脚本；字体族只写系统名，缺字体时由渲染器回退。

## 5. 检查清单（可复用到其它项目）

1. `theme.label` 非空且不是元词；中心主题能被材料标题或引文支撑。
2. 单一根、父子链无环、深度 ≤ 4、主分支 3–6 个。
3. 每个节点至少一条 evidence；覆盖率与 `node_evidence.csv` 的 `verified=yes` 行数一致。
4. 同一父节点下的子节点标签不得重复；长度差应 < 14 字（脚本按 14 字阈值报 `granularity_skew`）。
5. 边的 `type` 在七类词表内，方向符合语义；`dropped_edges` 里的每条都在 `pending_human.json` 有对应提问。
6. 标签数字都能在引文或材料原文检索到。
7. `mindmap.svg` 的 `node-*` 组数 = `mindmap.json.nodes` 数 + 1（root）；改字生效。
8. 预览文件是 PNG（首 8 字节 `\x89PNG\r\n\x1a\n`）且非 0 字节；`preview_mode` 与实际一致。
9. `result.json` 覆盖 `output_contract` 全部键，键名未改，缺值 `[]`。
10. 空输入、坏 JSON、极小材料三种输入各跑一次，退出码为 0 且 `result.json` 合法。

## 6. 复用与扩展

- 换材料类型只需在 `scripts/mmio.py` 的 `extract()` 增加分支，返回 `[{"locator": ..., "text": ...}]` 即接入全部下游能力（核验、CSV、覆盖说明）。
- 换布局只需替换 `mmcore.compose()`，保证返回 `boxes`/`curves`/`w`/`h` 四个键，渲染层无需改动。
- 换判定标准改 `golden.SPECS`（期望与出处）与 `audit.inspect()`（告警阈值），不要改 `result.json` 的形状。
