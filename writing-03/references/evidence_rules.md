# 证据、引文、定位与状态规则（writing-03）

## 1. 三段交付的对应关系

| 产物 | 粒度 | 关键字段 |
|---|---|---|
| 论断清单 `evidence.json.claims` | 句子 / 可判定主张 | `claim_id`、`claim`、`claim_type`、`supported` |
| 证据表 `evidence.json.claims[].evidence` | 一条 claim 的一个来源 | `source`、`locator`、`quote`、`verified`、`strength`、`support_scope` |
| 成稿 `deliverable.md` | 可编辑全文 | `[n]` 引用编号、限定语、证据边界、参考文献 |

join 规则：`claims[].claim_id` 与证据行 `claim_id` 必须一一对应，不允许悬空；
成稿中的 `[n]` 必须能解析到参考文献条目。

## 2. locator 规范

`locator = <相对 /input 的路径> [B<块>.S<句>] chars:<start>-<end>`

- `B`：以空行分隔的段落块序号（从 1 起）；`S`：块内句子序号（从 1 起）。
- `chars`：句子在**该文件解码后全文**中的字符区间，`text[start:end] == quote`。
- 路径统一用 `/`，相对 `/input`；不接受"见上文"之类的模糊定位。

## 3. quote（逐字引文）规范

- 必须与材料原文**逐字一致**：汉字、标点、数字、单位、CI 写法都不得改写。
- 允许的例外只有空白归一化（多空格/换行），且会被记为 `match=normalized`；`golden_standard` 只把
  `match=exact` 计入 `quote_verbatim_rate`。
- 未命中时：证据行保留但 `verified=false`，写入 `pending_human`，**不得改写原文或编造引文**。
- 只用摘要可核的，要在 `support_scope`/证据边界中注明"仅摘要可核"。

## 4. 证据强度分级（四因子）

按"研究设计 > 样本量 > 独立来源数 > 冲突"综合：

| 等级 | 典型情形 |
|---|---|
| 高 | 系统综述/荟萃分析或大样本随机试验（n≥1000），多来源一致 |
| 中 | 队列/指南/中等样本（100–999），单一来源或方向有限 |
| 低 | 病例对照/横断面/小样本（<100），或仅摘要可核 |
| 不足 | 病例报告/体外/预印本/未标明设计，或与结论不直接相关 |

成稿语气必须与等级相称：低/不足 → "可能/提示/尚需验证"；高 → 仍保留"相关"而非"证明"。
无干预设计的证据不得写因果（"导致/引起"改为"与…相关"），并在 `change_log` 记录原句与改句。

## 5. 展示与冲突

- 一条论断多篇来源：全部进 `evidence`，成稿按首次引用顺序编号。
- 方向相反/范围不一致：`support=冲突` 或 `部分支撑`，成稿用"然而/但"句显式呈现，**不得静默丢弃**。
- 材料未覆盖（如机制、特殊人群）：标"待核"，写入 `pending_human`，不补造。

## 6. status 枚举（必须诚实）

| status | 含义 |
|---|---|
| `ok` | 读取了 agent 工作稿；claims 有证据；引文全部逐字命中；契约键全部非空 |
| `partial` | 无工作稿（自动兜底）、contract 键有缺失、或有引文未命中/降级项 |
| `insufficient_evidence` | 材料存在但没有任何 claim 有可校验证据 |
| `input_error` | /input 缺失、case.json 坏、无可用材料；仍写最小合法产物 |

## 7. 常见失败与处置

1. **直接跑 build**：得到自动兜底稿，`status=partial`；正确做法是先 init 读材料、写 draft.json。
2. **quote 抄错/改写**：check 报 FAIL，build 标 verified=false；从 init 输出复制原文。
3. **locator 缺失**：`build` 会用逐字搜索回填 locator；仍建议工作稿自带。
4. **draft case_id 不一致**：视为旧稿忽略并回退兜底；重写当前案例的 draft。
5. **输出目录不可写**：脚本回退到 `/app/work/output` 并在 errors 记录。
6. **PDF 等不支持格式**：记录降级；用平台工具读原文后把 quote 写入 draft。

## 8. 复核方式

- `golden_standard.json`：逐条期望 + locator + 逐字 quote + 完整性统计；
- `diff_report.md`：契约回填表与逐条证据命中表；
- 第三方复核：把证据表 quote 贴回对应文件 locator 即可复算，或重跑 build 比对。
