# 工作稿字段字典（plan.json / content_map.json / result.json）

## A. `work/plan.json` — Agent 手写

| 键 | 必填 | 约束 |
|-|-|-|
| `title` | 是 | ≤140 字，研究对象 + 结论各占一半意思 |
| `subtitle` | 否 | 一行方法或意义补充，最多 2 行渲染 |
| `caption` | 否 | 图注：材料文件名 + 核对入口 |
| `panels` | 是 | 数组，2–4 项，按阅读顺序排列 |
| `panels[].id` | 否 | 缺省 `P1/P2/...`；content_map 的 panel 字段用它 |
| `panels[].role` | 是 | 四选一：`problem` / `method` / `results` / `implication` |
| `panels[].heading` | 否 | 面板抬头，短词；超宽自动缩到 9pt |
| `panels[].flow` | 否 | 指向本面板的箭头文字，如 `how?`、`quantified by` |
| `panels[].items[]` | 是 | 每面板 1–3 个图元，合计 6–10 |
| `items[].id` | 否 | 缺省 `<panel>-I<n>`；建议显式写 `E1..En` |
| `items[].kind` | 否 | `text`（粗体 label + detail）或 `value`（大字号量 + detail） |
| `items[].label` | text 必填 | ≤8 词的短标签 |
| `items[].value` | value 必填 | 数字/量/比值，作为视觉焦点 |
| `items[].detail` | 否 | ≤25 词，写条件、方向、限定 |
| `items[].evidence[]` | 是 | `source` + `locator` + `quote` 三件套，见 §C |
| `legend[]` | 否 | `{label, meaning}`；缺省时用四个角色生成图例 |

排序语义：数组顺序 = 阅读顺序；`role` 缺项会被 `check` 点名。**不要写坐标或尺寸**——几何全部由
`render_kit.compose_figure()` 依画布推导，保证同输入同版式。

## B. `output/content_map.json` — 脚本生成

每项对应一个可核验图元：

```
element_id  图元 id（与 SVG 里的 id 一致）
panel       所属面板 id
role        规范化后的四角色之一
text        label + value + detail 拼接出的可读文本
svg_id      "#<element_id>"
bbox        [x, y, w, h]（模型坐标）
evidence    {source, locator, quote, status}
```

`evidence.status` 取值：`verified`（locator 与引文都命中）/ `relocated`（句子命中但 locator 被脚本改正）/
`no_quote`（引文缺失或过短）/ `unverified`（任何段落都找不到该逐字片段）。

## C. locator 约定

| 材料 | locator 形式 | 示例 |
|-|-|-|
| 纯文本 / md | `para.<段号>`，空行分段 | `para.4` |
| CSV / TSV | `para.<行号>`，逐行 | `para.12` |
| PDF（pdftotext 可用） | `p.<页> b.<块>` | `p.3 b2` |
| PDF 抽不出文本 | 只写 `p.<页>`，引文靠人工读页抄录 | `p.5` |

取 locator 的唯一正确方式：`show --grep "<片段>"` 看打印结果，复制整段引文。

## D. `output/result.json` 键位

| 键 | 内容 |
|-|-|
| `output_contract` 的每个键 | 原样保留；语义匹配到产物或 `null` |
| `case_id` | case.json 的 `case_id`/`id`/`case_name`，否则文件名 |
| `status` | `ok` / `partial` / `insufficient_evidence` / `input_error` |
| `sources[]` | `{id, name, kind, sha1, paragraphs}` 材料清单 |
| `uncertainty[]` | 被剔除图元数、材料缺口等不确定性说明 |
| `pending_human[]` | 需要人确认的点：口径不明、图元被剔、PDF 不可抽 |
| `errors[]` | 运行异常文本；非空通常意味着 status=partial |
| `degradations[]` | 降级事件：PNG 引擎、plan 缺失、面板占位 |
| `changes[]` | `{what, detail}` 构建/修改流水 |
| `runtime` | 工具名、python 版本、耗时、`unmatched_contract_fields` |

contract 匹配是按关键词打分的模糊映射，例如契约键 `editable_source` 会命中 `svg/vector/source/editable`
一类产物；命中不了的键名会出现在 `runtime.unmatched_contract_fields`，此时该键值为 `null`。

## E. 常见字段错误与修法

| 写错的样子 | 后果 | 正确写法 |
|-|-|-|
| 把整段摘要塞进 `detail` | 面板溢出、被降级丢弃 | 只留条件与方向，≤25 词 |
| `role` 写 `result`（少 s） | 角色归为 other，check 报缺 results | 严格用 `results` |
| 图元没有 `evidence` | 被 check 判 unverified 并剔除 | 补 source/locator/quote |
| quote 与 detail 各引一段 | 数字校验失败 | 选一段同时包含实体与数字的原文 |
| legend 写颜色码 | 读者无法对应语义 | label 写类别，meaning 写含义 |
| 自己算百分比写进 value | 来源找不到该数字 | 用原文的量或相对值 |

## F. 一次成功的运行应该看到什么

`init` 打印材料清单与段落数；`check` 打印 `PASS` 与 coverage=1.0；`build` 打印
`status=ok`、图元数、被拒数，以及 svg/pdf/png 三个字节数。三个文件均非空，PNG 的 IHDR
尺寸等于画布，PDF 以 `%PDF-` 开头。若 `status=partial`，一定要能在 `degradations` 或
`exceptions` 里指出原因，否则说明状态记录本身也出了问题。
