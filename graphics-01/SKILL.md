---
name: figure-lineage
description: Convert research material from an /input case into a source-bound, still-editable schematic. It reads the case workorder plus prose, tables and PDF text layers, validates every drawn label against the material, emits a layered SVG whose text remains live, produces genuine PNG/PDF exports, and returns a result.json that maps every element back to a file/line quote. Use it whenever a reviewer must be able to reopen, relabel and re-export a scientific mechanism, workflow, device or data figure without a redraw.
version: 1.0.0
license: MIT
---

# figure-lineage

## 1. 它交付什么

这个 Skill 把"一段材料"变成"三件可以直接交出去的图稿加一份可复核台账"：

| 交付物 | 形态 | 关键要求 |
|-|-|-|
| 可编辑母版 | `figure.svg` | 按层分组；文字仍是 `<text>`，未转曲；每个图元有稳定 id |
| 位图导出 | `figure.png` | 真实 PNG（IHDR 可解），不是改后缀的文本 |
| 矢量导出 | `figure.pdf` | 真实 PDF（`%PDF-` 头 + 页对象），单页 |
| 中间表示 | `figure_model.json` | SVG、导出件与台账都只从这一份模型派生 |
| 编辑记录 | `edit_record.json` | 仅编辑类案例产生：基线 sha256、改动前后、元素定位 |
| 结论台账 | `result.json` | 契约字段 + 逐元素来源 + 机器检查 + 诚实状态 |

图的科学内容只取材料里出现过的东西：名称、关系、方向、数值、单位都要能被一句原文/一个表格单元格对上。材料没写的对象不会"顺手补全"，只进入缺口记录。

**不接手的事**：统计检验与数值方法选择、海报封面与艺术插画、正文写作与摘要生成。这些不在本 Skill 的评分范围，硬做只会引入不可核验内容。

## 2. 什么时候用它

- 用户给出科研材料（md/txt/csv/tsv/json/yaml/tex/xml/pdf/既有 svg），要求"把机制/流程/装置/数据画成图"。
- 用户要求图稿"还能改"：需要分层源文件、可选文字、能按元素重绘。
- 用户要求"每个元素说明出处"，或要投稿级 PNG/PDF 与导出检查。
- 用户给定一张既有 SVG，要求按指令做局部改字并保留原结构与 id。

以下请求不要套这个 Skill：只要一段文字描述、只要配色建议、要求生成纯装饰插画、要求统计建模。

## 3. 目录与命令

```
figure-lineage/
├── SKILL.md
├── scripts/
│   ├── build_figure.py     # 入口：发现输入 → 组模型 → 渲染 → 导出 → 写 result.json
│   ├── read_sources.py     # 材料扫描、关系挖掘、模型组装、基线编辑
│   ├── layout_studio.py    # 布局、图元、分层 SVG 序列化
│   └── export_drivers.py   # PNG/PDF 引擎探测与标准库兜底
└── references/
    ├── relation-semantics.md
    ├── figure-spec.md
    └── qa-playbook.md
```

一条命令跑完整条链路：

```bash
python3 -B scripts/build_figure.py --input /input --output /app/output
```

参数说明：

| 参数 | 语义 |
|-|-|
| `--input` | 案例目录；缺省按 `/input`、`/app/input`、`./input` 的顺序取第一个存在的目录 |
| `--output` | 产物目录；缺省 `/app/output`（若 `/app` 存在）否则 `./output` |
| `--case` | 直接指定某个 `case.json`，跳过自动发现 |

运行结束**永远返回 0**：出错不是靠退出码表达，而是靠 `result.json.status` 与 `exceptions`。开始分析前会先落一份 partial `result.json`，结束时原位覆盖，所以中途崩溃也留有可读结果。

跑完之后，`--output` 目录里应当长这样（数量以实际案例为准）：`figure.svg` 是可编辑母版；`figure.png` 与 `figure.pdf` 是给人看、给投稿系统用的视图；`figure_model.json` 是这一版图面的完整快照，下次改动可以拿它做新旧 diff；`edit_record.json` 只在编辑类案例出现；`result.json` 是结论与证据的总账。评审或下游脚本只需要读总账，就能知道每张图从哪来、由什么引擎导出、哪些检查过了、哪些缺口被如实记录。

