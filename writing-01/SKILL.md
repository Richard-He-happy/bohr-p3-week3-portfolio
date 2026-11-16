---
name: manuscript-evidence-drafting
description: 把 /input 里的 case.json 与科研材料（md/txt/json/docx）变成一份可直接改的学术章节稿，并给每条事实句留下 `文件:L行号` 的证据定位。用于撰写或续写摘要、引言、方法、结果、讨论、结论、参考文献与数据可得性声明，也用于核对已有稿件中的数字与引用是否逐字来自材料。缺材料、材料冲突、引用对不上时只标注、不补造。
version: 1.1.0
---

# 学术章节稿：材料锚定 + 逐句可回溯

它解决一个具体问题：**让稿里的每个数字、单位、样本量和引用都能指回材料原句**，而不是凭印象补全。它不评风格，只保证「写得实、引得对、全得起来、改得动」有可核对痕迹。

## 什么时候该用

- 案例给的是 `case.json` + 分节材料（正文片段、数据表说明、图注、参考文献条目），要求产出章节稿或补写/改写指定章节。
- 需要一份「作者能直接接手修改」的 Markdown 稿：标题层级、图注编号、引用格式都在，且每条事实句后面跟得出来源定位。
- 需要交付可复核的结构化结果：契约字段 + 证据映射 + 改动记录 + 待人工确认清单。

不适用：无任何材料、只要写作建议或提纲、需检索新文献（本包不联网）、需对 PDF 图像做 OCR（只登记文件名）。

## 三条底线

1. **证据逐字**：进入 `evidence_map` 的引文必须在材料里逐字出现（只忽略空白差异）。对不上就拒收，写进 `pending_human`，绝不改材料去凑。
2. **不新增材料外事实**：数值、单位、样本量、显著性、图注、作者、期刊、DOI 一律沿用材料原样；材料只给作者和年份时，不补 DOI 与卷期。
3. **退出码恒为 0**：任何输入异常都降级成 `errors`/`degradations` 记录 + 一份可读的 `result.json`，不抛异常给调用方。

## 运行面

| 项目 | 约定 |
|-|-|
| 输入 | `/input`：`case.json`（含 `case_id`、`task_instruction`、`output_contract`）+ 材料文件 |
| 工作目录 | `/app/work`：放 agent 草稿 `draft.json`，`check` 的结论写 `check.json` |
| 产物目录 | `/app/output`：`manuscript.md`、`result.json`、审计文件与 5 件可核验资产 |
| 入口 | `scripts/chapter_builder.py`（五资产的写出在 `scripts/assets.py`，差异/自检在 `scripts/audit.py`），只依赖标准库，不读网络，不依赖当前目录 |
| 子命令 | `init` / `show` / `check` / `build`，全部支持 `--input/--output/--work/--draft` |

目录可用环境变量 `SKILL_INPUT` / `SKILL_OUTPUT` / `SKILL_WORK` 覆盖；都没有时才落到上表的默认值。

**解释器必须是 `python3`。** 本包按 Python 3.8+ 编写；评测镜像以 `python3` 为准，`python` / `py` 不保证存在。
下面的命令一律写 `python3`，请不要替换成裸 `python`。

## 四步走

| 步骤 | 命令 | 你得到什么 |
|-|-|-|
| 1 清点 | `init` | 材料清单：编号、类型、字节、可读性；同时打印句子数与降级项 |
| 2 取句 | `show` | 25 条带定位符的候选原句，用来挑真正支撑论断的句子 |
| 3 自检 | `check` | 草稿里有多少引文逐字命中、哪些章节还没写、哪些引文被拒收 |
| 4 成稿 | `build` | `manuscript.md` + 完整 `result.json` + 四份审计文件 |

```bash
SKILL=/skills/weekly-skill
ENV="--input /input --output /app/output --work /app/work"
python3 -B "$SKILL/scripts/chapter_builder.py" init  $ENV   # 材料清单
python3 -B "$SKILL/scripts/chapter_builder.py" show  $ENV   # 带定位的候选句
# 读材料 → 写 /app/work/draft.json（格式见下一节）
python3 -B "$SKILL/scripts/chapter_builder.py" check $ENV   # 引文与缺章节自检
python3 -B "$SKILL/scripts/chapter_builder.py" build $ENV   # 成稿 + result.json + 5 资产
```

