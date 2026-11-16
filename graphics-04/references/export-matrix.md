# 导出引擎链与校验阈值

## 谁来写哪个文件

| 交付物 | 首选 | 备用链（从左到右，命中即停） | 结果里记录 |
|-|-|-|-|
| SVG 源 | 脚本自己的序列化器 | 无（它本身就是真值） | `editable_source` |
| PDF | `soffice --headless --convert-to pdf` | Chromium 无头打印 → 标准库直接写矢量 PDF | `export_artifact.pdf.engine` |
| PNG | `pdftoppm -png -r 160 -singlefile` | `gs -sDEVICE=png16m` → Chromium `--screenshot` → `soffice --convert-to png` | `export_artifact.png.engine` |

引擎名的含义：`soffice-svg2pdf`、`chromium-print-pdf` 两类会嵌入字体；`stdlib-vector-pdf` 只写几何与 Latin 文字，中文被跳过，会额外记 `pdf_degraded`；`pdftoppm`、`gs`、`chromium-screenshot`、`soffice-svg2png` 都是从 PDF/SVG 派生的光栅预览。

## 命令模板

```bash
# 桌面套件转 PDF（profile 放临时目录）
soffice --headless --nologo --nodefault --norestore --nolockcheck \
        -env:UserInstallation=file://<tmp>/lo --convert-to pdf \
        --outdir <out> <out>/figure.svg

# 无头浏览器打印 PDF
chrome --headless=new --disable-gpu --no-first-run --no-default-browser-check \
       --no-pdf-header-footer --user-data-dir=<tmp>/pdf \
       --print-to-pdf=<out>/figure.pdf file:///<out>/figure.svg

# 浏览器直接截图 PNG
chrome --headless=new --hide-scrollbars --user-data-dir=<tmp>/png \
       --window-size=<宽>,<高> --screenshot=<out>/figure.png file:///<out>/figure.svg
```

运行细节：office 的 profile 与 `HOME` 一律指向临时目录；子进程输出重定向到 `render.log` 并把 `stdin` 置空（office 会继承管道导致调用挂起）；单步 75–90 秒超时，整体渲染预算 640 秒；首次转换允许重试一次。

## 通过/不通过怎么判

| 对象 | 判据 | 不合格的含义 |
|-|-|-|
| SVG | 内容以 `<?xml` 起头 | 文件损坏或没落盘 |
| PDF | 前 5 字节是 `%PDF-`，且文件里至少一个 `/Type /Page` | 空文档或不是 PDF |
| PDF 质量 | 不含 `/Subtype /Image` | 被整页栅格化，属截图式 PDF |
| PNG | 前 8 字节是 PNG 签名 | 不是真 PNG |
| PNG 尺寸 | 宽高都大于 200 px | 画布异常过小 |
| PNG 内容 | 采样出多于一种颜色 | 空白或纯色预览 |

`artifact_audit` 会把三份交付物的字节数、sha256 前 16 位、签名校验结果与模型 id 覆盖情况汇总，便于一眼看出哪个产物其实是降级来的。

## 降级之后怎么写结果

- 少任何一个产物：`degradations` 里写明缺哪个，`status` 不低于 `partial`。
- PDF 由 Chromium 打印：`exceptions.pdf_engine_fallback`（minor），提醒投稿前再看字体。
- PDF 由标准库写出：`exceptions.pdf_degraded`（major），message 里说明跳过的 CJK 字符数。
- PDF 彻底失败：`exceptions.pdf_failed`（major），SVG 仍是可编辑真值。
- PNG 彻底失败：`exceptions.png_failed`（major），不要用文字说明冒充当图稿。

## 不同场景怎么交付

投稿/论文方法部分：PDF（矢量、字体嵌入）+ SVG（可再编辑）。组会汇报：PNG（长边约 2400 px）+ SVG。后续还要改图：只改 SVG 的图层与文字，重跑脚本统一导出，别单独修 PDF。
