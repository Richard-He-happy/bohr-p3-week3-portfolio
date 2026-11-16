# 证据强度算法与运行手册（writing-03 · 1.0.0）

## 0. 先看匹配，再看强度

强度再准，前提是找对了依据。匹配是确定性流程，任何人可以按同样步骤复算出同样结果：

1. **归一术语**。读 `terms_zh2en.tsv`，把中文短语替换成英文概念词，长词先替换；没被词表覆盖的汉字保留成二元组（bigram）。
2. **算重叠**。两边概念集合的交集大小除以各自大小的平方根再相乘，得到 0–1 的相似度；两边出现同一个数字时再加 0.08。
3. **锚点优先**。论断句尾带 `[n]` 或 `［n］` 时，先按 DOI 命中或标题相似度 ≥0.45 把文献表第 n 条对应到某个材料文件，然后主要在这个文件里找，阈值降到 0.05。
4. **补充独立来源**。主来源之外，不同文件中相似度不低于 max(阈值, 主来源×0.72) 的段落也算进来，最多凑 3 个来源，供"重复验证"因子使用。
5. **找不到就写找不到**。低于阈值时 `source_id` 给空、强度给"不足"、成稿改成待核句，并进 `pending_human`。

## 1. 四因子怎么算

总分由四项相加得到，再按封顶规则与分档表落档。四项分别是设计、样本、重复验证、冲突。

**设计分**：系统综述/荟萃分析、指南/共识、随机对照试验记 3.0；队列研究与病例对照记 2.0；横断面/调查记 1.5；叙述性综述、预印本、体外或动物实验记 1.0；病例报告/个案记 0.5；材料没写设计记 1.0。

**样本分**：报告样本量 ≥1000 记 2.0；100–999 记 1.5；10–99 记 1.0；小于 10 记 0.5；没有报告记 0。样本量从 `n = ...` 或"412 participants/名/例"这类写法里抽，抽不到就是未报告，不要估算。

**重复分**：同一论断已有 ≥2 个独立来源时加 1.0。

**冲突分**：存在方向相反的来源时减 1.0（冲突本身还要在产物里保留，见第 4 节）。

**封顶**：预印本总分不超过 4.0；样本量小于 100 不超过 3.4；只能看到摘要的来源最高只到"中"。

**分档**：总分 ≥5.5 → 高；3.5–5.4 → 中；1.5–3.4 → 低；不足 1.5 → 不足。

使用纪律：不因结论顺眼而升级，不因作者名气而升级；单篇小样本不写成共识；观察性设计不写成因果；材料没提就写未报告。

## 2. 分档决定措辞

落"高"时写"多项证据一致"，英文用 Evidence indicates that；落"中"写"研究提示"，英文用 Studies suggest that；
落"低"写"初步线索"，英文用 Preliminary evidence suggests；落到"不足"就写"材料不足以判断"，
英文用 The material cannot determine。

如果原句本来就有"可能/提示/初步/尚"或 may/suggest/prelim，再加限定语就会双重弱化，因此跳过不加。

## 3. 把过度推断改回来

改法按触发条件分成三组：

- **有观察但无随机化/对照组**：英文的 causes、leads to、proves、demonstrates that、confirms that 换成 is associated with；
  中文"导致 X"换成"与 X 相关"。
- **只有观察性研究或单一来源**：把"证明了""证实了""确证""必然"降为"提示"。
- **只有单篇研究或小样本**：英文全称词 all、always、never 改为 in the material reviewed；"所有""全部""总是""从来"
  改为"在所纳入材料中"。

数值、单位、样本量一律不动。每次修改要成对记录改前与改后的文本，附理由与定位，并标 `human_confirm: true` 提醒人再确认。

## 4. 冲突与缺口怎么表现

- 冲突来源写进证据行的 `conflicts` 数组（最多 3 条），同时成稿在对应句后补一句转折并引用反方来源。
- 强度因冲突下调 1.0，但两条证据都保留，不能只留支持自己的一边。
- 无来源的论断：证据行仍保留，字段置空、强度"不足"，成稿改成"（待核）"式表述，并入 `pending_human`。
- 只有摘要：标记 `abstract_only`，并在 `uncertainty` 中说明未回原文。

## 5. 跑起来

```bash
# 准备：/input/case.json、/input/task.md、/input/artifacts/*
python -B scripts/pipeline.py                       # 默认 /input -> /app/output
python -B scripts/audit.py                          # 复核，写 verification.json
```

产物一览（均在输出目录）：`result.json`、`claims.json`、`evidence_table.json`、`evidence_driven_draft.md`、`deliverable.md`、`evidence_strength.md`、`reference_check.md`、`uncertainty_notes.md`、`pending_human.json`，复核后多一个 `verification.json`。

合格标准：复核脚本打印 `verify PASS`；`result.json` 的 `status` 与实际待办一致。

## 6. 异常见处理

| 情况 | 脚本怎么应对 | 留下的痕迹 |
|---|---|---|
| 只有摘要没有全文 | 正常出表 | `abstract_only`、强度封顶"中"、`uncertainty` |
| 全篇没有文献表 | 证据表照出 | `reference_check.md` 缺口、一条待办 |
| 著录缺 DOI/年份/期刊 | 只抄已有字段 | 核验表"缺项"列 |
| 摘要与原文说法不一致 | 两段都收录 | 互标 `conflicts`、成稿转折句 |
| 多个来源互相冲突 | 不取平均 | 强度下调、冲突计数 |
| xlsx/pptx/doc | 不解析 | `degradations` 提示转 CSV/文本 |
| 扫描件 PDF | 不猜内容 | `read_method: none`、提示 OCR |
| 图片 | 不猜内容 | `pending_human` |
| 输出目录无法写入 | 换到当前目录 | `errors` 记录回退 |
| 缺 case.json | 尽力从材料推断，契约 5 键兜底 | `errors`、`status=partial` |
| 输入目录为空或 case.json 损坏 | 仍写 partial 结果 | `status=input_error/partial`，退出码 0 |

## 7. 示意例子（示意数据，不是评测结果）

假设 `demo/input/` 放了三类材料：一份含两句待补证文字的小节稿（其中一句把相关性写成因果）、
一份报告队列研究且样本为 412 的英文摘要、一份报告随机对照试验且写着 no significant difference 的摘要，
外加一份两条著录的文献表；`case.json` 的 `case_id` 为 DEMO-G7。

```bash
python -B scripts/pipeline.py --input demo/input --output demo/output
```

示意输出：`done partial claims=5 rows=7 quote=6/6 pending=1`。也就是论断 5 条、证据 7 行、6 行引文命中、
1 条留给人工补证；成稿里越级因果句被改成"与……相关[1][2]"；`result.json` 的 `status` 为 `partial`，
`overclaim_downgrades` 为 1。

## 8. 边界与维护

**边界**：① 不联网，文献真实性需另行用 Crossref/PubMed 复核；② 相似度是词面近似，同义改写或词表没覆盖的术语可能召回不足，此时宁可标待核也不硬凑；③ 强度是启发式，不能替代方法学阅读，分值明细写在 `strength_basis` 里供人工复核；④ 参考文献编号按首次引用重排，原编号保留在"材料内文献表"；⑤ 图片、扫描件、Office 表格不解析，按第 6 节降级。

**维护**：改分档阈值时同步 `scripts/audit.py` 的 `grade_row()` 与本文第 1 节；扩词表只加同义条目；每次改动跑一遍"生成器 → 复核器"，要求逐字、join、字段、引用编号四项全过。
