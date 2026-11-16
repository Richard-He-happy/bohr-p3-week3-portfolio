---
name: mindmap-evidence-forge
description: 把 /input 里的科研材料锻造成一张可继续编辑、可逐条回溯的思维导图。脚本承担材料索引、引文逐字核验、层级与规模体检、树形布局、SVG/位图输出和 output_contract 回填；Agent 承担主题、分支、节点与跨分支关系的判断。产物包括 mindmap.svg（真实 text/tspan，可直接改）、mindmap.json（结构真源 + 布局坐标）、mindmap_preview.png、node_evidence.csv（节点→locator/逐字引文）、coverage_report.md、pending_human.json 与键名完整的 result.json；build 另写 5 件可核验资产（金标准 golden_standard.json、逐项对照 diff_report.md、版本史 version_history.md、真实运行日志 run.log、机器自检 self_check.json）。适用于论文与综述结构梳理、实验方案、项目计划、会议决策、概念体系梳理等「材料→导图」任务。
version: 1.1.0
---

# 材料 → 可核验思维导图（mindmap-evidence-forge）

## 何时启用

触发词：思维导图、脑图、mindmap、知识结构、研究梳理、结构梳理、把材料整理成图、论文脉络、方案路线图。

启用条件（同时满足才用本 Skill）：

1. 输入是**材料**（论文、综述、笔记、方案、纪要、术语表），不是一句凭空命题；
2. 交付物是**结构化图**，需要层级 + 关系 + 可回溯证据；
3. 允许把结论落在可编辑文件上（SVG/JSON），而不是只有一段文字。

不适用：需要 OCR 的纯图片材料（只登记、不臆造）、需要定量统计的图表复现、需要排版成稿的期刊 LaTeX。

核心承诺：**没有 locator + 逐字 quote 的内容不进图**。宁可少一个节点，也不让评审在原文里找不到出处。

## 产出物一览

| 文件 | 角色 | 谁来写 | 复核方式 |
|---|---|---|---|
| `mindmap.svg` | 主产物，可编辑导图 | 脚本 | XML 可解析；每个节点一个 `<g id="node-*">`；文字在 `text/tspan` 内，可直接改字 |
| `mindmap.json` | 结构真源：theme/nodes/edges/layout/stats | 脚本 | 节点数、父子关系、引文、布局坐标都在这 |
| `mindmap_preview.png` | 预览位图 | 脚本 | PNG 魔数正确、非 0 字节；模式写在 `preview_mode` |
| `node_evidence.csv` | 节点→证据台账（一行一条证据） | 脚本 | 逐行把 quote 贴回原文检索 |
| `coverage_report.md` | 覆盖与结构说明（账目式，不写口号） | 脚本 | 与 `audit_report.json` 计数一致 |
| `pending_human.json` | 必须人工确认的清单 | 脚本 | 每条带 kind 与具体问题 |
| `golden_standard.json` | 金标准：每项期望及其出处 | 脚本 | 看 `source.verified` |
| `diff_report.md` | 实际产物 vs 金标准逐项对照（达标/偏差/缺失/待定） | 脚本 | 每行对应金标准一项；非达标项有理由 |
| `version_history.md` | 版本史 v0→v1.0.0→v1.1.0 + 回退方式 + 运行段 | 脚本 | 回退命令可执行；运行段与 `run.log` 对得上 |
| `run.log` | 真实运行日志（跨命令阶段时间线） | 脚本 | 时序可核对；`/app/work` 与 `/app/output` 各一份 |
| `self_check.json` | 机器自检断言（契约/主产物/引文/计数/兜底/退出码/版本） | 脚本 | `summary.pass` 总判，失败项见 `summary.failed` |
| `audit_report.json` | 逐项对照（达标/偏差/缺失/待定）+ 自检 + 探针 | 脚本 | 重跑 build 计数可复现 |
| `result.json` | 平台契约交付 | 脚本 | 契约键一个不少、键名不改 |

