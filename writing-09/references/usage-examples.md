# 调用示例（示例，非正式案例结果）

> 下面的输入片段和输出数字都只是示意图，用于解释接口，不是正式案例的结论，也不能当作评测证据。

## 一、准备一份最小输入

演示目录 `demo_input` 至少要有两样东西：`case.json` 与一份材料文本。

`case.json` 的骨架不用完整抄：只要 `case_id`、`output_contract` 五个契约键（`case_id` / `deliverable` /
`preserved_facts` / `evidence_map` / `change_log`），再加一个 `organizer_workorder` 对象。
workorder 里关键的是这几处：`authority` 写成 `organizer-workorder-not-funder-policy`；`source_basis` 里
`published_paper` 给论文编号、`external_authors` 给作者名、三个 `*_supplied` 布尔量按实际填 false；
`sections` 列七项标题；`draft_size` 写成"约 1600–2600 汉字"这种带区间的形式（脚本会解析）；
`planning_months=12`、`planning_unit_cap=100`；`consistency` 写"3 个目标 G1/G2/G3"；
`required_supporting_files` 与 `scientific_limits` 按题面列条目。

材料文本 `paper.md` 只要含带数值的句子即可触发事实抽取，例如一句
"Specimens were printed with a 0.4 mm nozzle at 210 ℃ and tested under three-point bending."

## 二、跑三步

```bash
python3 -B scripts/proposal_cli.py init     --input demo_input --output demo_out
# 中间：改写 demo_out/proposal.md，并补齐 evidence_map / planning_units / goal_matrix
#       / risks / pending_human / draft_boundary 等附属文件
python3 -B scripts/proposal_cli.py finalize --input demo_input --output demo_out
python3 -B scripts/audit_kit.py --output demo_out
```

`init` 的即时输出（示意）：`{"stage": "init", "case_id": "DEMO-01", "sources": 1,
"sections": ["立项依据", "科学问题", "研究目标", "研究内容", "创新点", "技术路线", "研究基础与可行性"],
"chars_range": [1600, 2600], "next": "编辑 proposal.md 后 finalize"}`。

## 三、目录里会出现什么

`proposal.md` 是七节正文；`workorder.json` 是要求原文留痕；`quote_bank.md` 放候选逐字引文与 locator；
`proposal_skeleton.md` 是每节带字数预算的骨架；`evidence_map.json`、`preserved_facts.json`、
`change_log.json` 记录论断来源、事实与改写动作；`goal_matrix.md` 是目标矩阵；`planning_units.json` 是分项与合计；
`risks.md` 放风险与备选；`pending_human.json` 放人工确认；`draft_boundary.md` 分已完成与拟开展；
`result.json` 是契约回填与审计结论。

## 四、一次正常运行的输出（示意，非正式结果）

`finalize` 打印类似 `{"stage": "final", "case_id": "DEMO-01", "status": "ok", "char_count": 1715,
"planning_units_total": 96, "issues": {"critical": 0, "major": 0, "minor": 0}}`。

`result.json` 里能读到：`deliverable.char_count` 落在 `[1600, 2600]`，`workorder_execution` 的
`sections_satisfied` 为 7、`goals_count` 为 3、`planning_units_in_cap` 为 true、`risks_count` 为 3、
`pending_human_count` 为 3、`contract_keys_missing` 为空数组。数值只示范字段形态。

## 五、出错时会怎样

输入目录空着：`status` 为 partial，`errors` 第一条是 `case_json_unreadable`，仍然产出骨架与合法 JSON，退出码 0。
`case.json` 是坏 JSON：同上，`degradations` 里多一条 `case_json_unreadable`。
没有 workorder：用默认七节 / 12 月 / 100 单位，`degradations` 记 `workorder_absent_defaults_applied`。
没写正文就 finalize：把骨架复制成 `proposal.md`，标 `proposal_absent_fallback_generated`。
引文定位不到：该条 `verified=false`，并追加一条 `PHQ` 人工确认。
规划单位超上限：按比例缩放并记 `CH-units`，回执里 `planning_units_in_cap` 变 true。
