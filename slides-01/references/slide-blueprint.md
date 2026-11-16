# 页级骨架模板（可复用）

本文件描述 `deck_model.json` 里 `slides[]` 应当长成什么样。生成器只是把这份骨架投影成 pptx 与 content_map；换论文、换模板都不需要改这里的方法论。

## 1. 角色阶梯（按论文贡献排序，不按章节顺序）

| 位置 | role | 优先取材章节 | 这一页放什么 | 证据定位写法 |
|---|---|---|---|---|
| 1 | `title` | 首页标题区 | 论文标题 + 作者/单位行 | `p.1` |
| 2 | `motivation` | abstract、introduction、background | 要解决的问题、难在哪（≤3 条） | `p.X / 章节名` |
| 3 | `approach` | abstract、introduction、method | 本文做了什么，用作者自己的措辞（"we propose…"） | `p.X / 章节名` |
| 4 | `method` | method、experiment | 数据、设置、流程 | `p.X / 章节名` |
| 5… | `evidence` | `Figure N`/`Table N` 标题 + 同页结果句 | 一页一图/表：caption 短语作主张，配 1–2 条结果句 | `Figure N, p.X` |
| … | `discussion` | discussion、result | 结果意味着什么（只写论文自己给的解释） | `p.X / 章节名` |
| … | `limitation` | discussion、limitation | 作者承认还不成立/不清楚的部分 | `p.X / 章节名` |
| … | `conclusion` | conclusion、discussion | 收束性结论 | `p.X / 章节名` |
| 末尾 | `thanks`（n ≥ 14 才出现） | acknowledgements | 致谢句；没有就放作者行 | `p.X` |

## 2. 页数预算（`role_sequence(n)`）

起点：`title, motivation, approach, method, discussion, limitation` + 尾部 `conclusion`（n ≥ 14 时再加 `thanks`），剩余槽位全部给 `evidence`。

页数不够时按这个顺序丢角色：**limitation → discussion → method → approach → motivation**——保证最后活下来的始终是"标题 → 问题 → 证据 → 结论"这条主线。n < 4 时退化为 title + motivation（+ conclusion）。

经验值：15 分钟报告约 2–3 分钟一页内容页；论文有图表时，证据页应占全 deck 的 30% 以上。

## 3. 逐页硬约束（脚本自动检查）

- 一页恰好一个 `claim`，且必须是锚定句的原文子句；
- 每页 **≤5 条 bullets，每条 ≤190 字符**（进 `compliance_checks.overflow`）；
- bullets 只能在子句边界做**前缀截断**，禁止改写/概括——这样数字、单位、方法名保持字节一致；
- 每页至少 1 条 evidence，且 `notes` 非空；
- 图/表页把编号写进标题（如 `Figure 1: ...`），让口头引用与论文编号对得上。

## 4. 讲稿模式

`If asked, cite <locator>; <locator>. Next: <下一页 role>.`

如果论文里还有未使用的旁证句，可以补第二句。讲稿与页面文字的 token 重叠率必须 ≤0.6，否则重写——讲稿的职责是提示过渡与被追问时的出处，不是复读页面。

## 5. 示例投影（12 页、3 个图表的论文）

```
1  title        论文标题
2  motivation   Why this matters       3 条，p.1 / Abstract
3  approach     Our approach           3 条，p.1 / Abstract
4  method       How the work was done  3 条，p.1 / 2 Method
5  discussion   What it means          3 条，p.1 / 4 Discussion
6  limitation   Limits and open questions
7  evidence     Figure 1: ...
8  evidence     Figure 2: ...
9  evidence     Table 1: ...
10 evidence     Key evidence 1          （多余结果句）
11 evidence     Key evidence 2
12 conclusion   Takeaways
```

## 6. 复用到其他场合

骨架与论文无关。换场合只改三处：角色显示名（`ROLE_LABELS`）、`role_sequence(n)` 的丢弃顺序、逐页 bullets 上限。**一页一主张**与**必须带 locator** 这两条不要动——它们是整份 deck 可复核的根基。
