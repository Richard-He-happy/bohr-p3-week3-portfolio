---
name: margin-reader
description: Turn one scientific document into a traceable reading session in a single scripted run — parse the material, cut it into anchored passages, bind the requested selection to a page and character span, answer inside a selection-bounded context, persist each note immediately, and render an offline single-file client plus a Markdown record. The emitted result.json backfills every output_contract key, quotes are verbatim and locatable, and unreadable material degrades honestly.
version: 1.0.0
---

# margin-reader：把一次科研阅读做成可复核的闭环

## 0. 一句话

给一份材料和一个阅读任务，跑一次脚本，就能得到：定位好的原文选区、带逐字引文的答案、
落盘可续读的批注、以及一个断网也能打开的单文件阅读客户端。任何结论都能按页码与字符偏移
回到原文核对。

## 1. 什么时候用、什么时候不用

**用**：带文本层的 PDF、双栏 PDF、已抽好的 TXT/MD；一条或多条阅读任务（定位→提问→批注→导出）。
**不用**：纯图片或扫描件（本技能不做 OCR）、需要人手点击才能推进的流程、加密到打不开的 PDF。
遇到后两类时脚本不会编内容，而是降级成明确的「待人工」状态。

## 2. 怎么调用

```bash
# 主流程：输入 /input，产物写 /app/output
python3 -B scripts/pipeline.py --input /input --output /app/output

# 只回看：不重新解析原文，从已落盘 JSON 重建客户端与阅读记录
python3 -B scripts/viewer.py --output /app/output
```

- `--input` / `--output` 都可省略，省略时读 `$INPUT_DIR` / `$OUTPUT_DIR`，再退回 `/input`、`/app/output`。
- 进程**永远返回 0**；错误、降级、待人工分别写进结果 JSON 的 `errors` / `degradations` /
  `pending_human`，不用退出码表达业务失败。
- 依赖只有标准库；`pdftotext`、`pdfinfo` 有就用，没有就切到标准库内容流扫描，并记录降级。
- 全程离线，资源用脚本自身位置定位，不依赖启动目录。

## 3. 数据怎么流动

1. **找输入**：读 `case.json` 的任务说明与 `output_contract`；任务列表兼容多种键名，按语义取
   问题、选区文本、目标章节；再递归扫描输入目录，把 PDF 与 TXT/MD 认成材料，题面文件跳过。
2. **建坐标系**：每页文本先清洗（统一换行、去软连字符、合并跨行断词、压缩空白），随后切成
   标题块与段落块；每块登记物理页、页脚印刷页、字符起止。
3. **定位**：选区文本先找逐字命中；不行再退到段落相似、章节关键词；每档都记下精度与理由。
4. **作答**：只用「选区片段 + 所在段落 + 章节标题」作上下文，在段落内抽逐字句子当答案。
5. **落盘**：批注先写 `annotations.json`（原子替换），再渲染 HTML；重跑时读旧批注合并。
6. **收尾**：写 `result.json`（契约回填）、`reading_record.md`、五件可核验资产。

## 4. 输出长什么样

`/app/output` 下会有：

- `result.json`：主结果。`output_contract` 的键一个不少；另外固定带 `sources`、`pending_human`、
  `errors`、`degradations`、`changes`、`runtime` 信封，以及五件资产的摘要字段（各含路径、字节数、
  sha256 或判定）。
- `reader/index.html`：离线单文件客户端。段落带 `id`，选区高亮，侧栏批注可点击跳转，内嵌
  anchors/annotations/qa 的 JSON 副本。
- `reader/anchors.json`：段落清单、物理页↔印刷页映射、每条选区的字符区间与精度。
- `reader/annotations.json`：批注与问答合并记录（回看、导出的唯一数据源）。
- `reader/qa_log.json`：问答日志与上下文范围。
- `reader/reading_state.json`：会话计数与续读标记。
- `reading_record.md`：Markdown 导出件，含闭环轨迹、定位表、批注、精度统计、复核命令。

同时生成 `golden_standard.json`、`diff_report.md`、`version_history.md`、`run.log`、
`self_check.json` 五件资产。字段级定义集中在 `references/result-and-anchor-contract.md`。

### 4.1 五件可核验资产（每次运行都写到输出根目录）

