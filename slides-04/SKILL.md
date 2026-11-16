---
name: paper-deck-template-binder
description: Bind the source paper in an evaluation case to the organizer's real PowerPoint template and deliver an editable deck plus an auditable evidence trail. The skill inspects the template package with the standard library, writes every page onto an existing slide layout so master, theme, type ladder and colour slots are genuinely inherited, maps each page claim back to a verbatim source quote with a locator, emits a rendered PDF (or an explicitly degraded text-outline PDF when no converter is installed), and packs per-item conformance evidence, a page-by-page diff, a version/rollback ledger, a run log and an export check. Use it when a case supplies a .pptx master/layout template and a starting deck and asks for a template-conformant academic talk with reviewable slides.
version: 1.0.0
---

# 论文→模板演示装订器（slides-04 执行手册）

一句话：**模板只借格式，事实只取 `/input`**。所有页面落在组织方模板已有的版式上，所有结论都能被
`unzip`、`grep` 或产物目录里的表格重新核对。

## 0. 30 秒速查

```bash
# 一次完整交付（在任意工作目录调用均可，脚本按自身路径定位同级模块）
python3 scripts/main.py --input /input --output /app/output \
    --template /input/<模板.pptx> --slides N
# 维护者自检（构造最小案例 + 三条降级路径断言）
python3 -B scripts/regression_check.py
```

退出码**永远为 0**；失败信息进 `result.json` 的 `errors` / `degradations`，不会以非零码中断评测。
`--help` 打印用法，含 `--input/--output/--template/--slides` 四个原始选项与可选 `--deck/--no-pdf`。

（下文的产物示例数值均为示意，不是正式案例成绩。）

## 1. 职责边界

做：
- 把输入材料组织成主线清晰的页面序列（封面/提纲/正文/图表/结论），页数与 workorder 对齐；
- 每页填进模板真实占位符，几何、字号、行距、主题字体与配色从母版继承；
- 为每页登记主张、原文逐字引用与定位，并给出内容与版式的偏差记录；
- 交付可继续编辑的 pptx、导出 PDF（含降级形态标注）、逐项合规证据与可复核账本。

不做：
- 不评价学术价值，不补造数据、图表编号或引用；
- 无模板时不会假装继承母版：改用内置骨架包，并在 `degradations` 与
  `template_spec.template.kind="synthetic"` 里写明"继承不计分"；
- 不在 pptx 中写 `notesSlide` 部件；讲稿文本保存在 `content_map[].notes`，该交付形态由
  `format_compliance` 的 CI-16 记录。

## 2. 输入盘点（先找齐，再动手）

1. **模板**：`--template` 显式指定；否则挑文件名含 template/master/layout/theme/brand/style 的
   pptx；仍没有就取目录里第一个 pptx。判据是包结构：zip 可开且存在 `ppt/presentation.xml`，
   否则算不可读模板。
2. **起始稿**：`--deck` 优先；否则挑名字含 start/deck/draft/current/original/source 的 pptx；
   都没有就沿用模板本身。
3. **案例元数据**：`case.json` 的键名允许被改写，按语义查找
   （`output_contract`、`organizer_workorder`、`total_slide_count`、`footer_text`、
   `page_number_required`、`min_font_pt`、`audience`、`task_instruction`）。
4. **论文正文**：优先级 `.md/.markdown` → `.txt` → `.docx` → `.pdf` → `.tex`，同类取体积最大。
   PDF 只有 `pdftotext` 可用时才抽文本；没有文本层就记为 `no_source_text`，只出标题级骨架。
5. **图片**：`.png/.jpg/.jpeg/.bmp/.gif`，按魔数读宽高做等比缩放；名称含 logo 的排除。

内容判定只看字节与结构，不看文件名暗示的领域：模板是不是真的模板、图片能不能解码、PDF 有没有
文本层，都以实际解析结果为准。

## 3. 调用面

| 参数 | 默认 | 说明 |
|---|---|---|
| `--input` | `$INPUT_DIR` 或 `/input` | 案例目录 |
| `--output` | `$OUTPUT_DIR` 或 `/app/output` | 产物目录，不存在会自动创建 |
| `--template` | 自动发现 | 显式模板 .pptx |
| `--deck` | 同模板 | 显式起始稿 .pptx |
| `--slides` | workorder 值 | 覆盖目标页数 |
| `--no-pdf` | 关 | 跳过 PDF 导出（调试用；正式案例不要带） |

外部程序全部是可选增强：`soffice`/`libreoffice` 负责真渲染 PDF，`pdftoppm` 生成 PNG 预览，
`pdftotext`/`pdffonts` 提供真实文本框与字体表，`fc-match` 判断字体回退。任一缺失都会降级并在
报告里写明缺少哪个工具。

## 4. 交付物矩阵

输出目录固定包含下列文件（`result.json` 用 `path` + `sha256` 指向它们）：

