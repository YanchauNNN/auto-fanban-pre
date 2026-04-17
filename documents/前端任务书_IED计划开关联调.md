# 前端任务书：IED计划开关联调

## 背景

后端已支持在交付任务中通过单个布尔字段控制是否生成 IED 计划。

当前规则：

- 字段名：`include_ied_plan`
- 类型：`boolean`
- 默认值：`true`
- 含义：是否生成 IED 计划并开放下载

当用户关闭该选项时：

- 后端仍正常生成封面、目录、设计文件、图纸 PDF/DWG、package.zip
- 后端不会生成 `IED计划.xlsx`
- 任务详情中的 IED 下载入口会隐藏

## 后端联调口径

### 1. 表单元数据

接口：

- `GET /api/meta/form-schema`

新增字段会出现在 `deliverable.sections` 中，结构如下：

```json
{
  "key": "include_ied_plan",
  "label": "include_ied_plan",
  "type": "checkbox",
  "required": false,
  "required_when": null,
  "source": "frontend",
  "default": true,
  "desc": "是否生成IED计划并开放下载，默认包含",
  "options": [],
  "ui": {
    "widget": "checkbox"
  }
}
```

### 2. 任务提交

接口：

- `POST /api/jobs/batch`

提交时在 `params_json` 中带上：

```json
{
  "include_ied_plan": true
}
```

或：

```json
{
  "include_ied_plan": false
}
```

注意：

- 这里必须传 JSON 布尔值，不要传字符串 `"true"` / `"false"`
- 不传时后端默认按 `true` 处理

### 3. 任务详情返回

接口：

- `GET /api/jobs/{job_id}`

相关字段：

- `artifacts.ied_available`
- `downloads.ied_download_url`

返回规则：

- 当 `include_ied_plan = true` 且 IED 生成成功：
  - `artifacts.ied_available = true`
  - `downloads.ied_download_url = "/api/jobs/{job_id}/download/ied"`
- 当 `include_ied_plan = false`：
  - `artifacts.ied_available = false`
  - `downloads.ied_download_url = null`

## 前端改动要求

### 1. 上传表单

在交付任务表单中新增一个复选框：

- 建议文案：`包含 IED 计划`
- 默认勾选：是

建议放置位置：

- 设计文件/IED 参数区域附近
- 与 `ied_status` 同组展示更容易理解

### 2. 提交行为

提交任务时，将复选框值写入 `params_json.include_ied_plan`

规则：

- 勾选时传 `true`
- 取消勾选时传 `false`

### 3. 详情页/结果页

根据任务详情接口返回值控制 IED 下载按钮：

- `artifacts.ied_available === true` 时显示
- `artifacts.ied_available === false` 时隐藏

不要自己根据表单值推断是否显示，必须以后端返回为准。

## 验收用例

### 用例 1：默认勾选

步骤：

- 打开上传页
- 不改复选框，直接提交

预期：

- 请求体中 `include_ied_plan = true`
- 任务成功后显示 IED 下载按钮

### 用例 2：手动取消勾选

步骤：

- 打开上传页
- 取消 `包含 IED 计划`
- 提交任务

预期：

- 请求体中 `include_ied_plan = false`
- 任务成功
- 不显示 IED 下载按钮
- 其他文档与图纸产物不受影响

### 用例 3：详情页刷新

步骤：

- 对一个 `include_ied_plan = false` 的任务刷新详情页

预期：

- 仍不显示 IED 下载按钮
- 不依赖前端本地缓存状态

## 备注

- `package.zip` 打包逻辑不需要改。IED 本来就不进入 `package.zip`。
- 本次仅需联调交付任务主链，不涉及审核替换任务。
