# 交付 QA 手册（qa playbook）

核验分五段：进场检查、产物与结构、证据链、导出件、状态诚实度。每段都对应 `result.json` 里的可读字段，走一遍就知道能不能交。

## 一、进场检查

1. 输入目录存在 `case.json`（或树内任意 `case*.json`），能解析出 `case_id` 与 `output_contract`；解析失败不算硬错误，但要能在 `errors` 里看到解释。
2. 至少一种材料可读：md、txt、csv、tsv、json、yaml、tex、xml，或带文本层的 pdf。全是 xlsx/docx 时只能降级并提示转格式。
3. 有工单时，实体清单与关系清单可解析；编辑类案例还要有基线 `*.svg` 与 `edit_operations`。
4. 输出目录可写，且不是只读挂载；下载类目录不要和图稿目录混用。

## 二、产物与结构

- 目录里应当出现 `figure.svg`、`figure.png`、`figure.pdf`；三者都不允许 0 字节。另有两个辅助文件 `figure_model.json`（中间表示）和 `result.json`；编辑案例额外有 `edit_record.json`。
- 用 XML 解析器打开 SVG 不报错；`layer-*` 分组至少 4 个；`<text>` 至少 1 个；`<marker>` 定义至少 2 种。这些数字与 `compliance_checks.svg_wellformed` 一致。
- 文字必须是活字：标签数量与 `text_count` 相符，没有字形轮廓化、没有整张图嵌位图；字体只声明回退栈 `Arial, Helvetica, 'DejaVu Sans', sans-serif`，不外嵌字体。
- 台账中列出的每个 SVG id 都真实存在（`id_map.missing` 为空）。这一项失败通常意味着模型与渲染用了两套几何，属于实现缺陷，必须修而不是绕过。

## 三、证据链

- 每个实体都要有 `source.locator`（文件#行、pdf#页+行、或工单锚点）和逐字 `quote`。抽查两三条：把 quote 拿去材料里搜，应该一搜就有。
- `coverage.mapped_entities` 必须等于必需实体数；`coverage.complete` 为真。
- 本包新增的 `source_locators` 检查会验证 locator 的文件部分确实在输入树里：`missing` 应为空。若有人把 locator 手改成不存在的路径，这里会立刻暴露。
- 关系的两端都必须是 `verified=true` 的实体；任何未验证端点都会让整条边被丢弃，并在 `exceptions` 留下 `relation_unverified`。
- 图例项数 = 关系类型数 + 数据系列数；`legend_consistency.ok` 必须真。
- 布局检查：`overlap.pairs == 0`、`overflow.outside_canvas == 0`、`overflow.text_overflow == 0`。文字溢出通常靠缩短标签或调换行阈值解决。

## 四、导出件

1. PNG 不靠肉眼：读 IHDR 得到宽高与位深，正常为 8 位 RGB；再抽样估算非白像素比例，应大于 0.004（本 Skill 会把比例写进 `export_artifact.png.probe`）。纯白图判 blank。
2. PDF 看三处：开头 `%PDF-`、尾部含 `%%EOF`、页对象计数 ≥1；页数写进 `export_artifact.pdf.probe.pages`。
3. 引擎名要落在 `export_artifact.png.engine` / `pdf.engine`；标准库兜底会显示 `stdlib-zlib` / `stdlib-pdf`，并在 `degradations` 里写明"ASCII/Latin 文字受限"。
4. 导出失败不要慌：把缺失写进 `{path:null,status:"missing"}`，保留 SVG 母版，状态降为 `partial`；绝不能用别的文件改名冒充。

## 五、状态与契约

- `status` 三选一：`ok` 要求三件齐、检查全过、所有标签可溯源；`partial` 表示有已记录缺口；`input_error` 表示连材料都没读到。
- `exceptions` 每条要有 `type / object / reason / action / locator`，能被另一个 Agent 直接读懂。
- `output_contract` 的每个键都要在结果根部出现，值可以为 null，但键不能缺；`output_contract_echo` 保留原始契约形态。
- 同输入跑两次，`figure.svg` 的 sha256 必须一致；不一致先查字典序、时间戳、随机 id 等非确定源。

## 六、材料改了一句话之后怎么重绘（本包新增流程）

1. 只改材料或工单，不要手改 SVG；从入口脚本重跑，让模型重建。
2. 用 `figure_model.json` 做新旧对比：实体、关系、数据系列的变化集合应与材料改动一一对应，多出来的对象要回查来源。
3. 对比 `content_map.svg_ids_expected`：id 增删意味着图例或 panel 也要变，别漏。
4. 再比一次两次运行的 SVG 哈希与 `determinism`，确认没有潜伏的不确定性。

编辑类案例例外：基线只换文字，`edit_record.json` 记录基线 sha256、元素 id、改前改后文本；没有匹配操作时保留原图并记 `no_edit_applied`。

## 七、打包前

包内文件应只有 `SKILL.md`、`scripts/*.py`、`references/*.md`。逐项确认：没有 `__pycache__`/`.pyc`、没有示例大图与测试输出、没有临时目录；`--help` 退出码 0；全部 UTF-8；无符号链接、无联网依赖；单脚本不超过 25KB。示例输入与正式案例分开存放，示例必须注明"示例，非正式案例结果"。
