---
name: experiment-route-figure-studio
description: 面向实验方案与科研汇报的成图工作流：读取 case 包与散落的装置/工艺/路线材料，先构成“器件—接口—连线—步骤/阶段”模型，再由同一个图元列表确定性生成分层 SVG 可编辑源、真实 PDF/PNG 导出与逐元素来源凭证；内置连接完整性、编号连续性、产物签名与二次渲染一致性检查，缺少字体或转换器时逐级降级并如实登记。
version: 1.0.0
---

# experiment-route-figure-studio

## 0. 这个 Skill 干什么

给定一份实验侧的 case（装置/工艺流程/技术路线文字材料 + 一个可选 workorder），产出一套能被别人打开、修改、复核、复跑的图稿与结构化记录。核心目标有且只有三个：图上的对象都能在材料里找到原句、对象之间的连线与先后顺序讲得通、交付物不是一张死的截图。

本 Skill 不负责：拟合分析、评价实验方案在科学上是否成立、期刊模板适配、以及“补全”材料没有提供的信息。

## 1. 交付物速览

| 交付物 | 类型 | 由谁产生 | 说明 |
|-|-|-|-|
| `figure.svg` | 分层矢量源 | 脚本直接序列化 | 文字是真文本、图元带 id 与 `data-src`，是最终真值 |
| `figure.pdf` | 单页矢量 | 外部转换器或标准库兜底 | 用于投稿/预览，引擎写入结果 |
| `figure.png` | 位图预览 | 由 PDF 光栅化或浏览器截图 | 用于组会/汇报，带 IHDR 与像素检查 |
| `figure_model.json` | 模型快照 | 脚本 | 部件/连接/步骤/阶段的确定性中间表示 |
| `result.json` | 结构化结果 | 脚本 | 字段契约见第 5 节 |

## 2. 怎么调用

```bash
python3 -B <skill>/scripts/route_figure.py --input <in> --output <out> --work <tmp>
```

- `<in>`：放 `case.json` 与材料，允许子目录混放；不要求固定的文件名集合。
- `<out>`：上表五个文件都写这里；目录不存在会自动建。
- `<tmp>`：转换器日志与临时 profile，不进交付。
- 依赖：Python 标准库即可。以下全部可选，缺哪个就走备用路线：`soffice`、`libreoffice`、`pdftoppm`、`gs`、Chromium 系浏览器。
- 退出码：永远 0。任何异常都会转成 `result.json` 里的可读记录。

## 3. 输入识别顺序

1. 找 case：先 `case.json`，再 `case*.json`，最后递归兜底；解析失败只记一条 `case_unreadable`，不放弃材料。
2. 抽文本：文本类直读；PDF 优先 `pdftotext -layout`，失败则解压内容流按 `\f` 切页；docx/pptx 读 word/ppt 的 XML；xlsx 拼共享字符串与单元格；不认识的后缀按二进制跳过。
3. 找 workorder：递归遍历 case 的任意值，第一个“像图单”的字典（含 `figure_kind`/`required_parts`/`required_connections`/`steps`/`stages`/`workorder_type` 中任一键）即为工作单。
4. 无工作单时的兜底：段落里的清单条目当部件、行首编号当步骤；在 `exceptions` 注明“由正文推断”。
5. 材料未给的内容只登记为缺口，不进图。

## 4. 内部模型

- **parts**：名称、数量、接口列表、可选分组；名称必须逐字取自材料。
- **connections**：起止部件、介质（material/energy/information）、方向、标签、接口；也接受 `A -> B(物料)` 这种一行式写法。
- **steps**：图上序号、标题、前置项、是否并行、回流目标、备注。
- **stages**：目标、方法、输入、输出、依赖、里程碑。

模型先落到 `figure_model.json`，再交给布局器；布局器只认图元，不回头改模型。

## 5. result.json 字段

### 5.1 顶层

| 键 | 内容 |
|-|-|
| `case_id` | 原样回填输入 case 的标识 |
| `status` | `ok` / `partial` / `insufficient_evidence` / `input_error` |
| `editable_source` | 源文件路径、格式、图层、viewBox、文字数、字节、sha256 |
| `export_artifact` | `png` 与 `pdf` 两个子对象，含引擎名与文件头校验 |
| `content_map` | 图元 ↔ 来源的对应表，含 coverage 统计 |
| `compliance_checks` | 全部自检项与总 pass/failures |
| `exceptions` | 逐条异常：code / message / severity / action |
| `sources` | 材料清单：编号、路径、类型、字符数 |
| `uncertainty` | 需要读者知道的不确定性 |
| `pending_human` | 必须人工确认的事项 |
| `errors` | 脚本级错误（含 trace 片段） |
| `degradations` | 导出链降级登记 |
| `changes` | 本次构建相对原图/前版的变化 |
| `runtime` | 版本、耗时、参数、Python 版本 |
| `output_contract` | 输入约定的回填结果 |

`output_contract` 里的每个键都会提升到顶层同名键位；没有值就写 `null`，键名不改、未知键保留。

### 5.2 content_map 与 checks

