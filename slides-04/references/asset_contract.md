# 审计资产字段字典

本文件说明 `--output` 下每份审计文件的字段含义、取值集合与交叉引用关系。路径一律相对输出目录，
所有取值都从本次运行的模板、pptx、PDF 回读，不存在写死的展示常量。

两类约定先写在前面：

- **自证约定**：任何"格式合规/继承真实"的结论都要带一个能在对应部件里按子串命中的证据片段；
- **降级约定**：任何依赖外部程序（转换器、PDF 工具、字体工具）的结论，在工具缺失时改成估算，
  并在产物里写明缺了什么，不把估算值伪装成实测值。

## 1. `template_spec.json` — 模板解剖

顶层字段：

| 字段 | 含义 |
|---|---|
| `spec_version` | 字段字典版本号 |
| `template` | 模板来源：`path`、`bytes`、`sha256`、包内部件数、`kind`（`case_template` 真实模板 / `synthetic` 内置骨架） |
| `slide_size` | 页面尺寸：EMU 宽高、英寸宽高、比例名与比例值、方向、取自 `p:sldSz` 的证据片段 |
| `counts` | 母版/版式/主题/模板自带页/媒体部件数量 |
| `masters[]` | 每个母版：部件名、哈希、占位符（类型/idx/名称/几何）、`clr_map`、`tx_styles`（title/body/other 的字号、行距、bullet、缩进）、标称 title/body 字号与行距、声明的版式数 |
| `layouts[]` | 每个版式：序号、部件名、哈希、名称、`type`、占位符与类型集合、颜色映射覆盖、是否显示母版图形 |
| `theme` | 主题部件名与哈希、名称、色板（每个槽位的取值方式 `sys/srgb` 与最终值）、字体方案（major/minor 各自 latin/ea/cs） |
| `theme_fonts` / `palette` | 主题字体与色板的投影，供其他模块直接取用 |
| `notes_slide_size` | 备注页尺寸（如可读出） |
| `protected_parts` | 受保护部件 → 模板原字节 sha256，是回退与漂移校验的真源 |
| `layout_map[]` | 逐页绑定：页码、页角色、版式部件/序号/名称/类型、已填与可用占位符、被"发明"的占位符、自由文本框数量 |
| `layout_map_status` | `pending_build`（先写骨架）→ `resolved`（打包后回填） |
| `layout_map_summary` | 页数、不同版式数、发明占位符总数 |
| `workorder` | 本次生效的页数、页脚、最小字号、页码要求、模式 |
| `parse_notes` | 模板解析中的异常或缺件说明 |

## 2. `format_compliance.json` — 逐项合规

单条检查固定七元组：

| 键 | 含义 |
|---|---|
| `id` | 稳定编号 `CI-01`…`CI-16` |
| `item` | 检查项名称 |
| `requirement` | 判定要求（含阈值来源，如母版标称字号、`min_font_pt`） |
| `actual` | 从产物 XML 里读回的实际值 |
| `status` | `pass` / `fail` |
| `evidence[]` | 每条含 `part`、`locator`、`snippet`、`verified_in_part`；`snippet` 必须是该部件中的真实子串 |
| `note` | 补充说明（可为空） |

顶层汇总：`items`、`total`、`passed`、`failed`、`fail_ids`、`pass_rate`、`pass`、
`template`、`template_kind`、`generated`。

十六项覆盖范围：页数（01）、页面比例（02）、母版未改写（03）、版式未改写（04）、主题未改写（05）、
逐页版式绑定（06）、占位符继承（07）、标题层级（08）、正文字号（09）、行距（10）、主题字体（11）、
色板（12）、页脚（13）、页码（14）、溢出（15）、讲稿交付形态（16）。

## 3. `export_check.json` — 导出/渲染核对

分六块：

1. `pdf`：`path`、`header`（应为 `%PDF-`）、`pages`、`bytes`、`size_in`、`mediabox_pt`、
   `embedded_font_programs`、`images`、`encrypted`，以及 v1.0 增加的两个降级标记
   `render_mode`（`converter-render` / `text-outline-fallback`）与 `text_outline_fallback`；
