import type {
  CalculationBookField,
  FormField,
  FormFieldType,
  FormSchema,
} from "../../platform/api/types";

type RawField = {
  key: string;
  label: string;
  type: string;
  required: boolean;
  required_when: string | null;
  source?: string | null;
  default: string | boolean | null;
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
  audit_check?: {
    unit_consistency?: {
      enabled?: boolean;
      project_units?: Record<string, readonly string[]>;
      allow_unlisted_unit_no?: boolean;
      unit_no_pattern?: string;
    };
  };
  audit_replace?: {
    project_options?: readonly string[];
    project_units?: Record<string, readonly string[]>;
    source_unit_options?: Record<string, readonly { value: string; label: string }[]>;
    target_unit_options?: Record<string, readonly { value: string; label: string }[]>;
    unit_factory_codes?: readonly string[];
    batch_filename_identity_regex?: string;
    factory_index_maps?: {
      source_variant_options?: Record<string, readonly string[]>;
      target_variant_options?: Record<string, readonly string[]>;
    };
  };
  calculation_book?: {
    templates?: readonly { value?: string | null; label?: string | null }[];
    project_options?: readonly { value?: string | null; label?: string | null }[];
    fields?: readonly {
      key?: string | null;
      label?: string | null;
      type?: string | null;
      required?: boolean | null;
      default?: string | number | boolean | null;
      unit?: string | null;
      placeholder?: string | null;
      options?: readonly string[] | null;
      options_from?: string | null;
      derived_from?: string | null;
    }[];
    archive?: {
      accept?: readonly string[] | null;
      required_root_directions?: readonly string[] | null;
      required_folders?: readonly string[] | null;
      root_figure_pattern?: string | null;
      description?: string | null;
    };
  };
  management?: {
    account?: {
      fields?: {
        office_code?: string | null;
        office_name?: string | null;
        account_id?: string | null;
        display_name?: string | null;
        role?: string | null;
        password?: string | null;
      };
      valid_roles?: readonly string[];
      admin_roles?: readonly string[];
      admin_created_default_password?: string | null;
    };
    workflow?: {
      terminal_status?: string | null;
      archive_trigger_status?: string | null;
      status_labels?: Record<string, string>;
      node_labels?: Record<string, string>;
      empty_current_node_label?: string | null;
      factor?: {
        default?: number | null;
        min?: number | null;
        max?: number | null;
        precision?: number | null;
      };
    };
    workload?: {
      settlement_trigger?: string | null;
      scope_roles?: Record<string, readonly string[]>;
      scope_labels?: Record<string, string>;
      status_options?: readonly { label?: string | null; value?: string | null }[];
    };
    archive?: {
      status_labels?: Record<string, string>;
    };
  };
};

type RawAuditCheckUnitConsistency = NonNullable<
  NonNullable<RawFormSchema["audit_check"]>["unit_consistency"]
>;

type RawAuditReplaceFactoryIndexMaps = NonNullable<
  NonNullable<RawFormSchema["audit_replace"]>["factory_index_maps"]