`content_map` 固定包含 `parts`、`connections`、`steps`、`stages`、`legend`、`panels`、`coverage` 七项；前四类元素都要带 `id`、`source{locator,quote,file}`、`source_verified`。

`compliance_checks` 中值得单独看的几项：`dangling_connections`、`step_numbering`、`id_coverage`、`quote_verification`、`pixel_probe`、`determinism`、`artifact_audit`。最后一项是本 Skill 自加的：把三份交付物的字节数、sha256 前 16 位、文件签名与模型 id 覆盖情况一次列出。

## 6. 证据规则

- 引文（`quote`）必须能在材料原文中连续检索到；检索不到就不写引文，元素标为未核验。
- `locator` 的构成：普通文本 `S<编号>:L<行>`；PDF `S<编号>:p<页>:L<行>`。`S<编号>` 与 `sources[].id` 对应。
- 数字、单位、温度、转速等照抄原文书写方式；材料写 `37 °C` 就不要写成 `310 K` 或 `37°C`。
- 交付前随机抽 3 条元素，回到原文核对引文是否真的存在。

## 7. 不确定时的处置

| 场景 | 决定 |
|-|-|
| 连接只给一端 | 不画；`conn_one_end` + `pending_human` |
| 端点不存在于部件表 | 不画；`conn_dangling`，宁可少画一条线 |
| 部件数量没写 | 图上标注“数量未报告”，不填数字 |
| 步骤原编号与出现顺序冲突 | 图上重排为连续序号，原编号记 `source_order` |
| workorder 图型与正文不符 | 以 workorder 为准；正文明显不支持时按正文出图并把冲突写进 `exceptions` |
| 完全无可画对象 | `insufficient_evidence`，画布写缺口说明 |

## 8. 降级手册

| 缺失/故障 | 行为 |
|-|-|
| case 缺失或 JSON 损坏 | 继续扫描材料，记 `case_unreadable` |
| 单个材料无法解析 | 记 `material_unreadable`，其余材料照常使用 |
| 没有 workorder | 从正文抽取，记 `parts_from_text` / `steps_from_text` |
| PDF 转换器全无 | 依次尝试 soffice、Chromium、标准库矢量写出；最后一种跳过 CJK 字形（记 `pdf_degraded`） |
| PNG 光栅器全无 | 依次尝试 pdftoppm、gs、Chromium 截图、soffice；全失败则 `png_failed`，不允许用文字替代图片 |
| 中文字体缺失 | SVG 保留真文本；PDF 的字体嵌入状态在 `fonts` 与引擎名里如实记录 |
| 内容超出画布 | 画布高度按包围盒自动加高；`overflow.ok` 断言 |

## 9. 验收清单

- [ ] `--help` 可跑，退出码 0，且与当前工作目录无关。
- [ ] 最小 case 能产出五个文件，`result.json` 合法。
- [ ] `output_contract` 的键全部出现在顶层。
- [ ] `compliance_checks.pass == true`，或 `failures` 每项都有解释。
- [ ] SVG 里 `layer-*` 分层齐全，`content_map` 的 id 都能在 SVG 里找到。
- [ ] PDF 有 `%PDF-` 前缀且不含整页位图；PNG 能解出 IHDR 且不是纯色。
- [ ] 同一输入运行两次，SVG 的 sha256 相同。
- [ ] 空目录、坏 JSON、缺工作单三种情况都仍写出合法 partial。

## 10. 示例（示例，不是正式案例结果）

输入（示意；`output_contract` 只列键名）：

```json
{"case_id": "sample-apparatus-07",
 "figure_workorder": {
   "workorder_type": "apparatus_and_technical_route",
   "figure_kind": "apparatus_schematic",
   "required_parts": [
     {"name": "氮气瓶", "qty": 1},
     {"name": "质量流量计", "qty": 1},
     {"name": "管式炉", "qty": 1}],
   "required_connections": [
     {"from": "氮气瓶", "to": "质量流量计", "medium": "material"},
     {"from": "质量流量计", "to": "管式炉", "medium": "information"}]},
 "output_contract": {
   "case_id": null,
   "status": null,
   "editable_source": null,
   "export_artifact": null,
   "content_map": null,
   "compliance_checks": null,
   "exceptions": null}}
```

输出（示意）：`figure.svg` 宽 1440、分层含 background/zones/connections/parts/steps/stages/data/legend/labels/notes；`figure.pdf` 单页矢量；`figure.png` 真实位图；`result.json.status` 为 `ok`，`coverage.parts` 为 3，`dangling_connections.count` 为 0。示例数据只用于演示接口，不代表正式答案。

## 11. 设计取舍与已知限制

- **为什么先写 partial**：评测预算有限，先落盘再干活，任何中断都不会出现“没有结果”的状态。
- **为什么 SVG 是唯一真值**：PDF/PNG 都从同一份图元列表派生，避免三个文件各画一遍导致不一致。
- **为什么不做局部放大/剖面**：当前布局器只覆盖整图视角；需要放大时应在材料里给出子图清单，或人工二次编辑 SVG。
- **标准库 PDF 的限制**：没有字体子集化能力，CJK 字形会被跳过；该路径只在没有任何转换器时触发，并明确写进 `exceptions`。
- **同类部件区分**：靠图内序号徽标（1..N）与名称文本区分，不做颜色区分，避免与介质色冲突。

