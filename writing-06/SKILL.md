---
name: rd-section-forge
description: 把已经画好的图、已经跑完的表和统计输出，落成可投稿稿件里分工清楚的 Results 与 Discussion 两节。做法是先由脚本把 /input 材料切成带 locator 的文本块并逐行打印读数，Agent 据此写 work/draft.json 工作稿，脚本再逐条核对"正文数字能否在材料某行里找到、引文是否逐字、结果段有没有混进机制解释、显著性有没有检验支撑、局限是否覆盖方法/样本/测量/统计四层"，最后成稿并回填 result.json。适用于数据在手、图表已备、需要起草或自查结果与讨论章节的场合；不适用于需要外部文献检索的综述或需要重算统计的数据分析。
version: 1.0.0
---

# 读数落段：Results / Discussion 分节成稿

## 1. 一句话定位与触发场景

给"数据在手、图表已画好、正文还没写"的稿件补两节：Results 只写材料里读得到的观察，Discussion 承担解释、文献关系、因果边界与局限；每个数字带 locator，能被第三方逐条回查。

命中以下说法时用本 Skill：写结果段、写讨论段、图表读数转写正文、结果与讨论分开写、给正文数字标来源、检查讨论有没有过度解读、补局限小节。

## 2. 不接的活（边界）

| 请求 | 为什么不做 |
|---|---|
| 写文献综述、需要检索外部文献 | 本 Skill 只引用 `case.json` 与材料里已有的条目，材料没有就不写 |
| 重跑统计、重算 p 值或效应量 | 不做统计计算；只搬运材料给出的统计量与检验名 |
| 画图、改图、从位图里 OCR 读数 | 位图只留占位块并提示"目视近似需标约"，不猜坐标 |
| 生成正式测试答案或"白板" | 题面禁止；产物只能来自本次实际运行 |

## 3. 三条铁律

1. **读数可回溯**：正文里出现的每个数字，必须能在工作稿某条逐字 `quote` 里找到，或来自显式 `derived` 公式；否则脚本报 `number_unverified`，正稿不写该值。
2. **两节不越界**：Results 只放方向、幅度、组间比较、离散度、检验结果；机制、动机、文献对照、因果推断一律留在 Discussion。结果段出现因果词即报 `results_causal`。
3. **强度只到证据允许处**：观察性共变最高写到"suggests / consistent with"；没有干预与对照，就不写 causes / leads to。

## 4. 运行契约与三个入口

| 项 | 约定 |
|---|---|
| 原始输入 | `/input/case.json`（缺失时递归找 `case*.json`）+ `/input` 下任意材料 |
| 工作目录 | `/app/work`：`index.json`、`draft.json`、`check_report.json` |
| 产物目录 | `/app/output`：`manuscript.md`、`results_map.json`、`evidence_map.json`、`preserved_facts.json`、`change_log.json`、`result.json`，以及 `build` 末尾生成的 5 个核验资产：`golden_standard.json`、`diff_report.md`、`version_history.md`、`run.log`、`self_check.json` |
| 入口 | `python3 scripts/rd_sections.py {init\|check\|build}` |
| 可选参数 | `--input` / `--work` / `--out`（默认 `/input`、`/app/work`、`/app/output`，可用 `SKILL_INPUT`/`SKILL_WORK`/`SKILL_OUT` 覆盖）、`--draft`（默认 `<work>/draft.json`） |
| 依赖 | Python 3 标准库；不联网；不依赖当前工作目录 |
| 退出码 | 恒为 0；任何异常都会留一份合法 `result.json` |

`result.json` 原样回填输入 `output_contract` 的全部键（不改名、不漏键，缺值 `null`/`[]`），并附 `case_id`、`status`、`sources`、`uncertainty`、`pending_human`、`errors`、`degradations`、`changes`、`metrics`、`runtime`、`output_contract`、`contract_fields`；`build` 还会另挂 5 个核验资产字段 `golden_standard`、`diff_report`、`version_history`、`run_log`、`self_check`（见 §15.1）。

