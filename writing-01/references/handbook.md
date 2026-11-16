# 手册：字段、定位、模板与复核

本文件是 `SKILL.md` 的附表，写给写 `draft.json` 的 agent 与逐条核对结果的作者。字段名与 `result.json` 完全一致。

## 1. 三种记录

| 记录 | 回答的问题 | 落在哪里 |
|-|-|-|
| 材料记录 | 这份材料是什么、能不能读、有多少可引文字 | `result.json: sources[]` |
| 事实记录 | 这个数值/单位/样本量出自哪句原话 | `preserved_facts[]` + `preserved_facts.json` |
| 论断记录 | 这句话凭什么这么说 | `evidence_map[]` + `evidence_map.json` |

三者用 `source_id`（`M01`…）与 `locator`（`相对路径:L行号`）串起来：`sources` 给编号与路径，另两个数组给编号 + 行号 + 原句，任一事实都能回到磁盘上的一行。

## 2. 草稿字段逐项

| 字段 | 必填 | 说明 |
|-|-|-|
| `title` | 否 | 省略时取 `case.json` 的 `source.title`，再退化到固定占位标题 |
| `sections[]` | 是 | 顺序即稿件顺序；也可写成字符串数组（只当纯段落处理） |
| `sections[].heading` | 是 | 章节名，建议带编号（`3 结果`）；缺失时记为「(未命名章节)」 |
| `sections[].paragraphs[]` | 是 | 段落数组；单个字符串视为无引文段落 |
| `paragraphs[].text` | 是 | 正文。只改表达，不改数值、单位、术语、引用编号 |
| `paragraphs[].quotes[]` | 否 | 该段的证据句；可写成字符串（无定位，靠全材料匹配） |
| `quotes[].quote` | 是 | 逐字原句，≥8 个字符，空白差异被忽略 |
| `quotes[].locator` | 建议 | 已知就填；填错不影响命中判定，但会降低可复核性 |
| `quotes[].source_id` | 建议 | 已知材料编号时填，命中判定会优先查该材料 |

草稿上限 8MB；未知键被忽略。

## 3. `result.json` 字段

### 3.1 契约字段（原样回填）

| 字段 | 类型 | 取值 |
|-|-|-|
| `case_id` | string | 取自 `case.json` 的 `case_id`，缺失时为空串 |
| `deliverable` | string | 主产物文件名；`partial` 阶段为 `null` |
| `preserved_facts` | array | 见 1.1 形状，最多 30 条 |
| `evidence_map` | array | 见 1.2 形状，最多 150 条 |
| `change_log` | array | 每章一条 + 末条 `finalize` |

`output_contract` 是对象时按它的键逐个回填；是数组时额外给出 `output_contract_fields`，并保留原名键。多出来的未知键一律给 `null`，不删。

**1.1 事实条目**（四个键，顺序无关）：`fact_id` + `value_text` + `source_id` + `locator`
`value_text` 是含数字的原句（≤240 字符），不是裸数值：保留整句才看得出单位与上下文。

**1.2 论断条目**（六个键）：`claim_id`、`section`、`quote`、`source_id`、`locator`，以及布尔位 `verified`
`verified` 只有在逐字命中材料时才为 `true`；拒收的句子不进入本数组，只进 `pending_human`。

### 3.2 台账字段

| 字段 | 用途 |
|-|-|
| `status` | 见第 4 节 |
| `sources[]` | 每份材料一条：`id`、`path`、`kind`、`bytes`、`chars`、`readable`、`note`；`kind` 取 text/json/docx/pdf/binary/instruction |
| `uncertainty[]` | 本稿的能力边界：摘录式初稿、未生成材料外内容、PDF 未解析等 |
| `pending_human[]` | 每条给 `item`（材料或章节）、`reason`（为什么）、`action`（作者要做什么） |
| `errors[]` | 输入级问题：`input_dir_missing`、`case_json_missing`、`case_json_unreadable:*` |
| `degradations[]` | 每项是降级代码 + 涉及路径，代码含义见 `SKILL.md` 的降级表 |
| `changes` | 与 `change_log` 同源，便于只读一方 |
| `coverage` | 计数：材料数、可读数、引文通过/拒收、二级标题数、字符数、事实数、`requested_sections`、`covered_sections`、`missing_sections`、`number_audit` |
| `runtime` | 起始时间、耗时、脚本版本、Python 版本、输入/输出根目录 |

## 4. 状态判定

按下列顺序取第一个成立的：

1. `input_error`：材料清单为空且输入目录不存在。
2. `insufficient_evidence`：既没有草稿章节，也没有通过校验的证据句。
3. `ok`：有草稿章节、零拒收、证据 ≥5 条。
4. 其余一律 `partial`（含「只有兜底组装」与「有拒收引文」两种常见情形）。

