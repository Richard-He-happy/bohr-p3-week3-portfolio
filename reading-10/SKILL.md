---
name: reading-bench-forge
description: 在评测现场把 /input 里的科研材料锻造成一套可判分的文献阅读题集：Agent 亲手出题并写评分锚点，脚本负责材料索引、逐字引文核对、0/1/2 点级算分、报告渲染与 result.json 契约回填。适合文献阅读 Benchmark 建设、题集可判性审计、引文抽查与版本对照。
version: 1.0.0
---

# 文献阅读题集锻造包（reading-bench-forge）

## 0. 这套东西到底解决什么

评测方给的是材料 + 一句任务要求，要的是**能判分、能复跑、能追溯**的题集，而不是一份题单。
本包把这件事拆成一条固定流水线：

```
材料索引  →  逐段阅读  →  写题卡（题 / 评分点 / 参考要点 / 逐字引文）  →  结构+引文核对  →  0/1/2 算分  →  五件产物
```

分工很明确：**出题是 Agent 的判断**（脚本不会替你读懂论文），**核对与算分是脚本的机械动作**（不靠人眼抽查）。
两者之间唯一的接口是「逐字引文 + locator」，所以只要引文对得上原文，分数就能被任何人复算。

## 1. 适用与不适用

**可以做**
- 单篇或多篇论文、技术报告、表格、DOCX / PDF / TXT / Markdown 材料的阅读题集建设；
- 中英文题面与评分点（中文按 4 字滑窗取关键串，英文按词做覆盖度）；
- 题集质量自检、引文可核验性抽查、给下一轮评测准备题集快照；
- 在 900 秒 / 64 次模型请求的预算内**先落盘再逐步变好**（见 §11）。

**不要拿它做**
- 替被评测的 Agent 答题（本包产出的是题，不是答案卷）；
- 编造分数或把 checker/合成数据写成官方分数；
- 拿材料以外的领域知识当证据（题面允许"材料未报告"作答，但不允许补造数字）；
- 纯图片材料的 OCR（脚本只登记缺口，需要你或平台工具先读出文字）；
- 需要跑代码复现实验的题（本包不执行被评测材料里的代码）。

## 2. 运行契约

- **读哪里**：输入根默认 `/input`；`case.json` 可有可无（也认 `case*.json`），其余文件一律当材料；
- **写哪里**：工作根默认 `/app/work`（索引、草稿、check 报告），输出根默认 `/app/output`（§4 五件产物）；
- **怎么调**：`python3 -B scripts/run_build.py <verb>`，verb 取 `init` / `show` / `check` / `build`；
  `scripts/reading_core.py` 是纯库，同样支持 `--help`；
- **路径可覆盖（本包增量）**：四个 verb 都收 `--input DIR`、`--output DIR`、`--work DIR`，
  不传就回落到上面三个默认根，方便本地冒烟与多案例批量跑；
- **退出码恒 0**：任何异常都不靠非零码表达，而是落到 `result.json` 的 `errors` / `degradations`；
- **依赖**：只要 Python 3 标准库，不联网；根路径从 `Path(__file__)` 推，跟当前目录无关；
- **预算**：64 次模型请求 / 900 秒；`init` 跑完就有一个合法 partial `result.json`，随时可停。

## 3. 材料是怎么被发现的（别假设键名）

`init` 递归扫描输入根，跳过隐藏文件、`__pycache__`、`.git`、`node_modules`，以及**根目录**的
`case.json` / `task.md` / `result.json`（这三个是外壳文件，不是材料）。每个材料按扩展名 + 魔数判型
（`%PDF`、`PK` 开头），抽取文本，再按空行切段，给每段一个**稳定 locator**：`M01#p7`
（`M` + 材料序号 + `#p` + 段序号）；PDF 额外记页码。

- 解码顺序：`utf-8-sig` → `utf-8` → `gb18030` → `latin-1`，全部失败才 `ignore` 并记一条降级；
- 材料类型：文本类（md/txt/csv/tsv/json/html/tex/…）直读；`.docx` 取 `word/document.xml`；
  `.xlsx` 取 sharedStrings；`.pdf` 依次尝试 `pdftotext` → PyMuPDF → pdfminer → 内置 zlib 流抽取；
  图片只登记 `no_text` 缺口。
