import {
  buildRecommendedProjectNos,
  evaluateRequiredWhen,
  isAdvancedField,
  isCustomRenderedField,
  normalizeFormSchema,
} from "./schema";

describe("normalizeFormSchema", () => {
  it("maps section titles, field labels, helper copy, and hides legacy frontend-only fields", () => {
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
                desc: "封面模板选择；1818 与非1818均使用通用/压力容器/核安全设备三选一；1818会切到对应专用模板",
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
            ],
          },
          {
            id: "catalog",
            title: "catalog",
            fields: [
              {
                key: "is_upgrade",
                label: "is_upgrade",
                type: "text",
                required: false,
                required_when: null,
                source: "frontend",
                default: "false",
                format: null,
                desc: "是否启用升版标记",
                options: [],
              },
              {
                key: "upgrade_sheet_codes",
                label: "upgrade_sheet_codes",
                type: "text",
                required: false,
                required_when: null,
                source: "frontend",
                default: "",
                format: null,
                desc: "输入图纸内部编码末三位",
                options: [],
              },
              {
                key: "upgrade_start_seq",
                label: "upgrade_start_seq",
                type: "text",
                required: false,
                required_when: null,
                source: "frontend",
                default: "",
                format: null,
                desc: "旧字段",
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
              {
                key: "ied_chief_designer",
                label: "ied_chief_designer",
                type: "text",
                required: false,
                required_when: null,
                source: "frontend",
                default: null,
                format: "姓名@ID",
                desc: "责任设总(W列)，填写规则同编制人/校核人等人员字段",
                options: [],
              },
              {
                key: "ied_discipline_office",
                label: "ied_discipline_office",
                type: "combobox",
                required: false,
                required_when: null,
                source: "frontend",
                default: null,
                format: null,
                desc: "专业室(BJ列)",
                options: ["结构室", "建筑室"],
              },
            ],
          },
        ],
      },
      audit_replace: {
        project_options: ["2016", "1818"],
        project_units: {
          "1915": ["1", "2"],
        },
        source_unit_options: {
          "2016": [
            { value: "1", label: "1号机组/岛" },
            { value: " 2 ", label: " 2号机组/岛 " },
          ],
        },
        target_unit_options: {
          "1915": [
            { value: "1", label: "1号机组/岛" },
            { value: "2", label: "2号机组/岛" },
          ],
        },
        factory_index_maps: {
          source_variant_options: {
            "2016": ["1", "2"],
          },
          target_variant_options: {
            "1916": ["3", "4"],
          },
        },
      },
      audit_check: {
        unit_consistency: {
          enabled: true,
          project_units: {
            "2016": ["1", "2"],
            "1916": ["3", "4"],
          },
        },
      },
    });

    expect(normalized.sections).toHaveLength(3);
    expect(normalized.sections[0].title).toBe("任务与项目");
    expect(normalized.sections[0].fields).toHaveLength(3);
    expect(normalized.sections[0].fields[0].label).toBe("项目号");
    expect(normalized.sections[0].fields[0].description).toBe(
      "可留空，会优先从DWG文件名自动推断",
    );
    expect(normalized.sections[0].fields[1].description).toBe("封面模板选择");
    expect(normalized.sections[0].fields[2].description).toBe("写入设计文件/IED");
    expect(normalized.sections[1].title).toBe("目录与升版");
    expect(normalized.sections[1].fields.map((field) => field.key)).toEqual([
      "is_upgrade",
      "upgrade_sheet_codes",
    ]);
    expect(normalized.sections[2].title).toBe("IED 基础信息");
    expect(normalized.sections[2].fields[0].type).toBe("nameId");
    expect(normalized.sections[2].fields[1].label).toBe("责任设总");
    expect(normalized.sections[2].fields[1].description).toBe("例如：王任超@wangrca");
    expect(
      normalized.sections[2].fields.some((field) => field.key === "ied_discipline_office"),
    ).toBe(false);
    expect(normalized.auditReplaceProjectOptions).toEqual(["2016", "1818"]);
    expect(normalized.auditReplaceProjectUnits).toEqual({
      "1915": ["1", "2"],
    });
    expect(normalized.auditReplaceSourceUnitOptions).toEqual({
      "2016": [
        { value: "1", label: "1号机组/岛" },
        { value: "2", label: "2号机组/岛" },
      ],
    });
    expect(normalized.auditReplaceTargetUnitOptions).toEqual({
      "1915": [
        { value: "1", label: "1号机组/岛" },
        { value: "2", label: "2号机组/岛" },
      ],
    });
    expect(normalized.auditReplaceFactoryIndexMaps).toEqual({
      sourceVariantOptions: {
        "2016": ["1", "2"],
      },
      targetVariantOptions: {
        "1916": ["3", "4"],
      },
    });
    expect(normalized.auditCheckUnitConsistency).toEqual({
      enabled: true,
      projectUnits: {
        "2016": ["1", "2"],
        "1916": ["3", "4"],
      },
    });
  });

  it("normalizes management schema from backend YAML metadata", () => {
    const normalized = normalizeFormSchema({
      schema_version: "frontend-form@1",
      upload_limits: {
        max_files: 50,
        allowed_exts: [".dwg"],
        max_total_mb: 2048,
      },
      deliverable: {
        sections: [],
      },
      management: {
        account: {
          fields: {
            office_code: "科室编码",
            office_name: "科室",
            account_id: "账号",
            display_name: "姓名",
            role: "角色",
            password: "密码",
          },
          valid_roles: ["designer", "admin"],
          admin_roles: ["admin"],
          admin_created_default_password: "yaml-pass",
        },
        workflow: {
          terminal_status: "archived",
          status_labels: {
            archived: "Archived",
          },
          node_labels: {
            custom_review: "Custom Review",
          },
          empty_current_node_label: "No active node",
          factor: {
            default: 1.05,
            min: 0.5,
            max: 1.3,
            precision: 3,
          },
        },
        workload: {
          settlement_trigger: "approval_terminal",
          scope_roles: {
            admin: ["admin"],
          },
          scope_labels: {
            me: "Mine",
            admin: "Admin",
          },
          status_options: [
            { label: "All", value: "" },
            { label: "Settled", value: "settled" },
          ],
        },
        archive: {
          status_labels: {
            succeeded: "Archived",
          },
        },
      },
    });

    expect(normalized.management?.account.validRoles).toEqual(["designer", "admin"]);
    expect(normalized.management?.account.fieldMap.accountId).toBe("账号");
    expect(normalized.management?.account.adminRoles).toEqual(["admin"]);
    expect(normalized.management?.account.adminCreatedDefaultPassword).toBe("yaml-pass");
    expect(normalized.management?.workflow.factor.max).toBe(1.3);
    expect(normalized.management?.workflow.terminalStatus).toBe("archived");
    expect(normalized.management?.workflow.statusLabels.archived).toBe("Archived");
    expect(normalized.management?.workflow.nodeLabels.custom_review).toBe("Custom Review");
    expect(normalized.management?.workflow.emptyCurrentNodeLabel).toBe("No active node");
    expect(normalized.management?.workload.scopeRoles.admin).toEqual(["admin"]);
    expect(normalized.management?.workload.scopeLabels.admin).toBe("Admin");
    expect(normalized.management?.workload.statusOptions[1]).toEqual({
      label: "Settled",
      value: "settled",
    });
    expect(normalized.management?.archive?.statusLabels.succeeded).toBe("Archived");
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
    expect(normalized.sections[0].fields[0].options).toEqual([
      "安装技术要求",
      "初步设计",
      "BOP子项施工图",
    ]);
  });

  it("keeps checkbox fields from form-schema and normalizes boolean defaults for the frontend draft", () => {
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
                key: "include_ied_plan",
                label: "include_ied_plan",
                type: "checkbox",
                required: false,
                required_when: null,
                source: "frontend",
                default: true,
                format: null,
                desc: "是否生成IED计划并开放下载，默认包含",
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

    expect(normalized.sections[0].fields[0]).toMatchObject({
      key: "include_ied_plan",
      label: "是否生成IED",
      type: "checkbox",
      defaultValue: "true",
    });
  });

  it("prioritizes 河北分公司-建筑结构所 responsible units while keeping combobox metadata", () => {
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
                key: "ied_responsible_unit",
                label: "ied_responsible_unit",
                type: "combobox",
                required: false,
                required_when: "ied_status == '发布'",
                source: "frontend",
                default: null,
                format: null,
                desc: "责任单位(X列)",
                options: [
                  "北京核化工研究设计院-放射性废物管理工程所-放射性废物管理二室",
                  "河北分公司-建筑结构所-结构一室",
                  "公用系统所-水工工艺二室",
                  "河北分公司-建筑结构所-建筑总图室",
                ],
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
    expect(normalized.sections[0].fields[0].options.slice(0, 2)).toEqual([
      "河北分公司-建筑结构所-结构一室",
      "河北分公司-建筑结构所-建筑总图室",
    ]);
  });
  it("preserves the calculation-book slab checkbox and its boolean default", () => {
    const normalized = normalizeFormSchema({
      schema_version: "frontend-form@1",
      upload_limits: {
        max_files: 50,
        allowed_exts: [".dwg"],
        max_total_mb: 2048,
      },
      deliverable: { sections: [] },
      calculation_book: {
        fields: [
          {
            key: "include_slab_stress",
            label: "包含楼板应力",
            type: "checkbox",
            required: false,
            default: false,
          },
        ],
      },
    });

    expect(normalized.calculationBook?.fields).toEqual([
      expect.objectContaining({
        key: "include_slab_stress",
        type: "checkbox",
        defaultValue: "false",
      }),
    ]);
  });

  it("preserves the calculation-book reinforcement source enum and safe default", () => {
    const normalized = normalizeFormSchema({
      schema_version: "frontend-form@1",
      upload_limits: {
        max_files: 50,
        allowed_exts: [".dwg"],
        max_total_mb: 2048,
      },
      deliverable: { sections: [] },
      calculation_book: {
        fields: [
          {
            key: "reinforcement_source",
            label: "配筋来源",
            type: "select",
            required: false,
            default: "provided",
            options: ["provided", "ai_suggested"],
          },
        ],
      },
    });

    expect(normalized.calculationBook?.fields).toEqual([
      expect.objectContaining({
        key: "reinforcement_source",
        type: "select",
        defaultValue: "provided",
        options: ["provided", "ai_suggested"],
      }),
    ]);
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
          label: "封面和目录版次",
          type: "text",
          required: false,
          requiredWhen: null,
          defaultValue: "",
          description: "封面和目录版次",
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
          description: "图册名称（英文）",
          options: [],
        },
        {},
      ),
    ).toBe(false);
  });
});

describe("buildRecommendedProjectNos", () => {
  it("dedupes and preserves inferred project numbers before schema options", () => {
    expect(buildRecommendedProjectNos(["1818", "2026", "1818"], ["2026", "2016"])).toEqual([
      "1818",
      "2026",
      "2016",
    ]);
  });
});

describe("isCustomRenderedField", () => {
  it("marks the new upgrade fields as custom rendered", () => {
    expect(isCustomRenderedField("is_upgrade")).toBe(true);
    expect(isCustomRenderedField("upgrade_sheet_codes")).toBe(true);
    expect(isCustomRenderedField("upgrade_entries")).toBe(true);
    expect(isCustomRenderedField("cover_revision")).toBe(true);
  });
});
