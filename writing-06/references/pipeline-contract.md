# 输入到产物的对账手册

这份文件只回答一件事：素材里的一个值，最后落在哪个文件的哪一处，中间经过哪几次登记。字段与文件名是固定约定，写代码、写稿、复核都以本文为准。

## 1 素材怎样被切开

按扩展名分派，切成带锚的块：

- `.md`、`.txt` —— 以空行分段，锚前缀 `p`，一块是一个自然段。
- `.json` —— 先格式化再逐行，锚前缀同样为 `p`，一行一块，便于逐字比对。
- `.csv`、`.tsv` —— 一行一块，表头单独占一号；块文本形如 `row 7: gauge_mm=2 | strength_MPa=41.6`。
- `.pdf` —— 文本层能取就按页编号，取不到时只留一条提示。
- 位图 —— 不做 OCR，只留一个视觉占位。

每个块在索引里带一个 `loc`，写法是「相对路径 + `#` + 锚前缀 + 序号」。序号取决于扫描顺序，引用时照抄打印结果，不要凭记忆补。

## 2 指向写法

四种锚各举一例：

- 段落 —— `notes/protocol.md#p4`
- 表格行 —— `data/tensile.csv#r3`
- 论文页 —— `refs/source.pdf#pg9`
- 图片 —— `figures/stress_strain.png#fig`

解析时只比对锚序号的数字与文件基名，所以 `tensile.csv#r3` 也能落到 `data/tensile.csv#r3`；输出里则一律写完整路径，免得不同目录的同名文件互相串味。

## 3 草稿里有哪些键

必填四项：`results`、`discussion`、`limitations`、`evidence`。其余可缺，缺了按下面的默认处理。

- `title` —— 一级标题；不填就用语言对应的默认标题。
- `language` —— `zh` 或 `en`；不填时按汉字占比自动判。
- `results`、`discussion` —— 数组，元素由小标题、图表编号列表、段落数组三部分组成。段落数组里一个元素就是一段，段内不要再换行。
- `limitations` —— 字符串数组；不填时由缺口扫描代填，至少要两条且四层齐。
- `evidence` —— 数组，元素是编号、摘录、指向三件套，可另加目视标记。
- `derived` —— 数组，元素是自算值、公式、备注；自算值必须与公式成对出现。
- `preserved_facts` —— 数组，元素是事实陈述、摘录、指向；用于逐条回溯。
- `changes` —— 数组，每条记动作、原句、改句、理由。
- `pending_human` —— 字符串数组，放需要作者拍板的事项。
- `uncertainty` —— 字符串数组，放"做了但心里没底"的判断。

`xref` 只放图号与表号，不放页码或段落号。

## 4 一份能跑通的最小草稿

```json
{"title": "Gauge length and tensile strength of the drawn filament",
 "language": "en",
 "results": [{"heading": "Strength falls as gauge length grows", "xref": ["Fig. 3B"],
   "paragraphs": ["Mean strength was 41.6 MPa at 2 mm (SD 1.9, n = 5) and 27.3 MPa at 12 mm (SD 2.6, n = 5)."]}],
 "discussion": [{"heading": "Reading the decline", "xref": [],
   "paragraphs": ["The drop is monotonic, consistent with a defect-limited failure mode; the design does not separate that from a handling artefact."]}],
 "limitations": ["方法层：只测准静态加载，所以高速行为得不出。", "样本层：同批 5 根丝，所以批间离散未评估。",
                 "测量层：夹具滑移未标定，所以绝对值只可相对比较。", "统计层：未校正多重比较，所以不报显著性强度。"],
 "evidence": [{"id": "e1", "quote": "row 2: gauge_mm=2 | strength_MPa=41.6 | sd=1.9 | n=5", "locator": "data/tensile.csv#r2"},
              {"id": "e2", "quote": "row 6: gauge_mm=12 | strength_MPa=27.3 | sd=2.6 | n=5", "locator": "data/tensile.csv#r6"}],
 "derived": [{"value": "14.3", "formula": "41.6-27.3", "note": "端点落差"}],
 "changes": [{"action": "收敛语气", "original_quote": "gauge length governs strength",
              "revised_quote": "strength declines with gauge length", "reason": "无机制证据"}],
 "pending_human": ["请作者确认 Fig. 3B 是否对应本表"],
 "uncertainty": ["夹具滑移量按图注估计"]}
```