2. `pptx`：幻灯片数、版面英寸、比例；
3. `consistency`：PDF 页数 vs 幻灯片数、比例是否一致、说明；
4. `fonts`：主题字体列表、字体表来源（`pdffonts` 或 `/BaseFont` 扫描）、
   每个字体的判定（`embedded` / `metric_substitute` / `substituted` / `unembedded` / `not_exercised`）、
   本册是否含 CJK 文本、主题字体是否全部有结论；
5. `render_text`：真实文本框来源（`pdftotext -bbox` 或降级说明）、逐页字数、墨迹包围盒、
   越界词数与最小页边距；
6. `overflow`：估算越界的页清单、最大填充比、模型说明（CJK 1.0em / Latin 0.52em × 1.20 行高 × 4% 余量）。

`rules` 给出五个布尔结论：页数相等、PDF 比例等于版面、无估算溢出、文字都在页内、字体已嵌入，
另含 `pdf_is_visual_render`（兜底文本大纲 PDF 时为 false）。`pass` 为前五项的合取；
`status` 取值 `pass | partial | degraded_outline | no_pdf`；`degradations` 列出本次缺失的工具。

## 4. `page_diff.md` — 页级差异

四节结构：

- `§1` 模板级：尺寸、版式库、受保护部件、页数、占位符、页脚、导出结论；
- `§2` 逐页格式：页号、角色、标题、版式、占位符（已用/可用）、最大字号、页脚、页码、
  填充率、偏差；
- `§3` 逐页内容：主张、原稿定位、逐字证据、重新比对命中/未命中；
- `§4` 未解决偏差与需要人工动作的条目（与 `pending_human` 对齐）。

## 5. `version_history.md` — 版本与回退

按版本链组织：基线骨架 → 可交付成稿 → 当前包；随后给出本次运行各产物的字节数与 sha256、
自动回退（guard）的机制说明、手动回退步骤与边界。回退的最终真源永远是组织方模板原件。

## 6. `run.log` — 运行日志

每行四段：ISO8601 UTC 时间、相对起点的耗时、级别、阶段名与消息。日志逐行立即落盘，
因此进程被杀后仍保留到崩溃前一刻；`result.json` 的 `run_log` 字段给出路径、行数与阶段清单。

## 7. `result.json.rollback` — 受保护部件回退记录

| 字段 | 含义 |
|---|---|
| `strategy` | 回退策略名 |
| `source_of_truth` | 模板文件名（唯一真源） |
| `protected_parts` | 受保护部件哈希表 |
| `checked` / `drift` / `repaired` | 校验数量、漂移部件、已恢复部件 |
| `verified` | 恢复后是否与模板哈希完全一致 |
| `method` | 校验与恢复方法（逐部件 sha256、字节恢复后重打包） |
| `manual_path` | 手工核对/回退步骤 |
| `level` | 模板部件自动恢复；页面级等价的回退方式是幂等重跑 |

## 8. `result.json` 主字段（与审计资产互相引用）

- `case_id`、`status`、`editable_source`、`export_artifact`、`content_map`、`compliance_checks`、
  `exceptions` 为固定主字段；`output_contract` 声明的键原样回填（缺值写 null/[]，不删键）；
- `sources[]` 为每个输入文件的字节数与 sha256；`editable_source.template` 记录母版/主题哈希与用到的版式；
- `content_map.slides[]` 每页含 `n`、`role`、`layout_id`、`layout_name`、`placeholders_filled[]`、
  `claim`、`evidence[]`、`freetextbox_count`、`deviation`、`body_pt`、`overflow`、`notes`、
  `footer_source`、`page_number_source`；
- `compliance_checks` 含 `pass`、`failures`、`warnings`、`slide_count`、`template_inheritance`、
  `placeholder_fill_rate`、`overflow_slides`、`batch_consistency`、`pptx_pdf_consistency`、`fonts`、
  `workorder_conformance`；
- `uncertainty` / `pending_human` / `degradations` / `changes` / `errors` / `runtime` 为诚实性记录字段：
  判 `ok` 需要 `errors` 为空且其余检查全过，否则 `partial` 并在这里写原因。
