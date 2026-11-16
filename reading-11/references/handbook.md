# 清洗手册：字段解释、脏数据谱系与扩展方式

本文件是 `lit-extraction-normalizer` v1.0.0 的配套资源，与 `scripts/run_clean.py`、`scripts/clean_engine.py` 同版本发布。
除明确标注"示例"的内容外，文中出现的数值与行都是说明性构造，不代表任何正式案例的结果。

## 一、目标宽表怎么读

默认字段表定义在 `references/rulebook.json` 的 `target_table`。案例若自带 `fields` / `schema` / `target_schema`，脚本会改用案例给出的字段名与允许值。

- 身份与来源：`row_id` 是原行身份，原样保留；缺失时补 `derived-N`，重复时后来者加 `#N`，两种情况都记降级。`source_document_id`、`source_locator` 原样保留，后者可以是页码、表号、图号或 JSON 路径。
- 名称：`indicator` 与 `material` 是归一后的标签，规则见 `indicator_aliases` / `material_aliases`；原始写法在 `original_field`。
- 条件：`condition_summary` 是把条件列拼成 `k=v; k=v` 的文本，仅用于展示与判定键，**不对条件列做单位换算**。
- 数值：`value` 存单值；区间拆到 `value_low` / `value_high`；误差拆到 `value_err`；`value_text` 是给人看的归一化文本。四类数值互斥使用，不会把区间中值塞进 `value`。
- 单位与原文：`unit` 是规范单位（不可换算时为空）；`original_value` 与 `original_unit` 是逐字原文，任何时候都不会被换算值覆盖。
- 追溯：`rule_ids` 用 `;` 串联本行用到的规则号；`judgment_key` 是去重判定键；`status` 与 `duplicate_of` 描述该行在去重中的处置。

`status` 的六个取值：`ok`（换算或直通成功）、`needs_review`（需要人判断）、`missing`（原文缺失）、`replicate`（重复实验）、`merged_duplicate`（被合并掉的重复记录）、`conflict`（同键数值冲突）。

## 二、脏数据谱系（可迁移到自己的抽取数据）

| 脏数据长什么样 | 典型例子 | 工具的处理 | 归到哪条规则 |
|---|---|---|---|
| 数量级前缀与上下标混写 | `μM`、`µmol L⁻¹`、`cm²` | 前缀表 + 上标字符归一后再换算 | R009 |
| 科学计数法多种写法 | `1.2×10³`、`1.2E3`、`1.2 10^3` | 统一改写成 1.2e3 再解析 | R009 |
| 复合单位 | `mg L-1 h-1`、`mg/(L*h)`、`umol/L/h` | 逐 token 累加量纲指数，斜杠取倒数 | R009 |
| 区间值 | `12–15`、`0.5–0.8`、`12 to 15` | 上下界分别换算，`value` 保持空 | R007 |
| 误差项 | `12 ± 0.5`、`12 +/- 0.5` | 主值与误差分列，共享 factor、不共享 offset | R008 |
| 不等号 | `<0.1`、`≥99` | 值照常换算，保留 `ineq` 标记并写不确定项 | R009 |
| 缺失记号 | `n.r.`、`–`、`n.d.`、空串、`-` | 值留空、`status=missing`，绝不写入 0 | R006 |
| 未知/任意单位 | `a.u.`、`arb. units`、`counts/s` | 不换算，进待人工清单 | R010 |
| 数值有、单位空 | 只有 `12` | 不换算，原因码 `missing_unit` | R011 |
| 同义物质 | `TiO2`、`titanium dioxide`、`TiO₂` | 归一到同一标签，原文另存 | R012 |
| 同义指标 | `band gap`、`bandgap`、`Eg` | 归一为 `band_gap` | R012 |
| 重复记录 | 同来源同条件同值出现两次 | 判定键相同且值相同 → 合并，后来行标 `merged_duplicate` | R013 |
| 重复实验 | 同条件两次测量、数值略不同 | 两行都保留，后来行标 `replicate` | R014 |
| 科学冲突 | 同来源同条件、数值差距远超容差 | 两行都保留、标 `conflict`、交人工 | R015 |
| 编码错乱 | GBK/GB18030 导出的 CSV | 编码级联解码，记录替换字符数 | R019 |
| 空表 | 只有表头、没有数据行 | `status=insufficient_evidence`，不伪装成功 | R020 |
| 列名变化 | `measured value`、`数值`、`raw_value` | 角色同义词表匹配，未命中列进 `unmapped` | R003 |

## 三、单位与精度约定

