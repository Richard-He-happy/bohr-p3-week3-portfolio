---
name: pathway-mechanism-drawer
description: 把一份生物机制/通路材料变成可逐条回查的分层矢量机制图。Agent 先读原文、写出实体—关系—区室工单（plan.json），脚本负责逐字引文校验、上下游泳道布局、语义箭头、图例自洽断言，并导出分层 SVG + 单页矢量 PDF + 真实 PNG 三件套与 result.json。适用于机制图、通路图、信号示意图、graphical abstract 的绘制，以及"在既有机制描述上改一个标签再重导"的保源编辑；不适用于统计推断、实验设计与版式美化。
version: 1.0.0
---

# 通路机制图绘制台（Agent 判断机制，脚本只当尺子和笔）

机制图不是插画，是一份能被逐条质疑的陈述。所以产物不是"一张好看的图"，而是**图 + 每个元素的
可回查证据 + 一串能重算的自检**。

## 0 一页速览

```
python3 -B <SKILL>/scripts/pathway_skill.py init  --input /input --output /app/output --work /app/work
python3 -B <SKILL>/scripts/pathway_skill.py show  --doc <材料名> --input /input --work /app/work   # 读原文
#   ← 你（Agent）在这里写出 /app/work/plan.json：实体、关系、区室、每条边一句逐字引文
python3 -B <SKILL>/scripts/pathway_skill.py check --input /input --output /app/output --work /app/work
python3 -B <SKILL>/scripts/pathway_skill.py build --input /input --output /app/output --work /app/work
```

`build` 之后 `/app/output/` 有：`figure.svg`（可编辑源）、`figure.pdf`（单页矢量）、`figure.png`
（1600×1000 真实位图）、`content_map.json`、`compliance_checks.json`、`plan.normalized.json`、
`golden_standard.json`、`diff_report.md`、`self_check.json`、`version_history.md`、`run.log`，以及把
`output_contract` 全部字段填满的 `result.json`。

## 1 什么时候用、什么时候不要用

用：材料里已写明"谁作用于谁"（机制段、通路描述、figure legend、工单 JSON），需要出图并保留可编辑
源；或给既有图改一处标签、改一条箭头的语义再重导。不用：做统计结论、设计实验、翻译图注——那不属于
本 Skill。它只保证图上每个实体、每条边、每处定位可回溯，不保证生物学结论成立。

## 2 安装、目录结构与依赖

- `SKILL.md`：本说明（契约、规范、失败处理）。
- `scripts/pathway_skill.py`：CLI 入口（init/show/check/build/selftest）。
- `scripts/material_audit.py`：切材料、比引文、验工单、读回图面、拼 content_map。
- `scripts/figure_engine.py`：布局内核（分带、层内择优、正交布线）。
- `scripts/figure_paint.py`：显示列表 → 分层 SVG / 单页 PDF。
- `scripts/png_canvas.py`：显示列表 → PNG（zlib 手写 + 5×7 点阵）。
- `scripts/figure_audit.py`：期望清单、逐项对照、自检探针、版本记录。
- `references/mechanism-grammar.md`：关系词表、区室归位、命名与图例规范。

依赖：Python ≥ 3.8，**只用标准库**，不联网、不读环境变量、不依赖 CWD（脚本用 `__file__` 定位）。
无字体文件：SVG 用字体族回退列表，PDF 用 base-14 Helvetica 正/粗/斜三款。

## 3 输入侧：/input 里可能出现什么

`/input/case.json` 是唯一必需文件，键名可能变体，脚本按语义识别（`case_id`、`task_instruction`、
`output_contract`、`organizer_workorder`/`workorder`/`figure_workorder` 都认）：

- `output_contract`：可能是数组也可能是对象；**列出的字段一个都不能改名、不能漏**，原样回填。
- `organizer_workorder`：`required_entities[]`、`required_relations[]`、`compartments[]`；缺哪个
  就不做哪项覆盖统计，并在 `pending_human` 说明。
- 材料：`/input/**` 下的 md/txt/csv/json/pdf/docx/xlsx/pptx 都会被索引。文本按空行切
  `文件#paraN`，PDF 按文本流切 `文件#streamN`；扫描件/位图只记缺口，**绝不猜内容**。

