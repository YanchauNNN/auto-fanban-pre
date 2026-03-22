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
    files: [],
    values: normalizeCombinedIedValues(getDefaultTaskValues(schema)),
    fieldErrors: {},
    formErrors: [],
    inference: {
      inferredProjectNos: [],
      primaryProjectNo: "",
      hasConflict: false,
    },
    replaceConfig: {
      sourceProjectNo: "",
      targetProjectNo: "",
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
    values: normalizeCombinedIedValues({
      ...defaultValues,
      ...currentDraft.values,
    }),
  };
}

export function getDefaultTaskValues(schema: FormSchema) {
  return normalizeCombinedIedValues({
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
  });
}

export function isAutoTodayField(fieldKey: string) {
  return AUTO_TODAY_FIELD_KEYS.has(fieldKey);
}

export function getTodayValue() {
  return new Date().toISOString().slice(0, 10);
}

function normalizeCombinedIedValues(values: Record<string, string>) {
  const checkedBy = values.ied_checked_by?.trim() || values.ied_discipline_leader?.trim() || "";
  const checkedDate =
    values.ied_checked_date?.trim() || values.ied_discipline_leader_date?.trim() || "";

  return {
    ...values,
    ied_checked_by: checkedBy,
    ied_discipline_leader: checkedBy,
    ied_checked_date: checkedDate,
    ied_discipline_leader_date: checkedDate,
  };
}
