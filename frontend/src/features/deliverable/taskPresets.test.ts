import { beforeEach, describe, expect, it } from "vitest";

import {
  applyTaskPreset,
  createTaskPreset,
  deleteTaskPreset,
  loadTaskPresets,
  renameTaskPreset,
  saveTaskPreset,
} from "./taskPresets";
import { createTaskConfigDraft } from "./taskDraft";
import type { FormSchema } from "../../platform/api/types";

const schema: FormSchema = {
  schemaVersion: "frontend-form@1",
  uploadLimits: {
    maxFiles: 50,
    allowedExts: [".dwg"],
    maxTotalMb: 2048,
  },
  sections: [
    {
      id: "project",
      title: "任务与项目",
      fields: [
        {
          key: "project_no",
          label: "项目号",
          type: "select",
          required: false,
          requiredWhen: null,
          defaultValue: "",
          description: "项目号",
          options: ["2016", "1818", "2020"],
        },
        {
          key: "album_title_cn",
          label: "图册名称（中文）",
          type: "text",
          required: true,
          requiredWhen: null,
          defaultValue: "",
          description: "图册名称（中文）",
          options: [],
        },
        {
          key: "ied_prepared_date",
          label: "编制日期",
          type: "date",
          required: true,
          requiredWhen: null,
          defaultValue: "",
          description: "编制日期",
          options: [],
        },
      ],
    },
  ],
};

describe("taskPresets", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("saves and loads named task presets from localStorage", () => {
    const draft = createTaskConfigDraft(schema);
    draft.intent = "audit_replace";
    draft.values.project_no = "2016";
    draft.values.album_title_cn = "示例图册";
    draft.values.ied_prepared_date = "2026-03-12";
    draft.replaceConfig = {
      sourceProjectNo: "2016",
      targetProjectNo: "1818",
    };

    const preset = createTaskPreset("默认方案", draft);
    saveTaskPreset(preset);

    expect(loadTaskPresets()).toEqual([preset]);
    expect(loadTaskPresets()[0].values.ied_prepared_date).toBeUndefined();
  });

  it("renames and deletes saved presets", () => {
    const draft = createTaskConfigDraft(schema);
    draft.values.album_title_cn = "示例图册";

    const preset = createTaskPreset("旧名称", draft);
    saveTaskPreset(preset);

    renameTaskPreset(preset.id, "新名称");
    expect(loadTaskPresets()[0].name).toBe("新名称");

    deleteTaskPreset(preset.id);
    expect(loadTaskPresets()).toEqual([]);
  });

  it("applies a preset onto the current draft without touching files or inference", () => {
    const draft = createTaskConfigDraft(schema);
    draft.files = [new File(["dwg"], "2016-A01.dwg", { type: "application/acad" })];
    draft.inference = {
      inferredProjectNos: ["2016"],
      primaryProjectNo: "2016",
      hasConflict: false,
    };

    const preset = createTaskPreset("翻版方案", {
      intent: "audit_replace",
      values: {
        ...draft.values,
        project_no: "2020",
        album_title_cn: "翻版图册",
        ied_prepared_date: "2026-03-12",
      },
      replaceConfig: {
        sourceProjectNo: "2020",
        targetProjectNo: "1818",
      },
    });

    const nextDraft = applyTaskPreset(schema, draft, preset);

    expect(nextDraft.files).toHaveLength(1);
    expect(nextDraft.inference.primaryProjectNo).toBe("2016");
    expect(nextDraft.values.project_no).toBe("2020");
    expect(nextDraft.values.ied_prepared_date).toBe(
      new Date().toISOString().slice(0, 10),
    );
    expect(nextDraft.intent).toBe("audit_replace");
    expect(nextDraft.replaceConfig.targetProjectNo).toBe("1818");
  });
});