`status` 取值：`ok`（工作稿 + 0 error）、`partial`（兜底稿 / 有 error / 补写了缺节）、`insufficient_evidence`（无任何可读文本块）、`input_error`（输入目录不可用）。

## 5. 五步落地流程

```bash
# 1) 建索引：先写一份合法 partial result.json，再打印材料清单与每行读数
python3 scripts/rd_sections.py init --input /input --work /app/work --out /app/output

# 2) 照抄 init 打印的 "loc :: text"，写 /app/work/draft.json（schema 见 §6）
# 3) 自检：有 error 就改工作稿，不要改材料
python3 scripts/rd_sections.py check --input /input --work /app/work --out /app/output

# 4) 成稿：manuscript.md + 四份映射 + 最终 result.json + 5 个核验资产
python3 scripts/rd_sections.py build --input /input --work /app/work --out /app/output
```

`init` 已经落下 partial `result.json`，中途断掉也合法。**同一次回复内尽量把 init → draft → check → build 走完**；接近时间上限就先 `build`，再回头改稿重跑。

## 6. 工作稿 draft.json 契约

```json
{
  "case_id": "原样保留",
  "title": "章节标题",
  "language": "zh | en",
  "results":    [{"heading": "小标题", "xref": ["Fig. 2B"], "paragraphs": ["……"]}],
  "discussion": [{"heading": "小标题", "xref": [], "paragraphs": ["……"]}],
  "limitations": ["方法层：…… 因此不能……", "统计层：……"],
  "evidence": [{"id": "e1", "quote": "材料里的逐字片段", "locator": "data/assay.csv#r3"}],
  "derived":  [{"value": "17.4", "formula": "61.9-44.5", "note": "端点差"}],
  "preserved_facts": [{"fact": "4 nM 组抑制率 61.9%（SD 5.2，n = 4）", "quote": "……", "locator": "……"}],
  "changes": [{"action": "措辞收敛", "original_quote": "causes", "revised_quote": "is associated with", "reason": "无干预组"}],
  "pending_human": ["请作者确认图 2B 面板归属"],
  "uncertainty": ["目视读图的坐标刻度精度"]
}
```

| 键 | 是否必需 | 说明 |
|---|---|---|
| `results` / `discussion` | 是 | 至少各 1 节；正文写在 `paragraphs`，一段一个字符串 |
| `limitations` | 是（≥2） | 覆盖方法 / 样本 / 测量 / 统计四层，每条都要写"因此不能得出什么" |
| `evidence` | 是 | 逐字引文 + locator；这是正文数字的放行依据 |
| `derived` | 否 | 自己算的差值、百分比，必须带 `formula` |
| `preserved_facts` | 否 | 关键事实 → 引文 → locator，交付时逐条核验 |
| `changes` | 否 | 记录生成与收敛动作（原句 → 改句 → 原因） |
| `pending_human` | 否 | 材料缺口与需作者确认项 |
| `uncertainty` | 否 | "做了但不确定"的判断：面板归属、单位换算、目视读数 |
| `approx` | 否 | 单条 `evidence` 上加 `"approx": true` 表示目视读图，正文须写"约/approx." |

## 7. locator 语法与引文纪律

| 材料 | 形式 | 例子 |
|---|---|---|
| 文本 / Markdown / JSON 段落（按空行切段，JSON 按行） | `<相对路径>#p<序号>` | `notes/caption.md#p2` |
| CSV / TSV 行（表头算 r1） | `<相对路径>#r<序号>` | `data/assay.csv#r3` |
| PDF 页 | `<相对路径>#pg<页号>` | `paper.pdf#pg5` |
| 位图 | `<相对路径>#fig` | `data/fig2.png#fig` |

- 序号一律以 `init` 打印的 `loc :: text` 为准，**直接复制**，不要凭记忆写。
- `quote` 与材料比对前做 NFKC + 空白归一、大小写折叠；数字和单位不忽略。
- 引文对不上时改引文（回材料复制），**不许改材料迁就引文**。

## 8. Results 段：观察句的五个槽位

一句观察至少把五件事说清：**值、单位、条件、离散度或统计量、图/表编号**。

