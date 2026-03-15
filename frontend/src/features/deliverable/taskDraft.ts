import type { FormSchema, TaskConfigDraft } from "../../platform/api/types";

const AUTO_TODAY_FIELD_KEYS = new Set([
  "ied_prepared_date",
  "ied_checked_date",
  "ied_discipline_leader_date",
  "ied_reviewed_date",
  "ied_approved_date",
]);

export function createTaskConfigDraft(schema: FormSchema): TaskConfigDraft {
  return {
    intent: "deliverable",
    runAuditCheck: false,
    files: [],
    values: getDefaultTaskValues(schema),
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
    values: {
      ...defaultValues,
      ...currentDraft.values,
    },
  };
}

export function getDefaultTaskValues(schema: FormSchema) {
  return Object.fromEntries(
    schema.sections.flatMap((section) =>
      section.fields.map((field) => [
        field.key,
        isAutoTodayField(field.key) && field.type === "date"
          ? getTodayValue()
          : field.defaultValue,
      ]),
    ),
  );
}

export function isAutoTodayField(fieldKey: string) {
  return AUTO_TODAY_FIELD_KEYS.has(fieldKey);
}

export function getTodayValue() {
  return new Date().toISOString().slice(0, 10);
}
