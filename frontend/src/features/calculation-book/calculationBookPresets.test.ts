import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CalculationBookSchema } from "../../platform/api/types";
import {
  applyCalculationBookPreset,
  createCalculationBookPreset,
  deleteCalculationBookPreset,
  loadCalculationBookPresets,
  renameCalculationBookPreset,
  saveCalculationBookPreset,
  updateCalculationBookPreset,
  type CalculationBookPreset,
} from "./calculationBookPresets";

const STORAGE_KEY = "auto-fanban.calculation-book-presets";

const schema = {
  templates: [
    { value: "wall", label: "Wall calculation" },
    { value: "slab", label: "Slab calculation" },
  ],
  projectOptions: [
    { value: "2016", label: "Project 2016" },
    { value: "2026", label: "Project 2026" },
  ],
  fields: [
    {
      key: "template_type",
      label: "Template",
      type: "select",
      required: true,
      defaultValue: "wall",
    },
    {
      key: "project_no",
      label: "Project number",
      type: "select",
      required: true,
      defaultValue: "2016",
    },
    {
      key: "project_name",
      label: "Project name",
      type: "text",
      required: true,
      derivedFrom: "project_no",
    },
    {
      key: "document_name",
      label: "Document name",
      type: "text",
      required: true,
    },
    {
      key: "version",
      label: "Version",
      type: "text",
      required: true,
      defaultValue: "A",
    },
    {
      key: "section_type",
      label: "Section type",
      type: "select",
      required: true,
      defaultValue: "wall",
      options: ["wall", "slab"],
    },
    {
      key: "design_phase",
      label: "Design phase",
      type: "select",
      required: true,
      options: ["construction"],
    },
    {
      key: "derived_title",
      label: "Derived title",
      type: "text",
      required: false,
      derivedFrom: "document_name",
    },
    {
      key: "include_slab_stress",
      label: "Include slab stress",
      type: "checkbox",
      required: false,
      defaultValue: "false",
    },
  ],
  archive: {
    accept: [".zip", ".rar"],
    requiredRootDirections: ["X", "Y", "Z"],
    requiredFolders: ["01", "02"],
    rootFigurePattern: "<wall>-X|Y|Z.png",
    description: "Required archive tree",
  },
} satisfies CalculationBookSchema;

function preset(
  overrides: Partial<CalculationBookPreset> = {},
): CalculationBookPreset {
  return {
    id: "preset-1",
    name: "Preset one",
    values: {},
    updatedAt: "2026-08-03T08:00:00.000Z",
    ...overrides,
  };
}

describe("calculationBookPresets", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("saves and loads only current non-derived schema values", () => {
    const created = createCalculationBookPreset("  Main preset  ", schema, {
      template_type: "wall",
      project_no: "2026",
      project_name: "Stale project name",
      document_name: "Reactor building",
      version: "B",
      section_type: "slab",
      design_phase: "construction",
      derived_title: "Stale derived title",
      include_slab_stress: "true",
      removed_legacy_field: "legacy",
    });

    expect(created.name).toBe("Main preset");
    expect(created.values).toEqual({
      template_type: "wall",
      project_no: "2026",
      document_name: "Reactor building",
      version: "B",
      section_type: "slab",
      design_phase: "construction",
      include_slab_stress: "true",
    });

    saveCalculationBookPreset(created);

    expect(loadCalculationBookPresets()).toEqual([created]);
  });

  it("updates an existing preset without creating a second entry", () => {
    const created = createCalculationBookPreset("Original", schema, {
      project_no: "2016",
      include_slab_stress: "false",
    });
    saveCalculationBookPreset(created);

    const updated = updateCalculationBookPreset(created.id, "Updated", schema, {
      project_no: "2026",
      include_slab_stress: "true",
    });
    saveCalculationBookPreset(updated);

    const stored = loadCalculationBookPresets();
    expect(stored).toHaveLength(1);
    expect(stored[0]).toMatchObject({
      id: created.id,
      name: "Updated",
      values: {
        project_no: "2026",
        include_slab_stress: "true",
      },
    });
  });

  it("renames and deletes saved presets", () => {
    saveCalculationBookPreset(preset());

    renameCalculationBookPreset("preset-1", "Renamed preset");
    expect(loadCalculationBookPresets()[0]?.name).toBe("Renamed preset");

    deleteCalculationBookPreset("preset-1");
    expect(loadCalculationBookPresets()).toEqual([]);
  });

  it("loads presets by updatedAt descending", () => {
    saveCalculationBookPreset(
      preset({ id: "newer", updatedAt: "2026-08-03T09:00:00.000Z" }),
    );
    saveCalculationBookPreset(
      preset({ id: "older", updatedAt: "2026-08-03T08:00:00.000Z" }),
    );

    expect(loadCalculationBookPresets().map((item) => item.id)).toEqual([
      "newer",
      "older",
    ]);
  });

  it("returns an empty list when stored JSON is damaged", () => {
    window.localStorage.setItem(STORAGE_KEY, "{not valid JSON");

    expect(loadCalculationBookPresets()).toEqual([]);
  });

  it("throws a clear Chinese error when localStorage cannot persist a preset", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });

    expect(() => saveCalculationBookPreset(preset())).toThrowError(
      "保存计算书预设失败，请检查浏览器本地存储后重试。",
    );
  });

  it("ignores stored presets whose updatedAt is not a valid ISO timestamp", () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        preset({ id: "valid", updatedAt: "2026-08-03T08:00:00.000Z" }),
        preset({ id: "invalid", updatedAt: "not-a-date" }),
      ]),
    );

    expect(loadCalculationBookPresets().map((item) => item.id)).toEqual(["valid"]);
  });

  it("applies only current schema fields and preserves missing current or default values", () => {
    const applied = applyCalculationBookPreset(
      schema,
      {
        template_type: "wall",
        project_no: "2016",
        project_name: "Project 2016",
        document_name: "Current document",
        section_type: "wall",
        design_phase: "construction",
        derived_title: "Current derived title",
        include_slab_stress: "false",
        removed_current_field: "remove me",
      },
      preset({
        values: {
          template_type: "slab",
          project_no: "2026",
          include_slab_stress: "true",
          derived_title: "Old preset derived title",
          removed_preset_field: "remove me too",
        },
      }),
    );

    expect(applied).toEqual({
      template_type: "slab",
      project_no: "2026",
      project_name: "Project 2026",
      document_name: "Current document",
      version: "A",
      section_type: "wall",
      design_phase: "construction",
      derived_title: "Current derived title",
      include_slab_stress: "true",
    });
  });

  it("falls invalid select values back to each field default or an empty string", () => {
    const applied = applyCalculationBookPreset(
      schema,
      {
        template_type: "slab",
        project_no: "2026",
        project_name: "Project 2026",
        section_type: "slab",
        design_phase: "construction",
      },
      preset({
        values: {
          template_type: "removed-template",
          project_no: "removed-project",
          section_type: "removed-section",
          design_phase: "removed-phase",
        },
      }),
    );

    expect(applied.template_type).toBe("wall");
    expect(applied.project_no).toBe("2016");
    expect(applied.project_name).toBe("Project 2016");
    expect(applied.section_type).toBe("wall");
    expect(applied.design_phase).toBe("");
  });

  it("recomputes project_name from the applied project_no", () => {
    const applied = applyCalculationBookPreset(
      schema,
      {
        project_no: "2016",
        project_name: "Project 2016",
      },
      preset({
        values: {
          project_no: "2026",
          project_name: "Stale project name",
        },
      }),
    );

    expect(applied.project_no).toBe("2026");
    expect(applied.project_name).toBe("Project 2026");
  });
});
