---
name: talk-deck-studio
description: 把已有的研究材料（PDF/DOCX/MD/TXT/CSV/XLSX/PPTX）组织成一份能直接上台的学术汇报：先按听众、时长与页数约束写出逐页主张与证据定位，再生成真实可编辑的 pptx（母版可继承、逐页讲稿备注）、真实 PDF 预览、逐页证据映射与合规自检。适用于组会、答辩、评审、合作方汇报等"从材料到可讲页面"的组织与交付；不适用于论文精读、成稿写作或科研绘图本身。
version: 1.0.0
---

# 学术汇报编排：从已有材料到可讲页面

## 1. 这个 Skill 做什么、不做什么

**做**：内容取舍、叙事顺序、逐页主张与要点、证据定位（原文逐字引用）、讲稿备注、图表引用绑定、模板母版继承、pptx 渲染、PDF 预览、交付自检。

**不做**：论文精读与翻译、论文写作本身、科研绘图、数据或文献编造。材料缺页、缺图、缺数字时，只能如实标缺口，不能补出"看起来完整"的内容。

**判对错的标准不是页数或模板华丽度，而是三件事**：页面上每个论断都能回到源材料的某个位置；叙事顺序服务于指定听众与时长；从材料到成片的取舍过程别人能独立复核。

## 2. 运行契约

| 项目 | 约定 |
|-|-|
| 输入 | `/input/case.json`、`/input/task.md`，以及 `/input/` 下递归出现的材料文件（PDF/DOCX/XLSX/PPTX/CSV/MD/TXT，可含模板或起始稿） |
| 工作区 | `/app/work`：`materials.json`（材料索引）、`index.md`（人读索引）、`slide_plan.json`（**由你手写**）、`check_report.json`（校验报告） |
| 产物 | `/app/output`：`presentation.pptx`、`preview.pdf`、`slide_plan.md`、`content_map.json`、`compliance_checks.json`、`result.json`，外加核验资产（第 10 节） |
| 依赖 | 仅 Python 3 标准库；不联网；不依赖当前目录。`soffice/libreoffice`、`pdftotext` 为可选增强，缺失时自动降级 |
| 退出码 | 恒为 0；所有异常写进 `result.json.errors`，不吞掉 |
| 预算 | 平台 64 次模型请求 / 900 秒；脚本自身约数秒完成 |
| 环境变量 | 可用 `IN_DIR` / `WORK_DIR` / `OUT_DIR` 覆盖默认根目录（便于本地试跑） |

`result.json` 必须原样回填 `output_contract` 的每个字段（无值用 `null`/`[]`，但键不能少），并附带 `case_id`、`status`、`sources`、`uncertainty`、`pending_human`、`errors`、`degradations`、`changes`、`runtime`、`deliverables`，以及金标准、差异报告、版本记录、自检、产物审计五组核验字段（只写路径与计数，文件本体在 `output/`）。

## 3. 四步流程

脚本按 `__file__` 定位自身，放在哪个卷都能跑；下面的 `/skills/weekly-skill` 是评测时的安装位置。

```bash
cd /app/work 2>/dev/null || cd .
python3 /skills/weekly-skill/scripts/deckctl.py init
python3 /skills/weekly-skill/scripts/deckctl.py show --grep '<关键词>'
#   ← 你（Agent）读完 show 打印的原文后，手写 work/slide_plan.json
python3 /skills/weekly-skill/scripts/deckctl.py check     # 逐字校验 quote，FAIL 就地改
python3 /skills/weekly-skill/scripts/deckctl.py build     # 出 pptx + PDF + 全部结果文件
```

若安装路径不同，改用 `python3 scripts/deckctl.py <子命令>` 即可，参数语义完全一致。

**为什么计划必须由你写**：`init` 只做材料索引（给每段一个 `[M1#p7]` 形式的 locator），`build` 不会替你读论文。读原文、判断听众与取舍、写逐页计划是你的工作；脚本负责校验与渲染。这也是本 Skill 与"模板一键生成器"的分界线。

## 4. 工作稿 `work/slide_plan.json`

完整字段字典见 `references/plan_contract.md`，这里给最小可用骨架：

```json
{
  "deck_title": "汇报主标题",
  "subtitle": "场合 / 日期",
  "audience": "听众类型（决定背景比例与术语解释范围）",
  "duration_min": 12,
  "target_slides": 8,
  "goal": "本次汇报要达成的可检查目标",
  "narrative": [{"act": "问题", "slides": "2-3", "purpose": "让听众接受这个问题值得解决"}],
  "slides": [
    {"n": 1, "title": "封面标题", "layout": "title", "subtitle": "副标题",
     "bullets": [], "notes": "开场 30 秒：听众、时长、要回答的问题"},
    {"n": 2, "title": "一句话结论式页标题", "claim": "本页唯一主张",
     "bullets": [{"text": "听众能复述的要点", "locator": "M1#p12",
                  "quote": "源材料里逐字出现的一段原文"}],
     "visual": "引用哪张图/表；没有就写'无（材料未提供）'",
     "evidence_strength": "strong|moderate|weak|unrated|none",
     "notes": "讲法：先讲什么、什么条件、被追问先答哪句"}
  ],
  "qa": [{"q": "可能的追问", "a": "与页面口径一致的回答", "backup": "指向第几页"}]
}
```

