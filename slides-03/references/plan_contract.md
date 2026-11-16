# slide_plan.json 字段契约与校验语义

工作稿默认位于 `work/slide_plan.json`；`check` / `build` 都支持 `--plan <path>` 指向别处。这份 JSON 是 Agent 的判断载体，脚本只校验、不代写。

## 1. 顶层键

| 键 | 必填 | 类型 | 含义 |
|-|-|-|-|
| `deck_title` | 是 | str | 封面主标题；可含方法名或结论方向 |
| `subtitle` | 否 | str | 会议、场合、日期 |
| `audience` | 是 | str | 听众类型；决定背景比例与术语解释范围 |
| `duration_min` | 是 | number | 汇报分钟数，与页数一起被 `1 页≈1.2–1.5 分钟` 校验 |
| `target_slides` | 是 | int | 目标页数；与任务给定页数不一致时 `page_match=false` |
| `goal` | 否 | str | 本次汇报要达成的可检查目标 |
| `narrative` | 否 | list | `{act, slides, purpose}` 组成的幕结构，写清取舍顺序 |
| `slides` | 是 | list | 页对象列表，页码从 1 连续 |
| `qa` | 否 | list | `{q, a, backup}`，问答预案 |

## 2. 页对象键

| 键 | 必填 | 说明 |
|-|-|-|
| `n` | 是 | 页码，从 1 开始连续 |
| `title` | 是 | 写结论（现象/数字 + 判断），不写"结果""方法"这类章名 |
| `layout` | 否 | 仅首页用 `"title"`；其余省略或写 `"content"` |
| `claim` | 内容页必填 | 本页唯一主张，一句话可复述 |
| `bullets` | 内容页必填 | 3–5 条，每条 `{text, locator, quote}` |
| `visual` | 否 | 引用的图号/表号；材料无图写 `"无（材料未提供）"` |
| `evidence_strength` | 否 | `strong` / `moderate` / `weak` / `unrated` / `none` |
| `notes` | 内容页必填 | 讲稿：讲法、适用条件、被追问先答什么；**不得复述页面文字** |

## 3. 证据两件套

- `locator`：`M<材料号>#p<段号>`，由 `deckctl.py show` 打印（如 `M1#p12`），不要手写猜测。
- `quote`：源材料中的**逐字**片段，长度不限，可跨行；脚本去掉空白后做包含匹配。改写、翻译、拼接都不通过。
- 校验失败的 `quote` 会让 `check` FAIL；`build` 时若计划整体不可用，会改用确定性兜底计划并相应降低 `status`。

## 4. 校验报告 `work/check_report.json`

```json
{"slides": 6, "bullets": 18, "quotes_checked": 18, "quotes_verified": 18,
 "slides_with_evidence": 6, "target_slides": 8, "page_match": false,
 "usable": true, "passed": false,
 "errors": [], "warnings": [{"slide": 4, "msg": "speaker notes missing"}]}
```

- `usable`：没有硬错误且带证据页占比 ≥80% → `build` 采用你写的计划。
- `passed`：`usable` 且页数等于 `target_slides`。
- 硬错误（任一出现即 unusable）：标题为空、内容页要点数不在 3–5、要点文本为空、`quote` 在材料里找不到。
- 软警告：缺 `notes`、要点缺 `quote`/`locator`、`locator` 与脚本解析出的位置不一致。

## 5. 一份完整的示意计划（示例，非正式案例结果）

```json
{"deck_title": "钙钛矿组件界面钝化的热稳定性收益", "audience": "课题组组会 + 合作企业工程师",
 "duration_min": 15, "target_slides": 6, "goal": "让听众认可钝化带来的效率与热稳定收益，并接受其成分边界",
 "narrative": [{"act": "背景与问题", "slides": "2", "purpose": "说明裸界面器件的降解瓶颈"},
               {"act": "方法与证据", "slides": "3", "purpose": "讲清钝化层的做法与对照设计"},
               {"act": "关键结果", "slides": "4-5", "purpose": "给效率与 1000 小时数据并标条件"},
               {"act": "边界与风险", "slides": "6", "purpose": "交代未测的组分与放大风险"}],
 "slides": [
  {"n": 1, "title": "钙钛矿组件界面钝化：效率与热稳定能否同时拿到", "layout": "title",
   "subtitle": "组会 + 企业合作方联合汇报", "bullets": [],
   "notes": "开场 40 秒：先声明结论是'效率略升、稳定性明显升'，再说明本次只讲 MAPbI3 体系。"},
  {"n": 2, "title": "裸界面在 85 °C 下先掉效率再掉填充因子", "claim": "未钝化器件的瓶颈是界面降解而非吸收层本身",
   "bullets": [
     {"text": "退火后裸界面器件 500 小时已掉 30% 效率", "locator": "M1#p4",
      "quote": "Unpassivated devices lose 30% of their initial efficiency after 500 hours at 85 °C."},
     {"text": "降解从界面开始，吸收层体相未见明显变化", "locator": "M1#p6",
      "quote": "Cross-sectional imaging shows degradation starting at the interface while the bulk absorber stays unchanged."},
     {"text": "因此本工作只处理界面，不改吸收层配方", "locator": "M1#p8",
      "quote": "We therefore restrict this study to interface passivation and keep the absorber composition fixed."}],
   "visual": "图 1（截面形貌对比）", "evidence_strength": "moderate",
   "notes": "听众里有人做组件封装，先说明'85 °C 干热'不等于'85/85 湿热'，两组数据不可直接比。"},
  {"n": 3, "title": "钝化层用旋涂 + 低温退火，工艺窗口宽", "claim": "钝化步骤能在现有产线上以 120 °C 以下完成",
   "bullets": [
     {"text": "钝化剂浓度 2–8 mM 均可成膜", "locator": "M1#p11",
      "quote": "Films stay uniform for precursor concentrations between 2 and 8 mM."},
     {"text": "退火 100–120 °C，不改变既有产线节拍", "locator": "M1#p13",
      "quote": "Annealing between 100 and 120 °C leaves the existing line takt time unchanged."},
     {"text": "对照组只做同温退火、不加钝化剂", "locator": "M1#p15",
      "quote": "Control devices received the same anneal without the passivating precursor."}],
   "visual": "表 1（工艺窗口）", "evidence_strength": "strong",
   "notes": "被问'为什么不做喷涂'时回答：本批次只验证旋涂，喷涂属于放大阶段的下一步。"}],
 "qa": [{"q": "1000 小时之后会怎样？", "a": "只测到 1000 小时，尚未出现二次拐点；按现有斜率预计 1500 小时仍高于 80%。",
         "backup": "第 5 页"},
        {"q": "无铅组分能用吗？", "a": "未测试；本批器件全部为 MAPbI3 吸收层，无铅体系属下一步。",
         "backup": "第 6 页"}]}
```

上例只展开到第 3 页示意字段用法，其余页按同一结构补完即可。示例中的数值、图号与结论全部取自示例材料，仅用于说明字段用法，不代表任何正式案例。
