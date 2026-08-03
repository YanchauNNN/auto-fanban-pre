import type { CalculationBookSchema } from "../../platform/api/types";

const STORAGE_KEY = "auto-fanban.calculation-book-presets";

export type CalculationBookPreset = {
  id: string;
  name: string;
  values: Record<string, string>;
  updatedAt: string;
};

export function loadCalculationBookPresets(): CalculationBookPreset[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return [];
    }

    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed
      .filter(isCalculationBookPreset)
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
  } catch {
    return [];
  }
}

export function createCalculationBookPreset(
  name: string,
  schema: CalculationBookSchema,
  values: Record<string, string>,
): CalculationBookPreset {
  const now = new Date().toISOString();
  return {
    id: `calculation-book-preset-${now}-${Math.random().toString(36).slice(2, 8)}`,
    name: name.trim(),
    values: selectPresetValues(schema, values),
    updatedAt: now,
  };
}

export function updateCalculationBookPreset(
  id: string,
  name: string,
  schema: CalculationBookSchema,
  values: Record<string, string>,
): CalculationBookPreset {
  return {
    id,
    name: name.trim(),
    values: selectPresetValues(schema, values),
    updatedAt: new Date().toISOString(),
  };
}

export function saveCalculationBookPreset(
  preset: CalculationBookPreset,
): CalculationBookPreset[] {
  const presets = loadCalculationBookPresets();
  persistCalculationBookPresets([
    preset,
    ...presets.filter((item) => item.id !== preset.id),
  ]);
  return loadCalculationBookPresets();
}

export function renameCalculationBookPreset(
  id: string,
  nextName: string,
): CalculationBookPreset[] {
  const presets = loadCalculationBookPresets().map((preset) =>
    preset.id === id
      ? {
          ...preset,
          name: nextName.trim(),
          updatedAt: new Date().toISOString(),
        }
      : preset,
  );
  persistCalculationBookPresets(presets);
  return loadCalculationBookPresets();
}

export function deleteCalculationBookPreset(id: string): CalculationBookPreset[] {
  const presets = loadCalculationBookPresets().filter((preset) => preset.id !== id);
  persistCalculationBookPresets(presets);
  return loadCalculationBookPresets();
}

export function applyCalculationBookPreset(
  schema: CalculationBookSchema,
  currentValues: Record<string, string>,
  preset: CalculationBookPreset,
): Record<string, string> {
  const nextValues = Object.fromEntries(
    schema.fields.map((field) => {
      const fallback = currentValues[field.key] ?? field.defaultValue ?? "";
      const candidate =
        isPresetManagedField(field) && hasOwn(preset.values, field.key)
          ? preset.values[field.key]
          : fallback;
      return [field.key, normalizeSelectValue(schema, field, candidate)];
    }),
  );

  if (schema.fields.some((field) => field.key === "project_name")) {
    nextValues.project_name =
      schema.projectOptions.find((option) => option.value === nextValues.project_no)?.label ?? "";
  }

  return nextValues;
}

function selectPresetValues(
  schema: CalculationBookSchema,
  values: Record<string, string>,
): Record<string, string> {
  return Object.fromEntries(
    schema.fields
      .filter(isPresetManagedField)
      .map((field) => [field.key, values[field.key] ?? field.defaultValue ?? ""]),
  );
}

function isPresetManagedField(field: CalculationBookSchema["fields"][number]) {
  return field.key !== "project_name" && !field.derivedFrom;
}

function normalizeSelectValue(
  schema: CalculationBookSchema,
  field: CalculationBookSchema["fields"][number],
  value: string,
) {
  let options: readonly string[] | undefined;
  if (field.key === "template_type") {
    options = schema.templates.map((option) => option.value);
  } else if (field.key === "project_no") {
    options = schema.projectOptions.map((option) => option.value);
  } else if (field.type === "select") {
    options = field.options ?? [];
  }

  if (options && !options.includes(value)) {
    return field.defaultValue ?? "";
  }
  return value;
}

function persistCalculationBookPresets(presets: CalculationBookPreset[]) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(presets));
  } catch {
    throw new Error("保存计算书预设失败，请检查浏览器本地存储后重试。");
  }
}

function isCalculationBookPreset(value: unknown): value is CalculationBookPreset {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Partial<CalculationBookPreset>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.name === "string" &&
    typeof candidate.updatedAt === "string" &&
    isIsoTimestamp(candidate.updatedAt) &&
    Boolean(candidate.values && typeof candidate.values === "object") &&
    Object.values(candidate.values ?? {}).every((item) => typeof item === "string")
  );
}

function isIsoTimestamp(value: string) {
  try {
    return new Date(value).toISOString() === value;
  } catch {
    return false;
  }
}

function hasOwn(values: Record<string, string>, key: string) {
  return Object.prototype.hasOwnProperty.call(values, key);
}