硬性要求：内容页要点 **3–5 条**；每条要点至少有 `quote`（逐字）或 `locator`；`notes` 必须提供页面之外的信息（讲法、适用条件、被追问时的第一句），不能复述页面文字；`layout: "title"` 只给首页。

## 5. 组织方法（评审最看这一段）

1. **约束先行**：先看 `init` 打印的 `hints`（audience / duration / slides）。题面给了页数就按页数做；没给就按 `1 页 ≈ 1.2–1.5 分钟` 反算并写进 `target_slides`。
2. **听众决定取舍**：组会/进展类重方法与风险，背景压缩到 1 页；答辩/评审类重创新点与边界，证据强度优先；跨领域听众只讲输入输出与直觉。术语只解释听众可能不会的。
3. **叙事不按论文目录搬**：主干是 问题（谁受影响）→ 现有做法为何不够 → 我们的做法 → 关键证据（2–3 页）→ 边界与结论。每页只回答一个问题。
4. **页标题写答案**：`"Top-1 从 31.4% 提升到 46.8%"` 比 `"实验结果"` 好；标题是结论，要点只是支撑。
5. **数字必须可回溯**：百分比、样本量、时长、p 值要在对应 `quote` 里逐字出现；同一数字跨页只允许一种口径。
6. **证据强度不越级**：单数据集、单模型、无对照 → `moderate` 或 `weak`，并在 `notes` 写明适用条件；相关性不写成因果。
7. **问答准备 ≥2 条**：覆盖机制、数据、对照、局限，答案与页面口径一致并指向存在的备用页。

展开版规则（听众矩阵、时长换算、三种场景骨架、页级检查清单、已知限制）见 `references/deck_rules.md`。

## 6. 证据规范

- locator 形如 `M<材料号>#p<段号>`：`M1` 是 `init` 给材料编的号，`p12` 是该材料第 12 段（PDF 走 pdftotext 的段落切分）。一律用 `show` 复制，不要手写猜。
- `quote` 必须是源材料中**逐字**出现的片段（允许跨行；脚本去掉空白后做包含匹配）。改写、翻译、拼接都会 FAIL。
- 一条要点对一条证据；同一段可以支撑多条，但一页不要只靠一段就堆 5 条。
- 材料没有的图、数、对照，写进 `pending_human` 或 `visual: "无（材料未提供）"`，不要造。
- `content_map.json` 会记录每条要点的 `quote`、`locator` 和脚本解析到的 `verified` 位置，供他人复核。

## 7. 模板、渲染与导出

- 输入里有 `.pptx`（模板或起始稿）时，`build` 默认继承它的**母版、版式、主题与字体**，只替换幻灯片内容；`compliance_checks.template.mode` 会记 `template_rebuilt` 或 `builtin_master`。继承失败会自动回落到内置母版并写 `degradations`，不要因此中断。
- 无模板时用内置母版：16:9（12192000×6858000 EMU），深蓝标题（1F4E79），Arial + Microsoft YaHei。
- 预览：优先 `soffice --convert-to pdf` 生成 `preview.pdf`；没有 LibreOffice 时用标准库写文本版 PDF 并如实记录降级。pptx 与 PDF 的页数由脚本交叉核对。
- pptx 是真实 OOXML：zip 可解压，含 `ppt/slides/slideN.xml` 与 `ppt/notesSlides/`，可在 PowerPoint / WPS / LibreOffice 里继续编辑。

## 8. 异常与兜底（脚本已实现，不要绕过）

| 情况 | 脚本行为 | 你需要做的 |
|-|-|-|
| `slide_plan.json` 缺失/不合法（quote 找不到、要点数越界、页数不符） | 退化为确定性计划：按源材料句子分段成页，每页 3–5 条，全部带 locator+quote | 先 `check` 修好；兜底计划不体现你的判断，质量分会低 |
| 个别材料解析失败 | 记入 `errors`，其它材料继续处理 | 在 `uncertainty` 里说明影响范围 |
| 材料全是图像/无文字层 | 只产出缺口页，status 降为 `partial`/`input_error` | 在 `pending_human` 里要求补文字版 |
| 模板继承失败 | 回落内置母版 + `degradations` | 交付时提示复核版式与字体 |
| LibreOffice 缺失 | 标准库文本 PDF + `degradations` | 提示在桌面端复核换行与字体 |
| 输入为空 / `case.json` 是坏 JSON | 仍写出合法 `result.json`（`input_error`/`partial`）和最小核验资产，退出码 0 | 在回复里说明缺了什么 |