工作区（不入交付）：`/app/work/index.json`（材料索引）、`/app/work/mindmap.json`（**Agent 工作稿**）、`/app/work/check.json`；`run.log` 同时写 `/app/work` 与 `/app/output`（交付件，供核对运行时序）。

## 运行环境与四步流水线

只依赖 Python 3 标准库，不联网，不依赖 CWD；路径默认 `/input`、`/app/work`、`/app/output`，可用 `BOHR_INPUT_DIR` / `BOHR_WORK_DIR` / `BOHR_OUTPUT_DIR` 覆盖（探针就是这么跑隔离用例的）。可选外部渲染器按 `rsvg-convert → inkscape → convert → chromium` 顺序探测，全缺席时用内置位图。

```bash
python3 /skills/weekly-skill/scripts/mindmap_cli.py init     # 1 建索引 + 先落 partial result.json
python3 /skills/weekly-skill/scripts/mindmap_cli.py show --material M1 --start 1 --limit 20
                                                             # 2 读原文，抄 locator 与逐字引文
python3 /skills/weekly-skill/scripts/mindmap_cli.py check    # 3 体检（error 必修，warn 视情况）
python3 /skills/weekly-skill/scripts/mindmap_cli.py build    # 4 出图 + 附件 + result.json
```

四步顺序不能颠倒：`init` 一定先写一份合法 `partial` 的 `result.json`，中途被打断也不会交白卷；`build` 幂等，可反复覆盖。

Agent 的活集中在第 2 步：用 `show` 拿到 `[p.3¶2]` 这类 locator，把原文片段**复制**进工作稿，先定中心主题，再定 3–6 个主分支，每个主分支下 2–5 个子节点，最后补跨分支关系。

## 输入识别与降级读取

`init` 递归扫描 `/input`，对每个文件做**扩展名 + 魔数**双识别（`%PDF`、`\x89PNG`、`PK\x03\x04` 后按内部路径判 docx/xlsx/pptx），JSON 按 `utf-8-sig` 读以避开 BOM。`case.json` 先按文件名找，再按内容找；键名按语义匹配（`case_id` / `output_contract` / `task_instruction` / `workorder` 等），不假设固定拼写。

| 格式 | 提取器 | 单元 locator |
|---|---|---|
| PDF | `pdftotext -layout`；无文本层时解压内容流兜底 | `p.3¶2`，兜底时 `stream7`（页码为估计值） |
| DOCX | 读 `word/document.xml` 去标签 | `¶7` |
| Markdown / TXT / TeX / Bib | 按空行切段 | `¶12` |
| JSON | JSON Pointer 遍历 | `json:/results/0/value` |
| CSV / TSV | 逐行 | `row5` |
| 图片 / 图表 | 只登记存在，不臆造内容 | `figure2`（可无 quote，但必须给 locator） |

单份材料解析失败只降级该材料，其余继续；全材料无文本时 `status=insufficient_evidence`，仍输出可打开的骨架图。

## 工作稿字段速查

`/app/work/mindmap.json` 是 Agent 唯一要手写的文件：

```json
{
  "theme": {"label": "材料的中心主题", "evidence": [{"material": "M1", "locator": "p.1¶1", "quote": "原文片段"}]},
  "nodes": [
    {"id": "q1", "label": "研究问题", "parent": "root", "role": "question",
     "summary": "一句话说清该节点主张", "status": "fact",
     "evidence": [{"material": "M1", "locator": "p.1¶2", "quote": "逐字片段"}]}
  ],
  "edges": [
    {"from": "m1", "to": "c1", "type": "support", "label": "支撑",
     "evidence": [{"material": "M1", "locator": "p.4¶3", "quote": "逐字片段"}]}
  ]
}
```

| 字段 | 取值 | 说明 |
|---|---|---|
| `theme.label` | 名词短语 | 中心主题取材料主题，不写「思维导图」「要点整理」这类元词 |
| `parent` | `"root"` 或节点 id | 层级只由 parent 表达，不写 level |
| `role` | question / method / evidence / finding / conclusion / limitation / gap / task / risk / concept / subtopic | 也接受中文（问题/方法/证据/结果/结论/局限/空白/任务/风险/概念/子题） |
| `status` | fact / summary / inference | inference 必须写 `summary` 说明依据，并会进 `pending_human` |
| `edges[].type` | cause / depends / contrast / sequence / cite / support / conflict | 也接受中文：因果/依赖/对比/时间/引用/支持/冲突 |

