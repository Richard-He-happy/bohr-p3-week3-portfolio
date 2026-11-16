---
name: grant-seven-part-drafter
description: 面向基金申请类写作的章节起草 Skill。拿一篇公开论文或一叠零散材料，再配组织方给出的写作要求，产出七个要素的中文章节稿（背景、问题、目标、内容、创新、路线、基础），并附要素对照、论断溯源映射、目标×工作包×里程碑×指标矩阵、非货币规划单位分项、风险与备选、人工确认项、已完成与拟开展边界。适合标书、申报书、立项依据、技术路线、proposal 一类请求；按 organizer_workorder 逐项执行，成果归属归还原作者，材料缺口显式留白。
tags: [proposal-drafting, workorder-compliance, provenance-map, deterministic-audit]
license: MIT
version: 1.0.0
---

# 七要素申请书章节起草器

## 定位

它把"源材料 + 写作要求"加工成能直接进申请书的七要素章节稿，并配套交付可复核的旁证文件。
四类常见翻车是它主要防的对象：意义写成口号串、创新点靠不可核验的溢美之词、目标与路线数量对不上、
把别人的已发表结果说成申请人自己的前期基础。

有一件事它做不到，也不假装能做到：真实前期成果、平台条件证明、资助机构指南这三类信息材料没给，
就不许补——全部转成待办项交给人工确认。

它还有一道别的写作工具一般没有的自检：把目标矩阵与规划单位分项交叉比对，要求两边 G 编号能 join，
同时检查边界表是否存在、正文里有没有"设备已具备""已获伦理/资助"这类没有证据支撑的既成事实表述。
这三项结果会写进 `checks.metrics`（`matrix_units_joined`、`boundary_present`、`unbacked_claims`），
供第三方一眼复核。

## 什么时候调用

题面或指令里出现下列任一线索：基金申请、标书、申报书、立项依据、关键科学问题、研究目标、技术路线、
工作包、考核指标、proposal、grant；或输入 JSON 里能见到 organizer_workorder 之类带七节结构的对象。

反过来，期刊投稿正文、纯翻译润色、真实经费预算表的编制，都不归它管（本 Skill 只用非货币规划单位）。

## 运行契约

输入来自三个地方：案例描述文件、任务说明文件，以及输入目录树里的文本、Markdown、JSON、CSV、DOCX、PDF 材料。
中间过程放 `/app/work`，交付物放 `/app/output`。主稿是 `/app/output/proposal.md`（七节中文正文，约 1600–2600 汉字），
结构化结果是 `/app/output/result.json`——输出契约里的键名一个不动地回填，`case_id` 照抄。
只用 Python 标准库，不联网，不假定当前目录（脚本按自身位置找资源）。进程退出码恒为 0，内部故障写进 `errors`。

## 三个步骤

```bash
python3 -B scripts/proposal_cli.py init --output /app/output --input /input
# 中间用编辑工具写 proposal.md 和各类附属产物
python3 -B scripts/proposal_cli.py finalize --output /app/output --input /input
```

第一步结束盘上就有合法 JSON（`status` 为 partial），后面即使中断也不至于交白卷。
第二步的写作规则见后文"素材识别""写作工序""七节要求"。
第三步做四件事：把事实句回填成溯源记录、复算规划单位、核验引文定位、跑全量审计并覆盖 `result.json`。
两次收尾都会顺带写出五份可核验资产（下一节），不需要额外命令。

想只看审计结论，不动稿件：`python3 -B scripts/audit_kit.py --output /app/output`，
要求 critical 与 major 都为零。

## 素材识别

案例文件是首选；读不出来就递归搜同名前缀的 JSON，最后用任务说明兜底。case_id 与输出契约原样带走。
写作要求不靠固定键名认，而看结构：一个字典只要同时有 sections 和 draft_size（或 planning_months、consistency）
就算命中；命中后马上另存成 `output/workorder.json`，再动手写。
判断材料能否解析，看后缀也看内容；元信息类文件（任务说明、案例描述、契约文档）不作事实来源。
材料没提到的对象坚决不写——题面标签写着增材制造，而材料里没有碳捕集内容，正文就绝不出现碳捕集。

## 写作工序

第一步抽事实：打开 `quote_bank.md`，里面是带 locator 的候选逐字引文，不够就回原文找，不许编。
第二步对表：把 workorder 的七类字段（sections、draft_size、planning_months、planning_unit_cap、consistency、
required_supporting_files、scientific_limits）各自对应到 result 的一个回执位。
第三步定计划：三个目标 G1–G3 先立住，再配三个工作包 WP1–WP3、里程碑月份与可检验指标；顺序反了必然"目标三个、路线两条"。
计划定了再按分节要求写正文，事实句直接取 `quote_bank.md` 原文。
写完跑 finalize，按 critical / major / minor 逐条修；每段再用"凭什么这么写、编号对得上吗、会被读成承诺吗"
三问过一遍，最后归档确认回执齐全。