| 资产 | 内容 | 怎么复核 |
|---|---|---|
| `golden_standard.json` | 按 `output_contract` 逐键登记、再按任务逐项列出期望交付：问答（答案与支撑句）、批注、锚点、选区，每项带来源 locator 与逐字 quote | 拿 `char_start`–`char_end` 到 `reader/anchors.json` 段落文本切片，应与该行 quote 逐字一致；契约项看 `json_pointer` |
| `diff_report.md` | 实际产物对本金标准的逐项对照：总览计数、每行判定与复核位置、非达标项处置 | 先看 §1 总览的 pass/missing/deviation/pending，再看 §2 表与 §3 清单 |
| `version_history.md` | 静态谱系 v0 → v1.0.0、当前包文件字节与 sha256、回退步骤；并在末尾追加「本次运行」段（run_id、命令、退出码、耗时、资产清单） | §2 可逐文件校验包体；§3 是五步回退与复核命令；§5 与本轮 `run.log` 对照 |
| `run.log` | 本次真实运行日志：步骤时间线、材料哈希、降级/异常/待人工、校验摘要 | 与 `result.json` 的 `runtime`、`closed_loop`、`errors` 对照 |
| `self_check.json` | 契约、主产物、引文、计数、兜底、退出码断言（C1–C12），附空输入/坏 JSON 子进程探针 | `overall` 非 `fail` 即通过；失败项与探针结果在 `checks[]`、`probes[]` |

五件资产在 `result.json` 顶层各有同名摘要键；每次运行覆盖写、不追加。资产由本次输入与材料机械推导，
不含预置答案；异常时由兜底路径写出最小版本并在 `self_check.json` 的 `C0` 记录原因。

## 5. 七步闭环

| 序号 | 步骤 | 脚本做的事 | 对应产物 |
|---|---|---|---|
| 1 | open | 抽文本、判文本层/加密/超限、按页切 | `document`、anchors |
| 2 | locate | 切标题段落，登记物理页与页脚印刷页 | `anchors.page_map` |
| 3 | select | 三档定位并记精度 | `anchors.selections` |
| 4 | ask | 边界上下文抽句作答 | `qa_log.json` |
| 5 | save | 逐条即时原子写批注 | `annotations.json` |
| 6 | review | 合并历史批注、记录会话 | `reading_state.json` |
| 7 | export | 渲染 HTML + 导出阅读记录 | `index.html`、`reading_record.md` |

每一步的状态写 `done` / `failed` / `skipped`（附原因）。只有七步全 `done`、所有任务都
`answered`、且没有 `unresolved` 锚点时才给成功状态（`ok`，或契约里声明的 `answered`），
其余一律 `partial`。

## 6. 证据判定要点

- 结论放在 `claims[]`，每条带 `kind`、`readability`、`condition`；证据的 `quote` 必须是原文
  逐字片段，位置写清 `pdf_page`、`printed_page`、`paragraph_id`、`section`、`char_start`、
  `char_end`。
- 引文先在 `anchors.json` 的段落文本里做子串校验；校验不过就降 `readability` 或进
  `uncertainties`，绝不改写原文。
- 精度分四档：字符级、段落级、页级、未解析。四档计数与选区条数必须相等；未解析只能出现在
  `uncertainties`，不能冒充段落级。
- 印刷页只从页首/页末的独立页码行读；读不到就是 `null`，不许拿物理页做加减推算。
- 字符偏移的坐标系、清洗规则见 `references/passage-anchoring-rules.md`。

## 7. 上下文边界与持久化（质量与体验的来源）

**上下文**：答案只能来自选区、选区所在段落、章节标题三者的并集；其他章节、摘要推断、外部知识
一律排除。答案句是段落内的抽取句，写回 `answer_quotes` 并接受「能否回贴原文」的检查。
`context_scope` 记录实际使用了什么、排除了什么、用了多少字符。

**持久化**：批注逐条 flush，先 JSON 后 HTML；重跑按「段落 + 问题」去重合并，条数只增不减；
`sessions` 自增并写 `resumed_from_previous`；只跑 `viewer.py` 也能仅凭 JSON 重建界面。
ID 不含随机数与时间戳，重复运行顺序稳定。

## 8. 出问题时怎么办

| 触发 | 行为 |
|---|---|
| 材料无文本层 / 扫描件 | `status=insufficient_evidence`，不生成正文，其余步骤 skipped，HTML 放占位说明，`pending_human` 要求 OCR 或人工录入 |
| PDF 加密 | 先尝试抽取；抽不出按无文本层处理，`pending_human.encrypted_pdf` |
| 文件超过 120MB | 只处理前 400 页，记 `degradations.oversize_pdf` |
| 没有 pdftotext | 标准库 inflate 内容流回退，分页为近似，记 `degradations.extractor_fallback` |
| 选区定位失败 | 精度 `unresolved`，给人工确认建议，不伪造锚点 |
| 段落里找不到依据 | 问答状态 `undetermined`，答案留空，进 `uncertainties` |
| 写批注/资产失败 | 记 `errors`，主 JSON 照常完整，退出码仍 0 |
| 客户端模板缺失 | 用内置极简模板渲染，并在 HTML 里注明 |
| 输入目录为空 | 闭环全 skipped，`status=input_error`，记 `missing_source` |

