import type { FormField, FormFieldType, FormSchema } from "../../platform/api/types";

type RawField = {
  key: string;
  label: string;
  type: string;
  required: boolean;
  required_when: string | null;
  source?: string | null;
  default: string | null;
  format: string | null;
  desc: string;
  options: readonly string[];
};

type RawSection = {
  id: string;
  title: string;
  fields: readonly RawField[];
};

type RawFormSchema = {
  schema_version: string;
  upload_limits: {
    max_files: number;
    allowed_exts: readonly string[];
    max_total_mb: number;
  };
  deliverable: {
    sections: readonly RawSection[];
  };
  audit_replace?: {
    project_options?: readonly string[];
  };
};

const SECTION_TITLES: Record<string, string> = {
  project: "任务与项目",
  from_titleblock: "子项信息",
  cover: "图册与封面",
  catalog: "目录与升版",
  design: "设计文件",
  ied: "IED 基础信息",
};

const FIELD_LABELS: Record<string, string> = {
  project_no: "项目号",
  cover_variant: "封面模板",
  classification: "密级",
  subitem_name: "子项名称（中文）",
  subitem_name_en: "子项名称（英文）",
  album_title_cn: "图册名称（中文）",
  album_title_en: "图册名称（英文）",
  cover_revision: "封面和目录版次",
  is_upgrade: "是否升版",
  upgrade_sheet_codes: "升版图纸编号",
  wbs_code: "WBS 编码",
  system_code: "系统代码",
  system_name: "系统名称",
  design_status: "设计文件状态",
  internal_tag: "内部标识",
  discipline_office: "专业室",
  file_category: "文件类别",
  attachment_name: "附件名称",
  qa_required: "是否质保核查",
  qa_engineer: "质保核查工程师",
  work_hours: "工时数",
  ied_status: "IED 状态",
  ied_doc_type: "文档类型",
  ied_change_flag: "变更标记",
  ied_design_type: "设计类型",
  ied_responsible_unit: "责任单位",
  ied_discipline_office: "专业室",
  ied_chief_designer: "责任设总",
  ied_person_qual_category: "人员资格类别",
  ied_fu_flag: "FU 标记",
  ied_internal_tag: "IED 内部标识",
  ied_prepared_by: "编制者",
  ied_prepared_by_2: "第二编制者",
  ied_prepared_date: "编制日期",
  ied_checked_by: "校核者与工种负责人",
  ied_checked_date: "校核日期与工种审核日期",
  ied_discipline_leader: "工种负责人",
  ied_discipline_leader_date: "工种负责人审核日期",
  ied_reviewed_by: "审核者",
  ied_reviewed_date: "审核日期",
  ied_approved_by: "审定者",
  ied_approved_date: "审定日期",
  ied_submitted_plan_date: "所提交计划",
  ied_publish_plan_date: "出版计划",
  ied_external_plan_date: "外部计划",
  ied_fu_plan_date: "FU 计划",
};

const FIELD_DESCRIPTION_OVERRIDES: Record<string, string> = {
  project_no: "可留空，会优先从DWG文件名自动推断",
  cover_variant: "封面模板选择",
  classification: "写入设计文件/IED",
  cover_revision: "封面和目录版次，写入封面和目录版次位（追加模式）",
  is_upgrade:
    "启用后只需填写升版图纸编号；关闭时会隐藏输入框，但会保留已输入的内容。",
  upgrade_sheet_codes:
    "输入图纸内部编码末三位，支持单个编号和区间组合。示例：001~099、001、003、005~009；支持分隔符：、 . ; ；；支持连接符：~ 和 -；留空表示仅标记目录文件本身为升版。",
  ied_chief_designer: "例如：王任超@wangrca",
  ied_checked_by: "例如：王任超@wangrca",
  ied_checked_date: "点击选择日期",
};

const LEGACY_UPGRADE_FIELDS = new Set([
  "upgrade_start_seq",
  "upgrade_end_seq",
  "upgrade_revision",
  "upgrade_note_text",
]);

const CUSTOM_RENDERED_FIELDS = new Set(["is_upgrade", "upgrade_sheet_codes"]);

const HIDDEN_FRONTEND_FIELDS = new Set([
  "ied_discipline_office",
  "ied_discipline_leader",
  "ied_discipline_leader_date",
  ...LEGACY_UPGRADE_FIELDS,
]);