| 文件 | 内容要点 |
|---|---|
| `presentation.pptx` | 可编辑演示稿；每页一个 `p:sld` + 模板版式关系；母版/版式/主题部件保持模板原字节 |
| `presentation.pdf` | 真实导出的 PDF；无转换器时写"文本大纲 PDF"并在 `export_check.pdf.render_mode` 标注 |
| `result.json` | 契约总表：case_id、status、六类主字段、契约原键回填、来源、不确定性、降级与改动记录 |
| `template_spec.json` | 模板解剖结果：页面尺寸、母版与 txStyles、版式库与占位符、主题字体/色板、受保护部件哈希、逐页 layout 映射 |
| `format_compliance.json` | CI-01…CI-16 逐项：`status` + 写入 XML 的实际值 + 支撑片段 `evidence[]` |
| `page_diff.md` | 模板级/逐页格式级/逐页内容级差异，含来源引用的重新比对命中统计 |
| `version_history.md` | 基线 → 成稿 → 本包的版本链、产物哈希、手动回退步骤 |
| `run.log` | 追加式阶段日志（时间、耗时、阶段、消息），崩溃也保留 |
| `export_check.json` | PDF 头/页数/尺寸、字体表与替换判定、真实文字越界、溢出估算、`render_mode` |
| `preview/`（可选） | `pdftoppm` 可用时前几页 PNG 预览 |

`result.json` 的兜底骨架在任何工作开始前就已落盘，因此中途异常也一定有一个合法文件可读。

## 5. 执行流水线（与 run.log 的阶段名一致）

`main.start` → `main.init` → 输入盘点 → 模板解剖 → 写 partial `template_spec` → 正文抽取 →
页级计划 → 打包 → 保护部件校验/修复 → PDF 导出与降级 → 回填 layout 映射 → 逐项合规 →
导出检查 → 页级 diff → 版本账本 → 契约回填 → `main.done`。

装配规则：
- 每页只引用模板中真实存在的 `slideLayout`，并优先写入该版式声明过的 `<p:ph>`；
- 页面里不写死坐标、字号、字体与颜色，全部继承母版与主题；
- 版式缺目标占位符时才用自由文本框，并在 `content_map[].deviation` 与 `freetextbox_count` 记账；
- 打包后重新计算受保护部件的 sha256；发现漂移就从模板原件恢复对应部件再重新打包。

## 6. 模板继承怎么算"真"

四个可机器复核的条件，全部进 `compliance_checks.template_inheritance` 与 `format_compliance`：
1. `ppt/slideMasters/*.xml` 与 `ppt/theme/*.xml` 的 sha256 与模板原件一致（`CI-03/04`）；
2. 每张幻灯片的 rels 目标确实落在模板 `slideLayouts/` 内（`CI-06` 与 `template_spec.layout_map`）；
3. 每页实际填充的占位符类型是该版式占位符类型的子集（`CI-07`），`placeholder_fill_rate` 越高越好；
4. 页面 `sldSz` 与模板一致（`CI-02`），标题文本与母版 `titleStyle` 字号层级匹配（`CI-08`）。

字体与色彩同样走继承：字号集合受 `min_font_pt` 约束（`CI-09`），页面不写死行距（`CI-10`），
latin typeface 不硬编码（`CI-11`），硬编码 RGB 必须落在主题色板内（`CI-12`）。

## 7. 页内容与证据定位

- 每页登记一个主张（claim）与一到多条 `evidence`，每条含 `quote`、`locator`、`kind`；
- `quote` 是来源文本的逐字片段，`locator` 形如 `§章节 ¶段 / p.页码`；
- 分句时只在标点后紧跟空白处断句，保证 `6.8 C`、`0.3 to 25 um` 这类带小数的数值不被切碎；
- `page_diff.md` 会把每条 `quote` 在源文本里重新做子串比对，命中/未命中数量公开；未命中不会
  被隐藏，而是写进 `pending_human`，**不改原文来凑通过**；
- 图表页要求图注也是逐字引用；找不到图注时记 `figure_embedded_without_verbatim_caption`。
- 格式类结论一律附带 `evidence.snippet`（部件内真实存在的 XML 片段）与 `verified_in_part`。

## 8. 状态判定与人工确认

`status` 取值 `ok | partial | insufficient_evidence | input_error`。判 `ok` 需同时满足：编排合规
`compliance_checks.pass`、PDF 存在、`format_compliance` 无 fail、`export_check.pass`、
模板非合成、`errors` 为空。任一不满足即 `partial`，并在 `uncertainty` 写清原因。

需要人确认的情形：
- 页数上限与章节数冲突：先保封面/提纲/结论，压缩正文页并写 `changes`；
- 主题字体在本机缺失、图注缺失、模板没有 ftr/sldNum 占位符、PDF 只能降级：逐项进
  `degradations` 与 `pending_human`，不静默替换、不声称"已修复"；
