import type { FormSchema, TaskConfigDraft } from "../../platform/api/types";

const AUTO_TODAY_FIELD_KEYS = new Set([
  "ied_prepared_date",
  "ied_checked_date",
  "ied_discipline_leader_date",
  "ied_reviewed_date",
  "ied_approved_date",
]);

const LOCAL_DEFAULT_VALUES = {
  plot_style_key: "red_wider",
} as const;

export function createTaskConfigDraft(schema: FormSchema): TaskConfigDraft {
  return {
    intent: "deliverable",
    runAuditCheck: false,
    runSplitOnly: false,
    fontCompatibilityMode: true,
    files: [],
    values: getDefaultTaskValues(schema),
    fieldErrors: {},
    formErrors: [],
    inference: {
      inferredProjectNos: [],
      inferredUnitNos: [],
      primaryProjectNo: "",
      primaryUnitNo: "",
      hasConflict: false,
      hasUnitConflict: false,
    },
    replaceConfig: {
      sourceProjectNo: "",
      sourceIslandNo: "",
      targetProjectNo: "",
      targetIslandNo: "",
    },
  };
}

export function syncTaskConfigDraft(
  schema: FormSchema,
  currentDraft: TaskConfigDraft | null,
): TaskConfigDraft {
  const defaultValues = getDefaultTaskValues(schema);

  if (!currentDraft) {
    return createTaskConfigDraft(schema);
  }

  return {
    ...currentDraft,
    runAuditCheck: currentDraft.runAuditCheck ?? false,
    runSplitOnly: currentDraft.runSplitOnly ?? false,
    fontCompatibilityMode: currentDraft.fontCompatibilityMode ?? true,
    values: {
      ...defaultValues,
      ...currentDraft.values,
    },
    replaceConfig: buildReplaceConfig(
      currentDraft.replaceConfig?.sourceProjectNo,
      currentDraft.replaceConfig?.sourceIslandNo,
      currentDraft.replaceConfig?.targetProjectNo,
      currentDraft.replaceConfig?.targetIslandNo,
      currentDraft.replaceConfig?.unitFactoryCodes,
    ),
  };
}

export function getDefaultTaskValues(schema: FormSchema) {
  return {
    ...LOCAL_DEFAULT_VALUES,
    ...Object.fromEntries(
      schema.sections.flatMap((section) =>
        section.fields.map((field) => [
          field.key,
          isAutoTodayField(field.key) && field.type === "date"
            ? getTodayValue()
            : field.defaultValue,
        ]),
      ),
    ),
  };
}

export function isAutoTodayField(fieldKey: string) {
  return AUTO_TODAY_FIELD_KEYS.has(fieldKey);
}

export function getTodayValue() {
  return new Date().toISOString().slice(0, 10);
}

function normalizeFactoryCodes(values: readonly string[] | undefined) {
  if (!Array.isArray(values)) {
    return [];
  }
  return values
    .map((value) => value.trim().toUpperCase())
    .filter((value, index, array) => value && array.indexOf(value) === index);
}

function buildReplaceConfig(
  sourceProjectNo: string | undefined,
  sourceIslandNo: string | undefined,
  targetProjectNo: string | undefined,
  targetIslandNo: string | undefined,
  unitFactoryCodes: readonly string[] | undefined,
) {
  const normalizedFactoryCodes = normalizeFactoryCodes(unitFactoryCodes);
  return {
    sourceProjectNo: sourceProjectNo ?? "",
    sourceIslandNo: sourceIslandNo ?? "",
    targetProjectNo: targetProjectNo ?? "",
    targetIslandNo: targetIslandNo ?? "",
    ...(normalizedFactoryCodes.length > 0 ? { unitFactoryCodes: normalizedFactoryCodes } : {}),
  };
}
