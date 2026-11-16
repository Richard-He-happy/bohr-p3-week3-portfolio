# 规格槽位、取值来源与单位换算表

## 1. 槽位总览

规格集合固定为 20 个槽位，按七个域组织：

**页面域（6）**
`page.size` 纸张型号（默认 A4）· `page.margin.top` 上边距 · `page.margin.bottom` 下边距 · `page.margin.left` 左边距 · `page.margin.right` 右边距（四边距默认 2.54cm，可写 mm）· `page.columns` 栏数（默认 1）。

**字体域（3）**
`body.font` 西文字族（默认 Liberation Serif）· `body.font.eastasia` 中文字族（默认 SimSun）· `body.size` 正文字号（默认 12pt）。

**正文域（2）**
`body.line_spacing` 行距（倍数 1.5 或定值 18pt，默认 1.5）· `body.align` 对齐（both/left/center/right，默认 both）。

**标题域（4）**
`heading.1.size`、`heading.2.size`、`heading.3.size` 对应三级标题字号（默认 16/14/12pt）· `title.size` 篇名字号（默认 18pt）。

**题注与文献域（3）**
`caption.size` 题注字号（默认 10.5pt）· `caption.table.position` 表注位置（above/below，默认 above）· `reference.style` 文献体例（numeric 顺序编码 / author-year 著者-出版年，默认 numeric）。

**文献补充（1）**
`reference.size` 参考文献字号（默认 10.5pt）。

**目录域（1）**
`toc.levels` 目录收录层级（默认 3）。

中文数字号名换 pt：初号=42，一号=26，小一=24，二号=22，小二=18，三号=16，小三=15，四号=14，小四=12，五号=10.5，小五=9。

## 2. 取值来源的强弱

合并时按来源从强到弱覆盖：

1. `template_docx`（docx 模板，最强）
2. `template_tex`（tex 模板）
3. `requirements`（文字格式要求）
4. 内置默认值（最弱，仅当上面全都缺位时使用）

同一槽位收到两个以上不同取值：生效值取最强来源，其余候选（含来源与定位）全部留档；不同来源给出同一个值则只留一份。若某槽位完全没有来源，就填默认值并标 `inferred=true`；有来源但引文回查对不上，标 `traceable=false`。这两种情形都必须进入人工确认列表。冲突记录形如 `{item, chosen, rule, values:[{value, source, locator}]}`。

## 3. 定位与引文格式

- 文字要求：定位符 `文件名#L行号`，引文就是该行原文（最长 120 字符）。
- docx 模板：定位符 `文件名#sectPr/pgMar@top` 或 `文件名#styles.xml[Normal]/sz` 或 `文件名#document.xml[TOC]`，引文为命中的 XML 片段。
- tex 模板：定位符 `文件名#命中的命令片段`，引文同样取原始命令片段。

回查步骤：按定位符 `#` 前段找到来源文本，在其中做子串检索；逐字命中才记 `traceable=true`。

## 4. 从字符串到 OOXML 数值

| 项目 | 换算方式 |
|-|-|
| 字号 | pt 乘 2 得 half-point，写入 `w:sz` |
| 行距（倍数） | 乘 240 得 `w:line`，配 `lineRule="auto"` |
| 行距（定值） | pt 乘 20 得 `w:line`，配 `lineRule="exact"` |
| 页边距 | cm 除 2.54 乘 1440 得 twip；mm 除 25.4 乘 1440 |
| 纸张 | A4=11906×16838 twip；A3=16838×23811；A5=8391×11906；其余按毫米折算 |
| 脚注字号 | 正文 half-point 减 4，最小 14 |
| 文献悬挂 | 模板有 `w:hanging` 用模板值，否则 567 twip |

## 5. 正则能力的已知边界

- 文字要求必须带"字号/行距/边距/栏数/题注/参考文献"等关键词；"正文用 12 号"这种省略写法的会漏检。
- 文献体例仅分顺序编码与著者-出版年两大档，更细的字段顺序与标点规则不解析。
- docx 模板只读 `word/document.xml` 与 `word/styles.xml`；主题字体与继承链读取不到，可能误判字体缺失。
- PDF 模板是否有文本取决于环境里有没有 `pdftotext`；没有就跳过该来源并记降级。
- 图片/扫描型模板不推测内容，直接走默认值并列入人工确认。

## 6. 加新槽位要动的四处

默认值表、对应扫描器的正则、换算函数、本文件第 1 节。