>;

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
  unit_no: "机组号",
  cover_variant: "封面模板",
  classification: "密级",
  subitem_name: "子项名称（中文）",
  subitem_name_en: "子项名称（英文）",
  album_title_cn: "图册名称（中文）",
  album_title_en: "图册名称（英文）",
  cover_revision: "封面和目录版次",
  is_upgrade: "是否升版",
  upgrade_sheet_codes: "升版图纸编号",
  upgrade_entries: "升版规则",
  wbs_code: "WBS 编码",
  system_code: "系统代码",
  system_name: "系统名称",
  design_status: "设计文件状态",
  internal_tag: "内部标识",
  discipline_office: "专业室",
  file_category: "文件类别",
  attachment_name: "附件名称",
  include_ied_plan: "是否生成IED",
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
  ied_checked_by: "校核者",
  ied_checked_date: "校核日期",
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
  unit_no: "用于纠错机组一致性检查，可从DWG文件名自动推断",
  cover_variant: "封面模板选择",
  classification: "写入设计文件/IED",
  cover_revision: "封面和目录版次，写入封面和目录版次位（追加模式）",
  is_upgrade:
    "启用后只需填写升版图纸编号；关闭时会隐藏输入框，但会保留已输入内容。",
  upgrade_sheet_codes:
    "输入图纸内部编码末三位，支持单个编号和区间组合。示例：001~099、001、003、005~009；支持分隔符：、, . ; ；；支持连接符：~ 和 -；留空表示仅标记目录文件本身为升版。",
  upgrade_entries:
    "结构化升版规则，由升版设置区自动维护；每行包含版次、图纸编号和是否新增。",
  ied_chief_designer: "例如：王任超@wangrca",
  ied_checked_by: "例如：王任超@wangrca",
  ied_checked_date: "点击选择日期",
  ied_discipline_leader: "例如：王任超@wangrca",
  ied_discipline_leader_date: "点击选择日期",
};

const LEGACY_UPGRADE_FIELDS = new Set([
  "upgrade_start_seq",
  "upgrade_end_seq",
  "upgrade_revision",
  "upgrade_note_text",
]);

const CUSTOM_RENDERED_FIELDS = new Set([
  "cover_revision",
  "is_upgrade",
  "upgrade_sheet_codes",
  "upgrade_entries",
]);

const HIDDEN_FRONTEND_FIELDS = new Set(["ied_discipline_office", ...LEGACY_UPGRADE_FIELDS]);

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
  "upgrade_entries",
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

const RESPONSIBLE_UNIT_PRIORITY_PREFIX = "河北分公司-建筑结构所";
const EXTRA_IED_DESIGN_TYPES = ["BOP子项施工图"];

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
          .filter((field) => !HIDDEN_FRONTEND_FIELDS.has(field.key))
          .map((field) => normalizeField(field)),
      }))
      .filter((section) => section.fields.length > 0),
    auditReplaceProjectOptions: payload.audit_replace?.project_options ?? [],
    auditReplaceProjectUnits: normalizeVariantOptions(payload.audit_replace?.project_units),
    auditReplaceSourceUnitOptions: normalizeUnitOptionMap(
      payload.audit_replace?.source_unit_options,
    ),
    auditReplaceTargetUnitOptions: normalizeUnitOptionMap(
      payload.audit_replace?.target_unit_options,
    ),
    auditReplaceUnitFactoryCodes: normalizeCodeOptions(
      payload.audit_replace?.unit_factory_codes,
    ),
    auditReplaceBatchFilenameIdentityRegex:
      payload.audit_replace?.batch_filename_identity_regex?.trim() || undefined,
    auditReplaceFactoryIndexMaps: normalizeAuditReplaceFactoryIndexMaps(
      payload.audit_replace?.factory_index_maps,
    ),
    auditCheckUnitConsistency: normalizeAuditCheckUnitConsistency(
      payload.audit_check?.unit_consistency,
    ),
    calculationBook: payload.calculation_book
      ? {
          templates: (payload.calculation_book.templates ?? [])
            .map((item) => ({
              value: String(item.value ?? ""),
              label: String(item.label ?? ""),
            }))
            .filter((item) => item.value && item.label),
          projectOptions: (payload.calculation_book.project_options ?? [])
            .map((item) => ({
              value: String(item.value ?? ""),
              label: String(item.label ?? ""),
            }))
            .filter((item) => item.value && item.label),
          fields: (payload.calculation_book.fields ?? [])
            .map((field) => ({
              key: String(field.key ?? ""),
              label: String(field.label ?? ""),
              type: (
                field.type === "number" ||
                field.type === "select" ||
                field.type === "checkbox"
                  ? field.type
                  : "text"
              ) as CalculationBookField["type"],
              required: Boolean(field.required),
              defaultValue: field.default == null ? undefined : String(field.default),
              unit: field.unit ?? undefined,
              placeholder: field.placeholder ?? undefined,
              options: field.options ?? undefined,
              optionsFrom: field.options_from ?? undefined,
              derivedFrom: field.derived_from ?? undefined,
            }))
            .filter((field) => field.key && field.label),
          archive: {
            accept: payload.calculation_book.archive?.accept ?? [".zip"],
            requiredRootDirections:
              payload.calculation_book.archive?.required_root_directions ?? ["X", "Y", "Z"],
            requiredFolders: payload.calculation_book.archive?.required_folders ?? ["01", "02"],
            rootFigurePattern:
              payload.calculation_book.archive?.root_figure_pattern ?? "<墙号>-X|Y|Z.png",
            description: payload.calculation_book.archive?.description ?? "",
          },
        }
      : undefined,
    management: normalizeManagementSchema(payload.management),
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
  const type = resolveFieldType(field);
  return {
    key: field.key,
    label: FIELD_LABELS[field.key] ?? humanizeKey(field.label),
    type,
    required: field.required,
    requiredWhen: field.required_when,
    defaultValue:
      type === "checkbox"
        ? field.default === true
          ? "true"
          : "false"
        : typeof field.default === "string"
          ? field.default
          : field.default == null
            ? ""
            : String(field.default),
    description: FIELD_DESCRIPTION_OVERRIDES[field.key] ?? field.desc,
    options: normalizeFieldOptions(field.key, field.options),
  };
}

