---
name: paper-deck-architect
description: 把单篇论文（PDF/DOCX/MD/TXT，可附目标模板或起始稿 pptx）重构为可直接上台讲的学术汇报演示：先产出页级骨架与逐页证据映射（页码/章节/图 N/表 N + 论文原句），再生成继承模板母版与版式的可编辑 .pptx、真实可解析的 PDF 预览、逐页 content_map，并把整份结果回填进 result.json 的 output_contract。用于论文转学术 PPT、paper-to-slides、组会/周会汇报、学术会议报告、论文答辩预演、按单位模板改稿等场景。
version: 1.1.0
---

# 论文 → 学术汇报演示（paper-deck-architect）

一句话定位：把连续叙述的论文改写成**页级离散表达**——一页只说一件事，这件事必须挂着论文里的某个页码/章节/图/表，并且落在一套真实模板的版式里，打开即可放映、逐页可编辑、每句话可回查。

这个 Skill 不是"自动写 PPT 的提示词合集"，而是一条可复跑的命令行流水线：输入一个 case 目录，输出演示文件 + 预览 PDF + 页级证据表 + 结构化结果信封。同一输入重复运行，页序与证据选择保持一致。

## 0. 接口速览

- 入口：`python3 <skill>/scripts/deckgen.py --input <case目录> --output <产物目录> --work <中间目录>`
- 三个路径参数都有默认值（`/input`、`/app/output`、`/app/work`），可只覆盖其中一部分。
- 输入侧约定：`<case>/case.json`、`<case>/task.md`、论文文件；可选 `artifacts/` 下的 workorder 与模板/起始稿。
- 输出侧约定：`presentation.pptx`、`presentation.pdf`、`plan.json`、`deck_model.json`、`result.json`；中间目录里另有 `verification.json` 与 `structure_check.json`。
- 每次运行收尾还会在输出目录写出五件可核验资产：`golden_standard.json`、`diff_report.md`、`version_history.md`、`run.log`、`self_check.json`（见 §9；摘要路径并入 `result.json`）。
- 依赖只有 Python 3.8+ 标准库。`pdftotext`、`soffice`/`libreoffice`、`office-renderer` 都是可选探测器：能发现就用，装不了就走降级路径，**绝不因此失败**。
- 进程退出码恒为 `0`。失败不是用 exit code 表达，而是写进 `result.json` 的 `errors` / `exceptions` / `degradations`。
- 时间预算：单进程跑完，普通论文秒级；不启动后台任务、不联网、不写全局状态。

想先确认环境是否可用，跑 `--help` 即可（退出码 0，且不依赖当前目录）。

## 1. 范围与红线

**该做**：抽取论文主线 → 定页级角色与主张 → 对齐图/表引用 → 建立逐页证据 → 写讲稿 → 按模板占位符排布 → 导出并自检。

**不该做**：替作者生成新结论、重绘论文插图、润色论文正文、冒充同行评审。相邻课题（论文精读、科研绘图、写作润色）的产出可以作为本 Skill 的输入材料，但本 Skill 只对"论文内容如何变成可讲、可核验、可编辑的学术演示"负责。

红线是一条：**页面上的每个事实都要能在论文原文里逐字命中**。数字、单位、方法名、图/表编号、结论性短语，一个都不能是模型凭印象补的。命中不了就写进 `pending_human` 等人工确认，宁缺毋滥。

## 2. 输入是如何被发现的

脚本不假设固定键名，而是按语义和文件特征找：

1. **case**：优先 `<input>/case.json`；不存在时递归找 `case*.json`；仍找不到就用默认契约继续跑，并在 exception 里记一笔。
2. **契约**：`output_contract` 与 `case_id` 原样保留——契约键顺序不改、大小写不改；未知字段不删；值缺失时保留键名、值置 `null` 或空数组。
3. **workorder**：先看 case 里有没有带 slide 语义的子字典，再找文件级的 `*workorder*.json` / `slide*spec*.json`。真正被消费的只有四组：请求模式、总页数、素材保留要求、模板继承要求；受众与时长等作为参考记录。整个原始 workorder 会塞进 `deck_model.workorder.raw`，方便以后追查。
4. **论文**：在 `pdf|docx|md|txt` 中挑体积超过 1.5 kB、且不是任务说明/README 的第一个文件。
5. **模板**：文件名含 `template`/`master`/`layout`/`style`/`brand` 的 `.pptx` 优先；否则退而取第一个 `.pptx`（起始稿也当模板基座用）。一个 `.pptx` 都没有时，用内置母版、两套版式与主题生成自包含包，并在降级列表里说明。
6. **缺失**：没有论文、图注抽不出、PDF 加密读不了……都变成 `exceptions` 或 `pending_human` 的显式条目。不猜、不补、不编。