## 4. 输入怎么被理解

**先看材料，再看工单，最后看案例壳。** 材料决定"能画什么"，工单决定"想画什么"，案例壳（`case.json`）决定"回填哪些契约字段"。

- 材料：文本类扩展名直接读入；PDF 只通过 `pdftotext` 取文本层，取不到就记 `no_text_layer` 并停止猜测；csv/tsv 额外解析成表头 + 行，供数据面板使用；既有 `*.svg` 视为编辑基线。
- 工单：依次在 case 内、`*workorder*.json`、`material.json` 中找。字段按语义识别，而不是死认一个拼写：标题类（`figure_title/title`）、实体类（`required_entities/entities/nodes`）、关系类（`required_relations/relations/edges`）、基线类（`source_artifact/baseline`）、编辑指令类（`edit_operations/edits`）。
- 案例壳：优先 `case.json`；没有就扫描输入树里任意 `case*.json`。文件坏了也继续跑，坏 JSON 写进 `errors`，`case_id` 允许为 `null`。
- 契约：`output_contract` 先按原样抄进 `output_contract_echo`，然后逐个键在结果根部占位（初始 `null`）。三种写法都接受：字符串数组、对象数组（取 `name/field/key/id`）、键值对象。键名不改，未知键保留。
- 缺口：读不动的材料记 `unsupported_source:<file>`；材料里找不到的对象记 `label_not_in_source` 并进 `pending_human`。

## 5. 处理流水线

**读入 → 定内容 → 定几何 → 出文件 → 记账。** 五段各自有明确的失败出口：

1. **读入**：扫描材料、PDF 文本层、表格与基线 SVG；不可读的记下来，不假装读过。
2. **定内容**：先取工单的实体与关系；工单缺失才退到句子抽取，被动句自动调转方向，抽不到的记 `extraction_mode=extracted` 与 `uncertainty`。随后逐条做来源校核：标签做 NFKC + 小写 + 空白归一后在材料里逐字检索，命中即写 `{kind, source_id, locator, quote}`；实体未命中仍然保留但标 `verified=false`，关系只要有一端不可核验就整条不入图。
3. **定几何**：把内容落成 `figure_model.json` 的唯一一份模型（画布、样式、实体框、关系路径与端点、图例、面板、图表、图层）。没有可画内容时给空画布并记 `no_drawable_content`。
4. **出文件**：由模型生成分层 SVG（`<g id="layer-*">`，箭头/T 形/菱形端点，文字保持活字），再按引擎链导出 PNG/PDF；一个引擎都没有时启用标准库自绘，并在 `degradations` 声明。布局问题会以 `overflow` / `overlap` 失败项暴露出来。
5. **记账**：解 PNG 的 IHDR、估算非白像素比例、核 PDF 头与页对象、比对 id 集合与图例一致性、复核确定性哈希；全部通过且标签可溯源才给 `ok`，有已记录缺口给 `partial`，连材料都没读到给 `input_error`。状态必须与证据一致。

编辑类案例走另一条支路：读基线 SVG 后保留其 id、图层与坐标，只替换工单点名的文字，写 `edit_record.json` 记录原文件 sha256 与每处改动；没有任何操作命中时原图原样保留并记 `no_edit_applied`。编辑模式下若环境没有 SVG 转换器，PNG/PDF 会如实标 `missing`——因为用其它方式重画会破坏基线几何。

## 6. `result.json` 长什么样

根节点字段分四组：

**主结果** — `case_id`（原样抄回）；`status`（三选一：`ok` / `partial` / `input_error`）；`editable_source`（路径、格式、可编辑标志、图层、文字数、元素数、端点类型、sha256、坐标系、工作模式）；`export_artifact`（png 与 pdf 两个槽位，各含路径、引擎、宽高或页数、字节数、探针；缺件时给 `path:null` 加 `status:"missing"`）。

**台账** — `content_map`：实体、关系、图例、数据点、覆盖率、期望 id 列表、SVG 双哈希；`compliance_checks`：画布、SVG 结构、id 对齐、标签逐字、字号线宽、端点、图例、重叠溢出、确定性、来源文件存在性，外加 `pass` 与 `failures`。

