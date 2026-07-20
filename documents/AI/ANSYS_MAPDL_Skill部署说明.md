# ANSYS MAPDL 18.2 Skill 部署说明

## 运行方式

- Skill 由后端自动触发，前端不显示技能选择按钮。
- 用户问题包含 ANSYS、MAPDL、APDL、命令名、单元名或 KEYOPT 等特征时，后端先检索本地只读语料，再把证据交给当前模型回答。
- `development_minimax` 和 `terminal_cnpe_intranet_qwen_fast` 使用同一套检索逻辑；切换模型 profile 不改变 Skill 行为。
- 通用问题不会触发 Skill。ANSYS 对话中的明确追问可继承上一轮 Skill 上下文。

## 开发环境安装

将私有离线包放在 `documents/AI` 后，在仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\ai\install_ansys_mapdl_skill.ps1
```

默认安装目录是 `storage/ai/skills/ansys-mapdl-18-2`。该目录和私有 ZIP 均不纳入 Git。

## 终端部署

终端包构建器会从已安装的 Skill 目录或 `documents/AI/ansys-mapdl-18-2-private-offline-*.zip` 自动生成：

```text
D:\FanBanServer\storage\ai\skills\ansys-mapdl-18-2
```

终端运行环境会设置：

```powershell
$env:FANBAN_ANSYS_MAPDL_SKILL_ROOT='D:\FanBanServer\storage\ai\skills\ansys-mapdl-18-2'
```

私有原始 ZIP 不复制到终端包。若 AI 参数已启用该 Skill 但构建时找不到完整语料，终端包构建会直接失败。

## 探针验收

继续使用现有探针：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File D:\FanBanServer\scripts\test_ai_model_connectivity.ps1 `
  -Profile terminal_cnpe_intranet_qwen_fast
```

诊断 JSON 中检查：

- `checks.ansys_mapdl_skill.local_status` 为 `passed`
- `checks.ansys_mapdl_skill.missing_files` 为空
- `checks.ansys_mapdl_skill.validation.passed` 为 `true`
- `checks.ansys_mapdl_skill.query.first_canonical` 为 `ANTYPE`
- `checks.ansys_mapdl_skill.application_registration.status` 为 `passed`
- `readiness.ansys_mapdl_skill.status` 为 `passed`
