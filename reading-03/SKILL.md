---
name: source-bound-paper-qa
description: 文献智能问答 Skill。读取带段落编号的英文论文文本与中文问题清单，逐题（含子问）作答，把每条论断和每个关键数值绑定到逐字原文引文、段落编号、字符偏移与成立条件；材料没写的内容明确判为“未报告”，不补外部知识，也不编造段落号。适用于论文精读问答、数值与实验条件核验、跨章节（方法+结果）合证，以及“论文是否报告 X”这类边界判断。
version: 1.0.0
---

# source-bound-paper-qa（文献智能问答，证据可回查版）

## 1. 它解决什么问题

典型输入是一篇论文的已抽取文本（摘要、正文、表格文字、图注、参考文献著录，段落带编号）
加上若干中文问题。典型输出是一份可被逐条回查的结构化问答：每题一条记录，每个关键数值一条论断，
每条论断挂原文逐字引文和段落号。目标是让评审不需要重读全文就能核对：

- 结论出自哪一段、原句怎么写的；
- 数字、单位、比较对象、实验条件是否与原文一致；
- 哪些子问题材料里根本没有报告，缺的是什么。

适用：单篇论文精读问答、数值/条件提取、跨章节证据合并、材料未报告判定。
不适用：需要 PDF 版式解析、图像像素识别、附件读取、联网检索或外部知识补全的问法。
本 Skill 不依赖任何第三方库、不联网、不调用模型 API，单次运行秒级完成。

## 2. 调用方式

```bash
python3 -B /skills/literature-qa/scripts/run_reader.py --input /input --out /app/output
```

- 平台把提交目录挂到 `/skills/literature-qa`；若实际挂载点不同，把命令里的路径换成真实目录。
- 不给参数也能跑：默认读 `/input`，写 `/app/output`；写不进去时依次退到 `./output`。
- 推荐先确认解释器与入口可用：`python3 -B <包根>/scripts/run_reader.py --help`，退出码应为 0。

| 参数 | 作用 |
|-|-|
| `--input` | 输入目录；默认识别该目录下的 `case.json`（见第 3 节发现规则） |
| `--out` | 输出目录；默认 `/app/output`，不可写时退到 `./output` |
| `--case` | 显式指定案例 JSON，覆盖自动发现 |
| `--apply` | 合并人工/Agent 写的 `answer_patch.json`（数字必须在已有引文中出现） |
| `--quiet` | 不打印一行运行摘要 |
| `--version` | 打印版本号（1.0.0） |
| `--help` | 用法说明 |

退出码约定：**任何情况下都返回 0**。脚本一启动就先写一份占位 `result.json`，
之后无论解析、检索、写盘是否抛错，都会把可读的 partial 结果留在 `--out` 目录里。

## 3. 输入发现（按语义找，不假设键名）

1. 优先读 `<input>/case.json`；找不到或不合法时，递归搜索 `<input>/**/*.json`，
   跳过文件名或目录名含 `score`、`gold`、`rubric`、`verifier`、`grading`、`expected`、`ground truth` 的评分材料。
2. 案例标识、论文标识、材料版本与 `output_contract` 一律原样保留；论文标识缺失写 `null`，不自造。3. 段落来源按语义识别：`paragraphs`、`paragraph_list`、`paras`、`segments`、`blocks`、`text_blocks`、
   `corpus`、`sentences`、`段落`，既支持扁平数组，也支持按章节嵌套的字典
   （`{"sections": {"results": [...]}}` 这样的结构会把 `results` 当作真实章节名）。
   段内字段兼容若干别名：编号可取 `pid`、`para_id`、`paragraph_id`、`id`；
   正文可取 `content`、`body`、`text`、`paragraph`；章节可取 `heading`、`section`。
   整篇正文只有一个长字符串、行首带 `P12 …` 标记时，按标记切段。
4. 表格、图注、参考文献当作伪段落纳入索引：章节记为 `table` / `figure_caption` / `references`；
   表格的 `rows` 会展开成“表头: 值”的序列，避免列错位。