**缺口** — `exceptions` 每条含 `type / object / reason / action / locator`；另有 `pending_human`、`uncertainty`、`errors`、`degradations`。

**运行时** — `sources`、`changes`、`runtime`（含耗时、契约字段数、输入输出目录）、`output_contract_echo`。

`content_map` 是台账核心。每条实体带 `source.locator`（形如 `artifacts/notes.md#L12`、`paper.pdf#p3+L12`、`workorder#required_entities`）和逐字 `quote`；每条关系带类型、方向与依据；数据点带 `表名#row=3,col=Expression` 与单元格原文。没有 quote 的条目不允许出现在最终图里。

## 7. 证据纪律（最容易被扣分的地方）

- 名称只从材料抄，不根据领域常识补：材料没出现的基因名、浓度、时间点、单位一律不写进图。
- 关系方向必须和句子语义一致；`STAT3 is inhibited by SOCS3` 画成 SOCS3 抑制 STAT3，不是反过来。
- 图例项数必须等于图面实际使用的编码分类数（关系类型 + 数据系列），由脚本比对，不靠肉眼。
- SVG 里每个实体、标签行、连线、图例项、柱子都有 id，`content_map.svg_ids_expected` 必须全中，缺一个即失败。
- 同一输入重复运行必须得到相同 SVG 字节；脚本用 `svg_sha256` 与 `svg_sha256_recheck` 两个哈希自证。
- 状态要诚实：有缺口就写 `partial`，把缺口和处置写进 `exceptions` / `pending_human`，不要为了好看写 `ok`。
- 每个来源定位器还要过一道"文件是否真的存在"的检查（`source_locators`），防止手改路径后无法回查。

## 8. 评分维度落在哪

- **任务完成** → 三件产物存在且非空；PNG 有真实 IHDR；PDF 有头有尾有页对象。
- **结果正确** → 关系类型映射到端点形状与颜色；被动句翻转；标签逐字检查。
- **结果完整** → 覆盖率达标、图例齐全、panel 字母与单位齐备。
- **可核验** → 每元素 locator + quote；id 集合机器比对；来源文件存在性检查。
- **质量增益** → 字号阶梯、线宽、避让、自动画布适配，一条命令完成全链。
- **效率增益** → 无手工步骤；`runtime.elapsed_s` 与引擎名都可复核。
- **增益可验证** → 确定性双哈希，两次运行字节一致。
- **创新点** → 实体—关系中间表示单向驱动全部产物；关系类型决定端点语义；表驱动图例重绘；导出前合规审计。
- **可靠体验** → 恒 0 退出、先写 partial、引擎降级表、结构化异常。
- **生态贡献** → 本说明加三份 references：关系语义、图面规范、QA 手册。

## 9. 异常与降级速查

完整对照表在 `references/qa-playbook.md` 的"故障"一节，这里只留几条必须记住的约定：

- 连材料都没有 → `input_error` + `no_result`，仍然写一份合法 result.json。
- `case.json` 损坏 → 继续跑，`case_id=null`，把解析错误写进 `errors`。
- 没有工单 → 句子抽取，`workorder_missing` + `extraction_mode=extracted` 都要出现。
- 标签在材料里查不到 / 关系端点不可核验 → 前者保留标未验证，后者整条不画；两者都要进 `exceptions` 与 `pending_human`。
- 没有 PDF 文本层、xlsx/docx 材料、没有 SVG 转换器 → 分别记 `no_text_layer`、`unsupported_source`、`missing`/`degradations`；任何情况下都不许改名冒充导出件。

## 10. 提交前自检

```bash
python3 -B scripts/build_figure.py --help                 # 期望退出码 0
python3 -B scripts/build_figure.py --input /input --output /tmp/o
python3 - <<'EOF'
import json
d = json.load(open('/tmp/o/result.json'))
print(d['status'], d['compliance_checks']['pass'], d['compliance_checks']['failures'])
print(d['content_map']['coverage'], d['export_artifact']['png']['probe'])
EOF
```

逐项排查见 `references/qa-playbook.md`。

## 11. 最小示例（示例，非正式案例结果）

输入 `case.json`：

