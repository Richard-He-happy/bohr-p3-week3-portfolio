# workorder 执行手册

开篇先定性：organizer_workorder 是评测方给出的写作要求，其 authority 一栏标明
organizer-workorder-not-funder-policy，含义是它并非真实资助机构的通知、政策或承诺。
行文时不要援引它当政策依据，也不要从它推出任何经费额度。

## 一、字段怎么落地

`id` 与 `version`：原样存进 `output/workorder.json` 留痕，回执写 `workorder_id`。

`authority`：作为口径约束，全文只当写作要求；回执 `authority_honored=true`。

`purpose` 与 `actual_topic`：影响"研究意义"的写法，别写"响应国家政策"；若标签与实际材料不符，以材料为准，
冲突记进 `degradations` 或 `uncertainty`。

`source_basis`：`published_paper` 进 `sources[]`；`external_authors` 要求每个既有结果句末尾标外部作者
（回执 `external_author_marked`）；凡是 `*_supplied=false` 的项，都要变成 `pending_human` 里的一条缺口。

`sections[]`：七节逐节写实质正文，逐节对照该节 `minimum` 自检；回执 `sections_satisfied`。

`draft_size`：汉字数落进区间，不足就如实标 partial 而不是注水；回执 `char_count` 与 `char_count_in_range`。

`planning_months`：所有时间标记都要 ≤ 上限，回执 `max_month_found`。

`planning_unit_cap` 与 `planning_unit_meaning`：分项之和等于 total 且不超上限，全文禁止货币化表述；
回执 `planning_units_total`、`planning_units_in_cap`、`currency_free`。

`consistency`：三个目标各自挂到工作包、里程碑与指标；回执 `goals_count`、`matrix_rows`。

`required_supporting_files`：六类附属产物齐备；回执 `supporting_files` 与 `supporting_files_missing`。

`scientific_limits`：归属、越界、虚构三类逐条不得违反；回执 `limits_checks` 与 `checks.issues`。

## 二、七节各自的写法要点

**立项依据**：先引一两条带条件的逐字事实，形如"在 X 条件下取得 Y"，再把边界外的空缺写成可观测差距，
最后说清此刻为何要做以及与拟用路径的关系。不要堆政策口号。

**科学问题**：一个主问题配两三个子问题；子问题必须写清对象、条件、可观测指标，问法用"是否 / 在何种条件下"。
子问题数量与目标数量一致。

**研究目标**：G1/G2/G3 各一句，包含做什么、量化口径、评估方式、时间点；收尾声明属于未来评估计划。

**研究内容**：WP1/WP2/WP3 与三个目标一一对应，各自写输入、方法、输出、依赖；工作包不多于目标。

**创新点**：三条，每条说清与哪项具体工作不同（点名）、难在哪、凭什么可行；可行性要么来自源材料方法，
要么来自计划依据。

**技术路线**：三阶段划分建议按 M1 到 M4、M5 到 M8、M9 到 M12 排布，逐段写输入、方法、输出、关键节点；
风险与备选引到 `risks.md` 编号。

**研究基础与可行性**：能力（会做什么）、证据（论文结果标外部作者；申请人自有成果标"未提供，待补"）、
关系（能力怎么支撑 WP1–WP3）。

## 三、变体处置

没有 workorder：按默认七节、12 个月、100 单位执行，并记 `workorder_absent_defaults_applied`。
只给摘要：正文只用摘要里能看见的事实，其余标待补。
标签与材料矛盾：以材料为准，在边界表和 `uncertainty` 里说明。
材料过长：只索引前若干单元，数值句优先，记 `input_truncated`。

## 四、执行顺序

先 `init` 落下 partial 结果与骨架、引文库、模板；再由 Agent 写正文与附属产物（事实句从 `quote_bank.md` 取）；
然后 `finalize` 做归属回填、单位复算、引文核验与审计；最后 `audit_kit.py --output <目录>` 复核，
critical 与 major 都归零才算完成。