## 3. 结果信封长什么样

先按契约回填，再补审计字段。契约里常见的七个键是：`case_id`、`status`、`editable_source`、`export_artifact`、`content_map`、`compliance_checks`、`exceptions`（以实际 case 给出的清单为准，脚本不会硬编码这份顺序）。

各块职责：

- **可编辑源**：记录 pptx 的相对位置、页数、字节数、sha256、装配 engine、带讲稿的页数，以及模板继承四元组（模板路径、母版名、用到哪些版式、是否真继承了）。哈希与字节数让评审能确认交付的就是本次跑出来的文件。
- **导出件**：PDF 的路径、页数、生成 engine、是否通过校验；`valid` 的判据不是"存在"而是"文件头真是 `%PDF-` 且页数与要求一致"。PNG 预览本版本不产出，为 `null`/0，PDF 承担渲染证据的角色。
- **逐页证据图**：deck 每一页一条记录，含页码、标题、角色、一句话主张、要点、证据数组（类型/编号/定位/逐字引文/是否命中）、资源说明与讲稿；另附覆盖率统计。
- **自检块**：页数、模板继承、密度、讲稿覆盖与重复率、图引用、数字白名单、证据覆盖、文件级检查，以及本包新增的两项投影一致性检查（见 §6）。
- **诚实块**：`exceptions`（缺什么）、`degradations`（降级了什么）、`pending_human`（要人确认什么）、`uncertainty`（哪里不确定）、`changes`（相对输入改了什么）、`sources`（材料与抽取来源）、`runtime`（耗时与请求数）、`errors`（运行期异常）。
- **资产摘要块（v1.1.0 新增）**：`golden_standard`、`diff_report`、`version_history`、`run_log`、`self_check` 五个字段，值是产物目录里的相对路径 + 摘要（页数/达标数/字节数/自检 pass 等）。这五个字段属于审计增量，`output_contract` 原有键一个不少、不改名、顺序不动。

字段级的完整字典、引文比对规则和全部阈值集中在 `references/result-contract.md`，实现代码只有 `deckgen.py` 一处，改阈值时两边同步。

状态判定：全部检查通过且没有 exception 才是 `ok`；deck 已生成但有瑕疵是 `partial`；材料在但抽不出可用句子是 `insufficient_evidence`；连论文文件都找不到是 `input_error`。四种状态都写出合法信封、都以 0 退出。

## 4. 流水线：一个模型投影出全部产物

```
扫描输入 → 抽取文本 → 切句/切节/抓图表标题 → 页级骨架
        → 主张 + 要点 + 证据 + 讲稿 → 模板继承的 pptx
        → PDF 预览 → 文件级校验 → content_map → result.json
```

**单一事实来源**：`deck_model.json` 里的 `slides[]` 是唯一模型；`plan.json`、`content_map`、pptx 正文、PDF 文本全部从它投影。这样页面上写的字和证据表里记的引文不可能对不上。要改稿就改模型或改输入后重跑，脚本本身不保存状态。

### 4.1 文本抽取（走了哪条路会写进 `sources.engine`）

按顺序探测：`pdftotext -layout -enc UTF-8` → 标准库解 FlateDecode 流并扫 `Tj/TJ` → DOCX/PPTX 的 OOXML 文本 → Markdown/纯文本直读。按换页符切页，因此 locator 里的页码是真实的。**空抽取不是"论文没内容"**：立刻转 `partial`、写 exception、不生成 deck，避免拿模型记忆替论文说话。

### 4.2 页序跟贡献走，不跟章节走

主线角色：开场标题 → 问题动机 → 本文做法 → 方法细节 → 证据页（每个图/表一页）→ 讨论 → 局限 → 收束结论；页数充足时补致谢页。角色与页数的换算由 `role_sequence(n)` 完成：先给固定角色，剩余槽位全部给证据页；页数不够时按"局限 → 讨论 → 方法 → 做法 → 动机"的顺序舍弃次要角色，保证最后剩下的是「标题 → 问题 → 证据 → 结论」这条最硬的主线。更细的角色预算与逐页规则在 `references/slide-blueprint.md`。

每一页都由四件套组成：

| 组成 | 要求 |
|---|---|
| 主张 | 一句话，取自锚定句的原文片段；允许截断，不允许改写成新事实 |
| 要点 | 最多 5 条，取论文句子前缀，在子句边界处截断，数字与单位原样保留 |
| 证据 | 至少一条，字段含类型/编号/定位/完整原句/是否命中；定位写到页码，图表页写到 `Figure N, p.X` |
| 讲稿 | 1–3 句行动提示：被追问时翻哪条证据、下一页讲什么；不得复述页面文字 |

### 4.3 证据、数字与图表编号怎么被验证

