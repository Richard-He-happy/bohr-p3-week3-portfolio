# 评分透视与故障处置

## 1. 评分维度 → 可指认的产物证据

| 维度 | 评审会看的证据 | 交付前动作 |
|-|-|-|
| 任务完成度 15 | 4 个面板齐备；`graphical_abstract.svg` + 单页 PDF + 真实 PNG | `check` PASS；把 PNG/PDF 各打开一次 |
| 结果正确性 15 | `content_map[].evidence.quote` 与原文逐字一致；箭头方向来自原文 | 抽 2 条 quote 用 `show --grep` 复现 |
| 结果完整性 5 | 图例、单位、条件标签、caption；缺口列在 `pending_human` | 逐面板自问“不看文字能懂吗” |
| 可核验性 5 | `sources[].sha1`、`changes`、`compliance_checks`、`runtime` | 任取一个图元说明它在图上的位置与来源 |
| 使用增益 25 | 一次 init→plan→check→build；改标签只改 plan 重跑 build | 连续两次 build 比较 SVG 字节 |
| 创新增益 15 | 引文校验 + 图面数字白名单校验 + 确定性布局 + 图元几何表 | 讲清“为何不是随手画一张信息图” |
| 可靠体验 10 | 坏输入仍有合法 `result.json`；退出码恒 0 | 空目录、坏 JSON、缺 plan 各跑一次 |
| 生态贡献 10 | plan 字段表、图层命名、导出参数、两份 references | 换一份材料能否零改动复用 |

## 2. 运行时出现的失败与处置

| 现象 | 根因 | 处置 |
|-|-|-|
| `E3: unverified - quote not found verbatim` | 改写了原文 / 跨段拼接 / 抄的是摘要 | 回 `show --grep` 取整段原文再填 |
| `E3: number(s) ['145'] not in its quote` | 图元里有数字，但引文没有该数字 | 改引文为含数字那句（如数据行），或删掉数字 |
| `E3: relocated` | 句子对、locator 写错 | 不用动，content_map 已换成正确 locator |
| `missing panel role: implication` | 缺结论段 | 补面板；结论文本必须是原文的结论句 |
| `no items` | 面板为空 | 每面板至少 1 个带证据的图元 |
| `PNG preview unavailable` | 绘图库与 pdftoppm 都不可用 | 本包由 `pngkit` 兜底，正常不会出现；若出现查 `pngkit` 报错 |
| `PDF text not extracted` | 无 pdftotext | 人工读页，locator 写页码，quote 保持逐字 |
| `status=insufficient_evidence` | 材料里没有可引用句子 | 在回复中说明缺什么，禁止编造 |

## 3. 交互过程中的常见错法

- 把整段摘要塞进一个面板：读者抓不到“问题→结论”的主线，且 check 容易因跨段引文失败。
- 只保留 PNG 截图：可编辑性与可核验性直接归零。
- 图上出现材料之外的数字：这是虚假数据，必须删。
- 面板之间没有关系词：评审分不清箭头表达“先后”还是“因果”，把方向写进 `flow`。
- 两次运行版式不同：原因通常是手工改过坐标或引入随机；坚持只改 plan。

## 4. 60 秒终检

1. `check` → PASS，`coverage ≥ 0.9`。
2. `result.json`：契约键齐全、`status` 与实情一致、`errors/degradations` 都能解释。
3. SVG 打开后文字可编辑、六图层结构可见；PDF 单页、文字可选中；PNG 文件头为 `\x89PNG`。
4. `content_map.json` 中任抽两条 quote 能复现。
5. 全文搜一遍图面数字，确认每个都在来源里出现过。

## 5. 对照实验怎么讲清楚

同一份材料跑两遍是复现，跑两套材料才是可复用。把这两件事分开说明：

- 复现：固定 input 与 plan，连续 build 两次，比较 SVG 的字节哈希；相同即说明布局无随机源。
  若不同，先查是否手工改过 plan 坐标（本包禁止），再查渲染器是否引入了时间戳或排序不定。
- 复用：换一份材料，只改 plan.json，不改任何脚本。能直接出图说明接口与版式是解耦的；
  需要改脚本才能跑通，说明契约没有真正稳定下来。
- 对照：报告里不要只贴最终图，同时给出 check 的 PASS 行、content_map 的图元计数、
  被剔除图元清单。评审据此能判断是“图好看”还是“图可核验”。

## 6. 证据抽查问答模板

被问到“这个 2.4-fold 从哪来”时，回答顺序固定为：材料文件名 → locator → 逐字引文 →
该引文出现在哪个面板哪个图元。三个要素缺一即视为不可核验。反过来，若某个数字只能回答
“从摘要里看到的”，说明它没有被正确引证，应当先修 plan 再重出图，而不是在口头上补解释。