遇到材料自相矛盾、选区跨页跨栏、页码与正文序号对不上时，不做二选一：写进 `uncertainties`
（标种类与人工动作），同时在 `pending_human` 给出段落 id、页码或缺口说明。

## 9. 自检清单

1. 两个脚本的 `--help` 都返回 0。
2. 最小输入跑一遭：`result.json` 合法，`output_contract` 键齐全，客户端四件套 + 阅读记录齐全。
3. `claims` 里每条引文能在 anchors 段落文本中逐字找到；`answer_quotes` 与段落原文一致。
4. 四档精度计数之和等于选区条数；`unresolved` 全部进了 `uncertainties`。
5. HTML 没有外链，段落 `id` 与 anchors 一一对应。
6. 同输入连跑两次：批注不减少、`sessions` 增大、续读标记为真。
7. 空输入、坏 `case.json`、无文本层材料都返回 0 且产出合法 `result.json`。
8. `self_check.json` 的 `overall` 不是 `fail`。
9. 包根五件资产齐全非空，`result.json` 顶层有同名摘要键且 `bytes` 与磁盘文件一致。
10. 包里没有 `__pycache__`、`.pyc`、大二进制或正式案例答案。

## 10. 最小示例（合成数据，不是正式案例结果）

输入要点：`case_id` 为 `DEMO-SAMPLE`；材料 `paper.txt` 的 Results 里有一句
「Rice lines carrying qDTY12.1 showed 28% higher grain yield under drought.」；任务是选中它
并提问。`output_contract` 声明 `case_id`/`status`/`result`/`claims`/`uncertainties` 五个键。

跑完后 `result.json` 的关键片段（合成示意）：

```
status = "answered"
result.closed_loop = [open, locate, select, ask, save, review, export] 全部 done
result.selections[0] = {task_id: t1, paragraph_id: p7, pdf_page: 2,
                        char_start: 368, char_end: 451, anchor_precision: char_exact}
result.anchor_precision_counts = {char_exact: 1, 其余三档: 0}
claims[0].evidence[0].quote = 上面那句原文（逐字）
claims[0].evidence[0].location = {pdf_page: 2, paragraph_id: p7, char_start: 368, char_end: 451}
```

`reader/index.html` 里 `p7` 段落会被高亮，侧栏出现一条 `an-p7-01` 批注卡。

## 11. 包结构

| 文件 | 角色 |
|---|---|
| `SKILL.md` | 本说明：调用、契约、流程、规则、自检、五件资产 |
| `GITHUB_URL.txt` | 提交目录要求的公开仓库链接（首行） |
| `scripts/pipeline.py` | 主流程与结果组装（输入发现、解析分段、七步编排、契约回填） |
| `scripts/viewer.py` | 定位/问答/渲染/导出，以及按 JSON 回看重建 |
| `scripts/evidence.py` | 证据层：载入产物、生成逐项期望与判定 |
| `scripts/audit.py` | 审计层：差异报告、版本谱系、日志、自检与保底写出 |
| `references/result-and-anchor-contract.md` | 结果、锚点、批注、问答、状态、资产字段说明 |
| `references/passage-anchoring-rules.md` | 规范化、切段、定位优先级、上下文、降级、回归流程 |
| `references/inline_client.html` | 单文件客户端模板（内联样式脚本，占位符注入） |

版本 1.0.0，9 个文件、约 125KB；每个脚本 ≤ 25KB，运行需要 Python 3.12 及以上。

## 12. 维护提示

- 换抽取器只动 `viewer.py` 的 PDF 装载分支，保持 `pages`/`text_layer` 语义不变。
- 改定位策略要同步改 `viewer.py` 与 `references/passage-anchoring-rules.md` 的定位章节。
- 改模板只改 `references/inline_client.html` 的占位符集合，并同步渲染函数的替换表。
- 数据格式向后兼容：只增字段不改名，靠 `schema` 字符串识别版本。
- 已知限制：跨页选区不拼接；`-layout` 回退时双栏顺序可能交错；印刷页依赖页脚页码；
  答案为抽取式，不做生成式改写。
