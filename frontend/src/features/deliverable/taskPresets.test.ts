import { beforeEach, describe, expect, it } from "vitest";

import {
  applyTaskPreset,
  createTaskPreset,
  deleteTaskPreset,
  loadTaskPresets,
  renameTaskPreset,
  saveTaskPreset,
  updateTaskPreset,
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
          key: "is_upgrade",
          label: "是否升版",
          type: "text",
          required: false,
          requiredWhen: null,
          defaultValue: "false",
          description: "是否启用升版标记",
          options: [],
        },
        {
          key: "upgrade_sheet_codes",
          label: "升版图纸编号",
          type: "text",
          required: false,
          requiredWhen: null,
          defaultValue: "",
          description: "输入图纸内部编码最后三位",
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
    draft.values.is_upgrade = "true";
    draft.values.upgrade_sheet_codes = "001、003";
    draft.values.ied_prepared_date = "2026-03-12";
    draft.replaceConfig = {
      sourceProjectNo: "2016",
      targetProjectNo: "1818",
    };

    const preset = createTaskPreset("默认方案", draft);
    saveTaskPreset(preset);

    expect(loadTaskPresets()).toEqual([preset]);
    expect(loadTaskPresets()[0].values.ied_prepared_date).toBeUndefined();
    expect(loadTaskPresets()[0].values.is_upgrade).toBe("true");
    expect(loadTaskPresets()[0].values.upgrade_sheet_codes).toBe("001、003");
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

  it("creates a new preset instead of overwriting the selected one when saving a different name", () => {
    const draft = createTaskConfigDraft(schema);
    draft.values.project_no = "2016";

    const firstPreset = createTaskPreset("方案一", draft);
    saveTaskPreset(firstPreset);

    draft.values.project_no = "1818";
    const secondPreset = createTaskPreset("方案二", draft);
    saveTaskPreset(secondPreset);

    const presets = loadTaskPresets();
    expect(presets).toHaveLength(2);
    expect(presets.map((preset) => preset.name)).toEqual(["方案二", "方案一"]);
    expect(presets.map((preset) => preset.id)).toContain(firstPreset.id);
    expect(presets.map((preset) => preset.id)).toContain(secondPreset.id);
  });

  it("updates the selected preset in place only when explicitly requested", () => {
    const draft = createTaskConfigDraft(schema);
    draft.values.project_no = "2016";

    const preset = createTaskPreset("方案一", draft);
    saveTaskPreset(preset);

    draft.values.project_no = "1818";
    const updatedPreset = updateTaskPreset(preset.id, "方案一-更新", draft);
    saveTaskPreset(updatedPreset);

    const presets = loadTaskPresets();
    expect(presets).toHaveLength(1);
    expect(presets[0]?.id).toBe(preset.id);
    expect(presets[0]?.name).toBe("方案一-更新");
    expect(presets[0]?.values.project_no).toBe("1818");
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
      runAuditCheck: true,
      values: {
        ...draft.values,
        project_no: "2020",
        album_title_cn: "翻版图册",
        is_upgrade: "true",
        upgrade_sheet_codes: "001~003",
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
    expect(nextDraft.values.is_upgrade).toBe("true");
    expect(nextDraft.values.upgrade_sheet_codes).toBe("001~003");
    expect(nextDraft.values.ied_prepared_date).toBe(new Date().toISOString().slice(0, 10));
    expect(nextDraft.intent).toBe("audit_replace");
    expect(nextDraft.runAuditCheck).toBe(true);
    expect(nextDraft.replaceConfig.targetProjectNo).toBe("1818");
  });
});
