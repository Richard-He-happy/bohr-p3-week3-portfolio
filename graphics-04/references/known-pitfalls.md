# 已知坑位与对应守卫

按“症状 → 代码守卫 → 证据字段”组织。每条都对应一次真实调试，不是理论清单。

## 内容类

**箭头半截、管路凭空多出来。** 守卫：任何连接必须能解析出两个存在于部件表的 id，否则 `drawable=false` 直接不画。证据：`dangling_connections.count` 必须为 0，`not_drawn` 列出被压下的连接；异常记 `conn_dangling` / `conn_one_end`。

**流向画反。** 守卫：先拓扑分层再画，上游层号严格小于下游；箭头统一挂在 `to` 端。证据：`flow_direction.ok`。

**编号与正文错位。** 守卫：图上编号只认出现顺序 1..N，workorder 给的原始编号进 `source_order`。证据：`step_numbering.contiguous_1_to_n`。

**冒出材料里没有的部件、数字、单位。** 守卫：所有图元都要求逐字引文，找不到就标 `source_verified=false` 并进人工确认清单。证据：`quote_verification.rate`。

**图例和线不一致。** 守卫：图例项与连线共用一张介质表，同源生成。证据：`content_map.legend[].in_svg`。

## 表达类

**技术路线变成并列词条。** 守卫：每个阶段固定输出目标/方法/输入/输出/依赖/里程碑六段，并画阶段间推进箭头。

**依赖箭头指向不存在的阶段。** 守卫：依赖只做相邻阶段箭头与文字标注，不生成图外线。

**装置/流程/路线判错。** 守卫：先读 `workorder_type`，同时出现 apparatus 与 route/process 就出组合图；再读 `figure_kind`；确实没写才按模型推断，记 `figure_kind_inferred`。

**图被裁。** 守卫：画布高度由包围盒计算，`overflow.ok` 断言全部元素在画布内。

## 导出类

1. **soffice 卡几分钟不动**：八成是 office profile 落在工作区。改法：profile 用 `tempfile.mkdtemp()`，`HOME` 环境变量指向它。
2. **调用 soffice 的 `subprocess.run` 不返回**：office 的子进程继承了管道。改法：stdout/stderr 重定向到日志文件，`stdin` 设为 DEVNULL，单步加超时。
3. **第一次 `--convert-to pdf` 没生成文件**：profile 尚在预热。改法：失败后原样重试一次。
4. **PDF 打开发现是整页截图**：走了位图导出路径。检查：文件里有没有 `/Subtype /Image`；有就说明 `vector=false`，属于扣分项。
5. **中文全变方框**：PDF 没有嵌入 CJK 字形。改法：优先用 soffice/Chromium 转换；标准库兜底 PDF 只保留 Latin 字符，`fonts.embedded_in_pdf` 会写明。
6. **PNG 一片空白**：光栅器缺失或画布尺寸异常。改法：像素探针 `non_blank=false` 判失败，逐级换引擎，最终记 `png_failed`，绝不拿文字描述糊弄。

## 运行类

- 单个材料解析失败 → 单文件 try/except，写 `material_unreadable`，其他材料照常。
- 空输入或 JSON 损坏 → 先写 partial `result.json`，退出码保持 0。
- 模型为空 → 装置面板提前返回缺口说明；计数处用 `max(..., default=1)` 兜底。
- 主流程异常 → 外层 catch 写 `errors.pipeline_error` 与 trace，仍然 finalize。
- 重复运行结果漂移 → 坐标全部由数据推导；`determinism.rerender_identical` 与 `artifact_audit` 双重断言。

## 复核者五步

1. 看 `status` 与 `compliance_checks.pass/failures`；
2. 抽 3 条 `content_map` 元素按 `locator` 回原文核引文；
3. 打开 `figure.svg` 看分层、文字是否可选、id 是否对得上；
4. 打开 `figure.pdf` 看中文是否正常、是否含位图；
5. 看 `export_artifact.*.engine` 判断走了哪条降级链。

## 维护者补充说明

修改布局或导出逻辑后，建议按下面的顺序回归，避免“改好一个、坏掉一片”：先跑一次最小输入看五件交付物是否齐全；再用空目录、坏 JSON、缺少 workorder 三个反例确认退出码仍是 0；最后连续跑两次比对 SVG 哈希。若改动涉及外部转换器，还要在装与不装 soffice 的两台环境各跑一遍，确认引擎名与降级记录都符合预期。

另外，`content_map` 的字段一旦被下游工具消费，就不要随意改名；新增字段可以，删除或重命名要同步 SKILL.md 与所有引用它的脚本。引文定位依赖 `sources[].id` 的稳定性，材料文件顺序变化会改变 `S` 编号，因此不要把 `S1`、`S2` 之类的编号写死在任何额外产物里。
