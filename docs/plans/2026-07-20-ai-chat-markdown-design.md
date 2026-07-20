# AI 对话 Markdown/GFM 安全渲染设计

## 目标

在完全断网的终端环境中，为 AI 回复增加安全的 Markdown/GFM 渲染，重点支持
APDL 代码块、表格、列表、普通换行和复制代码。用户消息继续按纯文本显示。

## 架构

前端新增独立的 `AiMessageContent` 组件，仅接收助手消息。组件使用
`react-markdown` 解析 CommonMark，使用 `remark-gfm` 扩展表格、任务列表和删除线，
使用 `remark-breaks` 将聊天回复中的普通换行转换为可见换行，并使用
`rehype-sanitize` 做第二层元素和属性清理。

终端部署继续使用 Vite 生成的 `frontend/dist` 静态产物。Markdown 依赖随构建结果
进入 `frontend-dist`，浏览器运行时不访问 npm、CDN 或互联网。

## 安全边界

- 不启用 `rehype-raw`，并设置 `skipHtml`，原始 HTML 不进入页面。
- 仅允许文本排版、列表、表格、引用、链接和代码所需元素。
- 禁止图片、音视频、iframe、表单和其他可自动请求外部资源的元素。
- 链接仅允许显式 `http` 和 `https` 协议，拒绝 `javascript`、`data`、`file`、
  相对路径和 UNC 路径。
- 外部链接使用新标签页打开，并设置 `noopener noreferrer`。
- 所有代码内容通过 React 文本节点输出，不使用 `dangerouslySetInnerHTML`。
- 用户消息不进入 Markdown 组件，继续使用普通文本节点。

## APDL 代码块

- 识别 `apdl`、`ansys`、`ansys-apdl` 和 `mapdl` 围栏语言，并统一显示 `APDL`。
- 保留命令缩进、空格、换行和 `!` 注释。
- 使用本地 JetBrains Mono 字体，长命令横向滚动，不撑破聊天抽屉。
- 围栏代码块提供复制按钮；行内代码不显示复制按钮。
- 复制内容仅包含代码正文，不包含围栏、语言标签和界面标题。

## 复制降级

复制操作首先调用 `navigator.clipboard.writeText`。若页面不是安全上下文、API
不可用或调用被拒绝，则使用隐藏 textarea 和 `document.execCommand("copy")`。
如果两种方式都失败，组件选中代码并显示“请按 Ctrl+C”提示，保证用户仍可手动复制。

## 模型输出约束

在 `documents/AI/参数规范_AI.yaml` 的 AI 聊天配置中增加统一响应格式提示：

- 使用 GFM 组织长回复。
- 命令、程序和配置使用围栏代码块。
- ANSYS/MAPDL/APDL 命令流使用 `apdl` 语言标签。
- 不输出原始 HTML。

后端把该提示作为所有 Agent 系统提示的后缀。开发 MiniMax 和终端内网模型使用
同一规则，不依赖具体模型 profile。

## 测试

- 组件测试覆盖标题、普通换行、列表、表格、任务列表和行内代码。
- 安全测试覆盖原始 HTML、危险协议、图片和用户消息纯文本。
- APDL 测试覆盖语言识别、缩进保留、复制成功、HTTP 回退和完全失败提示。
- 后端测试覆盖 YAML 加载和系统提示拼接。
- 最终运行后端目标测试、前端全量 Vitest、Vite 生产构建和浏览器烟测。