5. 问题来源：`questions`、`question_list`、`question_set`、`qas`、`queries`、`problems`、`tasks`、`问题清单`。
   条目可以是字典（`question_id` + `question`），也可以是纯字符串（自动生成稳定 `Q1..Qn`）。
   输入问题顺序就是输出答案顺序；重复 id 会自动改成 `Q<序号>`。
6. 材料没给的对象写进 `coverage.not_supplied`（例如“table 未提供”），或保持 `null`；不虚构页码、图注、数值。

## 4. 产物位置与文件

主产物是 `--out` 目录下的 `result.json`，同目录还会写：

| 文件 | 内容 |
|-|-|
| `result.json` | 主结果：契约字段 + 业务字段 + 自检摘要 |
| `answers.json` | 业务字段兼容件（case/paper/version + answers/claims/unanswered_parts/coverage） |
| `paragraph_index.json` | 段落索引：段落号、章节、类型、全文，供按偏移回查 |
| `evidence_map.csv` | 一行一条证据：claim、kind、段落号、章节、locator、char_start、quote 等 |
| `verify_report.json` | 自检报告：通过/失败的检查项、失败清单、引文命中率、数值痕迹率 |

`/app` 可写时额外写一份 `/app/answers.json` 兼容件；写不了只记降级，不影响主结果。

## 5. 输出字段

顶层按四组排列：标识（`case_id`、`paper_id`、`material_version`）、总状态与一句话摘要（`status`、`summary`）、
业务主体（`result`，内含 `answers`/`unanswered_parts`/`coverage`；`answers` 另在顶层放一份镜像）、
核验附件（共 14 个键：`verification`、`counts`、`changes`、`degradations`、`errors`、`pending_human`、
`sources`、`claims`、`question_ids`、`contract_keys`、`runtime`、`method_notes`、`primary_result`，
以及 `uncertainties` 与其别名 `uncertainty`）。

输入 `output_contract` 的每个键都在顶层原样出现：已知键填真实内容，未知键保留，缺值写 `null` 或 `[]`。
平台若把 `status`、`result`、`claims`、`uncertainties` 预声明为空值，脚本用真实结果回填，不会让空声明覆盖答案。

单题记录里的键分三类：

- 身份与状态：`question_id`、`status`、`question_type`、`flags`；
- 回答本体：`answer`、`conditions`；
- 证据与缺口：`claims`、`sub_questions`（字段 `index`/`question`/`status`/`claim_ids`/`evidence_paragraph_ids`）、
  `unanswered_parts`、`evidence_paragraph_ids`。

各位置的离散取值固定如下，多一个都不允许：

- 整体 `status`：`ok`、`partial`、`insufficient_evidence`、`input_error`；
- 逐题与逐子问 `status`：同上四值；
- `claims[].kind`：`reported` 或 `inferred`。

完整字段字典与判定细则见 `references/field_spec.md`，这里不重复。要点：

- `answered`：题干所有子问都有原文依据；数值题必须取到带单位的数值。
- `partial`：有依据但缺子问或缺数值。
- `insufficient_evidence`：全篇检索无可用依据，同时必须在 `unanswered_parts` 写明缺口。
- 逐题 status 不许出现 `ok`、`unknown`、`N/A`；有依据地说明“材料未报告”不算漏答。

## 6. 处理流程（六步，固定顺序，便于同输入对照）

1. **装载与索引**：找到案例文件，建立段落索引（段落号、章节、locator、字符数），
   统计章节，登记表格/图注/参考文献伪段落；解析问题清单。
2. **问题拆解**：按 `？?；;。` 与 `（1）` 拆子问；一句话里出现两个以上疑问焦点时按逗号拆，上限 4 个。
   按提示词判题型：`NUM`（数值）、`MECH`（机制/方法）、`BND`（边界/是否报告）、`INT`（数值+机制）。