## 12. 目录与扩展

`scripts/route_figure.py` 是入口（读输入、建模型、自检、写结果）；`scripts/svg_export.py` 管图元、布局与导出。三份 `references/` 分别讲图面语法、导出引擎链与坑位清单。

扩展方式：新格式 → 在 `read_material` 加分支；新图型 → 在 `choose_panels` 注册面板函数，函数必须返回新的 y 游标，且每个图元都要带 `eid` 与 `src`；改字段 → 同步 `blank_result`、`content_map`、`compliance_checks` 与第 5 节。回归方式：同一最小输入跑两次，比较 SVG sha256 与 `artifact_audit`。

## 13. 输入变体对照

材料长什么样，代码走哪条路，下表给出对照。遇到没列出的形态时，优先保证「实体名逐字、连接两端可解析、步骤顺序可对照」三条不倒。

| 材料形态 | 读取方式 | 需要注意 |
|-|-|-|
| 方法段落（无清单） | 整段作材料，workorder 缺失时按行内编号抽步骤 | 部件名可能只出现一次，引文取整行 |
| 表格（md/tsv/csv） | 纯文本直读，行内 `|` 不特殊处理 | 表头行不要当成部件名 |
| PDF 论文 | `pdftotext -layout`，失败解压内容流 | 页号进 locator，双栏文本顺序可能错乱 |
| docx 实验方案 | 取 `word/document.xml` 纯文本 | 修订痕迹与批注会被保留，人工确认时留意 |
| xlsx 参数表 | 拼共享字符串与单元格值 | 数字被格式化成字符串，按原样抄 |
| 既有 SVG/模型 | 当文本材料读，作为重建依据 | 不直接改旧图，`changes` 里声明重建来源 |
| 中英混排 | 统一按 UTF-8 读，字体栈先 CJK 后西文 | 折行按字符宽度估算，不做单词断行 |
| 同类部件多个 | 名称+图内序号区分 | 不要把「柱 A / 柱 B」合并成一个部件 |

## 14. 可复现的三个习惯

第一，所有坐标都从模型数据与常量算出来，不用随机数、不读时钟、不依赖文件遍历顺序；这样同一份模型每次布局一致。第二，模型先写 `figure_model.json` 再画图，复核者可以直接拿模型对照图面，不用反推。第三，任何外部转换器都当作可选件：缺了就换下一条链路，并把实际用的引擎与降级原因写进结果，绝不让“成功”靠猜测得来。

## 15. 常见问题

**问：材料里只有文字，没有数量，图还能不能画？** 能，部件框照画，下方标“数量未报告”，数量字段留空，并在 `pending_human` 里点出来。

**问：workorder 要求组合图，但材料只有装置部分怎么办？** 按 workorder 保留组合图骨架，缺的面板给出说明性占位文字，同时把缺失写进 `uncertainty`，不要编造流程步骤。

**问：连接出现在正文但没有画在图上？** 检查它的两端是否都在部件表里；缺一端或端点未知的连接会被主动压下不画，这是有意的保守策略，见 `dangling_connections.not_drawn`。

**问：为什么 PDF 里的中文和 SVG 不完全一样？** 当环境里没有任何 SVG→PDF 转换器时会走标准库兜底，它只写 Latin 文字；此时以 SVG 为准，`exceptions.pdf_degraded` 会说明跳过了多少字符。

**问：两个案例输出同名文件会不会串？** 脚本不读全局状态，输出目录由 `--output` 决定；评测时每个案例独立目录即可。

## 16. 与“直接让模型画图”的差别

直接让模型写绘图代码，常见问题是坐标靠猜、部件名被同义改写、连接方向没有约束，且第二次运行结果可能变样。本 Skill 把“读懂材料”和“画图”拆开：前者产出带引文的模型，后者只做确定性的几何映射；两者之间用 `figure_model.json` 解耦。这样每一步都能单独测试、单独复核，也能在不碰绘图代码的情况下替换输入解析策略。

第四，把每次运行当作一次可审计事件：
untime 记录参数与耗时，sources 记录读了哪些文件，changes 记录相对原图动了什么。这样即使换人接手，也能从结果文件还原出当时的输入与判断。工程上还有一个容易忽略的点：不要在脚本里硬编码绝对路径，入口脚本用自身所在目录定位同包模块，否则换机器或换挂载点就跑不起来。

## 17. 一次运行该留下哪些记录

交稿之前建议按下面的顺序留一份运行记录，方便自己和评审对照：输入目录的文件清单、脚本版本、运行命令、
esult.json 的 status 与 ailures、三份交付物的引擎名、SVG 的 sha256、以及两次运行的哈希是否一致。记录不必写成长文档，一条命令的输出粘贴即可；关键是可复核，而不是好看。

如果评测平台对单次运行有时限，建议把“先落盘再完善”当作硬规则：哪怕模型只建了一半，也要让 
esult.json 可读、exceptions 能解释缺什么。这样评分者看到的是一个交代清楚的半成品，而不是一个空目录。