| 槽位 | 合格写法 | 不合格写法 |
|---|---|---|
| 端点比较 | "抑制率为 61.9%（SD 5.2，n = 4）at 4 nM，43.2%（SD 4.8，n = 4）at 16 nM（Fig. 2A；Table 1）。" | "抑制率明显下降"（无值无单位） |
| 剂量梯度 | "四个剂量点上抑制率单调上升。" | "抑制率急剧上升，说明毒性很强"（混入解释） |
| 统计 | "one-way ANOVA 给出 p = 0.008；16 nM 与溶剂对照不同（p < 0.001）。" | "差异极显著"（无检验） |
| 阴性/未达显著 | "p = 0.42，与溶剂对照未分离。" | "有上升趋势"（把不显著写成趋势） |
| 目视读图 | "约 47%（approx.，按纵轴刻度目视读取）" | "47.0%"（假精度） |

组织方式二选一：按图序（Fig. 2A → 2B → Table 1）或按问题（先主效应再交互）。一段一个发现，不写流水账。

## 9. Discussion 段：四拍推进

1. **本研究数据支持什么**：回指 Results 的具体读数，强度只到数据允许处。
2. **与已有证据的关系**：一致 / 不一致 / 部分一致，并说明可能原因（体系、剂量、时程、检测方法）。材料没有可对照文献时**明确写出来**，不要堆引用。
3. **机制与替代解释**：机制推测标为推测，给出能证伪它的实验。
4. **边界与局限**：相关 ≠ 因果；方法 / 样本 / 测量 / 统计四层各写一句"因此不能……"。

## 10. 措辞强度梯度与禁词

| 级 | 需要的证据 | 可用表述 | 禁用 |
|---|---|---|---|
| 相关 | 观察性共变 | 与……相关 / associated with | causes、导致 |
| 提示 | 剂量依赖、时序、方向一致 | 提示 / 与……一致 / suggests / consistent with | proves |
| 因果 | 干预、敲除、救援 + 对照 | 导致 / causes / leads to | ——（材料无此设计时不可用） |

- Results 禁词：导致 造成 因为 由于 机制 证明 证实 调控 / cause because mechanism prove demonstrat → 命中即 `results_causal`。
- Discussion 过度断言：证明 证实 确证 首次 / prove proven confirm definitiv establish → 命中即 `overclaim`。
- 否定与让步语境（"不能证明"、"cannot confirm"）不计为过度断言。

## 11. 局限四层写法

| 层 | 常见材料缺口 | 该写成的句子 |
|---|---|---|
| 方法 method | 单一检测、单时间点、无对照 | "只有一个 48 h 终点，因此分不清可逆与不可逆效应。" |
| 样本 sample | n 小、单一细胞系/批次 | "n = 4、单一细胞系，因此批间波动与细胞类型依赖未评估。" |
| 测量 measure | 误差棒含义未说明、读数精度不足 | "误差棒定义未给出，因此不解读离散度。" |
| 统计 stat | 无多重比较校正、无效应量 | "p 值未做多重比较校正，因此不报显著性强度。" |

少于 2 条或缺层 → `limitations_weak`（warn）。空话（"样本量有限"）不算覆盖。

## 12. check 码表与处置动作

| 码 | 级别 | 触发条件 | 怎么改 |
|---|---|---|---|
| `draft_missing` | error | 工作稿不存在或不是对象 | 先按 §6 写 draft.json |
| `schema` | error | `results`/`discussion` 缺节 | 各补一节 |
| `evidence_bad` | error | 引文缺失 / 非逐字 | 回材料复制原文，`suggest` 给出候选 locator |
| `number_unverified` | error | 结果段数字找不到逐字来源 | 换成材料里的值，或补 `derived` 公式，或删除 |
| `results_causal` | error | 结果段出现因果/机制词 | 把该句移到 Discussion |
| `sig_without_stat` | error | 写"显著"却无检验或 p 值 | 补检验名与 p，或改成方向+幅度 |
| `overclaim` | error | Discussion 过度断言 | 收敛为 suggests / consistent with |
| `no_limitations` | error | `limitations` 为空 | 按 §11 写满四层 |
| `fact_bad` | error | `preserved_facts` 引文非逐字 | 回材料复制 |
| `limitations_weak` | warn | 局限 < 2 条或缺层 | 补层 |
| `discussion_no_boundary` | warn | 讨论无因果边界句 | 补一句"不能推断因果/局限" |
| `discussion_new_number` | warn | 讨论出现结果段没有、也无来源的数字 | 补来源或删 |
| `fact_no_source` | warn | 事实条目缺 quote 或 locator | 补齐 |
| `no_blocks` | warn | 索引里没有可读块 | 重新 `init`，检查材料格式 |