`build` 会把工作稿翻译成规范模型：补 `level`、`type`（中文别名）、`evidence_ids`、边的 `source`/`target`/`relation`，所以产物里中英字段并存，评审按哪种叫法查都能对上。

## 层级、粒度与规模纪律

- **单一根**、父子链不成环，父节点必须存在；断链的节点被挂回 root 并记入 `dropped_edges`，不静默丢失。
- 3–6 个主分支，每个分支 2–5 个子节点；**节点总数 15–40**，超 40 先合并同级再补证据。
- **深度 ≤ 4**（root 计第 0 层）。再深就说明分类没合并干净。
- 同一父节点下 ≤ 7 个子节点；超限按主题聚类折叠，并在 `coverage_report.md` 第 4 节写明折叠了什么。
- 同级粒度对齐：同一父节点下子节点标签长度差 < 14 字，别把「2 结果与讨论」和「产率从 61% 提升到 73% 说明配体电子效应主导」放成兄弟。脚本会以 `granularity_skew` 告警。
- 标签是名词短语、≤ 20 字；一句话结论放 `summary`。带数字的标签，**标签里的数字必须能在**该节点引文或材料原文中找到，否则触发 `number_untraced`。

## 关系七型：类型、方向、落笔条件

层级用 `parent` 表达，`edges` **只写跨分支关系**。类型是封闭词表，方向写死，写反即正确性失败。

| type | relation | 方向（材料语义） | 何时落笔 |
|---|---|---|---|
| `cause` | 因果 | 因 → 果 | 材料明说 A 导致 / 造成 / 引起 B |
| `depends` | 依赖 | 依赖方 → 被依赖方 | 方法/分析依赖某数据、前序步骤或前提 |
| `contrast` | 对比 | A ↔ B | 两组条件、两种方案或相反结论并列比较 |
| `sequence` | 时间 | 先 → 后 | 步骤、阶段、时间线 |
| `cite` | 引用 | 引用方 → 被引方 | 明确「据 X」「引自 X」 |
| `support` | 支持 | 证据 → 论断 | 某结果支撑某结论或假设 |
| `conflict` | 冲突 | A ↔ B | 两处材料互相矛盾，两边都保留 |

**无证据的关系不画**，只记入 `pending_human.json` 并在 `result.degradations` 说明。关系表同时写进 `golden_standard.json` 的 `relation_semantics`，评审可据此核对每条边。

## 引文与定位口径

- `quote` 必须是从材料复制的**连续片段**，不改写、不拼接、不翻译；建议 10–200 字，短于 6 字会判过短。
- 比对口径：NFKC 归一 → 破折号/引号折叠 → 空白压缩 → 小写；仍不命中则做「去空白去连字符」二次比对。**不要为了让 quote 命中而改原文**，改的是你抄的内容。
- `locator` 必须指到具体单元：`p.3¶2`、`¶7`、`row5`、`json:/x/y`、`slide3`、`figure2`。
- 每个节点至少一条 evidence，含 material + locator + 逐字 quote；命中率写进 `coverage_report.md` 与 `result.json`。
- 引文命中失败的节点会标 `unverified`，进入 `pending_human`，并在 `check` 里算 error。

## 覆盖矩阵：必含对象清单怎么核

`init` 把 `task_instruction` 抄进索引，`build` 会按指令里出现的要求词逐条对账，结果写进 `coverage_report.md` 第 3 节：

