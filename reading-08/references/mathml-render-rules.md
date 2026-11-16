# MathML 转 LaTeX 的判定规则

本文解释 `scripts/mathml_engine.py` 里的实际行为。核心原则：**按文档顺序与嵌套关系逐节点直译；认不出的东西留占位、打标记，不凭外观猜**。表外节点最终输出占位符 `\square`，并写一条 flag 供人工复核。

## 一、解析前做的三次尝试

1. 原样交给 ElementTree，成功即 `parsed`。
2. 失败时移除 XML 声明与 DOCTYPE，再把 `&alpha;` 一类命名实体替换为等价的数字实体并重试；成功则返回 `parsed_after_entity_repair`。
3. 仍失败、且正文出现 `mml:` 前缀却缺少 `xmlns:mml` 绑定时，先给根节点补一条声明再重试（本版新增分支）；成功返回 `parsed_after_namespace_repair`。

三种方式都不通过才向上抛异常，由入口脚本转成正则回退并登记降级。判断元素类型时只看本地名，因此带命名空间的默认写法、`mml:` 前缀写法和裸写法一视同仁。

## 二、结构类节点怎么落笔

- **分式**（`mfrac`）：写成 `\frac`，分子分母各作为一个参数组；参数本身是单个原子时不再额外包一层花括号。子节点不足两个时补空参数组并记 `mfrac_arity`。
- **上下标**（`msub`/`msup`/`msubsup`）：基写在前，下标接 `_{}`、上标接 `^{}`；只有单侧时另一侧省略。缺子节点记对应的 `<节点>_arity`。
- **根式**：`msqrt` 的输出是 `\sqrt{被开方式}`，多个子节点顺序拼接；`mroot` 输出 `\sqrt[阶数]{被开方式}`，缺阶数时记 `mroot_arity`。
- **定界符组**（`mfenced`）：成对输出 `\left` … `\right`，左右定界符取自 `open`/`close` 属性，属性缺失按圆括号处理。定界符会先过一遍算子替换表。
- **表格**（`mtable`）：两列且多行时按分段函数输出 `cases` 环境，并主动记 `mtable_as_cases`（系统无法区分它真是分段函数还是两列矩阵，必须人工确认）；其他形状输出 `matrix` 环境并记 `mtable_as_matrix`；一行都没有时记 `empty_mtable`。
- **上下置标**（`munder`/`mover`/`munderover`）：分别落到 `_{}`、`^{}`、`_{}^{}`。`mover` 的标记若是 `^`、`~`、`¯`，改写成 `\overline{基}` 并记 `accent_normalized`。`munderover` 的基不属于求和/连乘/积分/`lim`/`max`/`min` 时记 `munderover_nonbigop`。
- **透明容器**：`mrow`、`mstyle`、`mpadded`、`mphantom`、`menclose`、`mtd`、`math` 没有自身语义，按顺序拼接子节点即可。
- **空语义节点**：`mspace`、`none`、`prescripts` 输出空串。
- **语义包装**（`semantics`）：若内部带 `annotation[encoding=application/x-tex]`，直接采用该 TeX 原文（`latex_source=mml_annotation`），优先级高于结构映射。
- **文本**（`mtext`）：包成 `\text{}`，内部下划线与百分号做转义。
- **未收录节点**（例如 `mmultiscripts`）：输出 `\square` 并记 `unmapped:<节点名>`，绝不按相似性猜测。
- 嵌套深度超过 60 层时停止递归，输出占位符并记 `max_nesting_depth`。

## 三、记号类节点怎么落笔

- **标识符**（`mi`）：单字符走希腊表或通用转义；多字符纯字母串包成 `\mathrm{}`；函数名词（sin/cos/tan/cot/sec/csc/log/ln/lg/exp/max/min/lim/sup/inf/det/arg）输出对应命令，并归入算子集合而非变量集合。
- **数字**（`mn`）：去掉内部空白后原样输出。
- **运算符**（`mo`）：先按整串查替换表；整串查不到时退化为逐字符替换；仍失败即 `\square`。

替换表收的词：加减、等号、大小于号、乘除、逗号分号、圆括号方括号、竖线、`×`、`·`、`±`、`≤`、`≥`、`≠`、`≈`、`∼`、`∝`、`→`、`∑`、`∏`、`∫`、`√`、度数符号、百分号、下划线。

希腊表覆盖全部小写与大写希腊字母，另加 `∂` 到 `\partial`。表之外的字符（例如 `ϱ`）一律占位符。

## 四、符号清单的生成口径

1. 变量候选来自所有 `mi` 原子，以及 `msub`/`msup`/`msubsup` 中以 `mi` 为基的节点。符号名按实际上下标拼装，例如 `k_{B}`、`c^{2}`、`N_{0}^{2}` 各算一个符号。
2. 若上标的底数为自然常数 `e` 或 `10`，底数不进变量清单，但指数仍继续遍历：`e^{kt}` 只产出 `k` 与 `t`。
3. 函数名与运算是算子，不要求被变量表覆盖。
4. `plain` 是去掉 `\mathrm{}`、花括号、`^`、`_` 与反斜杠之后的可检索形式，用来在正文里寻找定义句，例如 `k_{B}` 的 `plain` 是 `kB`。

## 五、flag 词汇表

`unmapped:<节点名>`、`mfrac_arity`、`mroot_arity`、`msub_arity`、`msup_arity`、`msubsup_arity`、`max_nesting_depth`、`mtable_as_cases`、`mtable_as_matrix`、`empty_mtable`、`munderover_nonbigop`、`accent_normalized`、`xml_unparsed`、`placeholder_square`、`unbalanced_braces`、`empty_latex`。

只要公式带 `placeholder_square` / `unbalanced_braces` / `empty_latex` 中任一标记，该公式状态即记 `needs_review`，同时必须在其 `uncertainties` 里有对应条目。
