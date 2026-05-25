# CAD 环境差异化检查与同步脚本任务书

更新时间：2026-05-22

## 1. 背景与目标

当前问题不是单纯的 DWG 数据损坏：用户反馈同一张图纸在开发机 PDF 正常，在部署机 PDF 中 `TSSD_Label` 相关文字变大或挤出图框；同时拆分后的 DWG 在 CAD 中打开又是正常的。这说明问题更可能发生在部署机的 AutoCAD / AcCoreConsole 打印环境，而不是图框识别或 WBLOCK 拆图本身。

本任务的目标是让新对话可以直接开始制作一个“CAD 环境差异化检查并同步”的工具链：

- 在开发机生成一份“黄金环境指纹”。
- 在部署机生成一份“实际环境指纹”。
- 自动对比差异，明确哪些设置会影响字体、PDF、PC3/CTB、打印路径。
- 在用户确认后，将部署机同步到开发机等价环境，或至少把程序运行时强制设置为等价环境。

## 2. 已知项目现状

当前仓库中已经有以下相关能力：

- 字体库目录已经存在：`documents_bin/font-library/ttf` 与 `documents_bin/font-library/shx`。
- 运行期配置默认将字体库加入 `font_preflight.font_library_dirs`。
- AcCoreConsole 运行脚本会设置 `SupportPath`、`FONTMAP`、`FONTALT`，但当前实现是运行时脚本注入，不是完整 AutoCAD 用户 Profile 镜像。
- `backend/src/cad/slot_pool.py` 会生成 `fanban-slot-xx.arg` 文件，但目前该文件只是记录路径信息，不是 AutoCAD 官方 ARG Profile，也没有在 `accoreconsole.exe` 启动命令中使用 `/p` 参数。
- 2026-05-22 已将默认 PDF 打印主路径切到“拆分后 DWG 打印”，但部署机仍可能因 AcCoreConsole 环境差异导致 PDF 字体渲染异常。

## 3. 外部资料结论

Autodesk 官方明确记录过“AutoCAD 中显示正常，但打印为 PDF 后文字变形、挤压、移位、变大或挤出标题栏”的问题，并给出的规避方式之一是在 PDF Options 中关闭字体捕获并启用 `Convert all text to geometry`。[Text gets moved or resized after plotting to PDF in AutoCAD](https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Text-gets-moved-or-resized-after-plotting-to-PDF-in-AutoCAD.html?msockid=298b3a1be289676f05c92cb2e33a6643)