## 9. 交付前自检

- [ ] `check` 无 error：`quotes_checked == quotes_verified`，`usable: true`
- [ ] 页数 = `hints.slides`（或已在 `pending_human` 说明为何不同）；内容页每条 3–5 个要点
- [ ] 每页 `notes` 非空，且不是页面文字的复述（看 `compliance_checks.notes_not_repeating`）
- [ ] `content_map.json` 每条要点都有 `locator` 与 `verified`
- [ ] `presentation.pptx` 存在，`pptx_editable.pass = true`；`preview.pdf` 以 `%PDF-` 开头且页数与 pptx 一致
- [ ] `result.json` 的 `output_contract` 键齐全，`status` 与真实完成度一致
- [ ] 缺口全部进 `pending_human` / `uncertainty`，没有把推断写成事实
- [ ] 五个核验资产在 `output/`，`self_check.overall` 与 `artifact_audit.pass` 与真实产物一致

## 10. 核验资产（`build` 自动生成，无手写答案）

| 文件 | 内容 |
|-|-|
| `golden_standard.json` | 由 case.json / task.md / 材料规则推导的期望标准：约束 K1–K5、幕结构与预算秒、逐页期望（locator+quote，缺证页标 `expected_gap`）、讲解逻辑 L1–L7、验收项 C01–C20 |
| `diff_report.md` | 产物与期望逐项对照：`pass` / `deviation` / `missing` / `unmeasured` + 依据 + 处置建议 |
| `version_history.md` | Skill 包版本与本次产物版本，含"改了什么/为什么/如何回退"的可执行命令 |
| `run.log` | 追加式 `[+秒]` 时间线，跨 init/check/build 累积，含降级与异常 |
| `self_check.json` | 契约字段、证据覆盖率、数字一致性、三个兜底探针；`overall` 只看运行完整性 |
| `artifact_audit.json` | **本包自研增量**：build 末尾重新打开真实产物做二次核验——pptx 成员/页/备注数、PDF 头与页数、content_map 条数、契约键回填、status 诚实性；任一项不符则记 `failures` 并把本次运行标为 partial |

这些文件由 `evidence_audit.py` 在 `build` 时现场计算，重跑即重算；单项失败只降级该项并写 `degradations`。

## 11. 最小调用示例（示意，非正式案例结果）

输入 `case.json` 摘要：

```json
{"case_id":"demo-001","audience":"课题组组会","duration_minutes":12,"slide_count":8,
 "output_contract":{"editable_source":null,"export_artifact":null,"content_map":null,
   "compliance_checks":null,"exceptions":null}}
```

材料 `paper.md` 中有一句 `Top-1 accuracy improves from 31.4% to 46.8% on the 500-reaction subset.`

```bash
python3 scripts/deckctl.py init      # materials=1, hints={audience,duration,slides}
python3 scripts/deckctl.py show --grep accuracy
#   [M1#p12] Top-1 accuracy improves from 31.4% to 46.8% on the 500-reaction subset.
# → 手写 work/slide_plan.json（标题页 + 4 页内容页，12 条 quote）
python3 scripts/deckctl.py check     # {"quotes_checked":12,"quotes_verified":12,"usable":true}
python3 scripts/deckctl.py build     # status=partial（页数 5≠目标 8，已写 pending_human）
```

产物：`presentation.pptx`（5 页，逐页备注）、`preview.pdf`（5 页）、`slide_plan.md`、`content_map.json`、`compliance_checks.json`、`result.json`。示例中的数值只取自示例材料，不代表任何正式案例。

## 12. 包内文件与维护

```
SKILL.md                          本说明
references/plan_contract.md       slide_plan.json 字段字典与校验语义
references/deck_rules.md          听众/时长/叙事/问答规则与检查清单
scripts/deckctl.py                CLI：init / show / check / build
scripts/materialkit.py            材料发现、文本抽取、契约路由、计划校验与确定性兜底
scripts/slidewriter.py            OOXML pptx 生成（内置母版/模板继承）+ LibreOffice PDF 导出
scripts/rules_core.py             规则表、期望标准推导、数字扫描与逐项评分（纯规则）
scripts/evidence_audit.py         金标准/差异报告/版本记录/run.log/自检/产物二次核验
```

维护提示：新增材料类型只需扩 `materialkit.load_material_text`；新增版式改 `slidewriter.render_slide`；新增验收项在 `rules_core.ACCEPTANCE` 与 `grade_items` 同步加。版本 1.0.0，纯标准库、无网络、无硬编码绝对路径。