3. **双语检索**：中文问句词经 `references/term_map.md` 与脚本内置词表映射成英文本体词，
   再叠加问句里直接出现的英文词与两位以上数字；大小写、连字符、上下标、µ/° 写法归一；
   按词面命中与词形前缀打分。段落数 ≥4 时按文档频次剔除“photocatalyst”这类泛词；
   命中段落再按题型做章节偏置：问数值偏 results、abstract 与 table，问方法偏 methods，
   问边界偏 discussion 与 conclusion。
4. **取证**：在命中段落里按句打分，每段取最高分的 1 句，按字符区间切出 15–60 词引文（同段内按句延伸）。
   每子问保留 2–3 段。子问没有独立命中时，可借用同句/同段证据；条件型子问（温度/时间/浓度…）
   可采纳兄弟子问段落中带该单位数值的证据。
5. **判定与标注**：数值题要求命中数值的单位与被问量一致（问温度→`C/K`，问比表面积→`m2/g`，问效率→`%`），
   单位不符按未报告处理并记 `unit_mismatch`；边界题要求命中段落确实涉及被问特征，
   只沾边（只提到催化剂却问带隙）一律按未报告处理。每个数值单独一条 claim；
   非数值题只从最高分段落抽数值；跨段合并另立 `INT1` 推断 claim；
   全篇零命中立 `ABS1` 未报告 claim 并附检索统计。
6. **写盘与自检**：先写 partial，再写完整结果与 4 个辅助文件，最后跑自检并把结果写进
   `result.json.verification` 与 `verify_report.json`。

## 7. 证据纪律

- `quote` 必须是原段落逐字子串，不翻译、不改写、不拼接两段、不加省略号；一般 15–60 词。
  整段本来短于 15 词时保留自然句长，不强截断，`counts.quotes_below_15_words` 如实计数。
- 定位三元组：`paragraph_id` + `locator`（`/paragraphs/12`、`/tables/1`、`/raw_text/7`）+
  `char_start`（满足 `paragraph.text[char_start:char_start+len(quote)] == quote`）。
- 数值写法原样保留：`±`、p 值、比较符号、`MPa`、`°C`、`850 C`、`%`、`mg/L`、`h`、`min-1` 都不换算；
  `1,250` 按千分位处理，`2,4` 按小数逗号处理。
- 引文与章节、`paper_id`、`claims[].source_id` 必须一致；`char_start = -1` 的引文不计入命中率。
- 中文答句可以有，但数字、单位、条件、结论范围必须与引文一致；推断必须标 `inferred` 并写明由哪几段合并推出。

## 8. 异常与降级

| 情况 | 行为 | 产物痕迹 |
|-|-|-|
| 只给了整篇正文 | 按行首 `P1 …` 标记或空行回退切分 | `changes[item=paragraphs]` |
| 段落没写编号 | 生成 `P1..Pn`，`locator` 指回来源数组 | 段落索引可核对映射 |
| 缺问题清单 | 答案数组为空，契约字段照写 | `degradations[item=questions]`、`status=input_error` |
| 段落无章节标签 | 章节统一为 `unknown` | `coverage.read_status=section_labels_not_supplied` |
| 段落编号重复 | 追加序号去重，两段原文都保留 | 段落索引可见 |
| 单题内部异常 | 该题降级 `partial`，其余照常 | `errors[stage=answer]` |
| `--apply` 改写稿不合格 | 拒收该段，保留原回答 | `pending_human` + `changes` |
| 写不进 `/app` | 只在 `--out` 目录留产物 | `degradations[item=/app/answers.json]` |
| `/input` 无案例或 JSON 损坏 | 不抛异常，落成 `input_error` | `errors` 记 `stage=load_case`、`answers=[]` |
| 材料只有摘要 | 其余章节计入未读 | `coverage.unread_reason=[{...reason:only_abstract_supplied}]` |

## 9. 人工复核与改写接口

脚本产出的是抽取式回答：数值、单位、条件、引文都来自原文，但中文句式偏模板化。
需要更自然的表达时，**不要直接手改 `result.json`**，按下面流程走：