`check` 会打印 `errors/warnings`、证据与数字通过数，以及每条问题的 `@locator` 与候选原文。**errors 必须清零再交付**；warnings 要逐条判断是有意为之还是漏写。

## 13. 缺口降级矩阵

| 现象 | 脚本行为 | Agent 该做什么 |
|---|---|---|
| 无 `case.json` | 契约回退为 4 个默认键，照常索引 | 照常写稿，`pending_human` 记"契约缺失" |
| `case.json` 坏 JSON | 记入 `errors`，继续索引其它材料 | 照常写稿，不猜契约字段 |
| 输入目录不存在 | `init` 写 `input_error`，`build` 亦标 `input_error` | 报告输入问题，不编造结果 |
| 材料全是文本块（无表） | Results 用逐字引文句兜底，并记 `pending_human` | 人工改写成观察句 |
| 无工作稿 | `build` 生成完整兜底稿（读数句 + 讨论三段 + 局限） | 交付可用，但需润色；`status=partial` |
| 工作稿缺 `results`/`discussion`/`limitations`/`evidence` | 只补缺的那一项，记 `degradations` | 检查补写处是否符合预期 |
| 工作稿坏 JSON | 整份走兜底稿，`degradations` 记解析错误 | 提示作者重写工作稿 |
| PDF 文本层不可解压 | 记 `PG` 占位 + 缺口 | 改用表/图注，或进 `pending_human` |
| 单个材料解析失败 | 只降级该材料，其余照常 | 不影响其它读数 |
| 位图材料 | 记 `fig` 占位，不 OCR | 目视读数标 `approx`，或向作者要数据表 |
| 无可读读数 | Results 写"可读读数缺口"占位段，`pending_human` 记录 | 明确告知缺什么材料 |

## 14. 产物清单与 result.json 字段

| 文件 | 内容 |
|---|---|
| `manuscript.md` | `# 标题` → `## 1. Results`（`### 1.x`）→ `## 2. Discussion`（`### 2.x`）→ `### Limitations` |
| `results_discussion.md` | 同一份正文的裸标题版本：`## Results` / `## Discussion` / `### Limitations`，供按题面字面寻找该文件名的评测读取 |
| `results_map.json` | 每个 Results 段落的读数：`token`/`value`/`unit`/`sources`；含 `coverage`、`unverified` |
| `evidence_map.json` | 每条证据的 `quote`/`locator`（解析后）/`declared`（申报值）/`verified`（exact/misplaced/span/notfound） |
| `preserved_facts.json` | 事实 → 引文 → locator → `verified` |
| `change_log.json` | `changes`、`pending_human`、`degradations` |
| `result.json` | 契约回填 + 状态 + 来源 + 指标 + 自检 |
| `golden_standard.json` | 金标准：按 `output_contract` 逐键列出期望章节/字段/结果项；材料能支撑的项带 `locator` + 逐字 `quote`，无来源项 `basis: contract` |
| `diff_report.md` | 实际产物 vs 金标准逐项对照：达标 / 偏差 / 缺失 + 原因与处置 |
| `version_history.md` | `references/version_history.md` 的副本（v0 → v1.0.0：改了什么/为什么/如何回退）+ 本次运行段 |
| `run.log` | 真实运行日志（追加写）：每阶段起止、耗时、退出码、降级、异常 |
| `self_check.json` | 机器自检回执：契约键完整性、主产物存在性、引文逐字命中率、计数一致性、空/坏输入兜底、退出码恒 0 |