`partial` 不是失败：稿件可用但边界已知，边界写在 `uncertainty` 与 `pending_human`。

## 5. 章节模板与篇幅

`task_instruction` 点名了章节就只写点名的；没点名时按下面默认集合产出，并在 `coverage` 里逐节标覆盖。

| 章节 | 写什么 | 保守篇幅 |
|-|-|-|
| 摘要 | 对象、方法、关键数值结果、结论；不出现材料外数字 | 120–250 字 |
| 1 引言 | 材料给出的背景与未解决问题；不替作者补研究空白 | 150–300 字 |
| 2 方法 | 样本量、设备、参数、统计方法；与材料步骤一一对应 | 150–400 字 |
| 3 结果 | 数值 + 单位 + 离散度 + 显著性；趋势不等于因果 | ≥2 段 |
| 4 讨论 | 机制解释与局限；区分材料明说的与作者推测的 | ≥2 段 |
| 5 结论 | 只重述有证据支持的结论 | 80–200 字 |
| 参考文献 | 只用材料内出现的条目；缺卷期/DOI 就缺着 | 条数不限 |
| 数据可得性声明 | 材料说明存放位置时照抄；没说明就写「待作者补充」 | 1–3 句 |

篇幅服从指令；无规定时用上表下限，不注水。

## 6. 作者复核清单

- [ ] 打开 `manuscript.md`，每个 `定位：` 行都能在工作区里定位到那一行原文。
- [ ] `preserved_facts.json` 里的每个数字都能在正文中找到同一值（含单位）。
- [ ] `coverage.number_audit.hit_rate` 为 1.0；否则逐条查明未命中数字的来源。
- [ ] `change_log` 的 `use_agent_draft` / `assemble_from_source` 两类动作与稿件章节能对上。
- [ ] `pending_human` 每一项都已处理：补材料、改引文，或确认可以省略。
- [ ] 图表编号与引用格式是否符合目标期刊要求（脚本不判断风格）。

## 7. 常见错误与修法

| 现象 | 原因 | 修法 |
|-|-|-|
| `check` 报 `quotes_rejected` | 引文被改写、翻译或跨句拼接 | 回到 `show` 复制整句 |
| 章节出现在 `missing_required_sections` | 标题写法与关键词不匹配 | 用带编号的标准标题 |
| 稿件出现材料外数值 | 草稿里自行换算或估算 | 删掉，或换成材料原值并注明换算方式 |
| 参考文献少了 DOI | 材料本来没给 | 保留缺项，写进 `pending_human`，不要补造 |

## 8. 五件可核验资产（patch v1.1.0）

`build` 在输出目录写出 5 个文件，供评审逐项复核；字段细节见 `SKILL.md` 的「五件可核验资产」一节。

| 文件 | 关键字段 | 复核方式 |
|-|-|-|
| `golden_standard.json` | `items[]`：`id/group/expected/check/locator/quote/basis/source_file/verbatim_verified/note`；`counts.by_group/by_basis/verbatim`；`expected` 汇总 | 按 `locator` 打开源文件核对 `quote`；`basis=contract` 项看 `note` 的推导依据 |
| `diff_report.md` | 每行：金标准项 / 实际 / 判定（pass/missing/deviation/record）/ 原因；「关键一致性数字」表 | 先看 `missing` 与 `deviation` 清单；`record` 为人工语义项 |
| `version_history.md` | 静态版本表 + 回退方式 + 「本次运行（runtime append）」段 | 对照 `run.log` 与 `result.json.runtime` 是否一致 |
| `run.log` | 每行 `[累计耗时] [+阶段耗时] [阶段] 说明 kv`；末行 `[exit] exit_code=0 status=...` | 检查阶段是否完整、哪一步降级 |
| `self_check.json` | `checks[]`：`id/claim/expected/actual/ok/evidence`；`pass/passed/total/skipped`；`probes`；`exit_code_assertion` | 任一 `ok=false` 需修复；`ok=null` 为环境不允许的 skipped 检查 |

机器判据速查：

- **S1** 契约键齐全（`output_contract` 键 + 五常驻字段）；**S2** 主产物存在可评；
- **S3** 引文逐字命中率与 `number_audit.hit_rate`；**S4** `facts/evidence/sections/materials/changes` 计数自洽；
- **S5** 五资产字节 > 0；**S6/S7** 空输入、坏 JSON 子进程实测 exit 0 且 5 资产非空；
- **S8** 同一输入两次运行结构一致（幂等）；**S9** `status` 与错误/拒收/证据数逻辑一致；
- **S10** 5 个资产摘要已回填 `result.json`；**S11** 退出码断言（主流程与子进程均 0）。

`CHAPTER_ASSET_PROBE=0` 只跳过 S6/S7/S8 子进程实测（记 skipped），其余照常。
