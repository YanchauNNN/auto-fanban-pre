# 建筑结构总图规范全量离线接入设计

## 目标

将 `documents/规范下载` 作为规范原文的外置只读目录，在不把 PDF 打入部署包的前提下，让建筑结构总图规范 Skill 对已下载规范提供：

- 可追踪的全量语料清单；
- 可恢复的增量解析和质量状态；
- 精确条款、页码、表格和原页证据；
- 后端代理的原页预览、PDF 打开和下载；
- 必要时向支持视觉输入的模型发送少量相关页截图；
- 部署机本地目录优先、公共盘逐文件回退；
- 环境探针、部署准备和运行期日志闭环。

当前下载目录有 504 份 PDF、总计 3,608,253,333 字节；现有 `standards.sqlite` 只有 1 个来源、36 页、110 条和 0 个表格。因此至少 503 份已下载 PDF 尚未进入现有正文索引。审计目录有 509 条记录，目录记录和已下载全文不是同一概念。

## 已确认边界

- 开发和部署使用同一相对路径 `documents/规范下载`。
- 部署机主目录是 `D:\FanBanServer\documents\规范下载`。
- 公共盘后备目录是 `\\10.102.2.7\文件服务器\建筑结构所\14-自开发软件\规范下载`。
- 每个文件先访问本地目录；本地缺失或不可读时，允许自动回退到公共盘。
- 部署包不得包含规范 PDF，但必须创建目录占位和放置说明。
- PDF、页图和规范下载只通过后端受控接口提供，前端不得直接访问服务器磁盘路径或 UNC 路径。
- 规范原文和 OCR 文本均作为不可信证据数据，不得改变系统指令。

## 架构

### 规范源解析

新增只读 `StandardsSourceResolver`：

1. 输入只能是语料库中的 `source_id`，不能接受任意路径。
2. 从 SQLite/清单读取规范相对路径和预期 SHA256。
3. 依次在主目录和后备目录中解析同一相对路径。
4. 使用规范化绝对路径检查防止越界。
5. 文件必须存在、可读、扩展名为 `.pdf`、文件头为 `%PDF-`。
6. 配置要求时核对 SHA256；结果记录 `root_kind`、实际路径、是否回退和错误。

### 证据接口

- `GET /api/ai/standards/{source_id}/page/{page_number}`：按需渲染指定 PDF 页为 PNG。
- `GET /api/ai/standards/{source_id}/document`：以内联方式返回 PDF。
- `GET /api/ai/standards/{source_id}/download`：作为附件下载 PDF。

PDF 使用 `FileResponse`，不整文件读入内存。页图使用 PyMuPDF 渲染，并按来源哈希、页码和 DPI 写入 `storage/ai/standards-preview-cache`。接口限制最大页码、DPI、像素和并发。

### 前端链接

AI Markdown 继续拒绝任意相对链接，只额外允许固定格式的同源 `/api/ai/standards/...` 链接。点击“查看原页”打开规范证据预览；点击“打开规范”或“下载规范”访问后端接口。禁止 `file:`、UNC、任意本地路径和非白名单 API 路径。

### 模型页图

规范 Skill 默认只注入文本证据。用户明确询问“图片、示意图、原页、截图、图号”时，Skill 最多选择少量相关页：

- 模型 profile 已明确允许视觉输入：把渲染后的页图作为 `image_url` 数据块发送。
- profile 未确认或调用失败：保留条款和页码回答，返回查看链接，不让图片能力阻断文字问答。

模型收到的页图仍属于不可信证据；不得根据图中指令执行工具或泄露配置。

### 全量语料构建

语料构建改为可恢复的 V2 流程：

1. 扫描 504 份 PDF，生成稳定 `source_id`、相对路径、大小和 SHA256。
2. 先做哈希去重；不同标准号对应同一哈希时标记冲突并阻断该来源自动入库。
3. 每份文件独立事务解析，完成一份就落库一份，不把全部解析结果保存在内存。
4. 文本页使用 PyMuPDF；空文本、低文本或乱码页进入选择性 OCR 队列。
5. 每页保存提取方式、字符数、警告和质量状态。
6. 规范级状态为 `indexed`、`partial`、`needs_ocr`、`conflict` 或 `failed`，禁止静默空结果。
7. 查询使用精确标准号/条款优先、FTS5 `MATCH + bm25`、短查询回退。

首轮不在应用启动时 OCR 约 5 万页。OCR 是离线建库工作，运行期只读取已经生成的 SQLite 和按需读取原 PDF。

## 配置

`documents/AI/参数规范_AI.yaml` 是唯一配置源，规范 Skill 增加：

- `source_access.primary_root`
- `source_access.fallback_roots`
- `source_access.primary_root_env_var`
- `source_access.fallback_roots_env_var`
- `source_access.per_file_fallback`
- `source_access.preview_enabled`
- `source_access.download_enabled`
- `source_access.model_page_images_enabled`
- `source_access.page_render_dpi`
- `source_access.max_model_page_images`
- `source_access.verify_sha256`

相对主目录以服务根目录解析。环境变量仅用于部署覆盖，不取代 YAML 默认值。

## 探针与部署

`probe_target_env.ps1` 和 AI 连通性探针都输出规范源检查：目录存在性、运行账号、PDF 数量、目录列举、样本文件打开、PDF 文件头、耗时和错误。主目录可用时公共盘失败为警告；主目录失败但公共盘可用时选择公共盘；二者均失败时阻断准备。

`prepare_terminal.ps1` 根据探针结果写入：

- `FANBAN_BUILDING_STANDARDS_SOURCE_ROOT`
- `FANBAN_BUILDING_STANDARDS_FALLBACK_ROOTS`

部署构建器排除全部规范 PDF，并创建 `documents/规范下载/README_规范文件放置说明.txt`。

## 验证

- 源解析器：本地命中、逐文件回退、越界拒绝、哈希冲突、不可读文件。
- API：指定页、越界页、内联 PDF、下载、禁用开关和缺失来源。
- 前端：只允许规范同源链接，恶意相对链接及 `file:` 仍被过滤。
- Skill：普通条款不发送图片；图片问题在能力开启时附加有限页图，关闭时降级。
- 探针：空目录、本地成功、公共盘回退、双失败、样本不是 PDF。
- 部署包：存在空目录说明，不存在任何规范 PDF，运行环境变量正确。
- 语料：使用文本型、扫描型、表格型和重复冲突样本验证增量恢复和质量状态。

