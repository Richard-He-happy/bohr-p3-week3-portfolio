# 维护与复用说明

本文件面向"要换案例、要嵌进流水线、或要改代码"的人。普通使用只需要读 `SKILL.md`。

## 1. 换案例的最小步骤

1. 把新材料放进输入根（`case.json` 可以没有；材料名不限）。
2. `python3 -B scripts/run_build.py init` —— 建索引，同时写出一个合法的 partial `result.json`。
3. 用 `show --material M01 --start 1 --limit 20` 浏览原文，**复制**将要引用的句子。
4. 编辑 `work/questions.draft.json`，字段写法见 `references/question-spec.md`。
5. 先 `check` 再 `build`；`build` 覆盖写、幂等，重复跑不会叠加。
6. 要留档：把输出目录整体复制成 `output.v1` 之类，再继续迭代。

完全没有草稿也能出包（`mode=fallback_minimal`、`status=partial`）：脚本会从真实段落生成最小
摘录/数值题。这是保证"不空手而归"的兜底，正式交付前应当用人工题替换掉。

## 2. 三种复用姿势

**当命令行工具批量跑**：四个 verb 都接受 `--input` / `--output` / `--work`；也可以不改命令行，
改环境变量 `READBENCH_IN` / `READBENCH_OUT` / `READBENCH_WORK`。外层循环逐案例跑 `init` 到 `build` 即可。

**当 Python 库嵌进别的程序**：

| 需求 | 调用 |
|---|---|
| 只要材料索引 | `reading_core.index_input(input_root)` |
| 只要引文核验 | 先 `build_corpus(index)`，再 `locate_quote(corpus, material_id, quote)` |
| 只要题卡校验 | `reading_core.audit_items(draft_dict, corpus)` |
| 只要字段归一 | `reading_core.coerce_item(raw_item, seq_no)` |

**接自己的评分器**：拿 `benchmark.json`（题面 + rubric + 参考要点）和 `anchors.json`
（locator + 逐字引文）当输入，`scoring.json` 是可判性自检，允许整体替换成更强的评分器；
只要保证"每题分数都能回到一条 `locator`"这条约束即可。

## 3. 想改代码时看这里

- **新增题型**：`reading_core.KINDS` 加枚举值。`type` 不参与算分，只在报告里分组。
- **调评分档位**：`run_build.grade_items()` 中 `s = 2 if x >= 0.6 else (1 if x > 0 else 0)`；
  这一行同时定义了阈值（0.6）和档位映射，改动即语义变更，必须升版本。
- **支持新材料类型**：在 `reading_core.sniff_kind()` 判型、在 `extract_material()` 加抽取分支；
  抽取失败必须返回 `("", "none", 原因)` 而不是抛异常，否则一个坏文件会拖垮整次索引。
- **替换 PDF 解析**：`pdf_extract()` 目前探测 pdftotext → PyMuPDF → pdfminer → 内置 zlib；
  平台若有自研解析器，插到探测链最前面（引文能否核验依赖它）。
- **改报告版式**：`run_build.render_report()`；它的入参只有已算好的四份数据，不依赖全局状态。
- **加结构断言**：`run_build.self_audit()` 的 `checks` 列表；加完同步更新
  `references/contract-map.md` 的 §2，否则文档与实现不一致。

## 4. 已知限制

- 图片材料不做 OCR：只登记缺口，需要 Agent 或平台工具先读文字。
- 引文核验是字符串层面的逐字比对：改写、翻译、跨句拼接一律不通过（这是防伪设计，不是 bug）。
- `key_terms` 覆盖度是启发式：中文 4 字滑窗、英文 ≥4 字母词；短术语请手工写进 `key_terms`。
- 自检分回答"能不能判"，不回答"题难不难、好不好"；难度分布请看 `benchmark.json` 的
  `difficulty` 字段，别拿自检分当质量分。
- 兜底题只有摘录和数值两种，覆盖不了推理、冲突、跨段对比类题。
- 单线程实现；很大材料建议先用 `show` 定位到需要的段，避免整篇进上下文。

## 5. 排查清单（出现异常时按顺序看）

1. `--help` 是否 0 退出？脚本能不能被当前解释器导入？
2. `work/index.json` 里材料的 `status` 是否 `ok`？`degradations` 有没有记录？
3. `work/check_report.json` 的 `issues` 第一条是什么？通常是引文或 locator。
4. `result.json` 的 `status` 与 `pending_human` 是否与预期一致？
5. 输出目录是否可写？三条根路径是否指到了预期位置（看 `runtime.input_root` / `output_root`）。

## 6. 版本记录

当前 1.0.0：五步主流程（init → show → 草稿 → check → build）；`M01#pN` 稳定 locator；
点级 0/1/2 算分；契约字段回填；确定性兜底题；checker 日志只登记不评分；6 项结构自检；
路径参数化（`--input/--output/--work`）。

升版本时同步三处：`SKILL.md` 的流程与限制、`scripts/reading_core.py` 的 `V` 常量、本文件本表。
**凡是影响算分结果的改动（阈值、档位、权重处理）都必须写进本表并升版本**，否则前后分数不可比。

## 7. 移交给别人时

- `report.md` 是可以直接贴进评审文档的凭证：材料、题面、locator、自检分、缺口都在里面；
- `benchmark.json` + `anchors.json` 适合入库，前者是题集快照，后者是引文抽查表；
- `rejected` 与 `pending_human` 是下一轮专项题的原料，不要丢；
- 移交前过一遍 `SKILL.md` §12 的自检清单，特别是包内不得含 `__pycache__` 与预制答案。
