import { describe, expect, it } from "vitest";

import { createTaskConfigDraft, syncTaskConfigDraft } from "./taskDraft";
import type { FormSchema, TaskConfigDraft } from "../../platform/api/types";

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
          options: ["2016", "1818"],
        },
        {
          key: "album_title_cn",
          label: "图册名称（中文）",
          type: "text",
          required: true,
          requiredWhen: null,
          defaultValue: "默认图册",
          description: "图册名称",
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

describe("createTaskConfigDraft", () => {
  it("builds an initial draft from schema defaults", () => {
    const draft = createTaskConfigDraft(schema);

    expect(draft.intent).toBe("deliverable");
    expect(draft.runAuditCheck).toBe(false);
    expect(draft.files).toEqual([]);
    expect(draft.values).toEqual({
      plot_style_key: "red_wider",
      project_no: "",
      album_title_cn: "默认图册",
      ied_prepared_date: new Date().toISOString().slice(0, 10),
    });
    expect(draft.replaceConfig).toEqual({
      sourceProjectNo: "",
      targetProjectNo: "",
    });
  });
});

describe("syncTaskConfigDraft", () => {
  it("preserves user input while backfilling new schema fields", () => {
    const currentDraft: TaskConfigDraft = {
      intent: "audit_replace",
      runAuditCheck: true,
      files: [new File(["dwg"], "1818-A01.dwg", { type: "application/acad" })],
      values: {
        project_no: "1818",
        album_title_cn: "已修改图册",
        ied_prepared_date: "2026-03-12",
      },
      fieldErrors: {
        album_title_cn: ["required"],
      },
      formErrors: ["文件缺失"],
      inference: {
        inferredProjectNos: ["1818"],
        primaryProjectNo: "1818",
        hasConflict: false,
      },
      replaceConfig: {
        sourceProjectNo: "1818",
        targetProjectNo: "2020",
      },
    };

    const nextSchema: FormSchema = {
      ...schema,
      sections: [
        {
          ...schema.sections[0],
          fields: [
            ...schema.sections[0].fields,
            {
              key: "subitem_name",
              label: "子项名称",
              type: "text",
              required: false,
              requiredWhen: null,
              defaultValue: "默认子项",
              description: "子项名称",
              options: [],
            },
          ],
        },
      ],
    };

    const draft = syncTaskConfigDraft(nextSchema, currentDraft);

    expect(draft.intent).toBe("audit_replace");
    expect(draft.runAuditCheck).toBe(true);
    expect(draft.values).toEqual({
      plot_style_key: "red_wider",
      project_no: "1818",
      album_title_cn: "已修改图册",
      ied_prepared_date: "2026-03-12",
      subitem_name: "默认子项",
    });
    expect(draft.files).toHaveLength(1);
    expect(draft.replaceConfig.targetProjectNo).toBe("2020");
  });
});