## 4 五条命令与各自职责

| 命令 | 会写什么 | 什么时候跑 |
|---|---|---|
| `init` | `work/materials.json`、`plan.skeleton.json`、partial `result.json` | 每次运行第一步 |
| `show` | 只打印原文（带 locator） | 写 plan 之前，真的要读 |
| `check` | `work/check_report.json` + 终端 `CLEAN`/`NOT CLEAN` | 写完 plan，先看引文过不过 |
| `build` | 全部产物与资产，最后覆盖成正式 `result.json` | 收尾；可重跑，覆盖上一次 |
| `selftest` | `work/cli_probes.json`（三个探针的真实退出码） | 想自证健壮性时 |

任何命令**退出码恒为 0**：`build` 第一步就写一版合法 partial `result.json`，之后无论出什么事，
你都能拿到可解析的结果文件，并在 `errors`/`degradations` 里看到发生了什么。

## 5 工单文件 plan.json 怎么写

顶层键：`title`（写清机制，不写 "Figure 1"）、`subtitle`、`compartments`（按**上游→下游**排序，
每项 `{id,label,order}`）、`entities`、`relations`、`data_encoding`（有出处才写）、`gaps`、`edits`（改图时）。

```json
{"title": "EGF 诱导的 STAT3 激活与 SOCS3 负反馈",
 "compartments": [{"id": "extracellular", "label": "Extracellular", "order": 0},
                  {"id": "cytoplasm", "label": "Cytoplasm", "order": 2},
                  {"id": "nucleus", "label": "Nucleus", "order": 3}],
 "entities": [
   {"id": "EGF", "label": "EGF", "kind": "ligand", "compartment": "extracellular",
    "evidence": {"quote": "<材料原文连续一段，≥6 字符>", "locator": "note.md#para1"}},
   {"id": "SOCS3", "label": "SOCS3", "kind": "gene", "compartment": "nucleus",
    "sublabel": "transcript", "evidence": {"quote": "<原文>", "locator": "note.md#para3"}}],
 "relations": [{"id": "r1", "source": "EGF", "target": "EGFR", "type": "binding",
                "evidence": {"quote": "<原文>", "locator": "note.md#para1"}}],
 "gaps": ["SOCS3 蛋白是否入胞质，材料未写，未画。"]}
```

`kind` 取 `protein/gene/complex/ligand/cell/metabolite/phenotype/mirna/unspecified`，决定填充色与
是否斜体；`source`/`target` 必须是实体 `id`；关系可加 `badge`（`P`/`Ub`）与 `label`（画在线上）。

## 6 动词到线型：关系语义词表

完整中英动词表见 `references/mechanism-grammar.md`，脚本内是同一份词（`figure_engine.VERBS`）。
一句话里有多个动词时按 `modification > transport > inhibition > activation > binding` 取更具体的那层语义。

七种画法是硬要求：实心箭头=激活，T 形端=抑制，空心箭头=结合，实心箭头+`P`/`Ub` 角标=修饰，
双头箭头=转运，虚线=间接，点划线=未说明。方向取原文语序（"A 被 B 激活"写 `B -> A`）。
**激活与抑制画反等于给出错误论断**，拿不准就落到 `unspecified` 并在 `gaps` 写清楚，不要猜。

## 7 区室、跨膜与上下游位置规则

区室按 胞外→胞膜→胞质→核内 自上而下分层（`oth` 未注明区室排最后），层高与实体数成比例，每层
76px 下限。三条不能破的规则：

1. 跨膜受体必须压在磷脂双分子层的中心线上（自检断言 `box.y < membrane_y < box.y+box.h`）。
2. 跨区室的边必须真的穿过层界，路径上有越过边界的点；悬在层内就是布线错了（自检断言）。
3. 材料只说两层就只画两层；不要为了"看起来完整"凭空补一层。

## 8 画面规范：画布、分层与命名

- 画布固定 1600×1000 px（PDF 侧 1200×750 pt，1px = 0.75pt）；留白 56px；最小字号 14px。
- 七层顺序固定：`layer-background / title / zones / entities / relations / legend / notes`。
  文字全部是 `<text>`，不转曲——评审改一个标签就能重导。
