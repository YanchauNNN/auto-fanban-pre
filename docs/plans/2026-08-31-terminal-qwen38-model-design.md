# 终端内网 Qwen3.8 模型切换设计

## 目标

将终端内网环境使用的模型网关从 `qwen_fast / Qwen3.6-35A3` 原位切换为 `qwen_medium / Qwen3.8-27B`，不保留旧模型回退配置；开发环境继续使用 `development_minimax`，两套环境的选择逻辑保持隔离。

## 约束与选择

- 保留 profile 标识 `terminal_cnpe_intranet_qwen_fast`，避免已生成的 `runtime.env.ps1`、启动脚本及部署机环境变量因 profile 改名而失效。
- 只在 YAML 中维护可配置的网关地址、模型名称和供应方标识，不把新模型参数散落到运行时代码。
- 内网地址按 OpenAI-compatible 基地址保存为 `http://models.ai.cnpe.cc/qwen_medium/v1`，客户端和连通性脚本继续拼接 `/chat/completions`。
- `chat_model` 与 `structured_model` 均切换为 `Qwen3.8-27B`，确保通用对话、Excel 规范化、AI 配筋建议等结构化任务使用同一新模型。
- 保持 `stream_enabled: true`、无鉴权头和 `intranet_only` 网络策略。终端连通性诊断同时验证非流式 JSON 与流式 SSE；业务结构化调用仍使用非流式 JSON，以便稳定解析规则字段。
- 开发环境 `development_minimax` 的地址、模型和激活逻辑不变。

## 修改范围

1. 更新 `documents/AI/ai_model_gateway.yaml` 中现有终端 profile 的供应方、地址、模型和说明。
2. 更新终端部署包生成器内面向运维人员的说明文字，使新生成的部署说明与 YAML 一致；保留既有 profile 名和部署脚本选择逻辑。
3. 更新独立终端安装说明和 Skill 部署说明中的模型描述，不改变 Skill 行为。
4. 更新定向单元测试，断言新端点和新模型，并确认开发 profile 未被改变。
5. 运行连通性脚本的本地模拟测试；如当前主机可访问内网网关，再使用正式 profile 做真实的非流式与流式探测。

## 验收标准

- `AiSpecLoader` 选择终端 profile 后解析到 `http://models.ai.cnpe.cc/qwen_medium/v1` 和 `Qwen3.8-27B`。
- 终端部署脚本仍固定使用现有 profile，且网络策略仍要求 `intranet_only`。
- 新生成部署说明不再出现旧地址或旧模型。
- 开发环境仍解析到 MiniMax。
- 本地模拟的普通响应、SSE 流式响应测试均通过；真实内网探测结果如受网络环境限制，明确记录为剩余风险。