- `case.json` 不按固定 schema 死读，而是**按语义找同义词**：标识类认 `case_id` / `caseId` / `id` /
  `task_id`，契约类认 `output_contract` / `contract` / `required_outputs` / `output_schema`，指令类认
  `task_instruction` / `instruction` / `prompt` / `task`，此外 `organizer_workorder` 也会被收下；
  找到的契约**原样透传**（不改名、不丢字段、不重排声明顺序）。

材料清单会打印 `paras` / `chars` / `status`；带 `!` 的那一行表示文本质量或解析有降级，出题时要当心。

## 4. 五件产物与 result.json

| 产物 | 内容 | 谁读 |
|---|---|---|
| `benchmark.json` | 题集快照：items[]（题面 / rubric / 参考要点 / 证据）、rejected[]、mode | 复核人、下一版题集 |
| `anchors.json` | 引文抽查表：每条 `material` / `locator` / `quote` / `verified` / `match` | 抽查引文 |
| `scoring.json` | 逐题逐点的 0/1/2、basis、locator、aggregate、pending_human | 分数复核 |
| `report.md` | 一次评测的凭证：材料表 / 逐题表 / 评分汇总 / 缺口 | 汇报（不用打开 JSON） |
| `result.json` | 信封 + 契约回填 | 平台与下游 |

`result.json` 是"信封 + 契约回填"两层结构。信封固定带五组信息：运行标识与状态（`case_id` /
`status` / `stage` / `skill`）、追溯入口（`outputs` / `runtime` / `sources`）、结果摘要
（`benchmark` / `anchors` / `scoring`）、诚实性字段（`uncertainty` / `pending_human` / `errors` /
`degradations` / `changes`）、合成数据声明（`technical_synthetic`），外加契约审计用的
`contract_fields_present` / `contract_echo`。每个字段的类型与触发条件见
`references/contract-map.md` §1，本文不重复抄一遍。

另外，`output_contract` 里的**每个字段都会在顶层出现一次**：能算出来就填真实值，算不出来就给
`null` / `[]` / 同形空结构——**不允许整个键消失**。文件一律 UTF-8 无 BOM。
若输入里带了候选输出或 checker 日志，只登记进 `technical_synthetic`（`not_a_dsh_score: true`），
**不参与评分**，因为它不是独立语义验证。

## 5. 主流程（你是出题人，按顺序走）

1. **`init`**：建索引、打印材料清单与契约字段名、先落一个 partial `result.json`。
   看清每个材料的 `paras`、`chars`、`status`；有降级就先判断"这段还值不值得出题"。
2. **`show`**：按材料分页浏览原文（`--material M01 --start 1 --limit 20`）。后面要用的引文一律
   从这段输出里拷贝，手打、翻译、概括都会让引文核验失败——所有分数都建立在"逐字"两个字上。
3. **写题集草稿** `work/questions.draft.json`（字段字典见 `references/question-spec.md`）：
   - 每张卡：`id`、`type`、`difficulty`、`question`、`rubric[]`、`reference_answer[]`、`evidence[]`；
   - `rubric[]` 每点给 `id` / `text` / `weight` / `key_terms`；**两点比一点更能区分"答对一半"**，
     常用 0.5/0.5 或 0.6/0.4；
   - `key_terms` 用原文实词（数字、单位、术语），别写"正确""完整"这类空话；
   - 题目覆盖不同层次：可核对的数值/表格、方法与条件、机制与主张、材料内冲突、材料未报告项；
   - `evidence[]` 每条给 `material` + `locator` + `quote`，`quote` 逐字连续片段。
4. **`check`**：逐条报 `FAIL`（结构 / 引文 / locator / 权重）与 `NOTE`（可接受的提示）。
   按报错回到 `show` 重抄引文，改完再跑，直到 `RESULT: PASS`；剩余错误要明确写进 `pending_human`。
