# 规格项手册（spec-rubric）

排版规格的"合同"：有哪些项、取值长什么样、出处怎么记、单位怎么换、抽取会漏在哪里。
与 `scripts/extract.py` 的 `DEF` / `PROSE` / `RANK` / `units()` 一一对应，改代码请同步本文。

## 1. 规格项与兜底值

每项都有一条兜底值。兜底值只在模板与格式要求都没写时出现，出现时必定 `inferred: true`。

| 规格项 | 含义 | 取值形态 | 兜底 |
|-|-|-|-|
| `page.size` | 纸张尺寸 | `A4` / `A3` / `A5`；非标准纸写毫米，如 `210x297mm` | A4 |
| `page.margin.top` `bottom` `left` `right` | 四边页边距 | `2.54cm`、`25.4mm`、`1in` | 2.54cm |
| `page.columns` | 分几栏 | `1` 或 `2` | 1 |
| `body.font` | 西文字体族 | 字体名 | Liberation Serif |
| `body.font.eastasia` | 中文字体 | 字体名 | SimSun |
| `body.size` | 正文字号 | `12pt`；中文字号已折算成 pt | 12pt |
| `body.line_spacing` | 行距 | 倍数 `1.5`，或绝对 `18pt` | 1.5 |
| `body.align` | 对齐 | `both`/`left`/`center`/`right` | both |
| `heading.1.size` `heading.2.size` `heading.3.size` | 各级标题字号 | `16pt` | 16/14/12pt |
| `title.size` | 篇名 | `18pt` | 18pt |
| `caption.size` | 图表题注 | `10.5pt` | 10.5pt |
| `caption.table.position` | 表注位置 | `above`/`below` | above |
| `reference.style` | 文献条目体例 | `numeric` 或 `author-year` | numeric |
| `reference.size` | 文献条目字号 | `10.5pt` | 10.5pt |
| `toc.levels` | 目录收到第几级标题 | `1`–`4` | 3 |

另有 `reference.hanging`（悬挂缩进，twip）只在 docx 模板里出现时登记，不进兜底表。

中文字号换算表：初号 42 / 一号 26 / 小一 24 / 二号 22 / 小二 18 / 三号 16 / 小三 15 / 四号 14 / 小四 12 / 五号 10.5（pt）。

## 2. 出处与强度

`source` 取四值之一，强度顺序写死在 `RANK` 里：

| source | 来自 | 强度 |
|-|-|-|
| `template_docx` | docx/dotx 的 sectPr 与 styles.xml | 0（最强） |
| `template_tex` | tex/cls/sty 的版面命令 | 1 |
| `requirements` | 文字规定、case 里的 instruction 字段 | 2 |
| `default` | 兜底表 | 8（最弱） |

合并规则：同项按强度排序取第一条；出现两个以上不同取值即算冲突，`chosen` 记胜出值，`rule` 记 `docx>tex>prose>default`，`values[]` 保留每个候选的值、来源与定位。冲突项一律同时进 `pending_human`，措辞是"已取 X，请确认取舍"。

## 3. 定位符写法

| 来源 | `locator` 形态 | `quote` 取什么 |
|-|-|-|
| 文字规定 | `format_requirements.md#L7` | 该行原文，截到 120 字符 |
| docx 模板 | `template.docx#sectPr/pgMar@top`、`#sectPr/pgSz`、`#sectPr/cols`、`#styles.xml[Normal]/sz`、`#styles.xml[heading 1]/sz`、`#styles.xml[caption]/sz`、`#styles.xml[Bibliography]/ind`、`#document.xml[TOC]` | 命中的原始 XML 片段（`<w:spacing .../>` 整段、`<w:sz w:val="21"/>` 整段），不要手工拼 |
| LaTeX 类文件 | `journal-template.cls#\documentclass[10pt,twocolumn]` | 命中的命令行，空白折叠后截到 100 字符 |

`traceable` 的判定很硬：`quote` 必须在来源文件的文本里**原样**出现（docx 来源比对的是该包里所有 XML 拼成的文本）。没命中就记 `false` 并进待确认，**不修原文去凑命中**。没有 quote 的兜底项 `traceable: null`。

这条规则的实际价值：手工拼出的 quote（例如把 `<w:spacing w:line="300"/>` 拼出来，而原文是 `<w:spacing w:before="0" w:after="120" w:line="300" w:lineRule="auto"/>`）会立刻被判 `false`，逼迫抽取器交出真实片段。

## 4. 单位换算

| 规格 | 换算 | 落到哪 |
|-|-|-|
| 字号 pt | ×2 → half-point | `w:sz w:val` |
| 行距倍数 | ×240，`lineRule="auto"` | `w:line` |
| 行距 `NNpt` | ×20，`lineRule="exact"` | `w:line` |
| 边距 cm | ÷2.54×1440 → twip | `w:pgMar` |
| 边距 mm | ÷25.4×1440 → twip | `w:pgMar` |
| 纸张 | A4 11906×16838、A3 16838×23811、A5 8391×11906（twip） | `w:pgSz` |
| 自定义纸张 | 毫米 ÷25.4×1440 | `w:pgSz` |

换算因子改动后必须重跑 `--self-check`（SC1–SC9 覆盖了上表主要分支）。

## 5. 抽取盲区（知道会漏，别当成已覆盖）

- **语序**：`字体 Times New Roman` 与 `Times New Roman 字体` 都要认。只写"正文用 12 号字"这类没有"字号"字样的表述，规则抓不到，结果表现为该项 `inferred: true`。
- **一行多个值**：边距规则对整行全量扫描，四个方向都能拿到；其余规则每行只取首个命中，同一句里若写了两次同类值，第二次会被忽略。
- **参考文献体例**只分 `numeric`（GB/T 7714、IEEE、Vancouver、顺序编码）与 `author-year`（APA、Harvard、著者-出版年）两大类；字段顺序、作者截断、中英标点混排不解析。
- **docx 模板**只读 `word/styles.xml` 与 `word/document.xml`；`w:theme` 主题字体与样式继承链看不穿，可能把继承自主题的字体报成缺失。
- **表注位置**没有规范写法可依时（docx 模板通常不带这个信息），只能取兜底 `above` 并标推断。
- **页眉页脚距离**写死默认值（header 851、footer 992 twip），模板里若有特殊要求目前不抽取；需要时在 `units()` 增补规格项。

## 6. 与成品的对应关系

每条规格都能在成品里找到落点，这是"正确性可核"的前提：

| 规格项 | 成品落点 | 检查项 |
|-|-|-|
| `body.size` | `word/styles.xml` 的 `w:sz`（Normal） | C1 |
| `body.line_spacing` | `w:spacing/@w:line` | C3 |
| `body.font` | `w:rFonts/@w:ascii` | C4、I5 |
| `page.margin.*` | `word/document.xml` 的 `w:pgMar` | C2 |
| `page.columns` | `w:cols/@w:num` | C5 |
| `heading.n.size` | `Heading1-3` 样式的 `w:sz` | I7（计数同源） |
| `caption.size` | `Caption` 样式 | — |
| `reference.size` | `Bibliography` 样式 | — |
| `toc.levels` | `TOC \o "1-N"` 域 | — |
| 页码 | `word/footer1.xml` 的 `PAGE` 域 | C6 |
