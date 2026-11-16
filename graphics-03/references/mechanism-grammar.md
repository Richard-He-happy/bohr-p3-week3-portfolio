# 机制图语法手册（关系词表 / 区室归位 / 命名与图例）

`pathway-mechanism-drawer` 的随包查表资源：Agent 判型查这里，脚本 `figure_engine.VERBS` 用同一份词；
两边不一致时以本文件为准并同步改脚本。

## 1 关系词表：动词 → 边类型 → 画法

判定依据是材料里**写明的动词**，不是常识；一行两个动词时取离主语最近的那个。

| 边类型 | 端点与线型 | 中文动词 | 英文动词（含屈折） |
|---|---|---|---|
| `activation` | 实线 + 实心箭头 | 激活、促进、上调、增强、诱导 | activate(s/d), promote(s/d), induce(s/d), upregulate(s/d), stimulate(s), enhance(s), drive(s) |
| `inhibition` | 实线 + T 形端（无箭头） | 抑制、下调、阻断、负反馈、阻遏 | inhibit(s/ed), repress(es/ed), suppress(es/ed), block(s/ed), blockade, prevent(s) |
| `binding` | 实线 + 空心箭头 | 结合、募集、互作、二聚化、组装 | bind(s)/bound, interact(s), recruit(s/ed), dimerize(s), assemble(s), associates |
| `modification` | 实线 + 实心箭头 + `P`/`Ub` 角标 | 磷酸化、泛素化、甲基化、乙酰化、剪切、修饰 | phosphorylate(s/d), ubiquitinate(s/d), cleave(s/d), methylate(s), acetylate(s) |
| `transport` | 粗实线 + 双头箭头 | 转运、转位、分泌、释放、出核、入核、输出 | transport(s), translocate(s/d), secrete(s/d), release(s), export(s), import(s), shuttle |
| `indirect` | 虚线 + 空心箭头 | 推断、推测、间接 | imply/implies, suggest(s), presumably |
| `unspecified` | 点划线 + 空心箭头 | 原文未说类型，或说不清 | — |

**优先级**：`modification` > `transport` > `inhibition` > `activation` > `binding`。一句原文常含
两个语义（"EGFR phosphorylates STAT3 and activates it"）：共价修饰是更具体的事实，先记修饰，把"激活"
写进 `label`，不要为多画一条箭头把一句话拆成两条边。

**未命中** → `unspecified` + 点划线 + 写进 `gaps`，不凭印象贴"激活"。**无方向表述**（"A 与 B 相关"）
→ `direction: "undirected"`，画无箭头连接并写 `pending_human`；方向由原文语序决定（"A 被 B 激活"
= `B -> A`）。

## 2 区室归位

| 泳道 id | 中文 | 英文 | 归位关键词（命中即归位） |
|---|---|---|---|
| `ext` | 细胞外 | Extracellular | extracellular、secreted、lumen、medium、circulat、胞外、细胞外、分泌 |
| `mem` | 细胞膜 | Plasma membrane | membrane、plasma_mem、cell_surface、surface、bilayer、膜、质膜 |
| `cyt` | 细胞质 | Cytoplasm | cytoplasm、cytosol、cyto、胞质、胞内、细胞质、细胞浆 |
| `nuc` | 细胞核 | Nucleus | nucleus、nuclear、chromatin、细胞核、核内、染色质 |

三条硬规则：

1. **跨膜受体贴膜**：`mem` 实体的方框必须压在双分子层中心线上（断言 `box.y < membrane_y < box.y+box.h`）；
   只写"受体"没写区室的按膜蛋白处理，并在 `gaps` 说明。
2. **跨区室边必须穿过层界**：`from_lane != to_lane` 的连线，y 范围必须跨过两层边界；悬在层内即布线错误。
3. **层数不齐不硬凑**：材料只有胞质与核，就只画两层，不补一层空的细胞膜。

## 3 命名与判型

- **基因斜体、蛋白正体**：`kind:"gene"` 的文字用斜体（`data-italic="true"`）；`TP53`（基因）与
  `p53`（蛋白）必须分成两个实体，材料混用时在 `sublabel` 写清判型依据。
- **复合物整体成框**：`kind:"complex"`，双层边；成员不拆成边，除非原文分别写了成员关系。
- **同名异义**：同一标签出现在两个区室（胞质/核内 STAT3）→ 两个实体，`sublabel` 写
  `cytoplasmic pool`/`nuclear pool`；工单覆盖按候选集合比对，两者都算命中。
- **物种前缀**：`human EGFR`/`hEGFR`/`EGFR` 在 `species` 记一次，标签保留原文写法。
- **不补常见分子**：材料没写的 AKT、MAPK、GRB2 一律不画，缺环节写进 `gaps`。

## 4 图例与数据编码

- 图例由画面**实际出现**的种类与类型自动生成，条目数必须等于种类数 + 类型数；写死的图例一定和图面
  打架。
- 颜色只编码实体种类，线色 + 端点 + 虚线编码关系类型；**不做双重编码**。
- 数值编码（表达量、显著性、置信度）只在 `plan.data_encoding` 给出 `column` 或 `quote` 时启用；
  没来源不画，绝不拿"看起来合理"的数字填空。

## 5 交付前 30 秒自查

1. 每个实体有 `kind` 与 `compartment`，基因斜体；每条边有 `type`，激活箭头、抑制 T 端没画反。
2. 跨膜蛋白压膜线；跨区室边穿过层界。
3. 图例项数 = 种类数 + 类型数，且没有画面不存在的项。
4. `figure.svg` 的 `<text>` 还在（没转曲），改一个标签能重导 PDF；每条边都能追到 `quote`+`locator`。