推荐用上面的**绝对路径**（`/skills/weekly-skill/scripts/...`）调用：评测 Harness 把包安装在固定目录，
而进程的工作目录不保证是包根。若 shell 不保留变量，等价写法是：

```bash
python3 -B /skills/weekly-skill/scripts/chapter_builder.py build \
  --input /input --output /app/output --work /app/work
```

**相对路径回退**（仅本地调试用）：先 `cd` 到包根，再用 `python3 -B scripts/chapter_builder.py ...`；
脚本本身用 `Path(__file__).resolve().parent` 定位模块，所以只要解释器找得到脚本，从任何 CWD 调用都能跑。

`init → show → check → build` 四次调用即可闭合，正常耗时为秒级；预算紧张时也可以跳过 `check`，直接 `build`，代价是拒收的引文只能从结果里事后发现。

## 五件可核验资产（build/finalize 写出到 `/app/output/`）

`build` 除了主产物与 `result.json`，还会在输出目录写出下面 5 个文件，用来让评审**不看自述也能逐项复核**。
它们都是运行时产物（不占包体），任何输入（含空目录、坏 JSON）都会写出最小版本，保证不会 0 产物。

| 文件 | 内容 | 评审怎么用 |
|-|-|-|
| `golden_standard.json` | 按 `output_contract` / 题面逐项列期望交付：契约字段、章节、任务约束、材料事实、引用/图注条目、task.md 要求、交付物、行为与边界；每项带 `locator` + 逐字 `quote`，无来源的项标 `basis: contract` 并在 `note` 写推导依据；含 `counts.verbatim` 命中率与 `expected` 汇总 | 抽任意 `locator` 打开源文件核对 `quote` 是否逐字；`basis=contract` 项按 `check` 字段核产物 |
| `diff_report.md` | 实际产物 vs 金标准逐项对照表：`pass / missing / deviation / record` 四类判定 + 原因；另有「关键一致性数字」与三张清单 | 先看汇总计数，再抽查 `missing/deviation` 行；`record` 行是明确留给人工的语义项，不冒充通过 |
| `version_history.md` | 静态版本记录（v0 → v1.0.0 → 本 patch v1.1.0）+ 回退方式与回退验证命令；末尾「本次运行（runtime append）」写命令、输入输出、case_id、状态、耗时、主产物 sha256、资产字节 | 判断包版本与回退方法；复跑时看运行段是否与 `run.log` 对得上 |
| `run.log` | 本次 `build` 的真实阶段日志：每阶段带累计/增量耗时，附降级、异常、末行 `[exit] exit_code=0 status=...` | 核查流程是否真的执行、哪一步耗时/降级 |
| `self_check.json` | 机器断言 S1–S11：契约键、主产物、引文逐字命中率、计数自洽、5 资产、空/坏输入子进程实测、确定性、状态诚实、摘要回填、退出码；`pass/passed/total/skipped` 汇总 | 任一 `ok=false` 即需修复；`ok=null` 表示环境不允许该检查（如禁止子进程），如实记 skipped |

`result.json` 会**只增不改**地追加 5 个摘要对象（`golden_standard` / `diff_report` / `version_history` /
`run_log` / `self_check`，含 `path`、`bytes` 与关键计数）；原有契约字段一个不少。

环境开关（可选）：`CHAPTER_ASSET_PROBE=0` 只关闭 `self_check` 里的空/坏输入子进程实测（记 `skipped`，
不影响其余资产与主流程），用于禁止 `subprocess` 的受限环境。默认开启。

## 写草稿：agent 的主路径

决定稿件质量的是你写的 `draft.json`，脚本只做两件事：**校验引文**、**补齐未写的章节标题**。

```json
{
  "title": "可省略，省略时取 case.source.title",
  "sections": [
    {
      "heading": "3 结果",
      "paragraphs": [
        {
          "text": "按材料改写后的正文句，数值与单位沿用原文。",
          "quotes": [
            {"quote": "材料里的原句，逐字复制", "locator": "results.md:L42", "source_id": "M01"}
          ]
        }
      ]
    }
  ]
}
```