```bash
# 1) 读 /app/output/result.json 与 paragraph_index.json，按题改写 answer 文本
# 2) 写补丁文件，形如
#    {"answers": {"Q1": {"answer": "改写后的中文回答", "conditions": ["条件片段"]}}}
python3 -B /skills/literature-qa/scripts/run_reader.py --input /input \
        --out /app/output --apply /app/output/answer_patch.json
```

硬规则：改写文本里出现的每个数字都必须能在该题已有引文中逐字找到，否则整段拒收，
原回答保留并记入 `pending_human`。这条规则防止“润色”引入原文没有的数值。

## 10. 质量对照点（评分维度 → 落地字段）

| 关注点 | 在哪里体现 |
|-|-|
| 事实正确 | `claims[].text` 形如 `label = value unit`，单位与条件取自引文 |
| 逐题覆盖 | `answers[]` 题数 = 输入题数（含答不了的题），子问进 `sub_questions[]` |
| 完整 | 子问分块 `【子问N】`；缺项进 `unanswered_parts`，不静默丢弃 |
| 可核验 | 段落号 + locator + 字符偏移 + 逐字校验标志 + CSV 证据表 + 命中率 |
| 增益可对照 | `counts`（题数/子问数/数值 claim 数/引文命中率/数值痕迹率）、`method_notes`、`verify_report.json` |
| 创新点 | 跨段 `INT1` 推断、子问级状态、`conditions` 条件绑定、`ABS1` 未报告判定、数值痕迹审计 |
| 可靠体验 | 缺文件/坏 JSON/缺问题/单题异常均有分支，均不中断，退出码恒 0 |
| 可复用 | 本文件 + `references/field_spec.md` + `references/term_map.md` + `references/worked_example.md` |

## 11. 本版新增的自检项

在原有自检之外，本版增加「数值痕迹」审计：

- 对每条 `label = value unit` 型论断，取出数值部分，在该论断自己的 `evidence[].quote` 里逐字查找
  （比较前把引文侧的千分位与小数逗号归一，`1,250` ↔ `1250`、`2,4` ↔ `2.4`）；
- 结果写进 `counts.numeric_claims_checked` / `numeric_claims_traced` / `numeric_trace_rate`，
  以及 `verify_report.json.numeric_trace`；
- `verification.checks.numeric_values_trace_to_quotes` 与之一致，未命中的 `claim_id` 列入
  `unmatched_claim_ids` 待人工复核。

它的作用是把“claim 里的数字确实来自引文”从口头约定变成机器可查的断言。

## 12. 自检清单（提交/交付前逐项跑）

```bash
python3 -B /skills/literature-qa/scripts/run_reader.py --help          # 退出码 0
python3 -B /skills/literature-qa/scripts/run_reader.py --input /input --out /app/output
python3 -c "import json;d=json.load(open('/app/output/verify_report.json'));print(d['ok'],d['fails'],d['quote_hit_rate'],d['numeric_trace'])"
```

- [ ] `result.json` 能被 JSON 解析，`output_contract` 每个键都在顶层，`answers` 与 `result.answers` 一致；
- [ ] `answers` 题数 = 输入题数，每题 `status` 属于四个允许值，`sub_questions` 序号从 1 连续；
- [ ] 每个报告数值都有独立 claim，`kind` 只有 `reported`/`inferred`；
- [ ] `quote_hit_rate = 1.0`，`char_start` 逐字对上，`paragraph_id` 都来自段落清单；
- [ ] `numeric_trace.checked == numeric_trace.traced`；
- [ ] `partial` / `insufficient_evidence` 的题都有 `unanswered_parts`，未报告项有 `uncertainties` 记录；
- [ ] `coverage` 含已读章节、未读章节及原因、`not_supplied`；
- [ ] 空输入、坏 JSON、缺 `questions` 三种情况仍产出合法 partial `result.json`，退出码 0；
- [ ] 没有外部知识、没有翻译引文、没有自造 `paragraph_id`、没有预置正式案例答案。

## 13. 文件清单、维护与已知限制