function normalizeAuditCheckUnitConsistency(
  value: RawAuditCheckUnitConsistency | undefined,
): FormSchema["auditCheckUnitConsistency"] {
  if (!value) {
    return undefined;
  }
  const normalized: NonNullable<FormSchema["auditCheckUnitConsistency"]> = {
    enabled: Boolean(value.enabled),
    projectUnits: Object.fromEntries(
      Object.entries(value.project_units ?? {}).map(([projectNo, unitNos]) => [
        projectNo,
        unitNos.map((unitNo) => unitNo.trim()).filter(Boolean),
      ]),
    ),
  };
  if (value.allow_unlisted_unit_no !== undefined) {
    normalized.allowUnlistedUnitNo = Boolean(value.allow_unlisted_unit_no);
  }
  if (value.unit_no_pattern !== undefined) {
    normalized.unitNoPattern = value.unit_no_pattern;
  }
  return normalized;
}

function normalizeAuditReplaceFactoryIndexMaps(
  value: RawAuditReplaceFactoryIndexMaps | undefined,
): FormSchema["auditReplaceFactoryIndexMaps"] {
  if (!value) {
    return undefined;
  }
  return {
    sourceVariantOptions: normalizeVariantOptions(value.source_variant_options),
    targetVariantOptions: normalizeVariantOptions(value.target_variant_options),
  };
}