| 要求词 | 期望落点 | 判定方式 |
|---|---|---|
| 研究问题 / 研究目标 | `role=question` | 该类节点数 > 0 |
| 方法 / 实验 | `role=method` | 同上 |
| 数据 / 结果 / 发现 | `role=evidence` / `finding` | 同上 |
| 结论 | `role=conclusion` | 同上 |
| 局限 / 不足 | `role=limitation` | 同上 |
| 空白 / 展望 | `role=gap` | 同上 |
| 任务 / 风险 / 待办 | `role=task` / `risk` | 同上 |
| 对比 / 因果 | `edges[].type` | 该类关系数 > 0 |
| 契约字段 | `result.json` 顶层键 | 键存在即 covered |

七类节点（概念、问题、方法、证据、结论、任务、风险）在 `coverage_report.md` 第 2 节单独列表：材料确实没给某一类时写「材料未给」，不要造节点凑数——缺类而造，正是「抓得准」失分的主因。

## result.json：契约回填规则

`output_contract` 的每个键都**原样回填 output_contract 的全部字段，不改名、不漏键**；值按语义槽位映射，映射不到的键用通用交付摘要兜底（`{"note": ..., "artifacts": [...]}`），缺值一律写 `[]`。

| 契约键（正则命中） | 回填内容 |
|---|---|
| `deliverable` / 产物 / 主结果 | 摘要 + `primary`/`structure`/`preview`/`editable` 指针 |
| `evidence_map` / 来源映射 / locator | 节点→(material, locator, quote, verified) 列表 |
| `preserved_facts` / 事实 / 数字 | 同上（事实保留台账） |
| `change_log` / 修改 / 变更 | 本次动作记录 |
| `content_map` / 映射 | 同上（来源映射） |
| `mindmap` / 结构 / 分支 | 主题、节点数、边数、深度、主分支名 |
| `coverage` / 覆盖 / 统计 | 覆盖率、核验引文数、source_mode |
| `preview` / 预览 / png | 预览文件名或 `null` |
| `uncertainty` / 不确定 | 归纳层级、无文本材料等存疑点 |
| `note` / 说明 | 一句交付说明 |

固定字段：`case_id`、`status`（ok / partial / insufficient_evidence / input_error）、`sources`、`uncertainty`、`pending_human`、`errors`、`degradations`、`changes`、`runtime`、`artifacts`、`coverage`。增量字段（只增不改，与契约同名时让位给契约）：`editable_source`、`export_artifact`、`structure_file`、`node_count`、`edge_count`、`evidence_coverage`、`preview_mode`、`golden_standard`、`audit_report`、`self_check`、`node_evidence`、`coverage_report`、`probes`。

## 降级决策矩阵

| 触发情况 | 处置 | 记录位置 | status |
|---|---|---|---|
| `case.json` 缺失 / 坏 JSON | 继续跑，契约退化为空表，主题退化为材料标题 | `errors` / `degradations` | partial / input_error |
| 材料只有图片或无文本层 | PDF 走流解析兜底；仍无文本则该材料登记为空，不臆造 | `uncertainty` | insufficient_evidence |
| 工作稿缺失 / 节点全无效 | 用确定性要点抽取兜底成稿（引文仍是原文片段） | `degradations` + `pending_human` | partial |
| quote 未命中 | 该节点标 `unverified`，进 `pending_human` | `pending_human` / `node_evidence.csv` | partial |
| 关系无证据 / 类型非法 | 不画，进 `dropped_edges` 与 `pending_human` | `degradations` | 不变 |
| 节点规模爆炸（> 40） | 保留但告警，建议合并同级；布局仍不重叠 | `degradations` | partial |
| 无任何 SVG 渲染器 | 用内置几何位图出预览（色块+连线，无字形），`preview_mode=geometry-blocks` | `degradations` | 不变 |
| 位图也失败 | 保留 SVG，`preview_mode=none` | `degradations` | partial |
| 权限不足无法写 `/app/output` | 异常被捕获，尽力写最小 `result.json`，退出码仍 0 | `errors` | input_error |

所有分支的共同底线：**退出码恒 0**，且 `/app/output/result.json` 始终是合法 JSON。

## 五件可核验资产（`build` 写入 `/app/output`）

`build` 除主产物外固定再写 5 件资产；空/坏输入也写（诚实标注缺口），供评审按文件核对而非看自述。