- 元素 id 可寻址：`zone-<区室>`、`ent-<实体>`、`rel-<关系>`、`lg-<种类|类型>`。每个实体/关系
  分组都带 `data-quote` 与 `data-locator`（外加 kind/type/direction/from/to/italic），这就是
  "改标签 + 查来源"的最小接口。
- 基因名用斜体，蛋白正体；复合物画双层圆角框。
- 布线正交：同侧多条线沿端口均分，层内走行间通道，相邻层走层间走廊，跨多层走右侧轨道；每条竖线
  都做自由通道检查，**穿框数必须为 0**（交叉数只计数，不判失败）。

## 9 图例与数据编码的一致性

图例由画面实际出现的种类与关系类型自动生成，条目数必然等于「种类数 + 类型数」，自检断言这一点
（`legend_consistency`）。颜色只编码实体种类，线色+端点+虚线编码关系类型，同一通道不表达两件事。
任何数值（表达量、显著性、置信度、时间点）只有在 `plan.data_encoding` 给出 `column` 或 `quote`
时才允许画；没有来源就不画，也不用"看起来合理"的数字凑。

## 10 证据链：locator、逐字引文与可核验字段

每条实体、每条关系的 `evidence.quote` 必须是材料的**逐字切片**（≥6 字符，允许换行/多空格差异），
`evidence.locator` 写材料名 + `#paraN`/`#streamN`。状态有四种，写进 `content_map` 与 SVG 属性：

| 状态 | 含义 | 是否进图 |
|---|---|---|
| `verbatim` | 原文里能逐字找到 | 是 |
| `verbatim_loose` | 去掉标点/空格后能找到（吸收 PDF 抽字噪声） | 是 |
| `declared` | 引自工单条目（`case.json#workorder...`），不是材料正文 | 是，单独计数 |
| `unverified` | 找不到 | **否**，进 `content_map.pending` 与 `pending_human` |

改写、拼接、翻译都不算命中。宁可少画一条边，也不要画一条查不到出处的边。

## 11 产物清单与 result.json 结构

| 文件 | 内容 |
|---|---|
| `figure.svg` | 可编辑源：七层、文字为 `<text>`、逐元素 `data-*` |
| `figure.pdf` | 单页矢量，base-14 Helvetica，xref 可用，`%%EOF` 收尾 |
| `figure.png` | 1600×1000 RGB，IHDR 可解析，非纯色 |
| `content_map.json` | 实体/关系/区室/图例编码/覆盖率，每项含 `quote`+`locator`+`svg_id` |
| `compliance_checks.json` | 画布/字体/端点/区室/图例/溢出/像素/PDF 与 `pass`、`failures` |
| `golden_standard.json` + `diff_report.md` | 期望清单与图面逐项对照（含人工动作） |
| `self_check.json`、`version_history.md`、`run.log` | 探针数字、版本记录、运行日志 |

`result.json` 会把 `output_contract` 声明的字段**原样回填**（不改名、不漏键，缺值 `null`/`[]`），
再补 `case_id`、`status`（`ok`/`partial`/`input_error`）、`sources`、`uncertainty`、`pending_human`、
`errors`、`degradations`、`changes`、`runtime`、`skill`、`contract_fields`（含 `null_fields` 自查）。

## 12 失败与降级矩阵

| 情况 | 行为 | 落点 |
|---|---|---|
| `case.json` 缺失/坏 JSON | 继续跑兜底图，状态 `input_error` | `errors`、`contract_fields` |
| 没有 plan.json | 只用工单条目与"A 动词 B"明写句出兜底图 | `degradations`、`subtitle` |
| 引文找不到 | 该关系**不画**，整体转 `partial` | `content_map.pending`、`pending_human` |
| 同名异义（胞质/核内 STAT3） | 两实体 + `sublabel` 区分，工单按候选集合算覆盖 | `content_map.entities` |
| 关系缺方向 | 画无向连接（无箭头），标注待确认 | `gaps`、`pending_human` |
| 扫描件/位图材料 | 不进正文，只记缺口 | 材料 `note`、`gaps` |
| PNG 光栅器异常 | 不出 PNG，PDF 作检视件 | `degradations`、`exceptions` |
| PDF 非拉丁字符 | SVG 保留原文；PDF 丢弃并计数 | `compliance_checks.pdf` |
| 图面元素过多 | 网格降级（3 行）+ 14px 下限，溢出进 `overflow` | `compliance_checks.overflow` |

