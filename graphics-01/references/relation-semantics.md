# 关系判读手册（relation semantics）

用途有二：没有工单时，从材料句子推断"头实体—关系—尾实体"；有工单时，把工单里的关系类型翻译成图上的端点符号与颜色，避免把抑制画成激活。

机器可执行的权威表是 `scripts/read_sources.py` 里的 `VERB_TABLE`，每条形如 `(类型, 匹配模式, 端点, 颜色)`；本文是它的自然语言说明，改动时两边一起改。

## 一、九种关系与图面编码

每条关系最终只落在三种端点形状上，其余区分靠颜色与图例文字：

1. `activation`（激活/促进/上调/诱导/增强）——实心箭头，蓝色 `#0072B2`。
2. `inhibition`（抑制/下调/阻遏/阻断/削弱）——T 形平头，橙红 `#D55E00`。
3. `binding`（结合/互作/形成复合物/招募）——菱形，绿色 `#009E73`。
4. `phosphorylation`（磷酸化，含被动式）——箭头，紫色 `#CC79A7`。
5. `expression`（表达/编码）——箭头，天蓝 `#56B4E9`。
6. `containment`（包含/组成/隶属/亚基）——箭头，灰蓝 `#8d979f`；这类关系通常落在层级布局的相邻列。
7. `conversion`（转化/生成/产出）——箭头，琥珀 `#E69F00`。
8. `causal`（导致/引起/因此）——箭头，深灰 `#333333`。
9. `causal2`（随后/之后/接着）——箭头，浅灰 `#999999`；只表示先后，不当作因果。

不变量：图面用到几种关系类型，图例就必须有几条关系项；这个等式由 `legend_consistency` 机器校验，人工不要绕过。灰度打印或色盲读者只能依赖"形状 + 图例文字"，因此形状信息比颜色更关键。

## 二、词形提示（不是完整正则）

代码里用不区分大小写的正则匹配；维护时按下面的词族扩写即可：

- 激活族：activate / activates / activated / promoting / induces / upregulated / stimulates / enhances；中文用"促进、激活、上调、诱导、增强"。
- 抑制族：inhibit / inhibited / suppresses / repressed / blocks / downregulated / attenuates；中文用"抑制、下调、阻遏、阻断"。
- 结合族：bind / binds / binding / interacts with / forms a complex / recruits；中文用"结合、互作、相互作用、复合物、招募"。
- 磷酸化族：phosphorylate / phosphorylated / phosphorylation / "磷酸化"。
- 表达族：express / encoded by / encodes / "表达、编码"。
- 包含族：contains / includes / comprises / consists of / is part of / subunit of；中文"包含、包括、属于"。
- 转化族：converts / converted to / produces / generates / yields；中文"转化为、生成"。
- 因果族：leads to / results in / causes / caused by / therefore / thus / hence；中文"导致、引起、因此"。
- 时序族：subsequently / followed by；中文"随后、之后、接着"。

一句话命中多个词族时，按上表顺序取第一个命中；把更具体的类型排在前面，抽取结果更稳。

## 三、方向判定的完整规则

基线方向是"句子中先出现者 → 后出现者"。出现被动结构则反转：

- 英文信号：关系词右侧 14 个字符内以 be 动词（is/are/was/were/been）开头；或后文有 `by <施动者>`。
- 中文信号：关系短语以"被""受到""由"起头。

走查例子（可作为回归用例）：

| 原句 | 期望关系 |
|-|-|
| STAT3 is inhibited by SOCS3 | SOCS3 抑制 STAT3（方向翻转） |
| JAK2 activates STAT3 | JAK2 激活 STAT3（正向） |
| IL-6 binds IL-6R | IL-6 结合 IL-6R |
| ERK 被 MEK 磷酸化 | MEK 磷酸化 ERK |
| A 包含 B 与 C | A 包含 B；A 包含 C（两条 containment） |

工单若显式给了 `direction`，以工单为准；工单的 `from`/`to` 视为已定向，不再二次翻转。

## 四、实体边界与规模上限

- 英文实体取关系词左侧最后一个长 2–16 的字母数字连字符串；若它是小写且前一个单词首字母大写，则两词合并成复合名（如 `TNF signaling`）。
- 中文实体取关系词左侧最后 2–8 个汉字。
- 归一化后长度不足 2、或首尾同名的，直接丢弃，避免自环。
- 最多 16 个实体、22 条关系；触顶的信息进 `uncertainty`，不要悄悄截断。

## 五、宁可少画也不要画错

- 只有共现、没有关系词的句子：不连边。
- 一句里多个关系词、端点归属说不清：只保留两端互异且都能在材料中定位的关系。
- 工单与原文方向/类型冲突：图面服从原文，冲突写 `source_conflict` 并列入 `pending_human`。
- 关系任一端点无法逐字定位：整条关系丢弃，记 `relation_unverified`；不允许"看起来像"的猜测。

## 六、新增类型时同步四处

1. `VERB_TABLE` 加一行；端点只能是已实现的三种之一。
2. 新形状要同时改 `layout_studio.MARKER_DEFS`（`<defs>` 标记）与 `terminal_marker`（位图/PDF 兜底绘制）。
3. 本文件第一节与第二节补相应说明。
4. 重跑后确认 `legend_consistency.ok == true`，且 `markers.distinct_markers` 的增量符合预期。