| 资产 | 内容 | 复核方式 |
|---|---|---|
| `golden_standard.json` | 按 `output_contract` + 题面 + 材料锚点的逐项期望：13 条结构规则（节点 15–40、层级 ≤4、分支 3–6、每支 2–5 子节点、七型关系、标签唯一且 ≤20 字、数字可溯、契约完整等，每项带 `source.locator` + 逐字 `quote`）、材料分支锚点、关系方向表、契约字段期望（`case.json#/output_contract/<键>` + 逐字值） | `kind=material` 的 quote 贴回原文逐字命中；`skill_rule` 的 locator 指向包内文档行 |
| `diff_report.md` | 实际产物 vs 金标准逐项对照：每条期望的 达标/偏差/缺失/待定 + 实际 + 偏差说明 + 来源；另含契约回填表、字节表、可复算指标、偏差处置、复跑方法 | 每行对应金标准一项；非达标项有理由与处置 |
| `version_history.md` | 静态版本史 v0→v1.0.0→v1.1.0 + 回退方式（整包/只回退资产/只回退版本号）+ 每次 build 追加运行段 | 回退命令可执行；运行段与 `run.log` 对得上 |
| `run.log` | 真实阶段时间线：init/show/check/build、资产落盘、探针、降级，跨命令追加 | 时序可核对，不含伪造成功记录 |
| `self_check.json` | 20 项机器断言：契约键齐全/值非空/case_id 回显/status 诚实、SVG 可解析含 `<text>`、PNG 魔数、引文逐字命中、CSV/JSON 计数一致、金标准完整、diff 判定合法、5 资产非空、run.log 非空、空/坏输入兜底、退出码恒 0、版本一致、自检自身可回读 | `summary.pass=true` 即全绿，`summary.failed` 列失败断言 |

`result.json` 只增不改：新增 `verifiable_assets` 与 `diff_report`/`version_history`/`run_log`/`self_check` 路径计数，契约键同名时让位契约；最终自检失败时 `status` 从 `ok` 降为 `partial` 并写 `degradations`（不伪造通过）。

## 提交前自检

`build` 自动跑并在 `audit_report.json` 的 `checks[]` 留痕（`summary.pass` 为总判）：

1. 契约键齐、键名未改（C1）；证据覆盖率是否为 100%（C2）；数字是否可溯（C3）。
2. 节点数是否在 15–40（C4）；父子结构是否单根无环、深度 ≤ 4（C5）。
3. SVG 是否可解析、`node-*` 组数是否等于节点数 + 1、每组是否带 `data-quote`（C6）。
4. 节点框是否两两不相交（C7）——布局按「一行一节点、一列一层、列宽取该层最宽标签」推，天然不重叠，这项是兜底断言。
5. JSON 节点数 = CSV 行数 = SVG 组数（C8）；预览是否真 PNG（C9）。
6. 空输入 / 坏 JSON / 极小材料三个真实子进程探针（C10–C12，`--no-probe` 可跳过并标注未探测）。
7. 人工抽查：随机 3 条边的方向是否符合上表；3 条 quote 是否逐字命中；`mindmap.svg` 里改一个字是否生效。
8. 5 件资产是否齐全且非空、`self_check.json.summary.pass` 是否为 true、`diff_report.md` 是否逐项有判定——由 `assets.py` 在 finalize 后复核，失败把 status 降为 partial。

`check` 的 error 必须清零再 build：`theme_missing`、`nodes_empty`、`node_unverified`、`hierarchy_cycle`、`edge_dropped`（端点/类型非法）为 error；`label_long`、`label_dup`、`granularity_skew`、`fanout_wide`、`number_untraced`、`role_missing`、`depth_deep`、`node_many`、`node_few` 为 warn。

## 最小示例（示例，非正式案例结果）

输入 `/input/case.json`（示例）：

