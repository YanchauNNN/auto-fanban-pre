import { normalizeFormSchema } from "./schema";

describe("normalizeFormSchema independent IED checker fields", () => {
  it("keeps checker and discipline leader fields visible as separate inputs", () => {
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
                key: "ied_checked_by",
                label: "ied_checked_by",
                type: "text",
                required: true,
                required_when: null,
                source: "frontend",
                default: null,
                format: "姓名@ID",
                desc: "校核者(BB列)",
                options: [],
              },
              {
                key: "ied_checked_date",
                label: "ied_checked_date",
                type: "text",
                required: true,
                required_when: null,
                source: "frontend",
                default: null,
                format: "YYYY-MM-DD",
                desc: "校核日期(BC列)",
                options: [],
              },
              {
                key: "ied_discipline_leader",
                label: "ied_discipline_leader",
                type: "text",
                required: true,
                required_when: null,
                source: "frontend",
                default: null,
                format: "姓名@ID",
                desc: "工种负责人(BD列)",
                options: [],
              },
              {
                key: "ied_discipline_leader_date",
                label: "ied_discipline_leader_date",
                type: "text",
                required: true,
                required_when: null,
                source: "frontend",
                default: null,
                format: "YYYY-MM-DD",
                desc: "工种负责人审核日期(BE列)",
                options: [],
              },
            ],
          },
        ],
      },
      audit_replace: {
        project_options: [],
      },
    });

    const iedFields = normalized.sections[0]?.fields ?? [];

    expect(iedFields.map((field) => field.key)).toEqual([
      "ied_checked_by",
      "ied_checked_date",
      "ied_discipline_leader",
      "ied_discipline_leader_date",
    ]);
    expect(iedFields[0]?.label).toBe("校核者");
    expect(iedFields[1]?.label).toBe("校核日期");
    expect(iedFields[2]?.label).toBe("工种负责人");
    expect(iedFields[3]?.label).toBe("工种负责人审核日期");
  });
});