- 引文回到论文文本做比对：先归一化空白，再去标点做指纹比对；`matched` 记录结论，未命中的条目会进入 `compliance_checks.failures`。
- 页面出现的数字与百分号必须能在论文中找到；找不到的记入 `number_whitelist.misses`，不会为了"好看"改写数值。
- 页面提到的图/表编号必须存在于论文的图表标题清单；对不上就记 `figure_refs.mismatch`。
- 因为要点是"截断"而不是"重写"，`12.5%` 不可能在搬运中悄悄变成 `12%` 或 `约 13%`。

### 4.4 模板与起始稿

输入里出现 `.pptx` 时，产物必须**继承**它的母版、版式与主题：构建前后对 `slideMasters`、`slideLayouts`、`theme1.xml` 分别算 SHA-256 对比，结论写进 `template_inheritance`。每页尽量落在版式自带的占位符上（按占位符类型与 idx 匹配），位置、字号、配色由母版定义；模板原有的示例页会被替换掉，替换数量记入 `changes`。没有模板时生成自包含包（母版 + 标题版式 + 内容版式 + 主题 + notesMaster）。

### 4.5 讲稿必须和页面分离

讲稿由定位器驱动，形如「被问到就说：结果在 p.4；下一页讲影响」。脚本会算讲稿与页面文字的 token 重叠率（阈值 0.6），超限直接判不合格——讲稿是提示卡，不是页面文字的复读机。

## 5. 异常与降级怎么做

| 触发条件 | 怎么发现 | 怎么处理 |
|---|---|---|
| 扫描件/加密 PDF、无文本层 | 抽取链为空或有效文本 < 200 字符 | 记 exception，转 `partial`，不生成 deck，不补正文 |
| 文本抽取质量低 | engine 标为纯 Python inflate | 降级记录"图表标题可能不全" |
| 图表标题抓不到 | 标题正则零命中 | `pending_human` 请人工确认清单；页面只引页码/章节 |
| 插图无法随文本导出 | 本版本故意不从 PDF 抠位图 | 页面写图表编号 + 页码；资源栏注明"仅图注+定位" |
| 机器上没有 office 渲染器 | `soffice`/`office-renderer` 都探测失败 | 用标准库从 deck 文本层写一份真实 PDF（`%PDF-` 头、页数一致），标为降级 |
| 输入里没有模板 | 扫描不到 `.pptx` | 内置母版/版式/主题 + 降级记录 |
| 要求页数过小（<3） | 页数预算算不出证据页 | 角色收缩到最小主线，`slide_count.ok=false` 如实上报 |
| 版式没有正文占位符 | 占位符扫描为空 | 安全区内放绝对定位文本框；母版与主题照旧继承 |
| case.json 缺失/损坏 | JSON 解析失败或文件不存在 | 转 `input_error` 或 `partial`，仍写合法信封，退出 0 |
| 五件资产写出失败 | `assetkit` 的单项/整体异常 | 隔离成最小合法文件并记 `degradations`，主产物与契约字段不受影响，退出 0 |

所有分支的共同点：**先落盘 partial，再继续改进**。哪怕后续全崩，`/app/output/result.json` 里也有一份带契约键、带异常说明的半成品可以取证。

## 6. 每次运行都会算的自检

脚本自己算、自己写，不依赖外部工具：

1. **数量与继承**：实际页数 vs 要求页数；主题/母版哈希是否被改过；用到哪些版式。
2. **密度与讲稿**：单页要点数、单条字符数、讲稿覆盖率、讲稿与页面的 token 重叠率。
3. **事实一致性**：引文命中、数字白名单、图表编号匹配。
4. **文件级**：pptx 能否当 zip 打开、必需部件是否齐、XML 能否解析、slide/notes 部件数；PDF 是否 `%PDF-`、页数是否等于要求。
5. **投影一致性（本包新增）**：`content_map_completeness` 逐行断言八键齐全且主张/证据/讲稿非空；`structure_consistency` 重开 pptx 断言 slide 部件数、notes 部件数、content_map 行数、计划页数四者相等且行号连续。
6. **交付后自检回执（v1.1.0 新增）**：收尾时把上述检查连同「契约键完整性 / 五件资产存在且非空 / 导出件真实（PDF `%PDF-`、PNG IHDR）/ 空输入与坏 JSON 兜底探测 / 退出码 0」写成 `self_check.json`（每项带 expected / actual / status），并核对 `golden_standard.json` 页数与 pptx 页数一致。

任何一项失败都会写进 `failures` 并把 `pass` 置为 false；结构审计失败同样会拉低 `pass`。评分维度与检查项的对应关系、提交前清单与已知边界在 `references/rubric-map.md`。

## 7. 最小调用示例（示例，非正式案例结果）

示例 case（仅示意字段形态，不是正式素材）：