```json
{"case_id": "EXAMPLE-NOT-A-TEST-CASE",
 "task_instruction": "把材料整理成思维导图，覆盖研究问题、方法、结果、结论",
 "output_contract": {"deliverable": "可编辑导图", "evidence_map": "节点→来源", "change_log": "变更"}}
```

材料 `/input/paper.md`（示例）含三段：`## Method 使用 30 份样本做对照`、`## Results 产率提升 12%`、`## Conclusion 配体电子效应主导`。

工作稿片段（示例）：

```json
{"theme": {"label": "配体电子效应对催化产率的影响"},
 "nodes": [
   {"id": "m1", "label": "30 份样本对照实验", "parent": "root", "role": "method", "status": "fact",
    "evidence": [{"material": "M1", "locator": "¶2", "quote": "使用 30 份样本做对照"}]},
   {"id": "f1", "label": "产率提升 12%", "parent": "root", "role": "finding", "status": "fact",
    "evidence": [{"material": "M1", "locator": "¶4", "quote": "产率提升 12%"}]},
   {"id": "c1", "label": "配体电子效应主导", "parent": "root", "role": "conclusion", "status": "summary",
    "evidence": [{"material": "M1", "locator": "¶6", "quote": "配体电子效应主导"}]}],
 "edges": [{"from": "m1", "to": "f1", "type": "cause", "evidence": [
   {"material": "M1", "locator": "¶3", "quote": "对照条件下产率提升 12%"}]},
   {"from": "f1", "to": "c1", "type": "support", "evidence": [
   {"material": "M1", "locator": "¶6", "quote": "配体电子效应主导"}]}]}
```

调用：`init` → `show --material M1` → `check` → `build`。示意产物：`mindmap.svg` 三个分支节点 + 两条带箭头的关系线，`node_evidence.csv` 五行，`result.json.status = "partial"`（示例材料过短，节点数不足 15）。**以上为接口示意，不是任何正式案例的结果。**

## 包内文件、依赖与维护

```
SKILL.md                        本文件：触发、契约、流水线、规则、降级、自检
scripts/mindmap_cli.py          入口：init / show / check / build
scripts/mmio.py                 材料读入（扩展名+魔数、pdftotext、docx、json、csv）+ SVG/位图输出
scripts/mmcore.py               词表、工作稿规范化、引文核验、树形布局、契约回填、附件写入
scripts/golden.py               金标准（每项期望带出处）+ 逐项对照 + 要求覆盖对账
scripts/audit.py                结构体检、兜底成稿、自检探针、审计落盘
scripts/assets.py               5 件可核验资产：diff_report / version_history / run.log / self_check + 金标准兜底
references/node-edge-spec.md    schema、词表、定位口径、可复用检查清单
```

- 外部依赖为零：全部能力由 Python 3 标准库实现；可选 `pdftotext`（PDF 文本层）与 `rsvg-convert`/`inkscape`/`convert`/`chromium`（SVG 光栅化）。缺席即降级，不报错。
- 改 schema 要同步三处：`mmcore.build_model`（翻译）、`golden.SPECS`（期望）、`references/node-edge-spec.md`（文档）。
- 引文核验口径只允许收紧，不允许放宽；每次改动后至少跑一次空输入与坏 JSON 用例确认退出码 0。
- 版本：只需改本文件 frontmatter 的 `version` 与 `mmio.SKILL_ID`，两者要一致。

## 版本与变更

| 版本 | 变更 | 兼容性 |
|---|---|---|
| 1.0.0 | 首版：四步流水线、七型关系、逐字引文核验、几何位图回退、审计报告与三个真实探针 | — |
| 1.1.0 | build 额外写 5 件可核验资产（golden_standard / diff_report / version_history / run.log / self_check）；`result.json` 增量 `verifiable_assets` 等字段；SKILL.md 增资产小节。原入口、CLI、路径、退出码、契约字段与 8 件原产物不变 | 向下兼容，只增不改 |

上游若改契约字段名，只需在 `mmcore.CONTRACT_RULES` 增补一条正则，不必改流程；新增节点角色要先加进 `mmcore.ROLE_ZH`，否则会被降级为 `subtopic`。
