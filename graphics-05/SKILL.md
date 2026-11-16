---
name: ga-evidence-atlas
description: Compose a one-page graphical abstract (question, approach, findings, takeaway) from supplied research material, laid out deterministically and exported as layered editable SVG, single-page vector PDF and a genuine PNG, while an element-by-element atlas ties every drawn item to a verbatim source quote. Use for graphical abstracts, TOC/mechanism/pipeline summary figures, or any figure deliverable that must remain editable and auditable.
version: 1.0.0
---

# Graphical Abstract Evidence Atlas

研究材料进，单页四段图出。这张图必须同时满足三个条件：图上任何实体、关系、数字都能回到
原文逐字核查；同样的输入反复运行得到同一套版式；交付物是可继续修改的源文件而不是截图。

四段固定叙事：**研究问题 → 技术路线 → 关键发现 → 结论/含义**。四段之外的信息只能进图注。

不在范围内：写论文正文、做统计推断、设计新实验。材料里没有的基因名、数值、时间点、单位、
结论一律不补——编一个数字就足以让整份交付失效。

## 使用条件

用户要求 graphical abstract / 图文摘要 / 机制图 / 流程总结图，并且给了可读的研究材料
（pdf、md、txt、csv）。如果材料里找不到任何可以逐字引用的完整句子，输出
`insufficient_evidence`，在 `pending_human` 里写明缺什么，不要产出一张空壳图。

## 包结构与职责

- `scripts/main.py`：四个子命令的入口，负责索引、校验、编排与结果落盘。
- `scripts/render_kit.py`：唯一排版权威。输入 plan，输出 SVG / PDF 两套渲染结果。
- `scripts/pngkit.py`：标准库位图光栅器。绘图库不可用时由它保证 PNG 仍然真实存在。
- `references/workplan-fields.md`：plan.json 字段表、locator 语法、result.json 键位。
- `references/review-lens.md`：评分维度证据、失败处置表、交付前检查单。

## 调用方式

子命令统一支持 `--input`、`--work`、`--output`；评测默认值分别是 `/input`、`/app/work`、
`/app/output`。纯标准库、离线、与当前目录无关。**退出码永远为 0**，出问题写进 result.json，
读者从字段而不是从崩溃信息里判断状态。

| 子命令 | 作用 | 关键输出 |
|-|-|-|
| `init` | 扫描输入、切段落、分配 locator，先写 partial result.json | `work/index.json` |
| `show` | 按关键词或材料编号检索段落，打印原文与 locator | 可复制的逐字引文 |
| `check` | 审计工作稿：四角色、引文命中、数字白名单 | PASS / NEEDS WORK + `work/check.json` |
| `build` | 渲染三件套，产出证据表与合规表，覆盖 result.json | 六个交付文件 |

推荐节奏：init → 用 show 找 6–10 条事实 → 手写 plan → check 清零 → build → 汇报缺口。

## 交付文件（默认在 `/app/output`）

`graphical_abstract.svg` 是分层可编辑源：六个命名图层、文字为 `<text>`、每个图元带 id，
评审和作者都能直接改一个标签再导出。`graphical_abstract.pdf` 是单页矢量件，字体用 base-14
并带 CJK 回退，文字可选中可搜索。`graphical_abstract.png` 是真实位图预览，优先交给绘图库，
缺失时由 `pngkit` 生成，IHDR 尺寸等于画布、引擎名写进合规表。另有 `content_map.json`（图元级
证据）、`compliance_checks.json`（画布/字号/越界/图层/配色/覆盖率/像素引擎）、`result.json`
（主结果与运行记录）。

`result.json` 硬性要求：输出契约里的键全部保留，能对上产物就填产物，对不上填 `null`，
不允许删键或改名；`status` 只能是 `ok`、`partial`、`insufficient_evidence`、`input_error` 之一，
且必须如实反映本次运行的真实完成度。

## 工作稿 plan.json