要求与常见错误：

- `heading` 用 `task_instruction` 里点名的章节名（包括编号形式，如「3 结果」）；脚本按关键词匹配，写成「3 结果」和「结果」都能识别。
- `quotes` 允许省略（纯叙述句不需要引文），但没有引文的段落不会进入 `evidence_map`，也就失去可回溯性。
- `quote` 必须逐字，标点、数字、单位都不能改；跨行复制时脚本会忽略空白差异，但不会忽略标点差异。
- 一段话里出现材料没给过的数字（例如自己算的百分比），`build` 的 `coverage.number_audit` 会把它标出来，请在正文里删掉或改成材料原值。
- 只写材料支持的句子。材料没覆盖的章节，留空比编造好：`build` 会保留标题、写明缺口。

## `result.json` 里必须有的东西

`output_contract` 的每个键都原样回填（键名不改、未知键不删、缺值给 `null` 或 `[]`），核心五字段固定存在：

| 字段 | 内容 |
|-|-|
| `case_id` | 原样取自 case.json |
| `deliverable` | 主产物文件名，默认 `manuscript.md` |
| `preserved_facts` | 含数字的材料原句：`fact_id/value_text/source_id/locator` |
| `evidence_map` | 论断级映射：`claim_id/section/quote/source_id/locator/verified` |
| `change_log` | 每章一条改动记录 + 末条 `finalize` |

另附台账字段（顺序无关）：`runtime`、`coverage`、`changes`、`degradations`、`errors`、`pending_human`、`uncertainty`、`sources`，外加状态位 `status`（`ok`/`partial`/`insufficient_evidence`/`input_error`）。逐字段说明见 `references/handbook.md`。

patch v1.1.0 之后再**只增不改**地追加 5 个资产摘要对象（原契约字段一个不少）：

| 字段 | 内容 |
|-|-|
| `golden_standard` | `{path, bytes, schema, items, by_basis, verbatim{graded,hit,ratio}, case_id}` |
| `diff_report` | `{path, bytes, total, pass, missing, deviation, record}` |
| `version_history` | `{path, bytes, current_version}` |
| `run_log` | `{path, bytes}` |
| `self_check` | `{path, bytes, schema, pass, passed, total, skipped}` |

## 证据怎么定位、怎么复核

- 定位符格式固定为 `相对路径:L行号`，路径相对 `/input`；docx 取解包后的文本行，JSON 材料取展平后的行。跨行拆句可能偏 ±1 行，复核时以引文内容为准。
- 复核方式是「引文是否逐字出现在某个可读材料里」，空白差异被忽略，最短 8 个字符。命中记 `verified: true` 并归到具体材料编号。
- `coverage.number_audit` 是第二道闸：把正文与引文里的数字逐个拿去证据链里找，给出 `numbers_supported / numbers_in_draft` 与命中率。命中率低于 1.0 就说明有数字没有来源。

## 缺材料、冲突与人工确认

下列情形一律写进 `pending_human`，并在稿件末尾的「附录 缺口与待确认」里列出：

- PDF 未解析、图像/表格二进制未读取、docx 缺正文部件；
- 引文在材料里找不到（拒收，附带原 `locator`）；
- `task_instruction` 点名的章节在稿件里没有对应标题；
- 材料内部数值矛盾、图注与正文不一致（脚本只记录，不改数字，具体判断留给作者）。

每条记录是 `{item, reason, action}`：`item` 指向具体材料或章节，`action` 写清作者要做什么。不要把「待确认」改写成结论。

## 最小调用示例（示例，非正式案例结果）

```bash
$ python3 -B scripts/chapter_builder.py build --input ./smoke/input --output ./smoke/out --work ./smoke/work
built ./smoke/out/manuscript.md | status=ok | sections=8 / evidence=6 / h2=9 / chars=978
```

产物目录会同时出现：`manuscript.md`、`result.json`、`evidence_map.json`、`preserved_facts.json`、`change_log.json`、`pending_human.json`、`consistency_report.md`，以及 5 件可核验资产 `golden_standard.json`、`diff_report.md`、`version_history.md`、`run.log`、`self_check.json`。以上数字来自本地示例输入，不是任何正式案例的分数或结果。