5. **`build`**：生成五件产物、finalize `result.json`、跑 6 项结构自检并打印 `SELF-AUDIT 6/6 PASS`。

`build` 是幂等的：同样的输入 + 同样的草稿，重复跑产物一致，可以放心重试。

## 6. 题卡与证据的硬规则

- **locator 只认一种格式**：`M<材料号>#p<段号>`，例如 `M02#p11`；PDF 另带页码字段。
- **quote 必须是原文的连续片段**：允许空白差异，不允许拼接、改词、翻译、加省略号；长度 ≥12 字符；
  一句话尽量完整，别只抄三个词。
- 结构必填：`question` ≥10 字符、`rubric` ≥1、`reference_answer` ≥1、`evidence` ≥1；
  `Σweight` 应 ≈1.0（偏离 0.02 以上只 `NOTE`，不改分）。
- 引文命中后脚本反推它实际所在的段号：与声明的 `locator` 不同 → `locator_mismatch` FAIL；
  没写 `locator` 而命中位置明确 → 自动补上并记 `NOTE`。
- **一题没有任何可核验引文 → 整题拒收**，进 `benchmark.json.rejected` 与 `pending_human`，
  不参与算分，也不假装它"判过了"。
- 同一题可以有多条证据：算分取**覆盖度最高**的那条；跨段对比题给两条。

## 7. 0/1/2 的算法（可复算）

按 rubric 点算，不看整题：

| 档 | 条件 | 含义 |
|---|---|---|
| **2** | 有逐字锚点，且锚点文本覆盖该点 `key_terms` 的比例 ≥ 0.6 | 可判且判定有原文依据 |
| **1** | 锚点存在，但覆盖不足（0 < coverage < 0.6） | 能判一半，需要人复核 |
| **0** | 无可用锚点，或关键项一个都没覆盖 | 不可判（不是"答错"） |

题分 = `Σ(weight × 点分)`，满分 2。`aggregate` 给出 `n_items`、`n_points`、`n2/n1/n0`、`rate2`、
`judgeable_rate`、`mean_score`、`n_anchors`、`n_anchors_verified`；`pending_human` 列出所有 `<2`
的点，写明题号、评分点、basis——这就是下一轮要补强的位置。

**必须记住**：这是「这套题能否被判」的自检分，**不是被评测 Agent 的答题分，也不是 DSH 分数**。
`scoring.json` 里写了同样的声明，任何人重跑 `check`/`build` 都应该得到同样的结论。

## 8. 可追溯性：一个分数顺着什么找回去

题集侧三件产物通过 `item_id` 互相串起来，任一分数都能走完这条链：

```
scoring.json items[i].points[j].locator/basis
      → anchors.json 中同 item_id 的 quote / material / locator
      → benchmark.json 中同 item_id 的题面、rubric、reference_answer
      → /input 里 locator 指向的那一段原文
```

`result.json.outputs` 记录每个产物的绝对路径，`runtime.self_audit` 记录 build 结束时 6 项结构断言
（点数相加、locator 可解析、题号对齐、可判点有 locator、契约键在顶层、aggregate 可复算）的结果。

如果平台另外要求 `raw_output_ref` / `config_ref` / `scoring_record_ref` 三指针，映射关系见
`references/contract-map.md`：三指针分别指向被评测输出文件（+JSON Pointer）、本次运行的配置
（模型 / 权限 / 预算 / prompt 版本）、以及本包 `scoring.json` 的对应评分记录。

## 9. 异常与降级矩阵

- **`case.json` 坏掉或干脆没有**：不阻塞，继续扫目录出题，契约部分留空；`status` 落 `partial`，`errors` 记一条。
- **输入根一个材料都没有**：五件产物照常生成（空题集），`status` 落 `input_error`——让人一眼看出是输入问题。
- **材料抽不出文本**（图片、加密 PDF）：该材料标 `no_text` 并进 `degradations`，其他材料继续跑。
- **PDF 文字质量差 / 需要 OCR**：`degradations` 记 `pdf_text_quality_low`，同时在 `uncertainty` 提醒
  "引文需平台解析器复核"——不要硬把可疑的 OCR 结果当逐字证据。