无法判断的一律写进 `pending_human` 并说明要人确认什么，不要写成事实。

## 13 自检判据

`self_check.json` 的十四个探针，每个 `pass` 都是从盘上的文件重算出来的：

| 探针 | 判据 |
|---|---|
| `svg_xml` | 能解析；1600×1000；≥4 个 `layer-*`；最小字号 ≥14px |
| `geometry` | 无越界/无文本框重叠/无节点框重叠/穿框数 = 0 |
| `pdf` | `%PDF-1.4` 开头、单页、`%%EOF` 结尾、xref 偏移可解析 |
| `png` | PNG 魔数、≥800px 宽、颜色数 ≥3（不是空白图） |
| `pdf_svg_consistency` | WinAnsi 可编码的文字节点数 == PDF 的 `Tj` 数（同一份图元） |
| `content_map_1to1` | 图面 `ent-*`/`rel-*` 数量 == content_map 条目数 |
| `evidence` | 被拒引文数 = 0 |
| `compartment_containment` | 每个框在所属泳道内；膜蛋白压线 |
| `cross_lane_edges` | 每条跨区室边都越过层界 |
| `legend_consistency` | 图例项数 == 种类数 + 类型数，且每项都在画面出现 |
| `type_encoding` | 激活/抑制/结合/转运端点形状互不相同，且无（色, 虚线, 端点）撞车 |
| `gene_italics` | 每个 `gene` 实体在 SVG 上都是斜体分组 |
| `contract` | `output_contract` 声明的字段没有缺 |
| `probes_cli` | 有 `selftest` 记录时，三个探针退出码为 0 |

## 14 走查示例（**示例，非正式案例结果**）

最小输入：`case.json`（7 项契约 + workorder）+ `task.md` + 一段 4 句的机制笔记。

```
init  → materials 3 | contract: case_id, status, editable_source, export_artifact, content_map,
        compliance_checks, exceptions
check → entities 6 (verified 6) | relations 6 (verified 6, drawn 6) | rejected 0 | pending 0
        CLEAN
build → status=ok entities=6 relations=6 zones=ext,mem,cyt,nuc
        types=binding,modification,transport,activation,inhibition
        figure.svg 22.8KB | figure.pdf 7.2KB | figure.png 18.7KB | checks pass=True
```

六实体：EGF / EGFR（膜）/ STAT3（胞质）/ p-STAT3 / STAT3（核）/ SOCS3（基因，斜体）；六条边：
结合 → 磷酸化 → 磷酸化 → 转位 → 激活 → 抑制（负反馈）。图上无穿框、无交叉、膜蛋白压线、
图例 8 项（3 种类 + 5 类型）。这一段的真实命令与输出见随包 `SMOKE.md`，该文件在打包时删除。

## 15 已知限制、适用边界与维护

- **PNG 文字是点阵**：内置 5×7 拉丁字模，汉字画占位框表示字符宽度；正字以 SVG/PDF 为准。
- **PDF 只吃 WinAnsi**：中文留在 SVG（改字用 SVG），PDF 侧丢弃并计数
  （`chars_dropped_for_winansi`），是有意取舍，不是静默失败。
- **布局是启发式**：层内顺序用相邻交换爬山、3 轮内择优；元素极多时退到 3 行网格，用美观换
  "不穿框"。交叉数只报告不判失败。
- **科学判断不在脚本里**：脚本只断言"是否自洽、是否有出处"，不判断机制是否成立；`diff_report.md`
  的"达标"只表示与可回查原文一致。
- 扩展：改词表 → `figure_engine.VERBS` 与 `references/mechanism-grammar.md` 同步；改画法 → `EDGE`；
  改布局 → `fit_grid`/`share_heights`/`route`；新题型只在 `plan.json` 层扩展。