## 交付前自检

1. `python3 -B /skills/weekly-skill/scripts/chapter_builder.py --help` 退出码 0，帮助文本里能看到四个子命令与「5 件可核验资产」说明。
2. `/app/output/result.json` 能被 `json.loads` 解析，五个契约字段齐全，`case_id` 与输入一致；5 个资产摘要对象（`golden_standard/diff_report/version_history/run_log/self_check`）都存在且 `bytes > 0`。
3. `manuscript.md` 至少 5 个二级标题，且 `task_instruction` 点名的章节都能在 `coverage.covered_sections` 里找到；缺的项出现在 `coverage.missing_sections` 与 `pending_human`。
4. `coverage.number_audit.hit_rate` 为 1.0，或每个未命中数字都能在正文里解释清楚。
5. `evidence_map` 每条都有 `locator` 与 `quote`；`change_log` 至少有一条 `finalize`。
6. 打开 `self_check.json`：`pass` 为 `true`（或每个 `ok=false` 都有合理解释）；`S5` 五资产、`S6/S7` 空/坏输入子进程、`S11` 退出码断言均应为 `true`（环境禁止子进程时允许 `null`/skipped）。
7. `golden_standard.json` 的 `counts.verbatim.ratio` 为 1.0；`diff_report.md` 的 `missing` 为 0，`deviation` 每行都有原因。
8. 重复执行 `build`，`manuscript.md` 的校验和不变（幂等）。

## 降级一览

| 触发 | 处理 | 记录 |
|-|-|-|
| `/input` 不存在 | 空清单继续跑 | `errors: input_dir_missing` |
| 无 case.json 或 JSON 坏 | 按纯文本材料继续 | `errors: case_json_unreadable` / `case_json_missing` |
| PDF | 只登记文件 | `degradations: pdf_unparsed` + `pending_human` |
| 图像/表格类二进制 | 跳过 | `binary_unparsed` + `pending_human` |
| docx 缺 `word/document.xml` | 记空文本 | `docx_part_missing` |
| 单文件超 2MB / 总量超 20MB / 超 200 文件 | 截断或停止扫描 | `file_truncated` / `bytes_capped` / `file_capped` |
| 单文件读取出错 | 跳过该文件 | `file_error` |
| `task.md` 等任务说明文件 | 只登记，不当证据 | `instruction_excluded` |
| 输出目录不可写 | 回落到 work 目录 | `output_dir_fallback` |
| 五资产模块导入失败 | 主流程继续（`assets_module_unavailable`），不产出 5 资产 | `degradations` |
| 单个资产写入失败 | 其余资产与主产物照常写出 | `errors: assets:<stage>` |
| 空/坏输入子进程实测不可用 | `self_check` 对应检查记 skipped | `self_check.checks[].ok = null` |
| 未捕获异常 | 写 `input_error` 结果 + 占位稿 + 5 件最小资产 | `errors: fatal:<类型>` |

## 包内文件

| 文件 | 作用 |
|-|-|
| `SKILL.md` | 本说明：触发条件、四步流程、草稿格式、5 件可核验资产、自检 |
| `scripts/chapter_builder.py` | CLI、目录解析、渲染、`result.json` 组装、五资产 finalize 编排、异常兜底 |
| `scripts/material_ingest.py` | 材料读取与证据抽取：句子切分、定位符、引文校验、章节兜底组装 |
| `scripts/assets.py` | 五资产写出：`golden_standard.json`、`version_history.md`、`run.log`，以及 result.json 摘要回填 |
| `scripts/audit.py` | 差异报告 `diff_report.md`、空/坏输入子进程实测、机器自检 `self_check.json` |
| `references/handbook.md` | 字段表、定位规则、章节模板、五资产字段与复核清单 |

版本 1.1.0，Python ≥ 3.8，无第三方依赖。改动脚本后请重跑「交付前自检」的 8 条；升级时同步改 `VERSION`、本表与 `scripts/assets.py` 里的静态版本历史。
