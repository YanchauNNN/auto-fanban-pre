import { describe, expect, it } from "vitest";

import {
  buildRecommendedProjectNos,
  evaluateRequiredWhen,
  isAdvancedField,
  normalizeFormSchema,
} from "./schema";

describe("normalizeFormSchema", () => {
  it("maps section titles, field labels, helper copy, and hides deprecated approved_by", () => {
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
                desc: "项目号；可留空，API/桌面端会优先从DWG文件名自动推断，推断失败时回退2016",
                options: ["2016", "1818"],
              },
              {
                key: "cover_variant",
                label: "cover_variant",
                type: "select",
                required: true,
                required_when: null,
                source: "frontend",
                default: "通用",
                format: null,
                desc: "封面模板选择；1818 与非1818均使用通用/压力容器/核安全设备三选一，1818会切到对应专用模板",
                options: ["通用", "压力容器", "核安全设备"],
              },
              {
                key: "classification",
                label: "classification",
                type: "select",
                required: true,
                required_when: null,
                source: "frontend",
                default: "非密",
                format: null,
                desc: "密级，写入封面/设计文件/IED",
                options: ["非密", "秘密"],
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
    expect(normalized.sections[0].fields).toHaveLength(3);
    expect(normalized.sections[0].fields[0].label).toBe("项目号");
    expect(normalized.sections[0].fields[0].description).toBe(
      "可留空，会优先从DWG文件名自动推断",
    );
    expect(normalized.sections[0].fields[1].description).toBe("封面模板选择");
    expect(normalized.sections[0].fields[2].description).toBe("写入设计文件/IED");
    expect(normalized.sections[1].title).toBe("IED 基础信息");
    expect(normalized.sections[1].fields[0].type).toBe("nameId");
    expect(normalized.auditReplaceProjectOptions).toEqual(["2016", "1818"]);
  });

  it("preserves combobox fields from form-schema instead of downgrading them to plain select metadata", () => {
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
            id: "ied",
            title: "ied",
            fields: [
              {
                key: "ied_design_type",
                label: "ied_design_type",
                type: "combobox",
                required: false,
                required_when: "ied_status == '发布'",
                source: "frontend",
                default: null,
                format: null,
                desc: "设计类型(V列)",
                options: ["安装技术要求", "初步设计"],
              },
            ],
          },
        ],
      },
      audit_replace: {
        project_options: ["2016", "1818"],
      },
    });

    expect(normalized.sections[0].fields[0].type).toBe("combobox");
    expect(normalized.sections[0].fields[0].options).toEqual(["安装技术要求", "初步设计"]);
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