- **草稿缺失或所有题都核验不过**：走确定性兜底，从真实段落生成最小摘录/数值题（一段一题、上限 6 题），
  `mode=fallback_minimal`、`status=partial`，至少保证产物不为空。
- **只有部分题被拒**：能用的题正常出包，再补 2 道兜底题，`mode=agent_authored_with_fallback`。
- **输入夹带 checker 日志或候选输出**：只在 `technical_synthetic` 登记（`present=true`），不评分。
- **材料本身没报告某个结论**：题面就问"材料是否报告"，`reference_answer` 写"未报告"，
  绝不补造数字；这种情况进 `pending_human` 说明清楚。
- **任何未捕获异常**：打印栈、写合法 partial `result.json`（含 `errors[].traceback`）、进程退出 0。

## 10. 本地冒烟与批量（不用碰 /app）

路径全部可覆盖，所以可以在一台机器上把整条流程跑通、再和基线对照：

```bash
PY=python3   # 本机无 python3 时用解释器绝对路径
# 1) 索引 + partial result.json
$PY -B scripts/run_build.py init  --input test/input --output test/out --work test/work
# 2) 读原文抄引文
$PY -B scripts/run_build.py show  --input test/input --output test/out --work test/work \
        --material M01 --start 1 --limit 20
# 3) 写草稿后核对结构
$PY -B scripts/run_build.py check --input test/input --output test/out --work test/work
# 4) 出包 + 自检
$PY -B scripts/run_build.py build --input test/input --output test/out --work test/work
```

**降级三连测**：空输入目录、坏 `case.json`、缺草稿各跑一次 `build`，都要求退出码 0 且产出合法
partial `result.json`。**对照跑**：同一份输入喂给手头的基线实现，比较产物集合、`aggregate`、
`anchors[].verified`、`status`；允许措辞不同，不允许数字不同。

## 11. 预算与断点

- `init` 一跑就有合法 `result.json`，所以**先保底、再变好**：宁可 3 题可判，不要 8 题做不完。
- 每步都可中断重跑；`build` 幂等覆盖，不需要清理旧产物（要留档就先复制一份输出目录）。
- 接近 780 秒就别再追求多出两题，直接 `build` 收尾。
- 材料大时用 `show --start/--limit` 分页读，不要一次打印全文。

## 12. 交付前自检清单

- [ ] 两个脚本的 `--help` 都能跑：`run_build.py --help`、`reading_core.py --help`，退出码 0；
- [ ] 有 case 时，`contract_fields_present` 的每个名字都能在 `result.json` 顶层找到同名键；
- [ ] `benchmark.json` 的 `items` 不为空；若为空，`status` 已写明原因（输入错 / 证据不足）；
- [ ] `anchors.json` 里 `verified` 全为真；凡是有假值的题，必须出现在 `rejected` 里而不是分数里；
- [ ] `scoring.json.aggregate` 的 `n2 + n1 + n0` 等于 `n_points`，且 `runtime.self_audit.ok` 为真；
- [ ] `report.md` 四段齐全：材料表、逐题表、评分汇总、缺口；
- [ ] 包里干净：没有 `__pycache__`、`.pyc`、临时输出、大二进制，也没有预制答案。

## 13. 最小调用示例（示例，非正式案例结果）

示意题卡（节选，**示例数据，不是任何正式案例的答案**）：

```json
{"id": "Q07", "type": "numeric", "difficulty": "medium",
 "question": "催化剂 C-7 在 80 °C 下的转换频率是多少，作者给出的误差范围多大？",
 "rubric": [{"id": "R1", "text": "给出 0.42 mmol h-1 g-1", "weight": 0.6, "key_terms": ["0.42", "mmol"]},
            {"id": "R2", "text": "给出 ±0.03 的误差范围", "weight": 0.4, "key_terms": ["0.03"]}],
 "reference_answer": ["0.42 mmol h-1 g-1，误差 ±0.03"],
 "evidence": [{"material": "M03", "locator": "M03#p4",
               "quote": "the turnover frequency of C-7 at 80 °C reached 0.42 mmol h-1 g-1 (±0.03)"}]}
```