只写内容与结构，不写坐标。角色必须是 `problem`、`method`、`results`、`implication` 四选一，
四个都要出现；面板 2–4 个，每面板 1–3 个图元，总量 6–10。图元分两种：`text` 由粗体
`label` 加 `detail` 说明，`value` 用于把核心数字放大成视觉焦点。两个面板之间的箭头文字写在
后一个面板的 `flow` 上。`legend` 可选，缺省时用四个角色自动生成。字段细节见
`references/workplan-fields.md`。

## 证据纪律

- 引文必须是原文里连续的一段，从 `show` 的输出复制，不改写、不拼接、不拿摘要充数。
- locator 用 show 打印的值；句子本身对而位置写偏时脚本会自动纠正，并在证据表里标 `relocated`。
- 图元 label/value/detail 中出现的每个数字，都必须能在该图元自己的引文里找到，否则 check 拒绝。
- 原文用 "suggest / indicate / may" 表达不确定性时，照原语气引用，不升级成断言。
- 证据无法验证的图元会被剔除、面板降级为占位，并分别进入 `exceptions` 与 `pending_human`。

## 版面与视觉约束（脚本负责）

画布 1200×760，对应 PDF 12×7.6 in（864×547.2 pt）单页。配色取自 Okabe-Ito 子集，四个角色
各一色，同时面板抬头直接写角色文字，因此色觉差异或灰度打印都不会丢掉语义。字号阶梯从标题
30 到图例 10.5，最小约 9.2；放不下时先降字号到 0.76，再按顺序丢弃图元并把丢弃写进
`degradations`。面板不超过 4 个时排一行，超过则分两行。图层顺序固定为 background、structure、
content、legend、footer、titles。全部几何由画布推导，没有随机数也没有时间戳。

## 评分维度对应

| 维度 | 包里对应的证据 |
|-|-|
| 完成度 | 四段齐全、单页、可编辑 SVG、单页 PDF、真实 PNG |
| 正确性 | 每个图元逐字引文；方向词来自原文的 flow/detail |
| 完整性 | 图例、单位、条件标签、caption；缺口进 pending_human |
| 可核验 | content_map 逐条证据、材料 sha1、changes、runtime |
| 效率 | 一次流程出稿；改图只改 plan 后重跑 build |
| 稳定 | 确定性布局；同一 plan 两次运行 SVG 字节一致 |
| 异常 | 恒 0 退出码；partial 先落盘；PNG 有标准库兜底 |
| 复用 | 字段表与检查单独立成 references；图层与导出参数固化在渲染器 |

## 异常处置

| 情形 | 处置 | 落点 |
|-|-|-|
| case.json 不存在或坏 JSON | 递归找其他 case 文件；再没有就只靠材料与 task.md | errors[]，无法映射的契约键为 null，status=partial |
| 材料读不出文本 | 该材料标注 not parsed，其余材料继续 | degradations[]，提示人工读页 |
| 没有 plan.json | 从原文抽四句做确定性兜底，逐字引用 | status=partial，exceptions 记 plan_missing |
| 引文验证不过 | 剔除该图元，空面板给占位 | exceptions 记 element_dropped，pending_human 提醒 |
| 没有绘图库 | PNG 交给 pngkit，IHDR 与引擎如实记录 | compliance_checks.png.method 标明 degraded |
| 渲染抛异常 | 捕获后仍然 finalize result.json | errors[]，退出码 0 |

## 交前自检

`check` 通过且覆盖率不低于 0.9；result.json 契约键齐全、状态属实；SVG 里文字可编辑且六个
图层都在；PDF 单页文字可选中；PNG 以 PNG 魔数开头且尺寸等于画布；content_map 每项都有
source、locator、quote、status；图中没有材料之外的实体、数字、单位。最后用两分钟抽两条
引文，拿 `show --grep` 复现一次。

## 示例（示意，不是正式案例结果）

```bash
python3 -B scripts/main.py init  --input demo/input --work demo/work --output demo/out
# 阅读 show 输出，写 demo/work/plan.json
python3 -B scripts/main.py check --work demo/work
python3 -B scripts/main.py build --input demo/input --work demo/work --output demo/out
```

维护约定：字段变动要同步 check 与 content_map；版式只动 `render_kit.compose_figure`；PNG
兜底只动 `pngkit.py`。版本 1.0.0。
