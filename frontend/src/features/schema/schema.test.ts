import { describe, expect, it } from "vitest";

import {
  buildRecommendedProjectNos,
  evaluateRequiredWhen,
  isAdvancedField,
  normalizeFormSchema,
} from "./schema";

describe("normalizeFormSchema", () => {
  it("maps section titles, field labels, and hides deprecated approved_by", () => {
    const normalized = normalizeFormSchema({
      schema_version: "frontend-form@1",
      upload_limits: {
        max_files: 50,
        allowed_exts: [".dwg"],
        max_total_mb: 2048,
      },
      deliverable: {
        sections: [
          {
            id: "project",
            title: "project",
            fields: [
              {
                key: "project_no",
                label: "project_no",
                type: "select",
                required: false,
                required_when: null,
                source: "frontend",
                default: null,
                format: null,
                desc: "项目号",
                options: ["2016", "1818"],
              },
              {
                key: "approved_by",
                label: "approved_by",
                type: "text",
                required: false,
                required_when: null,
                source: "frontend",
                default: null,
                format: null,
                desc: "deprecated",
                options: [],
              },
            ],
          },
          {
            id: "ied",
            title: "ied",
            fields: [
              {
                key: "ied_prepared_by",
                label: "ied_prepared_by",
                type: "text",
                required: false,
                required_when: "ied_status == '发布'",
                source: "frontend",
                default: null,
                format: "姓名@ID",
                desc: "编制者",
                options: [],
              },
            ],
          },
        ],
      },
      audit_replace: {
        project_options: ["2016", "1818"],
      },
    });

    expect(normalized.sections).toHaveLength(2);
    expect(normalized.sections[0].title).toBe("任务与项目");
    expect(normalized.sections[0].fields).toHaveLength(1);
    expect(normalized.sections[0].fields[0].label).toBe("项目号");
    expect(normalized.sections[1].title).toBe("IED 基础信息");
    expect(normalized.sections[1].fields[0].type).toBe("nameId");
    expect(normalized.auditReplaceProjectOptions).toEqual(["2016", "1818"]);
  });
});

describe("evaluateRequiredWhen", () => {
  it("supports equality and inequality expressions without eval", () => {
    expect(
      evaluateRequiredWhen("project_no == '1818'", {
        project_no: "1818",
      }),
    ).toBe(true);
    expect(
      evaluateRequiredWhen("project_no != '1818'", {
        project_no: "2016",
      }),
    ).toBe(true);
    expect(
      evaluateRequiredWhen("project_no != '1818'", {
        project_no: "1818",
      }),
    ).toBe(false);
  });
});

describe("isAdvancedField", () => {
  it("moves optional fields into advanced options when they are not conditionally required", () => {
    expect(
      isAdvancedField(
        {
          key: "cover_revision",
          label: "封面版次",
          type: "text",
          required: false,
          requiredWhen: null,
          defaultValue: "",
          description: "封面版次",
          options: [],
        },
        {},
      ),
    ).toBe(true);
  });

  it("keeps optional primary fields out of advanced options when they are not in the advanced allowlist", () => {
    expect(
      isAdvancedField(
        {
          key: "album_title_en",
          label: "图册名称（英文）",
          type: "text",
          required: false,
          requiredWhen: null,
          defaultValue: "",
          description: "图册名称（英文），仅1818需要",
          options: [],
        },
        {},
      ),
    ).toBe(false);
  });

  it("keeps conditionally required fields in the primary section when the condition matches", () => {
    expect(
      isAdvancedField(
        {
          key: "ied_publish_plan_date",
          label: "出版计划",
          type: "text",
          required: false,
          requiredWhen: "ied_status == '发布'",
          defaultValue: "",
          description: "出版计划",
          options: [],
        },
        {
          ied_status: "发布",
        },
      ),
    ).toBe(false);
  });
});

describe("buildRecommendedProjectNos", () => {
  it("merges inferred project numbers with schema options and removes duplicates", () => {
    expect(
      buildRecommendedProjectNos(["1818", "2016", "1818", ""], [
        "2016",
        "2020",
        "1818",
      ]),
    ).toEqual(["1818", "2016", "2020"]);
  });
});
