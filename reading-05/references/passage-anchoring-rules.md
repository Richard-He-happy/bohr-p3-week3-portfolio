# 定位、切段与降级的实现约定

本文件规定 `scripts/pipeline.py`（解析与编排）和 `scripts/viewer.py`（定位/问答/渲染）共同遵守的
确定性规则。改脚本之前先改这里，保证文档与实现一致。

## 1. 先定坐标系：文本怎么清洗

每页抽出文本后按固定顺序处理：换行统一成 `\n`；删掉软连字符（U+00AD）；把行尾断词
（形如 `inter-\nnational`）拼回单词；去掉行尾空白；连续空行压成一个；行内多空格压成单空格；
段落内部的换行改成空格，使段文本成为一行。清洗后的每段文本用空行拼成全文，此后所有
`char_start`/`char_end`/`quote` 都以此为准，全文 sha256 记入 `doc_text_sha256`。

这样做的结果是：引文与 PDF 的视觉断行不再一致，但它和 `anchors.json` 的段落文本、和字符偏移
严格一致，复核者切片即可逐字核对。

## 2. 页怎么映射

`pages` 是抽取结果中换页符切出的段数，物理页从 1 编号。`pdfinfo` 报告的 `Pages` 只用来交叉验证；
两者不一致时以文本分段为准，原始数字留在 `document.pages_reported`。

`printed_page` 只在页面首行或末行是独立页码时才能取（纯数字、`Page 3 of 12`、`p. 7` 这类），
取不到就写 `null`。不要用物理页加减常数去猜印刷页。`page_map` 把每个段落的物理页与印刷页
并列放好，页脚有页码时一眼就能看出偏差。

## 3. 段落怎么切

逐页进行：先剥掉首尾的纯页码行，再按行判断标题。满足以下任一条件就算标题：命中章节词表
（摘要、引言、方法、结果、讨论、结论、参考文献、致谢等中英文词，且行长有限）、是编号标题
（如 `2.1 Methods`）、整行大写且含字母。标题单独成块，标题之间的内容归为段落块。

每个块保留：所属章节标题、物理页、页脚印刷页、清洗后的文本与字符区间。`paragraph_id` 由脚本
按顺序重排（`p1` 起），不采信外部编号；外部 id 只有在能逐字命中原文时才沿用。

## 4. 定位按什么顺序试

依次尝试下面五级，命中即停，并如实记录精度档位：

1. 选区逐字命中（含空白归一化后的映射）→ 字符级，方法 `verbatim_search`。
2. 选区与某段相似度 ≥ 0.55 → 段落级，方法 `fuzzy_paragraph_match`，答案句取段内最相关的句子。
3. 只给了章节或问题关键词 → 段落级，方法 `keyword_rank_in_section`（没有章节就
   `keyword_rank_global`）。
4. 章节存在但关键词都没命中 → 页级，方法 `section_first_paragraph`。
5. 全失败 → 未解析，必须写进 `uncertainties`。

补充：选区跨页时不拼接原文，按命中位置所在段落归属，`notes` 说明跨段；双栏排版优先用阅读
顺序模式抽取，只有为空才退 `-layout`，并在 `degradations` 记 `pdf_layout_mode`；外部段落编号
与正文序号不符时按重编号处理，不强行对齐。

## 5. 问答上下文只用三样东西

允许：选区片段、选区所在段落的全文、所在章节标题。不允许：其他章节、摘要与正文混合推断、
材料外知识。回答方式是段内句子打分，取最相关的 1–2 句逐字原文；如果这些句子在段落原文里
找不到，状态降为 `partial`。每次问答都把实际使用的范围写进 `context_scope`
（`used_scope`、`excluded_scope`、`chars_used`），供他人判断答案有没有越界。

## 6. 异常处置表

| 条件 | 识别 | 动作 | 产物可见处 |
|---|---|---|---|
| 扫描件、无文本层 | 文本不足 40 字符，或字母占比低于 25% | 不造正文；状态 `insufficient_evidence`；后续步骤 skipped | `pending_human.no_text_layer`、占位 HTML、uncertainties |
| 加密 PDF | `pdfinfo` 报 `Encrypted: yes` | 仍尝试抽取，失败同无文本层 | `pending_human.encrypted_pdf` |
| 文件超过 120MB | 读取大小 | 处理前 400 页并在日志标注 | `degradations.oversize_pdf` |
| 环境无 pdftotext | `shutil.which` 为空 | 标准库 inflate 扫描内容流；分页顺序为近似 | `degradations.extractor_fallback` |
| 选区定位失败 | 相似度低于 0.55 且关键词无命中 | 精度未解析 | 进 uncertainties，不得伪装段落级 |
| 问题没有依据 | 段内没有命中关键词的句子 | 问答状态 `undetermined`，答案空 | 进 uncertainties |
| 批注写失败 | 原子写异常 | 记错误继续跑 | `errors.write_failed`，result.json 完整 |
| HTML 模板缺失 | 文件不存在 | 用内置极简模板 | HTML 中注明 |
| case.json 非法 | 解析异常 | 用材料继续，case_id 置 UNKNOWN-CASE | `errors.case_json_invalid` |
| 输入目录无材料 | 扫描结果为空 | 闭环全部 skipped，状态 `input_error` | uncertainties 记 missing_source |
| 渲染或资产异常 | 对应函数抛错 | 记降级/错误，不影响 JSON | HTML 可能缺，JSON 合法 |

单份材料或单页失败只降级局部。进程退出码始终是 0。

## 7. 复现与回归

复现：段落顺序、映射表顺序、选区顺序分别跟文档顺序与任务顺序，方法里不含随机数；批注 id
由段落号与序号拼成；同一份材料两次运行，哈希相同、产物结构相同。

人工复核两条路：其一，把 `anchors.json` 段落文本按 `char_start`–`char_end` 切片，与 `quote`
逐字比对；其二，在 `index.html` 按段落 id 找到高亮位置，肉眼核对原文。

改脚本或模板后的回归五步：

1. 两个入口脚本的 `--help` 都返回 0。
2. 同一最小输入连跑两遍，第二遍批注数不减、`sessions` 递增。
3. 看 `self_check.json`：`overall` 非 `fail`，C12（引文回贴、问答对齐）为 pass；
   `diff_report.md` 的 pending 项都在 `uncertainties` 里。
4. 抽查三条：选区引文在 anchors 段落文本中逐字命中；`answer_quotes` 能在所属段落找到；
   HTML 的段落 id 与 anchors 一一对应。
5. 三种降级各跑一次（空输入、坏 case.json、无文本层材料），退出码 0 且
   `result.json` 分别给出 `input_error`、`partial`、`insufficient_evidence`。
