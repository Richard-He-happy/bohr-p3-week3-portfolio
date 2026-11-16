# 结果契约：字段字典、引文判定与阈值

本文件是 `result.json` 的验收口径。脚本每次运行都会按此写出信封；人工复核时按节序检查即可。

## 1. 状态取值（先看 `status`）

- `ok`：deck 已生成，所有机器检查通过，`exceptions` 为空。
- `partial`：deck 已生成，但至少一项检查失败、或存在 exception、或文本层为空。
- `insufficient_evidence`：材料在，但没有可用句子/图表标题，没有内容可以上页面。
- `input_error`：找不到论文文件，或 `case.json` 不可读且无其他可用材料。

四种状态都会产出可解析的 `result.json`，退出码始终为 0。

## 2. 顶层字段

`output_contract` 列出的键一律以同名键出现；契约没列的键也允许存在（未知字段保留，不用时值为 `null`）。

- `case_id`：从 case 原样拷贝，不截断不改写。
- `sources`：实际读到的材料信息，记录 `file`、`engine`（抽取链走过的路径）、`chars`、`pages`、`figures`、`tables`、`template`。
- `runtime`：`started` 时间、`seconds` 耗时、`model_requests` 计数。
- `exceptions`：缺材料、PDF 读不出、图表清单没确认等；每条是 `{kind, detail}`。
- `degradations`：无模板、仅用纯 Python 解析 PDF、无 office 渲染器等降级；每条是 `{what, detail}`。
- `pending_human`：对外使用前必须人工确认的点，`{action, detail}`。
- `uncertainty`：已知的不确定项，`{about, detail}`。
- `changes`：本次产物相对输入的改动，`{artifact, engine, slides, action}`，`action` 取 `add` 或 `modify`。
- `errors`：运行期异常列表；进程仍以 0 退出。

## 3. 可编辑源 `editable_source`

逐项核对下列内容：

- `path` / `format`：固定是 pptx 的路径与 `"pptx"`。
- `slides`：实际写进 deck 的页数；`notes_slides`：带讲稿的页数。
- `bytes` / `sha256`：产物文件的字节数与内容哈希，可用来证明交付的就是本次文件。
- `engine`：装配方式，模板手术为 `stdlib-ooxml-template-surgery`，内置包为 `stdlib-ooxml-minimal`。
- `template`：`path`、`master`（母版文件名列表）、`layouts_used`（用到的版式）、`inherited`（构建前后主题与母版哈希不变才为 true）。

## 4. 导出件 `export_artifact`

`pdf` 子对象包含 `path`、`pages`、`engine`、`valid` 四项。`valid` 的判据是文件头 `%PDF-` 且解析出的页数与页数要求一致。`engine` 有三种可能：`libreoffice`、`office-renderer`、`stdlib-textlayer`（无渲染器时由标准库从 deck 文本层写出，属降级但仍是真实 PDF）。

`png` 子对象本版本固定为 `{dir: null, count: 0}`——不产出位图预览，PDF 即渲染证据。

## 5. 逐页证据图 `content_map`

结构是 `{unit: "slide", slides: [...], coverage: {...}}`，`slides` 的行序必须等于 deck 页序，`n` 从 1 连续。每一行必须齐备：

- `n`：页码；`title`：页面标题；`role`：该页在主线里的角色。
- `claim`：该页唯一主张，取自论文锚定句的原文片段（可截断，不可改写成新事实）。
- `bullets`：≤5 条原文前缀片段。
- `evidence`：数组，元素含 `type`（`figure`/`table`/`section`/`page`）、`id`、`locator`、`quote`、`matched`。`locator` 形如 `p.<页码>`（可加 ` / <章节>`）或 `Figure N, p.X`。`matched=false` 表示引文没在论文中命中，同时会出现在 `compliance_checks.failures`。
- `assets`：图表资源说明。本版本不抠 PDF 位图，`path` 为 `null`、`note` 写 `caption+locator only`；宁可留白也不放替身图。
- `notes`：讲稿，必须非空，且不得复述页面文字。

`coverage` 汇总四个数字：`slides`（页面总数）、`with_evidence`（有证据的页数）、`evidence_items`（证据条数）、`quotes_matched`（引文命中的条数）。

## 6. 自检 `compliance_checks`

| 检查键 | 判定内容 |
|---|---|
| `slide_count` | `expected`/`actual`/`ok`：实际页数是否等于 workorder 要求 |
| `template_inheritance` | 声明值、装配 engine、主题哈希、母版哈希、用到的版式、`ok` |
| `overflow` | 单页 >5 条或单条 >190 字符时把页码记入 `dense_slides` |
| `notes_coverage` | 带讲稿页数 / 总页数 |
| `notes_overlap` | 讲稿与页面文字的 token 重叠率最大值，阈值 0.6 |
| `figure_refs` | 论文里的图表编号数量、页面上引用了但论文里不存在的编号数 |
| `number_whitelist` | 页面上出现但论文里找不到的数字个数 |
| `evidence_coverage` | 有证据的页数、缺失引文数 |
| `mode` | 从 workorder 读到的模式，原样回报 |
| `fonts` | 主题来源（template/builtin）、是否内嵌字体 |
| `files` | pptx/PDF 是否通过、slide/notes 部件数、PDF 页数、PNG 数量 |
| `content_map_completeness` | 逐行八键是否齐全、claim/evidence/notes 是否非空 |
| `structure_consistency` | slide 部件数、notes 部件数、content_map 行数、模型页数四者是否对齐 |
| `pass` | 以上全部通过且结构审计通过才为 true |
| `failures` | 人类可读的失败原因列表（最多 30 条） |

## 7. 能改的阈值（改这里再改代码）

生成 deck 最少文本 200 字符；引文最短 8 字符；每页 bullets 上限 5、单条字符上限 190；讲稿重叠率上限 0.6；图表页 caption 截断 95 字符；workorder 没给页数时的默认值 12。

对应实现位置：`scripts/deckgen.py` 的 `run()`、`run_checks()`、`compose_slides()`、`read_workorder()`。