```json
{"case_id": "demo-002",
 "organizer_workorder": {
   "workorder_type": "editable_relationship_schematic",
   "figure_title": "TNF 诱导的 NF-kB 通路",
   "required_entities": ["TNF", "TNFR1", "IKK", "NF-kB"],
   "required_relations": [{"from": "TNF", "to": "TNFR1", "type": "binding"},
                          {"from": "TNFR1", "to": "IKK", "type": "activation"},
                          {"from": "IKK", "to": "NF-kB", "type": "activation"}]},
 "output_contract": ["editable_source", "export_artifact", "content_map", "compliance_checks", "exceptions"]}
```

材料 `artifacts/notes.md`：

```
TNF binds TNFR1 on the cell surface.
TNFR1 activates IKK.
IKK activates NF-kB.
```

调用与示意输出（**示例，非正式案例结果**）：生成四实体三关系的分层图，`figure.svg` 含 6 个图层与 10 个活文字节点，`figure.png` 解析出 2400×1520 的 IHDR 且非白像素比例约 0.02，`figure.pdf` 单页；`result.json` 落到 `status=ok`、`coverage.complete=true`、`id_map.missing=[]`、`pass=true`。

## 12. 依赖、字体与维护

- 运行环境：Python ≥3.8（在 3.12 验证），只用标准库。可选程序按探测顺序使用：`pdftotext`（读 PDF）、`rsvg-convert` / `cairosvg` / `inkscape`（SVG→PNG/PDF）、`soffice`（LibreOffice Draw 导出）、`pdftoppm`（PDF→PNG）、`convert`/`magick`（ImageMagick）。
- 字体：SVG 不嵌入字体、不转曲，只在 `<g>` 上写系统回退序列（Arial → Helvetica → DejaVu Sans → 通用 sans-serif），由查看端选实际字形；标准库兜底 PDF 用 base-14 Helvetica（仅 Latin），标准库兜底 PNG 用内置 5×7 点阵字（仅 ASCII），两者都会在 `degradations` 里声明。
- 修改约定：改关系词表要同时动 `read_sources.VERB_TABLE` 与 `references/relation-semantics.md`；改画布/字号/配色要同时动 `read_sources.STYLE` 与 `references/figure-spec.md`；新增导出引擎在 `export_drivers.convert_via_engine` 加分支并在 `degradations` 说明。

## 13. 为什么是"单一中间表示"

图稿类任务最常见的坏味道是"三套几何各自手写"：SVG 一套坐标、PNG 一套绘制、台账再抄一遍文字。这样只要有任何一处改动，三者就会漂移，评审打开图改一个字就露馅。本 Skill 强制所有产物都从 `figure_model.json` 派生：布局只写一次，SVG 序列化只读模型，导出件只读同一模型，`content_map` 也只从模型取 id 与来源。因此"改标签后重导出一致性"不是靠承诺，而是结构上不可能不一致；"两次运行字节一致"也只取决于模型是否确定。

这条约束也解释了为什么导出失败时可以安心降级：母版（SVG + 模型）永远是完整的，PNG/PDF 只是视图。视图缺失时如实标记，母版仍可继续编辑。反过来，任何绕过模型、直接手改渲染结果的临时修补都会在下一次生成时被覆盖；要改就改材料或模型，而不是改渲染产物，这正是长期可维护性的来源。

之所以不用第三方绘图库当主路径，是因为评测环境未必装它，而"装了才出图"的技能在缺库时只能交空结果。标准库路径虽然字形覆盖有限，但至少保证任何环境都能交出一份真实可打开的 PNG/PDF 与一份结构完整的台账；有图像库时再把质量升级，失败面始终可控。

## 14. 一次成功运行的可观测指标

以一份 5 实体 4 关系的小案例为例，正常运行的观测量大致是：`runtime.elapsed_s` 在 1 秒以内；`figure.svg` 约 5–6 KB；`figure.png` 2400×1520、字节数 15–25 KB；`figure.pdf` 约 3 KB、1 页；`content_map.svg_ids_expected` 约 15–20 个 id；`exceptions` 为空；`failures` 为空。若某个数字明显偏离（例如 PNG 小于 2 KB 或非白比例低于 0.004），优先怀疑导出链路而不是布局。