| 文件 | 作用 |
|-|-|
| `SKILL.md` | 入口：用途、调用、输入发现、输出、流程、降级、自检 |
| `scripts/run_reader.py` | 检索、取证、作答、写盘、审计（参数 `--input`、`--out`、`--case`、`--apply`、`--quiet`、`--version`） |
| `scripts/reader_kit.py` | 案例发现与解析、数值/引文/覆盖工具、JSON/CSV 输出 |
| `references/field_spec.md` | 字段字典、状态判定、与评分点的对应、数值痕迹审计说明 |
| `references/term_map.md` | 中英检索词映射（通用 + 材料机械 + CS/ML + 环境光催化） |
| `references/worked_example.md` | 最小调用示例（自拟材料，标注“示例”）与复用建议 |

维护：换领域先加 `references/term_map.md` 或 `reader_kit.INLINE_TERMS`；调检索权重看
`run_reader.py` 的 `SECTION_PRIOR` 与 `score_paragraph`；改字段同步 `references/field_spec.md` 与本文件第 5 节；
改完重跑第 12 节自检并如实记录。

已知限制：

- 检索是词面 + 词形前缀匹配，依赖词表覆盖；语义等价但用词完全不同的段落可能漏检，
  此时按 `insufficient_evidence` 处理，不猜答案；
- 回答是抽取式的，句式模板化，必要时应走 `--apply` 改写，并接受“数字必须在引文中”的约束；
- 跨语言只靠词表桥接，不做语义翻译；数值标签由邻近词或单位类别生成，个别偏宽（如 `相对变化`）；
- `conditions` 是原文条件片段，不是规范化实验设计描述；
- 材料没有提供页图/表格图元时，无法给出页码与图像读数，也不做 OCR 与联网检索。

## 14. 常见问题排查（交付前自查用）

**问：结果里某题是 `insufficient_evidence`，但我觉得论文里明明写了。**
先看该题的 `uncertainties[].zero_hit_terms`：把问题里的中文术语逐个对照 `references/term_map.md`，
缺哪个就在文件末尾补一行 `- 中文 => 英文写法`，然后重跑。若命中了段落但证据被清空，
看 `changes` 里有没有“单位不一致”或“边界题未涉及被问特征”的记录——这是有意为之的拒答，
不是漏检索。

**问：某条 claim 的引文比段落长，或者看起来被截断了。**
引文按 15–60 词切片，并尽量落在整句边界上；超长句只取命中词附近的一段。逐字命中校验
（`quote_verified`）优先于“句子完整”，所以偶尔会出现从句子中间开始的情况，这属正常。

**问：为什么同一篇论文两次数值标签不一样？**
标签由数值前最近的实词生成；若改写 `term_map.md` 导致命中段落变化、最高分句子换了，
标签也会跟着变。只要 `numeric_trace_rate` 为 1.0，说明标签与数值都来自同一句原文。

**问：`coverage.sections_unread` 里有章节，但论文其实给了。**
多半是段落没有 `section` 标签，脚本把它记为 `unknown`；此时 `read_status` 是
`section_labels_not_supplied`，不是真的没读。可在输入侧补章节名，或在结果里按 `paragraph_id` 人工核对。

**问：可以把 `result.json` 直接改成更通顺的中文吗？**
不建议。手改会破坏 `char_start` 与引文的一致性，下一轮自检就对不上。改写请走第 9 节的补丁接口，
脚本会重新校验数字来源。

## 15. 设计取舍（为什么这样实现）

- **抽取式优先**：本任务的分差主要来自事实是否可核验，而不是文采；先把证据链做对，
  语言再通过补丁接口润色，风险最低。
- **先写占位产物**：任何异常都可能发生在解析中途，先落盘一个合法 partial 结果，
  平台至少能拿到结构完整的输出。
- **拒答要有检索统计**：只写“未报告”无法自证不是漏检索，因此每条未报告结论都附
  检索词、零命中数与已检索段数。
- **词表外置可读**：把中英桥接放在 `references/term_map.md` 而不是硬编码，
  换领域时使用者能自己扩展，不必改代码。
- **不引入第三方依赖**：评测环境不装包，纯标准库实现意味着复制目录即可运行。