跑出来的 `scoring.json` 里该题两个点都是 2 分，`basis` 会写清覆盖度与 locator；`report.md` 的逐题表
一行对应一题，`locator` 列就是抽查入口。

## 14. 常见失败模式（出题前先避开）

1. **只交"题单 + 截图"**：没有可跑脚本与可复算分数，完成度直接低档——本题面点名的反面。
2. **自造 gold answer**：来源没写的数值不能编；来源没有答案就标 `reference_missing`。
3. **把 checker 合成日志当评测分数**：revision2 题面明确否定；本包只登记不评分。
4. **只有总分没有依据**：没有 locator / basis 的分数不可复核，可核验分基本失守。
5. **报告数字与 `scoring.json` 不一致**：本包 `report.md` 由算分结果渲染，不手写数字。
6. **版本对比不判可比性**：改了 rubric 或 quote 的题不能直接和历史分数混算。
7. **无脑加功能**：多脚本 + 大来源文件 + Web 面板除了超时、超文件限额，没别的收益。

## 15. 文件清单、版本与维护

- `scripts/run_build.py`：命令行四 verb（init / show / check / build），≤25KB；
- `scripts/reading_core.py`：材料抽取、索引、引文定位、题卡校验、result.json 外壳，≤25KB；
- `references/question-spec.md`：草稿字段字典、check 规则表、出题建议；
- `references/contract-map.md`：result.json 字段字典、三指针映射、状态与降级对照；
- `references/maintenance.md`：换案例、当组件、扩展点、已知限制、变更记录；
- `SKILL.md`（本文件）：为什么做、契约、流程、规则、降级、自检。

- 换新案例：替换输入根里的 `case.json` 与材料 → `init` → `show` → 写草稿 → `check` → `build`，
  命令与产物结构都不变；旧产物会被覆盖（先手工留档即可）。
- 当组件用：`import reading_core as core`，`core.index_input()` 建索引、`core.locate_quote()` 核验引文、
  `core.audit_items()` 校验题集；或直接用 `--input/--output/--work` 批量跑多个案例。
- 改评分口径（覆盖度阈值 0.6、档位定义）属于**语义变更**：升版本号，并在
  `references/maintenance.md` 的变更表里记一条，否则历史分数不可比。

版本：1.0.0（首次交付：Agent 主导出题 + 确定性兜底 + 契约回填 + 6 项结构自检 + 路径参数化）。

## 16. 设计问答：为什么是这几条线

**Q1：为什么分数不直接给答案对错，而要挂在引文上？**
读材料的是 Agent，判分的是脚本，两者唯一的共同语言是原文。只要一个评分点的依据能落在
`M03#p4` 的某个连续片段上，这个点就能被其他人用同一条引文复算；反过来，一个"凭感觉给 2 分"
的评分点，无论写得多漂亮都无法复核。所以本包把"可判"和"判得对"拆开：脚本只保证前者，
后者交给 `pending_human` 和人工抽检。

**Q2：为什么宁可用确定性兜底题，也不允许空产物？**
评测现场一次运行就是一次交付。空题集拿到的是"没做完"，兜底题拿到的是"做完了但质量有限"，
两者在可复核性上差别很大；而且兜底题来自真实段落，仍然满足"引文可核验"这条底线，
评审可以直接看到哪些位置还需要补题。

**Q3：为什么把 checker 日志单独拎出来声明？**
合成检查日志看起来像分数（有 pass/fail、有计数），最容易被误读成评测结论。题面已经明确
"technical synthetic checker logs are not DSH scores or independent semantic validation"，
所以本包把它放进 `technical_synthetic` 并固定 `scored=false`，让"登记"和"计分"在数据结构上就是两件事。

**Q4：为什么不干脆扩大题量？**
题量增长带来的是模板化风险：同一个 rubric 结构复制十遍，重复度上去了，区分度没上去。
本包更看重「每种题型至少一条、可判率优先、缺口写清楚」，之后才是加题。