## 15. 端到端演练（示例，非正式案例结果）

把上文串起来看一次完整操作，便于第一次使用时对照：

**第 0 步，准备。/input** 下放 `case.json`、`task.md` 和至少一份材料（例如 `artifacts/notes.md`）。如果这一题是"改既有图"，再把基线 `*.svg` 放进输入树，并在工单里写 `edit_operations`。

**第 1 步，裸跑一次。**

```bash
python3 -B scripts/build_figure.py --input /input --output /app/output
echo $?      # 恒为 0，真实结论看 result.json
```

**第 2 步，读结果。** 先看 `status`：`ok` 表示可以交；`partial` 表示有缺口但产物仍在；`input_error` 表示输入没读进来。再看 `compliance_checks.failures`：它是失败检查项的名字清单，空数组最理想。接着看 `content_map.coverage` 与 `exceptions`，确认缺口都已被解释、没有被静默吞掉。

**第 3 步，验产物。** `figure.png` 用图片查看器打开，确认不是白板；`figure.pdf` 用阅读器打开，确认是单页矢量图；`figure.svg` 用文本编辑器打开，确认文字是 `<text>`、能看到 `layer-` 分组与 `marker` 定义。三步都通过，才说明"导出件"是真的。

**第 4 步，验可编辑性。** 在 SVG 里改一个 `<text>` 的内容，用任意 SVG 渲染器重新打开：改字应该只影响那一处，说明图层与文字结构有效。如果一改就全图散架，通常意味着文字被转曲或被合并成了 path。

**第 5 步，验确定性。** 换一个输出目录再跑一次，比对两次 `figure.svg` 的 sha256；不一致就要定位非确定来源，而不是接受"偶尔不同"。

**第 6 步，留档。** 把 `result.json`、`figure_model.json`、`figure.svg` 与导出件一起交付；评审需要的是"图 + 证据"，不是孤零零一张 PNG。

这一套流程在 5 实体 4 关系的小案例上通常 30 秒内能走完，其中真正耗时的只有 PDF/PNG 引擎探测。

## 16. 已知边界

- 关系抽取是句法启发式，不建模时序、剂量、条件、可能性；复杂句可能抽错端点，逐条 quote 供人工复核。
- 布局是确定性的分列启发式，不是期刊级手工排版；实体超过约 16 个时建议给全工单。
- xlsx/docx 不解析；扫描版 PDF 无文本层时不猜内容。
- 编辑模式只替换文字，不新增/删除图元；编辑模式依赖外部 SVG 转换器才能出位图预览。

## 17. 术语小抄

读 `result.json` 时容易混淆的几个词，统一在这里定义：

- **中间表示**：`figure_model.json`，图面几何与语义的唯一事实来源，不是给人看的草稿。
- **台账**：`content_map`，把图面元素（实体、关系、图例、数据点）映射回来源文件、行号与逐字原文。
- **活字**：SVG 中仍是 `<text>` 的文字，可选中、可编辑、可换字体，与转曲轮廓相对。
- **探针**：对导出件做的独立体检，PNG 看 IHDR 与像素分布，PDF 看魔数、尾标记与页对象。
- **降级**：本应使用某条路径但环境不支持时，如实换成更弱的路径并记录，而不是隐藏或伪造。
- **引擎链**：从强到弱排列的一组导出后端，前面的失败才轮到后面的，最终用了哪个必须写进结果。
- **覆盖面**：`coverage`，账本里已映射到来源的元素数与必需元素数之比；等于 1 才可能拿到 `ok`。
- **确定性**：同一输入重复运行得到逐字节相同的 SVG；由双哈希字段与 `determinism.ok` 共同证明。

## 18. 维护者清单

接手修改时按顺序看四处：先看本文件确认契约与边界；再读 `scripts/read_sources.py` 的模型组装；然后看 `scripts/layout_studio.py` 如何把模型变成分层 SVG；最后看 `scripts/export_drivers.py` 的引擎链与兜底。任何行为改动都要重跑一次冒烟案例，并把 `result.json` 的 `status`、`failures`、`coverage`、`determinism` 四个值当回归基线；改了词表或样式默认值，记得两处同步（代码常量 + 对应 reference）。
