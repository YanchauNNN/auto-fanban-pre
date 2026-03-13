import { isAutoTodayField, syncTaskConfigDraft } from "./taskDraft";
import type { FormSchema, TaskConfigDraft, TaskConfigPreset } from "../../platform/api/types";

const STORAGE_KEY = "auto-fanban.task-config-presets";

export function loadTaskPresets(): TaskConfigPreset[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return [];
    }

    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed
      .filter(isTaskPreset)
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
  } catch {
    return [];
  }
}

export function createTaskPreset(
  name: string,
  draft: Pick<TaskConfigDraft, "intent" | "values" | "replaceConfig">,
  existingId?: string,
): TaskConfigPreset {
  const now = new Date().toISOString();

  return {
    id: existingId ?? `preset-${now}-${Math.random().toString(36).slice(2, 8)}`,
    name: name.trim(),
    intent: draft.intent,
    values: omitPresetManagedValues(draft.values),
    replaceConfig: { ...draft.replaceConfig },
    updatedAt: now,
  };
}

export function saveTaskPreset(preset: TaskConfigPreset): TaskConfigPreset[] {
  const presets = loadTaskPresets();
  const nextPresets = [preset, ...presets.filter((item) => item.id !== preset.id)];
  persistTaskPresets(nextPresets);
  return loadTaskPresets();
}

export function renameTaskPreset(id: string, nextName: string): TaskConfigPreset[] {
  const renamed = loadTaskPresets().map((preset) =>
    preset.id === id
      ? {
          ...preset,
          name: nextName.trim(),
          updatedAt: new Date().toISOString(),
        }
      : preset,
  );
  persistTaskPresets(renamed);
  return loadTaskPresets();
}

export function deleteTaskPreset(id: string): TaskConfigPreset[] {
  const nextPresets = loadTaskPresets().filter((preset) => preset.id !== id);
  persistTaskPresets(nextPresets);
  return nextPresets;
}

export function applyTaskPreset(
  schema: FormSchema,
  currentDraft: TaskConfigDraft,
  preset: TaskConfigPreset,
): TaskConfigDraft {
  return syncTaskConfigDraft(schema, {
    ...currentDraft,
    intent: preset.intent,
    values: {
      ...currentDraft.values,
      ...preset.values,
    },
    replaceConfig: {
      ...preset.replaceConfig,
    },
    fieldErrors: {},
    formErrors: [],
  });
}

function persistTaskPresets(presets: TaskConfigPreset[]) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(presets));
}

function omitPresetManagedValues(values: Record<string, string>) {
  return Object.fromEntries(
    Object.entries(values).filter(([fieldKey]) => !isAutoTodayField(fieldKey)),
  );
}

function isTaskPreset(value: unknown): value is TaskConfigPreset {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Partial<TaskConfigPreset>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.name === "string" &&
    typeof candidate.intent === "string" &&
    typeof candidate.updatedAt === "string" &&
    Boolean(candidate.values && typeof candidate.values === "object") &&
    Boolean(candidate.replaceConfig && typeof candidate.replaceConfig === "object")
  );
}