## 七节要求

**立项依据**（约 420 字）：先落 1–2 条带条件与数值的逐字事实，再把边界外的空缺写成可观测差距，
最后交代此刻为何做、为何这条路推得动。政策口号堆叠与"具有重要意义"式空转是硬伤。

**科学问题**（约 260 字）：一个主问题加两三个可分解子问题；子问题必须写清对象、条件、可观测指标，
用"是否 / 在何种条件下"提问；数量与目标数一致，别出现问题比方法大的情况。

**研究目标**（约 220 字）：G1/G2/G3 各一句，包含做什么、量化口径、评估方式、时间点；
末尾声明"属于未来评估计划"，不能写成保证兑现的新结果。

**研究内容**（约 380 字）：WP1–WP3 与三个目标一一对应，每个写输入、方法、输出、依赖；
工作包不多于目标，别只堆方法名。

**创新点**（约 260 字）：三条，每条三句——跟哪项具体已有工作不同（要点名）、难在哪、凭什么做得成。
"首次/国际领先/填补空白/重大突破"这类词没有同句来源就删。

**技术路线**（约 320 字）：分三阶段（M1–M4、M5–M8、M9–M12），逐段写输入、方法、输出、关键节点；
风险与备选指向 `risks.md` 的编号，时间不得越过周期上限。

**研究基础与可行性**（约 260 字）：能力（会做什么）—证据（论文结果标外部作者；申请人自有成果标"未提供，待补"）
—关系（这些能力支撑哪几个工作包）。没有证据就写"拟依托（待补 PH3）"，绝不写"设备已具备"。

另外，立项依据里的空缺、科学问题、G1–G3、WP1–WP3、里程碑、指标必须能用同一套编号互相指认。

## workorder 逐项回执

七节写完要逐节对照该节 minimum 自检，回执是 `sections_satisfied`；正文字数落区间看
`char_count` 与 `char_count_in_range`；所有时间标记的上限看 `max_month_found`；
规划单位合计与是否越界看 `planning_units_total`、`planning_units_in_cap`；
三个目标与矩阵行数看 `goals_count`、`matrix_rows`；附属产物齐备度看 `supporting_files` 与`supporting_files_missing`；归属、越界、虚构三项扫描结果在 `limits_checks`；authority 只当写作要求，
回执 `authority_honored`。契约键有没有漏填，看 `contract_keys_missing`（正常是空数组）。

缺 workorder 时按默认值执行：七节、12 个月、100 单位；此时降级清单里必须出现
`workorder_absent_defaults_applied` 这一项，且正文仍要满足七节最低要求。

## 可核验资产（v1.0.0 增补）

`init` 与 `finalize` 收尾时，脚本还会往输出目录写五份旁证。这层不改任何原有命令、参数、路径与退出码；
即使资产层自身出问题，主流程仍按原样返回 0，原有产物与 `result.json` 的原字段都不受影响。

1. `golden_standard.json`——金标准。只从输入的 `output_contract` 和 `organizer_workorder` 导出期望条目
   （契约键、七节、篇幅区间、周期、三个目标、里程碑、风险条数、人工确认、规划单位、附属产物、科研边界），
   每条都带来源文件、JSON-pointer 形式的 locator 与逐字引文；输入里没有的项标 `builtin_default`，
   不伪造引文。正常案例约 30 条上下。
2. `diff_report.md`——把金标准逐条对到本次实际产物，判 met / deviation / missing 并写实际值与原因。
   金标准不因实际产物反向修改，所以报告能如实指出"还没写"，不会恒真通过；`init` 阶段偏差多、`finalize` 后应收敛。
3. `version_history.md`——上半部分静态记录 v0→v1.0.0 的改动、动机与三条回退路径（整包 / 单资产 / 运行期），
   下半部分按运行追加运行段；每次 `init`、`finalize` 各留一段，只追加不改写历史。
4. `run.log`——真实运行日志：每行含 UTC 时间、相对进程启动的耗时、阶段名与关键计数，尾部 `[SUMMARY]`
   记 status、五资产数量、diff 计数、自检通过数与 `exit_code=0`。
5. `self_check.json`——机器自检回执：契约键完整性、主产物存在性、金标准引文逐字命中率、计数重算一致性、
   空/坏输入降级探针、partial 先落盘、退出码零策略、资产齐备、禁用词与货币泄漏、金标准 locator 覆盖。
   `init` 阶段主产物与字数属 soft 项（骨架待写），到 `finalize` 阶段才转 hard。

`result.json` 只追加 `golden_standard` / `diff_report` / `version_history` / `run_log` / `self_check`
五个汇总键，原有契约字段一个不少。想回退到没有资产层的旧形态：删掉输出目录里这五个文件、删掉这五个键即可；
包内 `scripts/evidence_assets.py` 缺失时，主流程以 `EA=None` 降级运行，其余行为不变。

## 硬约束