- 模板损坏到不可解析：不猜结构，走内置骨架包并如实降级。

## 9. 导出与渲染降级（v1.0 新增能力）

- 有 `soffice`/`libreoffice`：转真 PDF；`pdftoppm` 在时补 PNG 预览；
- 没有转换器时**不再空手交付**：`main.publish` 的兜底写作器从打包好的 pptx 里读回每页文本，
  直接生成一份页面数、页面尺寸都与 pptx 一致的 PDF（`%PDF-` 头、`/MediaBox` 与版面比例一致、
  内置 Helvetica、不含嵌入字体）。该产物是**文本大纲而非视觉渲染**，因此：
  - `export_check.pdf.render_mode="text-outline-fallback"`、`rules.pdf_is_visual_render=false`、
    `status` 记为 `degraded_outline`；
  - `result.json` 的 `degradations` 记录 `stage=pdf_export` 与缺失原因；
  - `export_artifact.pdf.engine` 标注真实引擎，`pages` 与幻灯片数对齐。
- 有 PDF 后仍要核对：页数=幻灯片数、PDF 页面比例=版面比例、文字框不越界、字体嵌入/替换结论。
  `pdffonts` 缺失时退化为扫描 `/BaseFont`；`pdftotext` 缺失时退化为 XML 几何估算，并写明来源。

## 10. 溢出与图表适配

- 溢出模型：每字符 advance（CJK 1.0em / Latin 0.52em）× 行高 1.20 × 4% 安全余量，
  按固定版心宽度估行数；`export_check.overflow` 给出每页 `fit_ratio` 与越界清单；
- 处理顺序是**先收文案 → 再降一档字号（不低于 min_font_pt）→ 仍超则截断并记
  `text_trimmed_to_fit:N`**，不允许无限压字号硬塞；
- 图片按容器等比缩放（`fit_rect`），不改纵横比；无图注时逐字引用与偏差记录双写。

## 11. 自检与回归

1. `python3 -B scripts/main.py --help` → 退出 0，用法包含四个原始选项；
2. 造最小案例跑一遍，确认：pptx 可被 zipfile 打开、幻灯片数=要求、`presentation.pdf` 以
   `%PDF-` 开头、`result.json` 与六个审计资产全部存在且 JSON 可解析、`output_contract` 的键
   全部回填（缺值用 null/[]）；
3. 三条降级路径（空输入目录 / 坏 `case.json` / 缺元数据与模板）必须退出 0，仍有合法
   `result.json` 与最小 pptx；
4. `format_compliance` 每项都有 `actual` 与非空 `evidence`；`page_diff` 的未命中数与
   `pending_human` 条数一致；
5. `python3 -B scripts/regression_check.py`：一次性执行上面的正例与反例，末行打印
   `SELF-CHECK PASSED` 且退出 0（Windows 上临时目录删除失败不影响退出码）。

## 12. 维护入口

- 新增合规项：在 `template_kit.compliance()` 里追加一条，保持
  `id/item/requirement/actual/status/evidence/note` 七元组；报告与 `result.json` 投影会自动跟随。
- 换模板：只换 `--template`，页面尺寸/版式/字体/色板均从模板读，没有写死 16:9。
- 溢出模型：`template_kit.est_height()` 可调，改完重跑并看 `export_check.overflow`。
- 页面调度：`slide_engine.page_specs()`；脚本级回归见 `regression_check.py`。
- 已知限制：单母版假设（多母版只用第一套 txStyles）；不写 notesSlide 部件；不做动画/切页；
  PDF 视觉渲染依赖 `soffice`，缺失时以文本大纲 PDF + 明确降级状态交付。

## 13. 包内文件

| 文件 | 职责 |
|---|---|
| `SKILL.md` | 本手册（执行契约、判定规则、降级口径） |
| `scripts/main.py` | CLI、输入发现、页级装配、打包/保护校验、PDF 导出与兜底、编排与契约回填 |
| `scripts/slide_engine.py` | 正文抽取、分句与页计划、OOXML 发射、deck 基础检查 |
| `scripts/template_kit.py` | 模板解剖、16 项合规、导出/渲染检查、保护部件回退、内置骨架包 |
| `scripts/audit_docs.py` | `run.log`、`page_diff.md`、`version_history.md` 与回退记录 |
| `scripts/page_assets.py` | 页级资产：`page_golden.json`、`template_check.json`、`self_check.json`，给 `page_diff`/`version_history`/`export_check`/`format_compliance` 追加页级核验（build 收尾自动写） |
| `scripts/regression_check.py` | 一键回归（正例 + 三条降级路径断言） |
| `references/asset_contract.md` | 审计资产与 `result.json` 字段字典 |

全部为 UTF-8 文本、仅标准库、无软链接、无网络依赖；不打包预渲染的正式案例产物。