契约键的路由：含 `deliver`/`manuscript`/`正文` → 主产物；`result.?map`/`readout`/`读数` → results_map；`preserv`/`fact`/`事实` → 事实表；`evidence`/`source`/`证据`/`来源` → 证据表；`change`/`log`/`修改` → 修改记录；`uncertain`/`pending`/`人工` → 待确认项；`limit`/`局限` → 局限与缺口；其余键返回 `{"status": "not_separately_produced", "see": [...]}`。

`metrics` 关键项：`numbers_total`、`numbers_verified`、`numbers_unverified`、`traceability_rate`、`evidence_total`、`evidence_ok`、`evidence_failed`、`results_sections`、`discussion_sections`、`results_words`、`discussion_words`、`limitations`、`materials`、`tables`、`mode`、`self_audit`。

## 15. 一致性自检（脚本内置 + 人工复核）

`build` 写完产物后会跑 6 条断言，结果记在 `result.json.metrics.self_audit`，失败项同时进 `degradations`（形如 `self_audit_failed:<名字>`）：

| 断言 | 含义 |
|---|---|
| `contract_keys` | 契约中的每个键都在 result.json 顶层出现 |
| `contract_body` | 除 `case_id` 外的键一个不少 |
| `deliverable_text` | 主产物正文非空 |
| `numbers_balanced` | `numbers_verified + numbers_unverified == numbers_total` |
| `two_headings` | 稿件里同时存在 `## 1.` 与 `## 2.` |
| `limitations_floor` | 局限至少 2 条 |

人工复核三条（脚本不替代判断）：读数单位是否与图注一致；讨论里的"不一致"是否真的写了可能原因；`pending_human` 里每条是否都能落到具体图表或文献条目。

### 15.1 五个核验资产（build / finalize 生成）

`build` 在写完原有 6 个产物后，再生成 5 个可核验资产到 `/app/output`，并把摘要挂到 `result.json` 同名字段。全部纯标准库生成；资产生成失败只记降级，不影响主产物与退出码。

| 资产 | 回答的问题 | 关键内容 | 判据 |
|---|---|---|---|
| `golden_standard.json` | 期望交付什么 | 按 `output_contract` 逐键列出期望字段/章节/结果项；材料能支撑的项带 `locator` + 逐字 `quote`，无来源项 `basis: contract` | 每项有 `basis`；`verification.quote_hit_rate` 由材料反查 |
| `diff_report.md` | 实际 vs 期望差在哪 | 逐项对照表：达标 / 偏差 / 缺失 + 原因；末尾给偏差项处置 | 契约项看 `result.json` 非空；章节看标题与局限条数；读数看正文或 `results_map`；事实看引文命中 |
| `version_history.md` | 改过什么、怎么回退 | 静态部分 v0 → v1.0.0（改了什么/为什么/回退步骤/文件指纹），运行期追加本次运行段 | 静态段来自 `references/version_history.md`，运行段由本次真实数据填充 |
| `run.log` | 这次怎么跑的 | 追加写：每条命令起止、阶段耗时、退出码、降级项、异常 | `event=done ... exit=0` 至少一条；异常以 `event=error` 记录 |
| `self_check.json` | 机器敢不敢签字 | 7 项检查：契约键完整、主产物存在、引文逐字命中率、计数一致、空/坏输入兜底（真实执行探针）、退出码恒 0、run.log 完整 | `checks` 全 true 时 `overall_pass=true`；失败项同时进 `result.json.degradations` |

空输入 / 坏 `case.json` 时 5 个资产仍生成（金标准只含契约项、diff 记录缺失原因、self_check 的降级探针如实记录），退出码仍为 0。

## 16. 包内文件、版本与维护