- 目标恰好三个，编号 G1/G2/G3，每个都能在 `goal_matrix.md` 里 join 上工作包、里程碑、指标。
- 时间标记全部 ≤ 12 个月，三阶段区间不重叠。
- `planning_units.json` 的分项之和等于 total 且 ≤ 100；`unit_meaning` 必须写明非货币、非已获资金、非真实预算。
  正文出现"申请 100 万元"之类表述会被判 critical 的货币泄漏。
- 风险至少三条，每条都有触发信号与备选方案，并挂到某一阶段。
- 人工确认至少两条，必须覆盖真实申请人证据与真实资助要求。
- `draft_boundary.md` 用双栏把已完成（外部作者）与拟开展分开，缺它会记 minor。

## 表述纪律

论文结果统一以"已有研究显示（作者, 年）…"出现，并标注外部作者已完成；禁止写成"申请人已完成""本课题组已发表"。
拟开展的内容一律带"拟 / 计划 / 将 / 预计"。不虚构年份、试验结果、样本量、显著性、设备状态、伦理审批、
政策口径或经费额度。禁用修饰词清单：首次、填补空白、国际领先、重大突破、世界首创、国内外首创、
尚无先例、开创性突破、领跑全球——要用就在同句给出可核验 locator。

## 溯源写法

`evidence_map.json` 每条记 论断编号、所属章节、论断、类型（fact/plan/policy/method）、来源编号、locator、
逐字引文、verified。locator 形态：文本 L12-L40、PDF pdf-stream-N、DOCX para-N、JSON Pointer、CSV row-N。
引文要在源材料里定位得到（脚本做去空白与全半角归一后比对）；定位失败就 verified=false 并进 pending_human，
不许改原文凑通过。`preserved_facts.json` 保存数字、单位、条件、术语与作者归属，逐条带 locator。
`change_log.json` 记原句、改后句、原因、locator、归属，论文结果转成申请语态时必须标外部作者。

## 出问题怎么办

案例描述缺失或 JSON 坏掉，就递归翻材料继续出稿，同时在 `errors` 记一条、`degradations` 写
case_json_unreadable。材料只有摘要时，正文只写摘要里看得见的事实，其余留待补。PDF 抽不出文本层，
就让 Agent 自己读一遍再把引文标成未核验。标签与材料打架，以材料为准并在边界表与 uncertainty 说明。
材料过长，只索引前若干单元、数值句优先。字数不够下限，如实标 partial 而不是注水。
规划单位越界，finalize 会按比例缩放并留一条 change 记录。忘了写正文就 finalize，会把骨架复制成保底稿。
异常路径的结论是同一条：盘上永远留着一份说得清当前的 partial 结果。

## 交付前自检

七节齐全且有实质正文、字数在区间内；编号链（目标→工作包→里程碑→指标）逐环对得上；
时间与规划单位在上限内且可复算；风险数、人工确认数达标；禁用修饰要么删掉要么有来源；
计划句全部带限定词、论文结果全部标外部作者；契约键齐全、case_id 原样、异常记录不遮掩。
最后再跑一次 `audit_kit.py`，critical 与 major 归零即可提交。
再核一遍输出目录：五份可核验资产（金标准 / 差异报告 / 版本史 / 运行日志 / 自检回执）都存在且非空，
`result.json` 里对应五个汇总键齐全；`self_check.json` 的 hard 项应全为 true，soft 项按阶段接受。

另外两条工程约束值得单独提：一是运行产物（含二进制预览）与 JSON 是否合法是两件独立的事，
稿件坏了不要让 JSON 也一起坏；二是所有判断都基于盘上的真实文件，而不是对"材料应该写了什么"的假设——
遇到不确定就写进 uncertainty，而不是替材料补一个听起来合理的答案。

## 调用示例（示例，非正式案例结果）

```bash
python3 -B scripts/proposal_cli.py init --output ./demo_out --input ./demo_input
python3 -B scripts/proposal_cli.py finalize --output ./demo_out --input ./demo_input
```

示意结果（字段形态，不代表真实分数）："status": "ok"、"deliverable.char_count": 1836、
"workorder_execution.goals_count": 3、"planning_units_total": 93、"risks_count": 4、
"pending_human_count": 3。

## 文件构成

`SKILL.md` 是本说明；`scripts/proposal_cli.py` 管 init/finalize/all 主流程（`--help` 可用）；
`scripts/audit_kit.py` 管材料抽取、引文定位与全套审计；`scripts/evidence_assets.py` 是 v1.0.0 新增的
可核验资产层（金标准 / 差异报告 / 版本史 / 运行日志 / 自检回执），由主流程调用、不是新入口；
`references/workorder-runbook.md` 是字段执行手册；
`references/audit-rubric.md` 存复核口径与运行时模板（`<!--BEGIN:…-->` 块）；`references/usage-examples.md` 是示例。
版本 1.0.0。维护原则：新判据先写进 references，脚本只做确定性校验；改判据时同步脚本常量与复核口径文件。