```json
{"output_contract": ["status", "case_id", "content_map", "compliance_checks", "editable_source", "export_artifact", "exceptions"],
 "case_id": "sample-case-001",
 "organizer_workorder": {"total_slide_count": 12, "mode": "generate", "template_inheritance": true, "source_preservation": "full"},
 "formal_inputs": {"paper": "paper.md"}}
```

运行：

```bash
python3 scripts/deckgen.py --input ./case --output ./out --work ./work
```

在上述示例材料上观察到的结果（**示例数据，非正式案例结果**）：12 页；pptx 是合法 zip，含 12 个 slide 部件与 12 个 notes 部件；PDF 以 `%PDF-` 开头且 12 页；content_map 12 行、引文全部命中；数字白名单零缺失；两项投影一致性检查通过；`status=ok`。

## 8. 包结构与维护约定

| 路径 | 职责 |
|---|---|
| `SKILL.md` | 本文件：对外契约与做法说明 |
| `scripts/deckgen.py` | 输入发现、句段解析、页级模型、自检、结果信封 |
| `scripts/ooxml_kit.py` | 文本抽取链、pptx 装配（模板手术/内置包）、PDF 预览、文件级校验 |
| `scripts/assetkit.py` | 五件可核验资产：页级金标准、逐页 diff、版本历史、运行日志、机器自检；单件失败隔离 |
| `references/slide-blueprint.md` | 角色阶梯、页数预算、逐页上限、讲稿模式、投影示例 |
| `references/result-contract.md` | 结果信封字段字典、引文判定、阈值、状态判定 |
| `references/rubric-map.md` | 评分维度映射、提交前清单、已知边界 |

## 9. 可核验资产（五件，finalize 时生成到输出目录）

每次运行收尾都会在产物目录写出下列五件资产；它们不改变入口、CLI 与契约键，只把“结果可核验”落成可打开、可复算的文件：

| 资产 | 内容 | 怎么核验 |
|---|---|---|
| `golden_standard.json` | 页级金标准：逐页列期望标题/角色/要点/证据/图表/讲稿与页数预算。每个期望项带 `basis`：`input_quote` 项带论文 locator + 逐字 quote（并记回查结论 `matched`），工作单项带 `case.json` 键路径 + 逐字 JSON 片段，无可引用来源的展示标签明确标 `basis=contract` | 打开 JSON 逐页比对；`coverage.by_basis` 给出来源计数，`coverage.verbatim` 给逐字命中率，`coverage.unmatched` 列出未命中项 |
| `diff_report.md` | 逐页 diff：实际 pptx 每页（运行时重新解压读回文本）vs 金标准（达标/缺失/偏差 + 原因），并单列金标准/计划/pptx slide/notes/content_map/PDF 六者页数一致性检查 | 看 §1 总览与 §2 页数一致性结论；§3 是逐页表，§4 只在有缺口时列明细 |
| `version_history.md` | 静态版本记录 v0 → v1.0.0 → v1.1.0（每版改了什么、为什么）+ 回退方式（整包回滚 / 只关资产 / 只回退本次运行段）+ 末尾“本次运行”段 | 按 §3 回退表操作；§5 记录本次 case、命令、状态与主产物哈希 |
| `run.log` | 真实运行日志：启动参数、逐阶段名称/距上一行耗时/状态（ok/degraded/error）、收尾转写降级与异常、退出码 | 按阶段定位耗时与降级来源；运行中逐行 flush，不是事后补写 |
| `self_check.json` | 机器自检回执（`self_check.v1`）：契约键完整性、pptx 页数/notes 数/content_map 行数/金标准页数一致、导出件真实（PDF `%PDF-` + 页数；PNG 存在时校验 IHDR）、空输入与坏 JSON 兜底探测、退出码 0，逐项 expected/actual/status | 看 `pass`/`passed`/`skipped`/`failed`；`skipped` 表示该场景本次不适用（如无模板、契约不产出 PNG），不是伪造通过 |

使用约定：

1. 五件资产只写产物目录，不写包内、不写全局状态、不联网；每次运行按本次产物重新生成。
2. 资产里不放正式案例答案或预渲染成品：金标准全部来自本次输入材料的逐字抽取，抽不到的项记 `contract` 或进 `pending_human`。
3. `result.json` 的五个摘要字段（`golden_standard`/`diff_report`/`version_history`/`run_log`/`self_check`）是审计增量；原契约键集合与顺序不变。
4. 任何一件资产写出失败都会被隔离成最小合法文件并记入 `degradations`，主产物与退出码不受影响。

版本 1.1.0。修改规则时：先改本文件与 `references/rubric-map.md` 的版本号，再改阈值常量，最后用示例材料重跑一遍确认 `compliance_checks.pass=true`。本包不含任何预制答案、正式案例结果或预渲染成品。