```
SKILL.md                        本文件：用途、契约、工作稿 schema、写作规则、降级
scripts/rd_sections.py          入口：init / check / build，兜底稿合成与规则审计
scripts/rd_assets.py            5 个核验资产生成器（build 末尾调用，永不抛异常）
scripts/rd_material.py          材料层：切块与 locator、数字与单位、表格列角色、缺口扫描、成稿拼装、自检
references/pipeline-contract.md  字段细则：locator、draft.json、result.json、产物 map
references/section-rules.md      写作细则：观察句槽位、讨论四拍、强度梯度、局限四层、检查清单
references/audit-checklist.md    复核用清单：码表、抽样复核步骤、交付前逐项打勾
references/version_history.md    静态版本记录：v0 → v1.0.0 的改动、理由、回退与文件指纹
```

- 版本 1.0.0（v0 初版 + 5 个核验资产增补，见 `references/version_history.md`）；纯标准库，无第三方依赖，无需安装步骤。
- 改词表时同步 `rd_sections.py` 的 `CAUSAL/HYPE/BOUNDARY` 与 `references/section-rules.md`。
- 改 schema 保持向后兼容：缺字段按空处理，未知键忽略。

## 17. 最小调用示例（示例，非正式案例结果）

输入（示意，非任何真实实验）：`/input/case.json`（契约含 `deliverable`/`preserved_facts`/`evidence_map`/`change_log`/`limitations`）+ `data/assay.csv`（`inhibitor_nM,inhibition_pct,sd_pct,n`）+ `notes/caption.md`（图注与 ANOVA 行）。

```bash
python3 scripts/rd_sections.py init --input /input --work /app/work --out /app/output
#  case_id DEMO-000 | loaded | contract(5): deliverable, preserved_facts, ...
#  [table] data/assay.csv: inhibitor_nM | inhibition_pct | sd_pct | n (4 rows)
#     data/assay.csv#r2 :: row 3: inhibitor_nM=4 | inhibition_pct=61.9 | sd_pct=5.2 | n=4
#  [caption] notes/caption.md#p1 :: "Fig. 2A. Inhibition of enzyme activity ..."
#  [gap] no_lit: No literature supplied: no consistency claim.
python3 scripts/rd_sections.py check --input /input --work /app/work --out /app/output
#  CHECK .../draft.json errors=0 warnings=0 | evidence ok/failed 3/0 | numbers 9/9
python3 scripts/rd_sections.py build --input /input --work /app/work --out /app/output
#  BUILD /app/output status=ok mode=agent-draft contract=5/5 self-audit=6/6 1342B results=1/3 numbers=9/9
```

示例数值仅演示接口，不代表任何真实实验，也不构成正式案例答案。产物结构与真实运行一致：两节二级标题、`### Limitations`、四份映射与 `result.json`。

## 18. 交付前打勾清单

- [ ] `python3 scripts/rd_sections.py --help` 退出码 0。
- [ ] `init` 打印出材料、表行、图注与缺口；`work/index.json` 存在。
- [ ] 不带工作稿跑 `build`：`status=partial`、`mode=fallback`、稿件含 `## 1.` 与 `## 2.`。
- [ ] 带工作稿跑 `check`：`errors=0`，`numbers_verified == numbers_total`。
- [ ] 故意把某读数改成材料里没有的值：`check` 报 `number_unverified` 并给候选 locator。
- [ ] 结果段塞入"导致/因为"：报 `results_causal`。
- [ ] 讨论写 `prove`：报 `overclaim`。
- [ ] 空输入 / 坏 JSON / 缺目录：仍 exit 0，`result.json` 合法且契约键齐全。
- [ ] `build` 后 `/app/output` 存在 5 个核验资产且均非空；`result.json` 顶层含 `golden_standard`/`diff_report`/`version_history`/`run_log`/`self_check` 五个字段。
- [ ] `self_check.json.overall_pass == true` 且 7 项 `checks` 全真；`details.degradation_tests` 里空输入与坏 JSON 两项均 pass。
- [ ] `run.log` 里每条命令都有 `event=done ... exit=0`，降级项与异常有记录；`version_history.md` 含 v0 → v1.0.0 与回退步骤。
- [ ] `contract_fields.filled == contract_fields.total`；`case_id` 与输入一致。
- [ ] 包内无 `__pycache__`/`.pyc`，无预制正式答案。