`FONTMAP` 是字体映射文件系统变量，初始值通常是 `acad.fmp`，并且只作用于 `MTEXT`；如果映射命中，会改变 MTEXT 字体替代结果。[FONTMAP System Variable](https://help.autodesk.com/cloudhelp/2021/ENU/AutoCAD-Core/files/GUID-FC45A5DC-31F5-4725-A482-C95769273C1C.htm)

AutoCAD 的字体替代会使用 `FONTALT`，亚洲 Big Font 也会受替代字体影响；官方同时提醒替代字体不相似时容易造成文本长度或换行问题。[About Substitute Fonts](https://help.autodesk.com/cloudhelp/2023/ENU/AutoCAD-Core/files/GUID-928DF015-1E04-4CC2-AF1B-0037548DFBAE.htm)

Autodesk 对缺失 SHX 的处理建议包括把 SHX 放入 AutoCAD 字体目录，或把自定义字体目录加入 `Support File Search Path`。[One or more SHX files are missing](https://www.autodesk.com/support/technical/article/AutoCAD-cannot-find-SHX-font/)

AutoCAD 支持通过命令行 `/p` 参数指定 Options 中的 Profile 名称或一个导出的 ARG Profile 文件；这为“部署机加载开发机同等 Profile”提供了官方入口。[Command Line Switch Reference](https://help.autodesk.com/cloudhelp/2020/ENU/AutoCAD-Core/files/GUID-8E54B6EC-5B52-4F62-B7FC-0D4E1EDF093A.htm)

## 4. 需要优先验证的假设

### 假设 A：部署机 AcCoreConsole 加载的 Profile 与人工 CAD 不一致

现象解释：

- 用户在 GUI CAD 中手工打印正常。
- 程序通过 AcCoreConsole 打印异常。
- 说明 GUI CAD 当前 Profile、Plotter、PDF Options、字体路径可能正常，但 AcCoreConsole 启动环境没有继承同一套设置。

检查方式：

- 对比 GUI CAD 与 AcCoreConsole 中的 `FONTMAP`、`FONTALT`、`ACADPREFIX`、`ROAMABLEROOTPREFIX`、`LOCALROOTPREFIX`。
- 对比 PC3/PMP/CTB 实际加载路径与文件 hash。
- 检查 AcCoreConsole 启动命令是否使用 `/p` 加载固定 Profile。

### 假设 B：PDF2.pc3 的 PDF Options 不一致

现象解释：

- DWG 打开正常，但 PDF 文字变大。
- Autodesk 官方记录过 PDF 输出阶段文字会变形，并建议使用 `Convert all text to geometry`。

检查方式：

- 对比开发机与部署机 `打印PDF2.pc3`、PMP 文件、CTB 文件的 SHA256。
- 在 GUI CAD 中检查 `PDF Options > Font Handling`。
- 在程序打包资源中固定 PC3/PMP，并在运行期复制到 slot 私有 Plotters 目录。

### 假设 C：同名 SHX / BigFont 搜索命中顺序不同

现象解释：

- 文件名相同不代表运行时真的加载了同一份文件。
- `findfile` 返回路径可能指向 AutoCAD 自带目录、用户 Roaming Support、程序字体库或其他插件目录。

检查方式：

- 在 GUI CAD 和 AcCoreConsole 中分别执行：

```lisp
(findfile "tssdeng.shx")
(findfile "hztxt.shx")
(findfile "tssdchn.shx")
(getvar "FONTMAP")
(getvar "FONTALT")
(getvar "ACADPREFIX")
```

- 对 `findfile` 返回文件计算 SHA256。
- 对比 `TSSD_Label` 的 `FontFile`、`BigFontFile`、`XScale`、`TextSize`。

## 5. 建议脚本设计

建议新增两个脚本，而不是一个脚本直接修改环境：

### 5.1 `cad_env_fingerprint.ps1`

用途：只读采集，不修改机器。

输入：

- `-CadExe` 或 `-AccoreConsoleExe`
- `-SampleDwg`
- `-OutputJson`
- `-FontLibraryDir`
- `-Pc3Name`
- `-CtbName`

输出 JSON 建议字段：

- `machine`: 机器名、用户名、Windows 版本。
- `autocad`: `acad.exe`、`accoreconsole.exe`、版本、语言、安装目录。
- `profile`: 当前 Profile、`ROAMABLEROOTPREFIX`、`LOCALROOTPREFIX`、`TRUSTEDPATHS`。
- `support_paths`: `ACADPREFIX` 展开后的路径列表。
- `font_vars`: `FONTMAP`、`FONTALT`、`FONTALT` 解析结果。
- `font_findfile`: `tssdeng.shx`、`hztxt.shx`、`tssdchn.shx`、`simplex.shx`、`gbcbig.shx`、`simsun.ttc` 的 `findfile` 路径与 SHA256。
- `text_styles`: `TSSD_Label`、`TSSD_Norm`、`STANDARD` 等样式的 `FontFile`、`BigFontFile`、`XScale`、`TextSize`、是否 UseBigFont。
- `plot_assets`: `打印PDF2.pc3`、PMP、目标 CTB 的路径、大小、SHA256。
- `pdf_vars`: `BACKGROUNDPLOT`、`PDFSHX`、`EPDFSHX`、其他能读取到的 PDF/plot 相关变量。
- `sample_plot`: 使用样本 DWG 输出一页测试 PDF，并记录 result、日志路径、PDF size。

实现建议：

- PowerShell 负责启动 AcCoreConsole 与收集文件 hash。
- AutoLISP 或 .NET Bridge 负责在 CAD 内执行 `getvar`、`findfile`、样式表扫描。
- 输出必须包含原始 `accoreconsole.log` 与 `module5_trace.log`。

### 5.2 `cad_env_sync.ps1`

用途：根据黄金指纹同步部署机。

默认必须是 dry-run：

```powershell
.\cad_env_sync.ps1 -GoldenJson .\golden.json -TargetJson .\target.json -Apply:$false
```

可同步项：

- 将团队字体库路径前置到 Support Path。
- 写入固定 `FONTMAP` 或清空异常 `acad.fmp` 映射。
- 写入固定 `FONTALT`。
- 复制 PC3/PMP/CTB 到程序 slot 私有目录。
- 可选：生成并加载官方 ARG Profile。
- 可选：设置 PDF Options 走 `Convert all text to geometry` 的 PC3 变体。

禁止默认修改项：

- 不直接覆盖用户全局 AutoCAD 原 Profile。
- 不删除用户字体。
- 不修改系统字体目录。
- 不静默覆盖 AutoCAD 安装目录文件。

## 6. 后端联动建议

### 方案 1：最小增强，先做诊断

在 `AcCoreConsoleRunner` 运行每个 CAD 任务前后，额外写出环境探针日志：

- `getvar FONTMAP`
- `getvar FONTALT`
- `getvar ACADPREFIX`
- `findfile tssdeng.shx`
- `findfile hztxt.shx`
- `findfile 打印PDF2.pc3`

优点：最快定位实际机到底加载了什么。

风险：只能定位，不能自动修复。

### 方案 2：固定运行时环境，推荐

将 CAD 运行环境当作正式产物管理：

- 程序打包时包含字体库、PC3、PMP、CTB、固定 FMP、固定 Profile 模板。
- 每个任务 slot 使用私有 Support/Plotters/Plot Styles 目录。
- AcCoreConsole 启动时尽量使用 `/p` 加载固定 ARG Profile。
- 运行脚本仍兜底设置 `SupportPath`、`FONTMAP`、`FONTALT`、`BACKGROUNDPLOT=0`。

优点：最接近工程化部署，能解释并消除“本机好、部署机坏”的环境漂移。

风险：需要确认 AcCoreConsole 对 ARG Profile 的兼容性，并避免影响用户全局 CAD。

### 方案 3：PDF 文字转几何兜底

为 `打印PDF2.pc3` 增加一个“文字转几何”变体，例如：

- `打印PDF2-text-geometry.pc3`

遇到 `TSSD_Label`、SHX BigFont、或部署机环境不可信时使用该 PC3。

优点：对 PDF 文本变形类问题非常直接，符合 Autodesk 官方建议。

风险：PDF 中文字可能不可复制/不可搜索，文件体积可能变大；需要业务确认是否可接受。

## 7. 推荐实施路线

1. 先做 `cad_env_fingerprint.ps1`，只读输出开发机与部署机 JSON。
2. 用同一张样本 DWG 同时采集 GUI CAD 与 AcCoreConsole 环境。
3. 对比字体命中路径、PC3/PMP/CTB hash、`FONTMAP/FONTALT`。
4. 如果差异明确，做 `cad_env_sync.ps1` dry-run。
5. 确认后只同步 slot 私有目录与程序运行时配置，不改用户全局 CAD。
6. 再做 PDF 文字转几何 PC3 变体，作为 `TSSD_Label` 高风险样本兜底。
7. 最后将环境指纹附加到任务记录，后续出现问题时能直接定位部署环境漂移。

## 8. 验收标准

- 开发机与部署机的环境指纹 JSON 可稳定生成。
- 指纹对比能指出 `FONTMAP/FONTALT/SupportPath/PC3/PMP/CTB/hash` 的差异。
- 同一问题 DWG 在同步后 PDF 文字不再变大或挤出图框。
- 任务日志中能看到实际加载的 `tssdeng.shx`、`hztxt.shx`、PC3、CTB 路径。
- 脚本默认 dry-run，不会误改用户全局 AutoCAD 环境。