## 5 摘录核验会给出五种结论

- `exact` —— 就在申报的那一块里，直接可用。
- `misplaced` —— 命中别的块；记下真实位置，仍算可核。
- `span` —— 只在该文件拼接后的文本里命中；可核，但建议改成单块摘录。
- `notfound` —— 整份素材都没有；判为不可核。
- `empty` —— 摘录是空串；同样判为不可核。

判定之前只做三步归一：字符转半角（NFKC）、连续空白压成一个、大小写不敏感。数值与量纲要求严格一致，不做近似。

## 6 数字进正文的三条通道

1. **逐字摘录** —— 编号、摘录、指向三件套齐备，摘录里出现过这个值。
2. **目视读数** —— 同一条摘录加目视标记，正文写"约 / approx."，小数位不超过刻度分辨率。
3. **公式自算** —— 自算值与公式成对，四舍五入位数与正文一致。

三条之外的值，`check` 会逐条点名，并附上含该值的候选块；改法只有换值、补公式、删句三种。

## 7 七个交付件各自给谁看

- `manuscript.md` —— 给人直接投稿或贴进 Word 用，带编号小节与限制小节。
- `results_discussion.md` —— 给按文件名取件的评估脚本用，标题是不带编号的裸标题。
- `results_map.json` —— 给想从正文点回原图的人用，逐段列出数值、量纲与来源块，另有覆盖统计与未核清单。
- `evidence_map.json` —— 给想确认摘录真伪的人用，逐条给核验结论。
- `preserved_facts.json` —— 给想核对事实清单的人用。
- `change_log.json` —— 给想复盘措辞收敛的人用，含改写留痕、待确认项、兜底动作。
- `result.json` —— 给平台与评审用，结构见下一节。

## 8 result.json 的顶层键

- `case_id` —— 与输入逐字一致；输入没有 case 文件时为 `null`。
- `status` —— 四种取值：`ok`、`partial`、`insufficient_evidence`、`input_error`，永不为空。
- `sources` —— 素材清单，每项含路径、类型、字节数、块数、可读性；空目录时为 `[]`。
- `uncertainty`、`pending_human` —— 字符串数组，无内容时为 `[]`。
- `errors` —— 素材级异常与 case 解析错误；顺利时为 `[]`。
- `degradations` —— 兜底动作与自检失败项；顺利时为 `[]`。
- `changes` —— 改写留痕，至少含一条装配记录。
- `metrics` —— 计数与比率，口径见下一节。
- `runtime` —— 版本、阶段、写入时刻。
- `output_contract`、`contract_fields` —— 前者原样透传，后者给出总数、已填数与键名清单；输入无契约时按默认四键。

契约里的每个键还会在顶层各放一份值。认不出用途的键，返回一个"未单独产出"的说明加一个 `see` 列表，指向最接近的两件交付件。

## 9 计数口径

- `numbers_total` —— 结果段段落里扫到的数值记号；图号、表号、年份不计。
- `numbers_verified` —— 其中命中前述三条通道的。
- `traceability_rate` —— 上两者相除，保留三位小数；分母为零记 0.0。
- `evidence_ok`、`evidence_failed` —— 可核与不可核的摘录条数。
- `results_words`、`discussion_words` —— 汉字按字计，西文按空格切。
- `self_audit` —— 断言通过数、失败数与失败项名字。

## 10 三种常见对账失败

- **位置对了、条件错了** —— 只要素材里存在这个数值就放行，但剂量、长度、批次仍需人工再看一眼。
- **量纲被悄悄换掉** —— 数值相同而单位不同；来源块里的量纲必须与正文一致。
- **草稿不是合法 JSON** —— 整份回落到兜底稿，兜底动作会写清解析错误；这种稿子必须人工改写后再交。
