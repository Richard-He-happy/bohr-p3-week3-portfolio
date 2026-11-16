# 模板与异常处置矩阵（自研增量）

本文件补齐「可直接复用」的交付模板与六类异常的处置口径，属于本包在参考实现之上的增量资产。

## 1. 术语表模板（`glossary.csv`）

```
term,target,locator,note,status
photocatalysis,光催化,M2:paper.md#P003,学科语境：环境催化,locked
XRD,X 射线衍射（XRD）,M2:paper.md#P005,首次出现展开，后文沿用缩写,locked
resolution,分离度,M2:paper.md#P012,本文为色谱语境；成像语境应为分辨率,locked
in situ,原位,M2:paper.md#P020,拉丁短语保留斜体标记,pending_human
```

列约定：`status=locked` 表示全篇按此译名执行；`pending_human` 表示译名待作者确认（此时该行 `target` 可为空）。同一 `term` 严禁两行不同 `target`。

## 2. 双语对照模板（`translation.md` 的单段形状）

```
### M2-P003 · body · M2:paper.md#P003

**Source [paper.md]**
> Photocatalytic degradation of phenol reached 92.4% within 60 min under UV irradiation (Fig. 2) [12].

**Target [zh]**
> 紫外照射下，苯酚的光催化降解率在 60 min 内达到 92.4%（图 2）[12]。

_note: 数字 92.4/60 原样保留；引用 [12] 与图号（图 2）原位保留_
```

要求：`para_id` 与 `locator` 原样来自索引；`Source` 是逐字摘录；`Target` 是完整译文；`note` 只写处理说明。

## 3. 待人工确认模板（`pending_human` 条目）

```json
{"item": "resolution", "reason": "色谱与成像语境各有一个公认译法，本文语境需作者确认", "locator": "M2:paper.md#P012"}
{"item": "number:95% vs 92%", "reason": "正文与表 2 的降解率不一致，两值均保留", "locator": "M2:paper.md#P003;M2:table2.csv#R4"}
{"item": "scan-annex.pdf", "reason": "扫描件文本层为空，图内文字未取读", "locator": "M1"}
```

## 4. 六类异常的处置矩阵

| 异常 | 识别方式 | 脚本动作 | Agent 动作 |
|---|---|---|---|
| 公式与表格并存 | 段落 `kind=formula`，或材料含 CSV/表格 XML | 公式段单独成段入索引；CSV 按行读 | 公式整体搬运、只译文字说明；表格逐行对齐，单元格不合并 |
| 术语表冲突 | 给定术语 `target` 与学科习惯不一致 | 索引把给定术语列进 `supplied_terms`，优先走校验 | 以给定译法为准，冲突写 `change_log.reason`；同时进 `pending_human` 提示作者 |
| 超长文本 | 段落数大于单轮可读量 | 分块索引，`show --material`/`--max-chars` 分段读 | 分批写工作稿，每批后 `check`；不得截断后声称全文完成 |
| 语向不支持 | 判断不出目标语种 | 按源文语种默认反向；`target_lang` 可被草稿覆盖 | 在 `uncertainty` 写清推断依据；无法确定则 `partial` |
| 引用格式异常 | 上标/方括号/作者-年份混排 | `MARKER_RX` 同时识别数字标记与括号年份 | 原样保留标记与编号，只调整体例括号 |
| 输入编码错误 | 解码失败或出现替换字符 | 多编码链回退读取，读不到的标 `quality=low` | 在 `degradations` 记录，必要时进 `pending_human`，不猜正文 |

## 5. 与主流程的衔接

- 六类异常优先在 `init` 阶段暴露：看 `init` 输出里的 `quality`、`warnings`、`term_candidates`。
- 处置结果必须落到产物里：术语冲突 → `change_log` + `pending_human`；编码问题 → `degradations`；超长分块 → `metrics.paragraphs_translated` 与 `coverage`。
- 不要为了「看起来完整」而填满槽位；`partial` + 明确的缺口清单比虚假的 `ok` 分值更高。