const NAME_ID_FIELDS = new Set([
  "ied_chief_designer",
  "ied_prepared_by",
  "ied_prepared_by_2",
  "ied_checked_by",
  "ied_discipline_leader",
  "ied_reviewed_by",
  "ied_approved_by",
]);

const ADVANCED_FIELDS = new Set([
  "cover_revision",
  "is_upgrade",
  "upgrade_sheet_codes",
  "system_code",
  "system_name",
  "design_status",
  "internal_tag",
  "discipline_office",
  "attachment_name",
  "qa_required",
  "qa_engineer",
  "ied_change_flag",
  "ied_design_type",
  "ied_responsible_unit",
  "ied_chief_designer",
  "ied_fu_flag",
  "ied_internal_tag",
  "ied_prepared_by_2",
  "ied_submitted_plan_date",
  "ied_publish_plan_date",
  "ied_external_plan_date",
  "ied_fu_plan_date",
]);

export function normalizeFormSchema(payload: RawFormSchema): FormSchema {
  return {
    schemaVersion: payload.schema_version,
    uploadLimits: {
      maxFiles: payload.upload_limits.max_files,
      allowedExts: payload.upload_limits.allowed_exts,
      maxTotalMb: payload.upload_limits.max_total_mb,
    },
    sections: payload.deliverable.sections
      .map((section) => ({
        id: section.id,
        title: SECTION_TITLES[section.id] ?? humanizeKey(section.id),
        fields: section.fields
          .filter((field) => (field.source ?? "frontend") === "frontend")
          .filter((field) => field.key !== "approved_by")
          .filter((field) => !HIDDEN_FRONTEND_FIELDS.has(field.key))
          .map((field) => normalizeField(field)),
      }))
      .filter((section) => section.fields.length > 0),
    auditReplaceProjectOptions: payload.audit_replace?.project_options ?? [],
  };
}

export function evaluateRequiredWhen(
  expression: string | null,
  values: Record<string, string>,
): boolean {
  if (!expression) {
    return false;
  }

  const match = expression.match(/^([a-zA-Z0-9_]+)\s*(==|!=)\s*'([^']*)'$/);
  if (!match) {
    return false;
  }

  const [, field, operator, expected] = match;
  const actual = values[field] ?? "";
  return operator === "==" ? actual === expected : actual !== expected;
}

export function isAdvancedField(field: FormField, values: Record<string, string> = {}) {
  if (field.required || !ADVANCED_FIELDS.has(field.key)) {
    return false;
  }

  return !evaluateRequiredWhen(field.requiredWhen, values);
}

export function isCustomRenderedField(fieldKey: string) {
  return CUSTOM_RENDERED_FIELDS.has(fieldKey);
}

export function buildRecommendedProjectNos(
  inferredProjectNos: readonly string[],
  schemaOptions: readonly string[],
) {
  const deduped = new Set<string>();

  for (const projectNo of [...inferredProjectNos, ...schemaOptions]) {
    const normalized = projectNo.trim();
    if (!normalized) {
      continue;
    }
    deduped.add(normalized);
  }

  return Array.from(deduped);
}

function normalizeField(field: RawField): FormField {
  return {
    key: field.key,
    label: FIELD_LABELS[field.key] ?? humanizeKey(field.label),
    type: resolveFieldType(field),
    required: field.required,
    requiredWhen: field.required_when,
    defaultValue: field.default ?? "",
    description: FIELD_DESCRIPTION_OVERRIDES[field.key] ?? field.desc,
    options: field.options,
  };
}

function resolveFieldType(field: RawField): FormFieldType {
  if (field.type === "combobox") {
    return "combobox";
  }
  if (field.type === "select" || field.options.length > 0) {
    return "select";
  }
  if (field.format === "YYYY-MM-DD") {
    return "date";
  }
  if (field.format === "姓名@ID" || NAME_ID_FIELDS.has(field.key)) {
    return "nameId";
  }
  return "text";
}

function humanizeKey(value: string) {
  return value
    .split("_")
    .filter(Boolean)
    .map((segment, index) =>
      index === 0 ? segment.charAt(0).toUpperCase() + segment.slice(1) : segment,
    )
    .join(" ");
}
