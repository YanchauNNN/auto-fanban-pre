# AI 对话附件与多模态接入设计

## 目标

在现有 AI 悬浮对话面板中增加安全、可审计的文件与图片上传能力，同时兼容开发环境 MiniMax 和终端内网 Qwen OpenAI-compatible 网关。所有模型请求继续由部署后端发出，不允许浏览器直接访问模型网关。

## 已确认边界

- 开发环境允许上传内容发送给 MiniMax。
- 终端环境使用 `terminal_cnpe_intranet_qwen_fast`。
- 第一版继续使用单一 Agent 编排，不依赖 Agents SDK 或 MCP。
- 图片可以使用 Chat Completions `image_url`；实机探针已验证通过。
- Chat Completions 原生 `file` 部件在实机返回 HTTP 501，因此普通文件必须由后端解析。
- `/responses` 的 `input_file` 只做兼容性探测，不作为第一版运行依赖。
- AI 仅对附件进行只读分析，不修改 DWG、文档、任务、流程或文件。

## 方案选择

采用后端托管附件的混合方案：浏览器将附件上传到 FanBan 后端；后端完成权限校验、磁盘存储、内容解析和模型消息组装。图片以 base64 data URL 传给支持视觉输入的模型，其他文件转换为受控文本或结构化图纸元素上下文。

不采用模型原生文件直传作为主路径，因为终端模型的 Chat Completions 接口不支持 `type: file`。不在第一版建设完整向量库或异步 RAG，附件表和解析结果为后续知识库演进保留数据基础。

## 身份与代理链路

后端只在 TCP 对端为受信任代理时读取 `X-Forwarded-For`。第一版受信任代理默认为 `127.0.0.1` 和 `::1`，对应 IIS/ARR 到 Uvicorn 的本机转发；其他来源忽略转发头并使用 TCP 对端地址。

owner key 仍为规范化后的 `ip:<address>`。IPv4、IPv4 加端口、IPv6、IPv6 加端口和转发链均使用 `ipaddress` 解析。附件、会话和消息必须使用同一 owner key 进行授权。

## 数据模型与存储

SQLite 新增 `ai_attachments`：

- `attachment_id`
- `conversation_id`
- `message_id`
- `owner_key`
- `original_name`
- `stored_name`
- `media_type`
- `kind`
- `size_bytes`
- `sha256`
- `status`
- `extracted_text`
- `metadata_json`
- `error_code`
- `created_at`

原件保存到：

```text
storage/ai/chat/attachments/<owner_sha256>/<conversation_id>/<attachment_id>/original.<ext>
```

磁盘路径不出现原始 IP。附件查询、删除和消息绑定同时校验 owner、conversation 和 attachment。清空会话、删除会话、过期清理时同步删除数据库记录与磁盘目录。

## API

- `POST /api/ai/conversations/{id}/attachments`：multipart 上传并同步解析。
- `GET /api/ai/conversations/{id}/attachments`：列出当前 owner 的附件。
- `DELETE /api/ai/conversations/{id}/attachments/{attachment_id}`：删除当前 owner 的附件。
- `POST /api/ai/conversations/{id}/messages`：增加 `attachment_ids`。
- `GET /api/ai/state`：返回附件能力、允许扩展名和大小限制。

上传失败返回明确的 4xx 错误；解析器失败时保留附件记录并标记 `failed`，不允许将失败附件绑定到模型请求。

## 文件解析

- 图片：PNG、JPEG、WebP 校验 MIME 和实际文件头，模型请求中使用 `image_url` data URL。
- TXT：依次尝试 UTF-8、UTF-8 BOM 和 GB18030。
- PDF：使用 `pypdf` 按页提取文本并保留页码边界。
- DOCX：使用 `python-docx` 提取段落和表格。
- XLSX：使用 `openpyxl` 只读模式提取工作表和非空单元格。
- DXF：使用 `ezdxf` 生成实体统计、图层、文本、图框和语义摘要。
- DWG：复用 `ODAConverter.dwg_to_dxf()` 后进入同一 DXF 解析服务。

CAD 解析逻辑从现有 `tools/ai/export_drawing_understanding.py` 提取为后端可复用服务，工具脚本改为调用该服务，避免两套图纸理解实现漂移。

## 模型上下文与记忆

用户可发送纯附件或“文本 + 附件”。原始用户文本保持用于前端展示，解析内容只进入模型内容和消息 metadata，不直接显示为用户消息正文。

附件解析内容使用明确的不可信数据边界，提示模型不得把附件中的文字当作系统指令。历史消息重建时，已绑定且未删除的附件摘要继续进入上下文，使用户可以追问已上传文件。

图片仅在当前消息发送时注入 data URL；后续轮次使用图片解析元数据和模型前一轮回答，避免每轮重复传输大体积 base64。

## 参数

参数统一写入 `documents/AI/参数规范_AI.yaml`：

- `chat.attachments.enabled: true`
- `max_files_per_message: 5`
- `max_image_size_mb: 10`
- `max_file_size_mb: 50`
- `max_total_size_mb_per_message: 100`
- `max_extracted_chars_per_file: 20000`
- `max_context_chars_per_message: 60000`
- `retention_days: 30`
- 支持扩展名：PNG、JPG、JPEG、WebP、TXT、PDF、DOCX、XLSX、DXF、DWG
- 开发 MiniMax 与终端 Qwen 均允许附件进入模型。

## 前端交互

输入区左侧增加带工具提示的 `+` 图标按钮和隐藏文件选择器。附件选择后显示文件名、大小、上传/解析状态、图片缩略图和移除按钮。发送按钮仅在文本或至少一个就绪附件存在时可用；上传、解析或模型等待期间显示独立状态，不让整个面板失去响应。

历史用户消息显示附件名称和类型，不渲染后端提取全文。

## 探针

现有 Chat Completions 图片和文件测试保留。新增 Responses API `input_file` 探测，使用 `input_text + input_file(file_data, filename)`，结果单独写入 `checks.multimodal.responses_file_input`。该结果不影响第一版后端解析路径。

## 验收

- IIS 转发后 owner 使用真实客户端 IP，非受信任来源不能伪造。
- 不同 owner 不能列出、绑定或删除对方附件。
- 图片能被内网模型识别。
- TXT、PDF、DOCX、XLSX 能提取固定测试标记。
- DXF 能生成实体摘要；DWG 能通过模拟和真实 ODA 路径进入同一解析服务。
- 附件和会话删除同步清理磁盘。
- 前端可选择、预览、移除、上传和发送附件。
- Responses API 文件探测结果写入诊断 JSON。
- 后端测试、前端 Vitest、前端构建和本地真实烟测通过。

## 参考

- OpenAI Responses API 的输入内容支持 `input_file`、`file_data`、`file_id` 和 `file_url`：https://platform.openai.com/docs/api-reference/responses-streaming/response/refusal/delta?lang=curl