function normalizeManagementSchema(
  value: RawFormSchema["management"],
): FormSchema["management"] {
  if (!value) {
    return undefined;
  }
  return {
    account: {
      fieldMap: {
        officeCode: String(value.account?.fields?.office_code ?? "科室编码"),
        officeName: String(value.account?.fields?.office_name ?? "科室"),
        accountId: String(value.account?.fields?.account_id ?? "账号"),
        displayName: String(value.account?.fields?.display_name ?? "姓名"),
        role: String(value.account?.fields?.role ?? "角色"),
        password: String(value.account?.fields?.password ?? "密码"),
      },
      validRoles: normalizeStringList(value.account?.valid_roles),
      adminRoles: normalizeStringList(value.account?.admin_roles),
      adminCreatedDefaultPassword: String(value.account?.admin_created_default_password ?? ""),
    },
    workflow: {
      terminalStatus: String(value.workflow?.terminal_status ?? ""),
      archiveTriggerStatus:
        value.workflow?.archive_trigger_status == null
          ? undefined
          : String(value.workflow.archive_trigger_status),
      factor: {
        default: requiredNumber(value.workflow?.factor?.default, "workflow.factor.default"),
        min: requiredNumber(value.workflow?.factor?.min, "workflow.factor.min"),
        max: requiredNumber(value.workflow?.factor?.max, "workflow.factor.max"),
        precision: requiredNumber(value.workflow?.factor?.precision, "workflow.factor.precision"),
      },
      statusLabels: normalizeStringMap(value.workflow?.status_labels),
      nodeLabels: normalizeStringMap(value.workflow?.node_labels),
      emptyCurrentNodeLabel: String(value.workflow?.empty_current_node_label ?? ""),
    },
    workload: {
      settlementTrigger: String(value.workload?.settlement_trigger ?? ""),
      scopeRoles: Object.fromEntries(
        Object.entries(value.workload?.scope_roles ?? {}).map(([scope, roles]) => [
          scope,
          normalizeStringList(roles),
        ]),
      ),
      scopeLabels: Object.fromEntries(
        Object.entries(value.workload?.scope_labels ?? {}).map(([scope, label]) => [
          scope,
          String(label),
        ]),
      ),
      statusOptions: (value.workload?.status_options ?? [])
        .map((option) => ({
          label: String(option.label ?? "").trim(),
          value: String(option.value ?? "").trim(),
        }))
        .filter((option) => option.label),
    },
    archive: {
      statusLabels: normalizeStringMap(value.archive?.status_labels),
    },
  };
}

function normalizeVariantOptions(value: Record<string, readonly string[]> | undefined) {
  return Object.fromEntries(
    Object.entries(value ?? {}).map(([projectNo, variants]) => [
      projectNo,
      variants.map((variant) => variant.trim()).filter(Boolean),
    ]),
  );
}

function normalizeStringList(value: readonly string[] | undefined) {
  return Array.from(new Set((value ?? []).map((item) => item.trim()).filter(Boolean)));
}

function normalizeStringMap(value: Record<string, string> | undefined) {
  return Object.fromEntries(
    Object.entries(value ?? {})
      .map(([key, label]) => [key.trim(), String(label).trim()])
      .filter(([key, label]) => key && label),
  );
}

function requiredNumber(value: number | null | undefined, fieldKey: string) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  throw new Error(`management.${fieldKey} is required`);
}

function normalizeCodeOptions(value: readonly string[] | undefined) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of value ?? []) {
    const normalized = item.trim().toUpperCase();
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function normalizeUnitOptionMap(
  value: Record<string, readonly { value: string; label: string }[]> | undefined,
) {
  return Object.fromEntries(
    Object.entries(value ?? {}).map(([projectNo, options]) => [
      projectNo,
      options
        .map((option) => ({
          value: option.value.trim(),
          label: option.label.trim(),
        }))
        .filter((option) => option.value && option.label),
    ]),
  );
}

function normalizeFieldOptions(fieldKey: string, options: readonly string[]) {
  const deduped = Array.from(
    new Set(
      options
        .map((option) => option.trim())
        .filter(Boolean),
    ),
  );

  if (fieldKey === "ied_design_type") {
    for (const option of EXTRA_IED_DESIGN_TYPES) {
      if (!deduped.includes(option)) {
        deduped.push(option);
      }
    }
  }

  if (fieldKey === "ied_responsible_unit") {
    return [
      ...deduped.filter((option) => option.startsWith(RESPONSIBLE_UNIT_PRIORITY_PREFIX)),
      ...deduped.filter((option) => !option.startsWith(RESPONSIBLE_UNIT_PRIORITY_PREFIX)),
    ];
  }

  return deduped;
}

function resolveFieldType(field: RawField): FormFieldType {
  if (field.type === "checkbox") {
    return "checkbox";
  }
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