1. 换算模型固定为仿射式 `after = before * factor + offset`。只有纯温度量纲使用 offset（例如 `25 C → 298.15 K`），复合单位中的温度只参与比例项。
2. `change_log.csv` 同时写 `factor`、`offset`、`formula`（如 `v*1.602176634e-19`）与 `precision`（源数据小数位），因此任何一个数都可以被手工复算。
3. 百分数、ppm、ppb、‰ 属于独立的 `fraction` 量纲，不会被当成无量纲计数，`0.5` 也不会被自动改写成 `50 %`。
4. 规范单位字符串按从左到右的斜杠链解释：`mg/L/h` 等于 mg 每升每小时。
5. 量纲签名在 `signature_targets` 里查不到时，用 `dimensions` 的基准单位拼出派生规范单位（如 `m^2*kg*s^-2`），并在变更记录里注明是派生。
6. 换算结果最多打印 6 位有效数字；`precision` 只反映源数据的小数位，不代表测量精度。

## 四、如何扩展

- **加单位**：在 `unit_registry.json` 的 `units` 追加一条 `{"symbol","dims","to_base","shift","spellings"}`；若引入新的量纲组合，在 `signature_targets` 补一条"签名 → 规范单位"。
- **加规则**：在 `rulebook.json` 的 `rules` 追加定长数组，字段顺序见 `rule_fields`（编号、优先级、适用对象、触发条件、变换、示例、失效情形、是否必须人工）。案例自带规则默认 priority=10，会覆盖同号内置规则并被记录到 `rules.json.suppressed_rules`。
- **加列名别名**：在 `column_roles` 里给对应角色补别名，无需改脚本。
- **调整去重容差**：`matching.conflict_relative_tolerance` 与 `matching.replicate_relative_tolerance`，默认都是 0.05。
- **换同义词**：只加真正等价的写法。不同物质（如 `TiO2` 与 `TiN`）绝不可以指向同一标签；把不同物质错并会让正确性直接失分。
- **版本纪律**：两份 JSON 资源与两个脚本同号发布；改资源就升版本，并在 SKILL.md 与本节同步版本号。

## 五、自查与复核方法

```bash
python3 scripts/run_clean.py --input /input --output /app/output
python3 scripts/run_clean.py --input /input --output /app/output --determinism
cat /app/output/verify_report.json
```

`verify_report.json` 的七项检查：计数核对、`row_id` 唯一、公式复算一致、规则号可解析、待确认行无泄漏值、变更行身份可解析、可统计行数复核。

人工抽查建议：

1. 从 `change_log.csv` 随机挑 5 行，用 `before*factor+offset` 手算并核对 `after`。
2. 挑 3 组 `result.duplicates` 的判定键，确认来源与条件确实相同，没有把不同实验并到一起。
3. 检查 `pending_review.csv` 里的行在 `cleaned.csv` 中对应 `value` 为空。
4. 检查所有 `status=conflict` 的行都出现在 `anomaly_report.md`。
5. 用恶意输入（空目录、坏 JSON、只有表头的 CSV）各跑一次，确认退出码仍为 0 且 `result.json` 合法。


## 六、这份实现与常见"临时脚本"的差别

常见做法是拿到表就写一段换算代码，跑完把结果表交出去。本实现刻意多做了四件事，代价是包体稍大，收益是可复核：

1. 规则先落到资源文件里，每条有编号、优先级、失效情形与是否必须人工，脚本只是执行器；改规则不改代码。
2. 每次改动都留三件套：改前值（带原单位）、公式、改后值（带规范单位与精度说明），因此评审可以手算复核。
3. 不敢确认的值被隔离：清洗表里是空的，待确认清单里有原值与原单位，统计时不会被误当成真值。
4. 同一输入重复运行结果逐字节一致，不依赖运行时刻或文件系统顺序。

## 七、故障排查

- **运行后 cleaned.csv 只有表头**：先看 `result.status`。如果是 `insufficient_evidence`，说明没有找到记录表或所有行都为空；检查输入 JSON 是否把行挂在非预期的键下（脚本会逐层找 dict 列表，但列表为空则无法继续）。
- **所有行都进 pending_review**：多半是单位列没识别出来。检查表头是否写了 `unit`/`单位`/`uom` 之外的奇怪名字，把它加进 `column_roles` 的 `unit` 别名。
- **换算因子全是 1**：源单位与规范单位恰好同量纲同比例（如 mg/L 保持 mg/L），属于正常直通，不是失败。
- **同一物质出现两个标签**：检查 `material_aliases` 是否漏了写法；注意大小写与空格，脚本先做小写与空格压缩再查表。
- **两个文件的内容被拼进一张表**：这是预期行为，所有记录文件会汇总；如果希望分开，按文件分批调用 `--input`。
- **编码告警**：`degradations` 里有替换字符计数，说明文件不是 UTF-8；数据若已乱码，需要回到导出环节确认原始编码。


补充一点使用建议：把 `verify_report.json` 的 `verdict` 当作一次运行的准入条件，`PASS` 表示七项检查全过；如果出现 `CHECK`，优先看 `formula_consistency_pct` 与 `counts match` 两项。前者不为 100 说明换算记录与数值不符（通常是改了输出精度而没同步公式），后者不匹配说明落盘文件被外部改动过或计数口径变化。两种情况都应该先修复再交付，而不是在报告里解释。
