# 评分维度映射、提交前清单与已知边界

版本 1.0.0（与 `SKILL.md` 保持一致）。

## 1. 评分维度 → 本包实际产物

| 维度（权重） | 评分点 | 对应的字段 / 检查 / 产物 |
|---|---|---|
| 实际效果 40 · 完成度 15 | 主线成立、页序可讲、能在目标模板里交付 | `plan.json.slides[].role`、`deck_model.json`、按模板版式重建的 `presentation.pptx`、`compliance_checks.template_inheritance` |
| 实际效果 40 · 正确性 15 | 数字/单位/方法名/结论与论文一致，图表编号对得上，不拿示意图当数据 | `compliance_checks.number_whitelist`、`figure_refs`、`content_map.slides[].evidence[].quote`（逐字 + `matched`）、bullets 为原文前缀截断 |
| 实际效果 40 · 完整性 5 | 六要素齐：主线、页结构、图表引用、讲解逻辑、模板约束、导出 | `plan.json`、`content_map`、`presentation.pdf`、`compliance_checks.files`、`deck_model.json` |
| 实际效果 40 · 可核验性 5 | 每页可回溯到图/表/章节/页码，源文件 + 导出件 + 金标准记录俱全 | `evidence[].locator`、`content_map.coverage`、`editable_source.sha256`、`export_artifact.pdf.pages` |
| 使用增益 25 · 质量 15 | 同论文、同模板、同页数下页级正确性与版式合规稳定优于无 Skill 基线 | 固定流水线：parse → plan → build → verify；同输入得到同一份 `plan.json` |
| 使用增益 25 · 效率 5 | 端到端耗时与人工改页量 | `runtime.seconds`、单条命令、无需手工搬页 |
| 使用增益 25 · 可验证 5 | 同输入同模板 → 同结构 | 选择逻辑确定（按关键词得分再按出现顺序排序）；重跑 `plan.json` 可 diff |
| 创新 15 · 新增能力 5 | 页级图/表引用、占位符约束排版、讲稿与页面文字分离 | `evidence[].type/id/locator`、`template.layouts_used`、`notes_overlap ≤ 0.6` |
| 创新 15 · 方法改进 5 | 主线抽取、角色→页映射、图表对齐、讲稿生成 | `role_sequence(n)` 预算、caption 锚定的证据页、locator 驱动的讲稿 |
| 创新 15 · 证据 5 | 说明与通用 PPT 工具的边界 | `compliance_checks` + `deck_model.json` 可 diff；抽取失败时不造图（`assets.note`） |
| 可靠体验 10 · 调用 3 | 可被触发、一条命令、路径清晰 | `SKILL.md` §0/§2、`--help` 退出码 0 |
| 可靠体验 10 · 稳定 4 | 能打开、不崩版、可编辑、可重跑 | `inspect_deck`（zip 成员、XML 可解析、页数）、`inspect_pdf`（头 + 页数） |
| 可靠体验 10 · 异常 3 | 处理读不出的 PDF、缺图表标题、缺模板、页数不可行 | `exceptions[]`、`degradations[]`、`pending_human[]`、`status=partial/input_error` |
| 生态贡献 10 · 文档 3 | 用法、依赖、模板要求、限制 | `SKILL.md` §0–§8 + 本 references 三件套 |
| 生态贡献 10 · 复用 4 | 页骨架、证据映射、模板适配层、检查清单可复用 | `references/slide-blueprint.md`、`references/result-contract.md`、`ooxml_kit.assemble_deck()` |
| 生态贡献 10 · 分享 3 | 可分享的方法与示例，且明确标注为示例 | `SKILL.md` §7 标注「示例，非正式案例结果」 |

## 2. 提交前逐项打勾

- [x] 包根有 `SKILL.md`，frontmatter 合法（kebab-case `name`、`description`、`version: 1.0.0`）。
- [x] `python3 -B scripts/deckgen.py --help` 退出码 0，且不依赖 CWD（用 `Path(__file__).resolve().parent`）。
- [x] 仅两个脚本（`deckgen.py`、`ooxml_kit.py`），纯标准库；单脚本体积在 25 KB 以内。
- [x] 最小 case（contract + workorder + 论文 + 模板）可跑到 12 页、PDF 12 页。
- [x] `result.json` 契约键齐全，`case_id` 原样，`status` 取值合法。
- [x] `presentation.pptx` 可被 zipfile 打开，含 `[Content_Types].xml`、`ppt/presentation.xml`、`ppt/slides/slideN.xml`，XML 可解析，页数符合 workorder。
- [x] `presentation.pdf` 以 `%PDF-` 开头、页数等于页数要求（无 office 渲染器时走文本层回退）。
- [x] workorder 的 `mode` / 总页数 / source preservation / template inheritance 被读出并原样回报。
- [x] 有模板时主题与母版哈希不变（`template_inheritance.ok=true`）。
- [x] `content_map` 每页都有 claim + evidence（locator + 逐字 quote），图表编号与论文一致。
- [x] 数字白名单通过；未命中的数字只进 failures，不会硬凑上页面。
- [x] `notes_coverage` 100%，`notes_overlap` 低于阈值。
- [x] `content_map_completeness` 与 `structure_consistency` 双通过。
- [x] 空输入 / 坏 JSON / 无文本层 PDF：合法 partial `result.json`、退出码 0、`exceptions` 说明白。
- [x] 包内无预渲染正式 deck、无硬编码路径、无联网、无 `__pycache__`。

## 3. 已知边界（如实说明，不遮掩）

1. PDF 里的位图**不会**被抠出来放进页面，页面引用 `Figure N, p.X` + 图注；错误配图比缺图更糟，所以选保守策略，嵌入图片列为下一版计划。
2. 文本抽取依赖像样的文本层；扫描件退回 `status=partial`，绝不补写正文。
3. 句子选择是关键词打分而非语义理解：冷门论文可能给某个角色挑到不够中心的句子。对外汇报前应先看 `plan.json`。
4. 不产出 PNG 预览；PDF 就是渲染证据。无 office 渲染器时的文本层 PDF 只保证可解析、页数对，不保证版面保真（`degradations` 中注明）。
