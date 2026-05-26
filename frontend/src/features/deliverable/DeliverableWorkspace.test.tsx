import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { DeliverableWorkspace } from "./DeliverableWorkspace";
import type { ApiAdapter, FontPreflightResult, FormSchema } from "../../platform/api/types";

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
          description: "可留空，会优先从DWG文件名自动推断",
          options: ["2016", "1818", "2020"],
        },
        {
          key: "unit_no",
          label: "机组号",
          type: "select",
          required: false,
          requiredWhen: null,
          defaultValue: "",
          description: "用于纠错机组一致性检查",
          options: ["1", "2"],
        },
        {
          key: "cover_variant",
          label: "封面模板",
          type: "select",
          required: true,
          requiredWhen: null,
          defaultValue: "通用",
          description: "封面模板选择",
          options: ["通用", "压力容器", "核安全设备"],
        },
      ],
    },
    {
      id: "cover",
      title: "图册与封面",
      fields: [
        {
          key: "album_title_cn",
          label: "图册名称（中文）",
          type: "text",
          required: true,
          requiredWhen: null,
          defaultValue: "",
          description: "图册名称（中文），例如：XXX厂房XX标高模板图",
          options: [],
        },
        {
          key: "subitem_name",
          label: "子项名称（中文）",
          type: "text",
          required: true,
          requiredWhen: null,
          defaultValue: "",
          description: "子项名称（中文），例如：反应堆厂房",
          options: [],
        },
        {
          key: "file_category",
          label: "文件类别",
          type: "combobox",
          required: false,
          requiredWhen: null,
          defaultValue: "",
          description: "文件类别(U列)",
          options: [
            "1 总体文件",
            "1.1 管理性文件",
            "1.1.1 项目管理大纲",
            "1.1.2 质量保证文件",
            "1.1.3 项目设计管理程序（进度、接口）",
            "1.1.4 项目月报",
            "1.1.5 项目季报",
            "1.2 总体技术文件",
            "1.2.1 设计总说明书",
            "1.2.2 设计参数汇总表",
            "1.2.3 技术要求说明",
            "1.2.4 接口协调文件",
          ],
        },
        {
          key: "cover_revision",
          label: "封面和目录版次",
          type: "text",
          required: false,
          requiredWhen: null,
          defaultValue: "",
          description: "封面和目录版次，写入封面和目录版次位（追加模式）",
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
          description: "输入图纸内部编码末三位，支持单个编号和区间组合。",
          options: [],
        },
        {
          key: "upgrade_entries",
          label: "升版规则",
          type: "text",
          required: false,
          requiredWhen: null,
          defaultValue: "[]",
          description: "结构化升版规则",
          options: [],
        },
        {
          key: "upgrade_start_seq",
          label: "升版起始号",
          type: "text",
          required: false,
          requiredWhen: null,
          defaultValue: "",
          description: "旧字段",
          options: [],
        },
      ],
    },
    {
      id: "ied",
      title: "IED 基础信息",
      fields: [
        {
          key: "ied_prepared_date",
          label: "编制日期",
          type: "date",
          required: true,
          requiredWhen: null,
          defaultValue: "",
          description: "点击选择日期",
          options: [],
        },
      ],
    },
  ],
  auditReplaceProjectOptions: ["2016", "2035"],
};

const schemaWithIedPlan: FormSchema = {
  ...schema,
  sections: schema.sections.map((section) =>
    section.id === "ied"
      ? {
          ...section,
          fields: [
            {
              key: "include_ied_plan",
              label: "包含 IED 计划",
              type: "checkbox",
              required: false,
              requiredWhen: null,
              defaultValue: "true",
              description: "勾选后生成 IED 计划并提供下载。",
              options: [],
            },
            ...section.fields,
          ],
        }
      : section,
  ),
};

const schemaWithRequiredIedPlanFields: FormSchema = {
  ...schemaWithIedPlan,
  sections: schemaWithIedPlan.sections.map((section) =>
    section.id === "ied"
      ? {
          ...section,
          fields: [
            ...(section.fields ?? []),
            {
              key: "ied_doc_type",
              label: "IED 文档类型",
              type: "text",
              required: true,
              requiredWhen: null,
              defaultValue: "",
              description: "IED 文档类型",
              options: [],
            },
            {
              key: "ied_checked_by",
              label: "IED 校核者",
              type: "text",
              required: true,
              requiredWhen: null,
              defaultValue: "",
              description: "IED 校核者",
              options: [],
            },
          ],
        }
      : section,
  ),
};

const schemaWithIedPlanInDesignSection: FormSchema = {
  ...schema,
  sections: [
    schema.sections[0],
    schema.sections[1],
    {
      id: "design",
      title: "设计文件",
      fields: [
        {
          key: "wbs_code",
          label: "WBS 编码",
          type: "text",
          required: true,
          requiredWhen: null,
          defaultValue: "",
          description: "WBS编码，全图册共用",
          options: [],
        },
        {
          key: "include_ied_plan",
          label: "是否生成IED",
          type: "checkbox",
          required: false,
          requiredWhen: null,
          defaultValue: "true",
          description: "勾选后生成IED计划并提供下载。",
          options: [],
        },
      ],
    },
    schema.sections[2],
  ],
};

function createAdapter(): ApiAdapter {
  return {
    getHealth: vi.fn(),
    getFormSchema: vi.fn(),
    preflightFonts: vi.fn(),
    createAuditCheck: vi.fn(),
    createAuditReplace: vi.fn(),
    createSplitOnlyBatch: vi.fn(),
    listJobs: vi.fn(),
    getJobDetail: vi.fn(),
    createBatch: vi.fn(),
  };
}

function createOkFontPreflightResult(filename = "2016-A01.dwg"): FontPreflightResult {
  return {
    files: [
      {
        filename,
        status: "ok",
        missingFonts: [],
        detectedStyleCount: 12,
        missingStyleCount: 0,
        fontReplacementApplied: false,
        replacementFont: null,
        replacementFonts: {},
        replacedStyleCount: 0,
        verifyAfterReplace: null,
        fontReplacementIncomplete: false,
        errors: [],
      },
    ],
    replacementOptions: [],
    replacementOptionsByKind: {},
    defaultReplacementFont: null,
    defaultReplacementFonts: {},
    requiresConfirmation: false,
  };
}

function createMissingShxFontPreflightResult(
  filename = "A01.dwg",
  defaultReplacementFonts = { shx: "simplex.shx" },
): FontPreflightResult {
  return {
    files: [
      {
        filename,
        status: "missing_fonts",
        missingFonts: [
          {
            styleName: "HZTXT",
            fontName: "missing.shx",
            bigfontName: "",
            kind: "shx",
            usedInBlock: true,
          },
        ],
        detectedStyleCount: 12,
        missingStyleCount: 1,
        fontReplacementApplied: false,
        replacementFont: null,
        replacementFonts: {},
        replacedStyleCount: 0,
        verifyAfterReplace: null,
        fontReplacementIncomplete: false,
        errors: [],
      },
    ],
    replacementOptions: [],
    replacementOptionsByKind: {
      shx: [
        {
          label: "simplex.shx (AutoCAD SHX)",
          value: "simplex.shx",
          family: "simplex",
          path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\simplex.shx",
          kind: "shx",
          source: "autocad_fonts",
        },
        {
          label: "romans.shx (AutoCAD SHX)",
          value: "romans.shx",
          family: "romans",
          path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\romans.shx",
          kind: "shx",
          source: "autocad_fonts",
        },
      ],
    },
    defaultReplacementFont: null,
    defaultReplacementFonts,
    requiresConfirmation: true,
  };
}

describe("DeliverableWorkspace", () => {
  const albumTitleLabel =
    schema.sections[1].fields.find((field) => field.key === "album_title_cn")?.label ?? "";
  const subitemNameLabel =
    schema.sections[1].fields.find((field) => field.key === "subitem_name")?.label ?? "";
  const coverRevisionLabel =
    schema.sections[1].fields.find((field) => field.key === "cover_revision")?.label ?? "";
  const isUpgradeLabel =
    schema.sections[1].fields.find((field) => field.key === "is_upgrade")?.label ?? "";
  const upgradeSheetCodesLabel =
    schema.sections[1].fields.find((field) => field.key === "upgrade_sheet_codes")?.label ?? "";

  it("shows an update notice after updating the current preset and clears it on further edits", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    const adapter = createAdapter();

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText("图册名称（中文）"), "方案图册");
    await user.type(screen.getByLabelText("子项名称（中文）"), "反应堆厂房");
    await user.type(screen.getByLabelText("方案名称"), "1818-2");
    await user.click(screen.getByRole("button", { name: "保存为新方案" }));
    await user.click(screen.getByRole("button", { name: "更新当前方案" }));

    expect(screen.getByText("已更新配置")).toBeInTheDocument();

    await user.type(screen.getByLabelText("方案名称"), "A");
    expect(screen.queryByText("已更新配置")).not.toBeInTheDocument();
  });

  it("fills inferred project number and keeps full project and cover menus visible while typing", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "2016-A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    const projectNo = await screen.findByRole("combobox", { name: "项目号" });
    expect(projectNo).toHaveValue("2016");

    await user.clear(projectNo);
    await user.type(projectNo, "zzz");

    expect(await screen.findByRole("option", { name: "2016" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "1818" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "2020" })).toBeInTheDocument();

    const coverVariant = screen.getByRole("combobox", { name: "封面模板" });
    await user.clear(coverVariant);
    await user.type(coverVariant, "zzz");

    expect(await screen.findByRole("option", { name: "通用" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "压力容器" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "核安全设备" })).toBeInTheDocument();
  });

  it("shows unit number next to project number and submits it for audit runs", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "20261NS-JGS01.dwg",
          status: "ok",
          missingFonts: [],
          missingStyleCount: 0,
          detectedStyleCount: 1,
          fontReplacementApplied: false,
          replacedStyleCount: 0,
          replacementFont: null,
          replacementFonts: {},
        },
      ],
      defaultReplacementFont: null,
      defaultReplacementFonts: {},
      availableReplacementFonts: [],
      availableReplacementFontsByKind: {},
    });
    adapter.createBatch = vi.fn().mockResolvedValue({
      batchId: "batch-1",
      jobs: [],
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "20261NS-JGS01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    expect(await screen.findByRole("combobox", { name: "项目号" })).toHaveValue("2026");
    expect(screen.getByLabelText("机组号")).toHaveValue("1");

    await user.type(screen.getByLabelText(albumTitleLabel), "示例图册");
    await user.type(screen.getByLabelText(subitemNameLabel), "反应堆厂房");
    await user.click(screen.getByRole("button", { name: "纠错" }));
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    await waitFor(() => {
      expect(adapter.createBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          project_no: "2026",
          unit_no: "1",
        }),
        expect.arrayContaining([expect.objectContaining({ name: "20261NS-JGS01.dwg" })]),
        true,
      );
    });
  });

  it("uses the replace target project number as the deliverable project number during handoff", async () => {
    const adapter = createAdapter();

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "20261NH-JGS51-B合并版.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        pendingReplaceConfig={{
          sourceProjectNo: "1916",
          sourceIslandNo: "3",
          targetProjectNo: "2016",
          targetIslandNo: "1",
          runDeliverable: true,
        }}
        schema={schema}
      />,
    );

    expect(await screen.findByRole("combobox", { name: "项目号" })).toHaveValue("2016");
  });

  it("does not expose a replace entry inside the deliverable workspace anymore", () => {
    const adapter = createAdapter();

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    expect(screen.queryByRole("button", { name: "翻版" })).not.toBeInTheDocument();
  });

  it("shows helper copy and defaults plot style to red_wider", () => {
    const adapter = createAdapter();

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    expect(screen.getByText("子项名称（中文），例如：反应堆厂房")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "红色更宽" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows all file category candidates inside a scrollable dropdown menu", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.click(screen.getByRole("combobox", { name: "文件类别" }));

    expect(await screen.findByRole("option", { name: "1 总体文件" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "1.2.4 接口协调文件" })).toBeInTheDocument();
  });

  it("moves upgrade controls into the primary area and reveals related inputs only when enabled", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    const upgradeToggle = screen.getByRole("button", { name: isUpgradeLabel });
    expect(upgradeToggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByLabelText(coverRevisionLabel)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(upgradeSheetCodesLabel)).not.toBeInTheDocument();

    await user.click(upgradeToggle);

    const coverRevision = screen.getByLabelText(coverRevisionLabel);
    const upgradeSheetCodes = screen.getByLabelText(upgradeSheetCodesLabel);
    expect(coverRevision).toHaveValue("B");
    await user.clear(coverRevision);
    await waitFor(() => expect(coverRevision).toHaveValue(""));
    await user.type(upgradeSheetCodes, "005~012");

    await user.click(screen.getByRole("button", { name: "展开高级选项" }));

    expect(screen.getAllByRole("button", { name: isUpgradeLabel })).toHaveLength(1);
    expect(screen.getAllByLabelText(coverRevisionLabel)).toHaveLength(1);
    expect(screen.getAllByLabelText(upgradeSheetCodesLabel)).toHaveLength(1);

    await user.click(upgradeToggle);
    expect(screen.queryByLabelText(coverRevisionLabel)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(upgradeSheetCodesLabel)).not.toBeInTheDocument();

    await user.click(upgradeToggle);
    expect(screen.getByLabelText(coverRevisionLabel)).toHaveValue("B");
    expect(screen.getByLabelText(upgradeSheetCodesLabel)).toHaveValue("005~012");
  });

  it("duplicates upgrade rule rows and submits structured upgrade entries", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue(createOkFontPreflightResult());
    adapter.createBatch = vi.fn().mockResolvedValue({
      batchId: "batch-upgrade-rules-1",
      jobs: [],
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "2016-A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText(albumTitleLabel), "示例图册");
    await user.type(screen.getByLabelText(subitemNameLabel), "反应堆厂房");
    await user.click(screen.getByRole("button", { name: "同线宽" }));

    const upgradeBlock = screen.getByTestId("upgrade-config-section");
    await user.click(within(upgradeBlock).getByRole("button", { name: isUpgradeLabel }));

    const firstCodesInput = within(upgradeBlock).getByLabelText(upgradeSheetCodesLabel);
    await user.type(firstCodesInput, "001~003");
    await user.click(within(upgradeBlock).getByRole("button", { name: "复制升版规则" }));

    const revisionInputs = within(upgradeBlock).getAllByLabelText(coverRevisionLabel);
    const codesInputs = within(upgradeBlock).getAllByLabelText(upgradeSheetCodesLabel);
    expect(revisionInputs).toHaveLength(2);
    expect(revisionInputs[1]).toHaveValue("B");
    expect(codesInputs[1]).toHaveValue("001~003");

    await user.clear(revisionInputs[1]);
    await user.type(revisionInputs[1], "D");
    await user.clear(codesInputs[1]);
    await user.type(codesInputs[1], "021~024");
    await user.click(within(upgradeBlock).getAllByRole("checkbox", { name: "新增" })[1]);

    await user.click(screen.getByRole("button", { name: "纠错" }));
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    await waitFor(() => expect(adapter.createBatch).toHaveBeenCalledTimes(1));
    const submittedValues = vi.mocked(adapter.createBatch).mock.calls[0]?.[0] ?? {};
    expect(submittedValues).toEqual(
      expect.objectContaining({
        is_upgrade: "true",
        cover_revision: "D",
        upgrade_sheet_codes: "001~003",
      }),
    );
    expect(JSON.parse(String(submittedValues.upgrade_entries))).toEqual([
      { revision: "B", sheet_codes: "001~003", is_added: false },
      { revision: "D", sheet_codes: "021~024", is_added: true },
    ]);
  });

  it("maps 422 param errors into field and form messages", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A01.dwg",
          status: "ok",
          missingFonts: [],
          detectedStyleCount: 12,
          missingStyleCount: 0,
          fontReplacementApplied: false,
          replacementFont: null,
          replacementFonts: {},
          replacedStyleCount: 0,
          verifyAfterReplace: null,
          fontReplacementIncomplete: false,
          errors: [],
        },
      ],
      replacementOptions: [],
      requiresConfirmation: false,
    });
    adapter.createBatch = vi.fn().mockRejectedValue({
      status: 422,
      detail: {
        upload_errors: {
          files: ["only .dwg files are allowed"],
        },
        param_errors: {
          album_title_cn: ["required"],
        },
      },
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    expect(await screen.findByText("A01.dwg")).toBeInTheDocument();
    await user.type(screen.getByLabelText("图册名称（中文）"), "示例图册");
    await user.type(screen.getByLabelText("子项名称（中文）"), "反应堆厂房");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    await waitFor(() => {
      expect(screen.getByText("only .dwg files are allowed")).toBeInTheDocument();
      expect(screen.getByText("required")).toBeInTheDocument();
    });
  });

  it("preflights fonts immediately after upload and keeps the searching action clickable while waiting", async () => {
    const adapter = createAdapter();
    let resolvePreflight!: (value: FontPreflightResult) => void;
    adapter.preflightFonts = vi.fn().mockImplementation(
      () =>
        new Promise<FontPreflightResult>((resolve) => {
          resolvePreflight = resolve;
        }),
    );

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    expect(await screen.findByText("A01.dwg")).toBeInTheDocument();
    await waitFor(() => {
      expect(adapter.preflightFonts).toHaveBeenCalledWith([
        expect.objectContaining({ name: "A01.dwg" }),
      ]);
    });
    expect(screen.getByRole("button", { name: "正在执行字体搜索..." })).toBeEnabled();

    resolvePreflight({
      files: [
        {
          filename: "A01.dwg",
          status: "ok",
          missingFonts: [],
          detectedStyleCount: 12,
          missingStyleCount: 0,
          fontReplacementApplied: false,
          replacementFont: null,
          replacementFonts: {},
          replacedStyleCount: 0,
          verifyAfterReplace: null,
          fontReplacementIncomplete: false,
          errors: [],
        },
      ],
      replacementOptions: [],
      replacementOptionsByKind: {},
      defaultReplacementFont: null,
      defaultReplacementFonts: {},
      requiresConfirmation: false,
    });

    await screen.findByRole("button", { name: "创建交付任务" });
  });

  it("continues submit automatically after the user clicks create during upload-time font preflight", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    let resolvePreflight!: (value: FontPreflightResult) => void;
    adapter.preflightFonts = vi.fn().mockImplementation(
      () =>
        new Promise<FontPreflightResult>((resolve) => {
          resolvePreflight = resolve;
        }),
    );
    adapter.createBatch = vi.fn().mockResolvedValue({
      batchId: "batch-deliverable-font-waiting",
      jobs: [],
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    expect(await screen.findByText("A01.dwg")).toBeInTheDocument();
    await waitFor(() => {
      expect(adapter.preflightFonts).toHaveBeenCalledWith([
        expect.objectContaining({ name: "A01.dwg" }),
      ]);
    });

    await user.type(screen.getByLabelText("图册名称（中文）"), "示例图册");
    await user.type(screen.getByLabelText("子项名称（中文）"), "反应堆厂房");
    await user.click(screen.getByRole("button", { name: "正在执行字体搜索..." }));

    expect(adapter.createBatch).not.toHaveBeenCalled();

    resolvePreflight({
      files: [
        {
          filename: "A01.dwg",
          status: "ok",
          missingFonts: [],
          detectedStyleCount: 12,
          missingStyleCount: 0,
          fontReplacementApplied: false,
          replacementFont: null,
          replacementFonts: {},
          replacedStyleCount: 0,
          verifyAfterReplace: null,
          fontReplacementIncomplete: false,
          errors: [],
        },
      ],
      replacementOptions: [],
      replacementOptionsByKind: {},
      defaultReplacementFont: null,
      defaultReplacementFonts: {},
      requiresConfirmation: false,
    });

    await waitFor(() => {
      expect(adapter.createBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          font_replace_policy: "none",
        }),
        expect.arrayContaining([expect.objectContaining({ name: "A01.dwg" })]),
        false,
      );
    });

    expect(adapter.preflightFonts).toHaveBeenCalledTimes(1);
  });

  it("submits font compatibility mode when the footer checkbox is enabled", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A01.dwg",
          status: "ok",
          missingFonts: [],
          detectedStyleCount: 12,
          missingStyleCount: 0,
          fontReplacementApplied: false,
          replacementFont: null,
          replacementFonts: {},
          replacedStyleCount: 0,
          verifyAfterReplace: null,
          fontReplacementIncomplete: false,
          errors: [],
        },
      ],
      replacementOptions: [],
      replacementOptionsByKind: {},
      defaultReplacementFont: null,
      defaultReplacementFonts: {},
      requiresConfirmation: false,
    });
    adapter.createBatch = vi.fn().mockResolvedValue({
      batchId: "batch-deliverable-font-compatibility",
      jobs: [],
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await screen.findByText("A01.dwg");
    await user.type(screen.getByLabelText(albumTitleLabel), "font-compatibility");
    await user.type(screen.getByLabelText(subitemNameLabel), "font-compatibility-subitem");
    await user.click(screen.getByLabelText("以字体兼容模式打印"));
    await user.click(screen.getByRole("button", { name: /创建交付任务/ }));

    await waitFor(() => {
      expect(adapter.createBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          font_replace_policy: "none",
          font_compatibility_mode: true,
        }),
        expect.arrayContaining([expect.objectContaining({ name: "A01.dwg" })]),
        false,
      );
    });
  });

  it("renders font compatibility mode between the font review and submit buttons", async () => {
    const adapter = createAdapter();

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await screen.findByText("A01.dwg");

    const reviewButton = screen.getByRole("button", { name: "查看字体替换" });
    const compatibilityToggle = screen.getByRole("checkbox", {
      name: "以字体兼容模式打印",
    });
    const submitButton = screen.getByRole("button", { name: "创建交付任务" });

    expect(
      reviewButton.compareDocumentPosition(compatibilityToggle) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      compatibilityToggle.compareDocumentPosition(submitButton) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("opens the font replacement review from cached upload preflight without another request", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue(
      createMissingShxFontPreflightResult("A06.dwg"),
    );
    adapter.createBatch = vi.fn();

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A06.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    expect(await screen.findByText("A06.dwg")).toBeInTheDocument();
    await screen.findByRole("button", { name: "创建交付任务" });

    await user.click(screen.getByRole("button", { name: "查看字体替换" }));

    const dialog = await screen.findByRole("dialog", { name: "字体替换管理" });
    expect(within(dialog).getByLabelText("替代字体")).toHaveValue("simplex.shx");
    expect(adapter.preflightFonts).toHaveBeenCalledTimes(1);
    expect(adapter.createBatch).not.toHaveBeenCalled();
  });

  it("waits for the upload-time font preflight promise when reviewing replacement settings", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    const adapter = createAdapter();
    let resolvePreflight!: (value: FontPreflightResult) => void;
    adapter.preflightFonts = vi.fn().mockImplementation(
      () =>
        new Promise<FontPreflightResult>((resolve) => {
          resolvePreflight = resolve;
        }),
    );

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A07.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    expect(await screen.findByText("A07.dwg")).toBeInTheDocument();
    await waitFor(() => expect(adapter.preflightFonts).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole("button", { name: "查看字体替换" }));
    resolvePreflight(createMissingShxFontPreflightResult("A07.dwg"));

    const dialog = await screen.findByRole("dialog", { name: "字体替换管理" });
    expect(within(dialog).getByLabelText("替代字体")).toHaveValue("simplex.shx");
    expect(adapter.preflightFonts).toHaveBeenCalledTimes(1);
  });

  it("saves manual font replacement defaults from the review dialog without creating a task", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue(
      createMissingShxFontPreflightResult("A08.dwg"),
    );
    adapter.createBatch = vi.fn();

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A08.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await screen.findByRole("button", { name: "创建交付任务" });
    await user.click(screen.getByRole("button", { name: "查看字体替换" }));

    const dialog = await screen.findByRole("dialog", { name: "字体替换管理" });
    await user.selectOptions(within(dialog).getByLabelText("替代字体"), "romans.shx");
    await user.click(within(dialog).getByRole("button", { name: "保存设置" }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "字体替换管理" })).not.toBeInTheDocument();
    });
    expect(window.localStorage.getItem("auto-fanban.font-replacement-overrides")).toBe(
      JSON.stringify({ shx: "romans.shx" }),
    );
    expect(adapter.createBatch).not.toHaveBeenCalled();
  });

  it("uses manual font replacement defaults before backend defaults when creating a task", async () => {
    window.localStorage.clear();
    window.localStorage.setItem(
      "auto-fanban.font-replacement-overrides",
      JSON.stringify({ shx: "romans.shx" }),
    );
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue(
      createMissingShxFontPreflightResult("A09.dwg", { shx: "simplex.shx" }),
    );

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A09.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText(albumTitleLabel), "manual-font-default");
    await user.type(screen.getByLabelText(subitemNameLabel), "manual-font-default-subitem");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    const dialog = await screen.findByRole("dialog", { name: "缺失字体处理" });
    expect(within(dialog).getByLabelText("替代字体")).toHaveValue("romans.shx");
  });

  it("falls back to backend defaults when manual font replacement defaults are not visible candidates", async () => {
    window.localStorage.clear();
    window.localStorage.setItem(
      "auto-fanban.font-replacement-overrides",
      JSON.stringify({ shx: "missing-local-only.shx" }),
    );
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue(
      createMissingShxFontPreflightResult("A11.dwg", { shx: "simplex.shx" }),
    );

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A11.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText(albumTitleLabel), "manual-font-missing");
    await user.type(screen.getByLabelText(subitemNameLabel), "manual-font-missing-subitem");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    const dialog = await screen.findByRole("dialog", { name: "缺失字体处理" });
    expect(within(dialog).getByLabelText("替代字体")).toHaveValue("simplex.shx");
  });

  it("shows remembered font replacement information when review finds no missing fonts", async () => {
    window.localStorage.clear();
    window.localStorage.setItem(
      "auto-fanban.font-replacement-overrides",
      JSON.stringify({ shx: "romans.shx" }),
    );
    window.localStorage.setItem(
      "auto-fanban.last-font-replacements",
      JSON.stringify({ ttf: "simsun.ttc" }),
    );
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue(createOkFontPreflightResult("A10.dwg"));

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A10.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await screen.findByRole("button", { name: "创建交付任务" });
    await user.click(screen.getByRole("button", { name: "查看字体替换" }));

    const dialog = await screen.findByRole("dialog", { name: "字体替换管理" });
    expect(within(dialog).getByText("当前文件未检测到缺失字体。")).toBeInTheDocument();
    expect(within(dialog).getByText("手动默认设置")).toBeInTheDocument();
    expect(within(dialog).getByText("SHX：romans.shx")).toBeInTheDocument();
    expect(within(dialog).getByText("上次成功提交记忆")).toBeInTheDocument();
    expect(within(dialog).getByText("TrueType：simsun.ttc")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("替代字体")).not.toBeInTheDocument();
  });

  it("submits split-only without document parameters", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue(createOkFontPreflightResult());
    adapter.createSplitOnlyBatch = vi.fn().mockResolvedValue({
      batchId: "batch-split-only-1",
      jobs: [],
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "20261RS-JGS65.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.click(screen.getByRole("button", { name: "仅拆图" }));
    await user.click(screen.getByRole("button", { name: "创建仅拆图任务" }));

    await waitFor(() => {
      expect(adapter.createSplitOnlyBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          project_no: "2026",
          font_replace_policy: "none",
        }),
        expect.arrayContaining([expect.objectContaining({ name: "20261RS-JGS65.dwg" })]),
      );
    });
    expect(adapter.createBatch).not.toHaveBeenCalled();
  });

  it("preflights fonts before direct deliverable submit and proceeds immediately when all files are ok", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A01.dwg",
          status: "ok",
          missingFonts: [],
          detectedStyleCount: 12,
          missingStyleCount: 0,
          fontReplacementApplied: false,
          replacementFont: null,
          replacedStyleCount: 0,
          errors: [],
        },
      ],
      replacementOptions: [],
      requiresConfirmation: false,
    });
    adapter.createBatch = vi.fn().mockResolvedValue({
      batchId: "batch-deliverable-font-ok",
      jobs: [],
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    expect(await screen.findByText("A01.dwg")).toBeInTheDocument();
    await user.type(screen.getByLabelText("图册名称（中文）"), "示例图册");
    await user.type(screen.getByLabelText("子项名称（中文）"), "反应堆厂房");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    await waitFor(() => {
      expect(adapter.preflightFonts).toHaveBeenCalledWith([
        expect.objectContaining({ name: "A01.dwg" }),
      ]);
      expect(adapter.createBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          font_replace_policy: "none",
        }),
        expect.arrayContaining([expect.objectContaining({ name: "A01.dwg" })]),
        false,
      );
    });

    expect(
      vi.mocked(adapter.preflightFonts).mock.invocationCallOrder[0],
    ).toBeLessThan(vi.mocked(adapter.createBatch).mock.invocationCallOrder[0] ?? Number.POSITIVE_INFINITY);
  });

  it("renders the IED plan toggle as checked by default and submits a boolean true", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A01.dwg",
          status: "ok",
          missingFonts: [],
          detectedStyleCount: 12,
          missingStyleCount: 0,
          fontReplacementApplied: false,
          replacementFont: null,
          replacementFonts: {},
          replacedStyleCount: 0,
          verifyAfterReplace: null,
          fontReplacementIncomplete: false,
          errors: [],
        },
      ],
      replacementOptions: [],
      replacementOptionsByKind: {},
      defaultReplacementFont: null,
      defaultReplacementFonts: {},
      requiresConfirmation: false,
    });
    adapter.createBatch = vi.fn().mockResolvedValue({
      batchId: "batch-deliverable-ied-default",
      jobs: [],
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schemaWithIedPlan}
      />,
    );

    expect(await screen.findByLabelText("包含 IED 计划")).toBeChecked();
    await user.type(screen.getByLabelText(albumTitleLabel), "ied-plan-default");
    await user.type(screen.getByLabelText(subitemNameLabel), "ied-plan-default-subitem");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    await waitFor(() => {
      expect(adapter.createBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          include_ied_plan: true,
        }),
        expect.arrayContaining([expect.objectContaining({ name: "A01.dwg" })]),
        false,
      );
    });

    const submittedValues = vi.mocked(adapter.createBatch).mock.calls[0]?.[0] ?? {};
    expect(submittedValues.include_ied_plan).toBe(true);
  });

  it("renders the IED plan toggle next to the IED section instead of the design file grid", async () => {
    const adapter = createAdapter();

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schemaWithIedPlanInDesignSection}
      />,
    );

    const toggle = await screen.findByLabelText("是否生成IED");
    const designSection = screen.getByRole("heading", { name: "设计文件" }).closest("section");
    const iedSection = screen.getByRole("heading", { name: "IED 基础信息" }).closest("section");

    expect(designSection).not.toBeNull();
    expect(iedSection).not.toBeNull();
    expect(within(designSection as HTMLElement).queryByLabelText("是否生成IED")).not.toBeInTheDocument();
    expect(within(iedSection as HTMLElement).getByLabelText("是否生成IED")).toBe(toggle);
  });

  it("submits a boolean false when the IED plan toggle is unchecked", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A01.dwg",
          status: "ok",
          missingFonts: [],
          detectedStyleCount: 12,
          missingStyleCount: 0,
          fontReplacementApplied: false,
          replacementFont: null,
          replacementFonts: {},
          replacedStyleCount: 0,
          verifyAfterReplace: null,
          fontReplacementIncomplete: false,
          errors: [],
        },
      ],
      replacementOptions: [],
      replacementOptionsByKind: {},
      defaultReplacementFont: null,
      defaultReplacementFonts: {},
      requiresConfirmation: false,
    });
    adapter.createBatch = vi.fn().mockResolvedValue({
      batchId: "batch-deliverable-ied-off",
      jobs: [],
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schemaWithIedPlan}
      />,
    );

    const includeIedPlan = await screen.findByLabelText("包含 IED 计划");
    expect(includeIedPlan).toBeChecked();
    await user.click(includeIedPlan);
    expect(includeIedPlan).not.toBeChecked();

    await user.type(screen.getByLabelText(albumTitleLabel), "ied-plan-off");
    await user.type(screen.getByLabelText(subitemNameLabel), "ied-plan-off-subitem");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    await waitFor(() => {
      expect(adapter.createBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          include_ied_plan: false,
        }),
        expect.arrayContaining([expect.objectContaining({ name: "A01.dwg" })]),
        false,
      );
    });

    const submittedValues = vi.mocked(adapter.createBatch).mock.calls[0]?.[0] ?? {};
    expect(submittedValues.include_ied_plan).toBe(false);
  });

  it("does not require IED-only fields when the IED plan toggle is unchecked", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A01.dwg",
          status: "ok",
          missingFonts: [],
          detectedStyleCount: 12,
          missingStyleCount: 0,
          fontReplacementApplied: false,
          replacementFont: null,
          replacementFonts: {},
          replacedStyleCount: 0,
          verifyAfterReplace: null,
          fontReplacementIncomplete: false,
          errors: [],
        },
      ],
      replacementOptions: [],
      replacementOptionsByKind: {},
      defaultReplacementFont: null,
      defaultReplacementFonts: {},
      requiresConfirmation: false,
    });
    adapter.createBatch = vi.fn().mockResolvedValue({
      batchId: "batch-deliverable-ied-off-required-fields",
      jobs: [],
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schemaWithRequiredIedPlanFields}
      />,
    );

    const includeIedPlan = await screen.findByLabelText("包含 IED 计划");
    await user.click(includeIedPlan);
    await user.type(screen.getByLabelText(albumTitleLabel), "ied-plan-off");
    await user.type(screen.getByLabelText(subitemNameLabel), "ied-plan-off-subitem");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    await waitFor(() => {
      expect(adapter.createBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          include_ied_plan: false,
        }),
        expect.arrayContaining([expect.objectContaining({ name: "A01.dwg" })]),
        false,
      );
    });
  });

  it("opens a missing-font confirmation dialog and submits with the chosen replacement font", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A01.dwg",
          status: "missing_fonts",
          missingFonts: [
            {
              styleName: "HZTXT",
              fontName: "missing.shx",
              bigfontName: "",
              kind: "shx",
              usedInBlock: true,
            },
          ],
          detectedStyleCount: 12,
          missingStyleCount: 1,
          fontReplacementApplied: false,
          replacementFont: null,
          replacedStyleCount: 0,
          errors: [],
        },
      ],
      replacementOptions: [
        {
          label: "simplex.shx (AutoCAD SHX)",
          value: "simplex.shx",
          family: "simplex",
          path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\simplex.shx",
          kind: "shx",
          source: "autocad_fonts",
        },
        {
          label: "Arial (TrueType) (arial.ttf)",
          value: "arial.ttf",
          family: "Arial",
          path: "C:\\Windows\\Fonts\\arial.ttf",
          kind: "ttf",
          source: "windows_fonts",
        },
      ],
      requiresConfirmation: true,
    });
    adapter.createBatch = vi.fn().mockResolvedValue({
      batchId: "batch-deliverable-font-replaced",
      jobs: [],
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    expect(await screen.findByText("A01.dwg")).toBeInTheDocument();
    await user.type(screen.getByLabelText("图册名称（中文）"), "示例图册");
    await user.type(screen.getByLabelText("子项名称（中文）"), "反应堆厂房");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    const dialog = await screen.findByRole("dialog", { name: "缺失字体处理" });
    expect(within(dialog).getByText("A01.dwg")).toBeInTheDocument();
    expect(within(dialog).getByText("HZTXT")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("option", { name: "simplex.shx (AutoCAD SHX)" }),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("option", { name: "Arial (TrueType) (arial.ttf)" }),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).getByText("对 SHX / 大字体缺失，候选会优先来自 AutoCAD Fonts 目录。"),
    ).toBeInTheDocument();
    expect(adapter.createBatch).not.toHaveBeenCalled();

    await user.selectOptions(within(dialog).getByLabelText("替代字体"), "simplex.shx");
    await user.click(within(dialog).getByRole("button", { name: "继续提交" }));

    await waitFor(() => {
      expect(adapter.createBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          font_replace_policy: "replace_missing",
          font_replacement_font: "simplex.shx",
        }),
        expect.arrayContaining([expect.objectContaining({ name: "A01.dwg" })]),
        false,
      );
    });
  });

  it("remembers the last successful replacement font and preselects it next time", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    const firstAdapter = createAdapter();
    firstAdapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A01.dwg",
          status: "missing_fonts",
          missingFonts: [
            {
              styleName: "HZTXT",
              fontName: "missing.shx",
              bigfontName: "",
              kind: "shx",
              usedInBlock: true,
            },
          ],
          detectedStyleCount: 18,
          missingStyleCount: 1,
          fontReplacementApplied: false,
          replacementFont: null,
          replacedStyleCount: 0,
          errors: [],
        },
      ],
      replacementOptions: [
        {
          label: "simplex.shx (AutoCAD SHX)",
          value: "simplex.shx",
          family: "simplex",
          path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\simplex.shx",
          kind: "shx",
          source: "autocad_fonts",
        },
        {
          label: "romans.shx (AutoCAD SHX)",
          value: "romans.shx",
          family: "romans",
          path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\romans.shx",
          kind: "shx",
          source: "autocad_fonts",
        },
      ],
      requiresConfirmation: true,
    });
    firstAdapter.createBatch = vi.fn().mockResolvedValue({
      batchId: "batch-deliverable-font-memory-1",
      jobs: [],
    });

    const { unmount } = render(
      <DeliverableWorkspace
        adapter={firstAdapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText(albumTitleLabel), "font-memory-first");
    await user.type(screen.getByLabelText(subitemNameLabel), "subitem-first");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    const firstDialog = await screen.findByRole("dialog", { name: "缺失字体处理" });
    await user.selectOptions(within(firstDialog).getByLabelText("替代字体"), "romans.shx");
    await user.click(within(firstDialog).getByRole("button", { name: "继续提交" }));

    await waitFor(() => {
      expect(firstAdapter.createBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          font_replace_policy: "replace_missing",
          font_replacement_font: "romans.shx",
        }),
        expect.arrayContaining([expect.objectContaining({ name: "A01.dwg" })]),
        false,
      );
    });

    unmount();

    const secondAdapter = createAdapter();
    secondAdapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A02.dwg",
          status: "missing_fonts",
          missingFonts: [
            {
              styleName: "HZTXT",
              fontName: "missing.shx",
              bigfontName: "",
              kind: "shx",
              usedInBlock: true,
            },
          ],
          detectedStyleCount: 18,
          missingStyleCount: 1,
          fontReplacementApplied: false,
          replacementFont: null,
          replacedStyleCount: 0,
          errors: [],
        },
      ],
      replacementOptions: [
        {
          label: "simplex.shx (AutoCAD SHX)",
          value: "simplex.shx",
          family: "simplex",
          path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\simplex.shx",
          kind: "shx",
          source: "autocad_fonts",
        },
        {
          label: "romans.shx (AutoCAD SHX)",
          value: "romans.shx",
          family: "romans",
          path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\romans.shx",
          kind: "shx",
          source: "autocad_fonts",
        },
      ],
      requiresConfirmation: true,
    });
    secondAdapter.createBatch = vi.fn().mockResolvedValue({
      batchId: "batch-deliverable-font-memory-2",
      jobs: [],
    });

    render(
      <DeliverableWorkspace
        adapter={secondAdapter}
        incomingFiles={[new File(["dwg"], "A02.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText(albumTitleLabel), "font-memory-second");
    await user.type(screen.getByLabelText(subitemNameLabel), "subitem-second");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    const secondDialog = await screen.findByRole("dialog", { name: "缺失字体处理" });
    expect(within(secondDialog).getByLabelText("替代字体")).toHaveValue("romans.shx");

    await user.click(within(secondDialog).getByRole("button", { name: "继续提交" }));

    await waitFor(() => {
      expect(secondAdapter.createBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          font_replace_policy: "replace_missing",
          font_replacement_font: "romans.shx",
        }),
        expect.arrayContaining([expect.objectContaining({ name: "A02.dwg" })]),
        false,
      );
    });
  });

  it("uses the remembered replacement font when the backend does not return a default replacement", async () => {
    window.localStorage.clear();
    window.localStorage.setItem("auto-fanban.last-font-replacement", "romans.shx");
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A03.dwg",
          status: "missing_fonts",
          missingFonts: [
            {
              styleName: "HZTXT",
              fontName: "missing.shx",
              bigfontName: "",
              kind: "shx",
              usedInBlock: true,
            },
          ],
          detectedStyleCount: 18,
          missingStyleCount: 1,
          fontReplacementApplied: false,
          replacementFont: null,
          replacedStyleCount: 0,
          errors: [],
        },
      ],
      replacementOptions: [
        {
          label: "tssdchn.shx (AutoCAD SHX)",
          value: "tssdchn.shx",
          family: "tssdchn",
          path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\tssdchn.shx",
          kind: "shx",
          source: "autocad_fonts",
        },
        {
          label: "romans.shx (AutoCAD SHX)",
          value: "romans.shx",
          family: "romans",
          path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\romans.shx",
          kind: "shx",
          source: "autocad_fonts",
        },
      ],
      requiresConfirmation: true,
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A03.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText(albumTitleLabel), "font-default-priority");
    await user.type(screen.getByLabelText(subitemNameLabel), "subitem-default-priority");
    await user.click(screen.getByRole("button", { name: /创建交付任务/ }));

    const dialog = await screen.findByRole("dialog", { name: /缺失字体处理/ });
    expect(within(dialog).getByLabelText(/替代字体/)).toHaveValue("romans.shx");
  });

  it("describes the replacement step as selecting fonts by kind", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A03.dwg",
          status: "missing_fonts",
          missingFonts: [
            {
              styleName: "HZTXT",
              fontName: "missing.shx",
              bigfontName: "",
              kind: "shx",
              usedInBlock: true,
            },
          ],
          detectedStyleCount: 18,
          missingStyleCount: 1,
          fontReplacementApplied: false,
          replacementFont: null,
          replacedStyleCount: 0,
          errors: [],
        },
      ],
      replacementOptions: [
        {
          label: "tssdchn.shx (AutoCAD SHX)",
          value: "tssdchn.shx",
          family: "tssdchn",
          path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\tssdchn.shx",
          kind: "shx",
          source: "autocad_fonts",
        },
      ],
      requiresConfirmation: true,
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A03.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText(albumTitleLabel), "font-kind-description");
    await user.type(screen.getByLabelText(subitemNameLabel), "subitem-kind-description");
    await user.click(screen.getByRole("button", { name: /创建交付任务/ }));

    const dialog = await screen.findByRole("dialog", { name: /缺失字体处理/ });
    expect(
      within(dialog).getByText("检测到当前批次存在缺失字体。请按缺失字体类型选择替代字体，确认后再继续正式提交。"),
    ).toBeInTheDocument();
  });

  it("auto-selects the only available replacement option when there is no explicit default or remembered value", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A04.dwg",
          status: "missing_fonts",
          missingFonts: [
            {
              styleName: "HZTXT",
              fontName: "missing.shx",
              bigfontName: "",
              kind: "shx",
              usedInBlock: true,
            },
          ],
          detectedStyleCount: 12,
          missingStyleCount: 1,
          fontReplacementApplied: false,
          replacementFont: null,
          replacedStyleCount: 0,
          errors: [],
        },
      ],
      replacementOptions: [
        {
          label: "simplex.shx (AutoCAD SHX)",
          value: "simplex.shx",
          family: "simplex",
          path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\simplex.shx",
          kind: "shx",
          source: "autocad_fonts",
        },
      ],
      requiresConfirmation: true,
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A04.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText(albumTitleLabel), "font-single-option");
    await user.type(screen.getByLabelText(subitemNameLabel), "subitem-single-option");
    await user.click(screen.getByRole("button", { name: /创建交付任务/ }));

    const dialog = await screen.findByRole("dialog", { name: /缺失字体处理/ });
    expect(within(dialog).getByLabelText(/替代字体/)).toHaveValue("simplex.shx");
  });

  it("shows an explicit error when continue submit is clicked without a valid replacement choice", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A01.dwg",
          status: "missing_fonts",
          missingFonts: [
            {
              styleName: "HZTXT",
              fontName: "missing.shx",
              bigfontName: "",
              kind: "shx",
              usedInBlock: true,
            },
          ],
          detectedStyleCount: 12,
          missingStyleCount: 1,
          fontReplacementApplied: false,
          replacementFont: null,
          replacedStyleCount: 0,
          errors: [],
        },
      ],
      replacementOptions: [
        {
          label: "simplex.shx (AutoCAD SHX)",
          value: "simplex.shx",
          family: "simplex",
          path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\simplex.shx",
          kind: "shx",
          source: "autocad_fonts",
        },
        {
          label: "romans.shx (AutoCAD SHX)",
          value: "romans.shx",
          family: "romans",
          path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\romans.shx",
          kind: "shx",
          source: "autocad_fonts",
        },
      ],
      requiresConfirmation: true,
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText(albumTitleLabel), "font-error-case");
    await user.type(screen.getByLabelText(subitemNameLabel), "subitem-error");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    const dialog = await screen.findByRole("dialog", { name: "缺失字体处理" });
    const replacementSelect = within(dialog).getByLabelText("替代字体");
    await user.selectOptions(replacementSelect, "");

    const continueButton = within(dialog).getByRole("button", { name: "继续提交" });
    expect(continueButton).toBeEnabled();

    await user.click(continueButton);

    expect(within(dialog).getByText("请先选择SHX替代字体。")).toBeInTheDocument();
    expect(adapter.createBatch).not.toHaveBeenCalled();
  });

  it("groups replacement choices by kind and submits font_replacement_fonts for mixed missing fonts", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A05.dwg",
          status: "missing_fonts",
          missingFonts: [
            {
              styleName: "HZTXT",
              fontName: "missing.shx",
              bigfontName: "",
              kind: "shx",
              usedInBlock: true,
            },
            {
              styleName: "正文",
              fontName: "missing.ttf",
              bigfontName: "",
              kind: "ttf",
              usedInBlock: false,
            },
          ],
          detectedStyleCount: 24,
          missingStyleCount: 2,
          fontReplacementApplied: false,
          replacementFont: null,
          replacementFonts: {},
          replacedStyleCount: 0,
          verifyAfterReplace: null,
          fontReplacementIncomplete: false,
          errors: [],
        },
      ],
      replacementOptions: [],
      replacementOptionsByKind: {
        shx: [
          {
            label: "simplex.shx (AutoCAD SHX)",
            value: "simplex.shx",
            family: "simplex",
            path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\simplex.shx",
            kind: "shx",
            source: "autocad_fonts",
          },
        ],
        ttf: [
          {
            label: "SimSun (simsun.ttc)",
            value: "simsun.ttc",
            family: "SimSun",
            path: "C:\\Windows\\Fonts\\simsun.ttc",
            kind: "ttf",
            source: "windows_fonts",
          },
        ],
      },
      defaultReplacementFont: null,
      defaultReplacementFonts: {
        shx: "simplex.shx",
        ttf: "simsun.ttc",
      },
      requiresConfirmation: true,
    });
    adapter.createBatch = vi.fn().mockResolvedValue({
      batchId: "batch-deliverable-font-kinds",
      jobs: [],
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A05.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText(albumTitleLabel), "font-kind-grouping");
    await user.type(screen.getByLabelText(subitemNameLabel), "font-kind-grouping-subitem");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    const dialog = await screen.findByRole("dialog", { name: "缺失字体处理" });
    expect(within(dialog).getByText("HZTXT")).toBeInTheDocument();
    expect(within(dialog).getByText("正文")).toBeInTheDocument();
    expect(within(dialog).getByText("是否在块中使用：是")).toBeInTheDocument();
    expect(within(dialog).getByText("是否在块中使用：否")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("SHX 替代字体")).toHaveValue("simplex.shx");
    expect(within(dialog).getByLabelText("TrueType 替代字体")).toHaveValue("simsun.ttc");

    await user.click(within(dialog).getByRole("button", { name: "继续提交" }));

    await waitFor(() => {
      expect(adapter.createBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          font_replace_policy: "replace_missing",
          font_replacement_fonts: {
            shx: "simplex.shx",
            ttf: "simsun.ttc",
          },
        }),
        expect.arrayContaining([expect.objectContaining({ name: "A05.dwg" })]),
        false,
      );
    });

    const submittedValues = (adapter.createBatch as ReturnType<typeof vi.fn>).mock.calls[0]?.[0];
    expect(submittedValues).not.toHaveProperty("font_replacement_font");
  });

  it("blocks final submit and shows file-level errors when preflight reports failed files", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A01.dwg",
          status: "failed",
          missingFonts: [],
          detectedStyleCount: 0,
          missingStyleCount: 0,
          fontReplacementApplied: false,
          replacementFont: null,
          replacedStyleCount: 0,
          errors: ["A01.dwg：字体预检失败"],
        },
      ],
      replacementOptions: [],
      requiresConfirmation: false,
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText("图册名称（中文）"), "示例图册");
    await user.type(screen.getByLabelText("子项名称（中文）"), "反应堆厂房");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    expect(await screen.findByText("A01.dwg：字体预检失败")).toBeInTheDocument();
    expect(adapter.createBatch).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "缺失字体处理" })).not.toBeInTheDocument();
  });

  it("preserves the draft when the modal closes and reopens", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    const onClose = vi.fn();
    const { rerender } = render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={onClose}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText("图册名称（中文）"), "草稿图册");
    await user.click(screen.getByRole("button", { name: "关闭任务配置" }));
    expect(onClose).toHaveBeenCalledTimes(1);

    rerender(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[]}
        isOpen={false}
        onBatchCreated={vi.fn()}
        onClose={onClose}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    rerender(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={onClose}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    expect(await screen.findByDisplayValue("草稿图册")).toBeInTheDocument();
    expect(screen.getByText("A01.dwg")).toBeInTheDocument();
  });

  it("reports no deliverable draft synchronously after successful submit before closing", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    const onDraftAvailabilityChange = vi.fn();
    adapter.preflightFonts = vi.fn().mockResolvedValue(createOkFontPreflightResult("A01.dwg"));
    adapter.createBatch = vi.fn().mockResolvedValue({
      batchId: "batch-draft-cleared",
      jobs: [],
    });

    function ClosingHarness() {
      const [open, setOpen] = useState(true);

      return open ? (
        <DeliverableWorkspace
          adapter={adapter}
          incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
          isOpen
          onBatchCreated={vi.fn()}
          onClose={() => setOpen(false)}
          onDraftAvailabilityChange={onDraftAvailabilityChange}
          schema={schema}
        />
      ) : null;
    }

    render(<ClosingHarness />);

    await screen.findByText("A01.dwg");
    await user.type(screen.getByLabelText(albumTitleLabel), "submitted-draft");
    await user.type(screen.getByLabelText(subitemNameLabel), "submitted-subitem");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    await waitFor(() => expect(adapter.createBatch).toHaveBeenCalledTimes(1));
    expect(onDraftAvailabilityChange).toHaveBeenLastCalledWith(false);
  });

  it("defaults IED dates to today without rendering a shortcut button", async () => {
    const adapter = createAdapter();

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    const today = new Date().toISOString().slice(0, 10);
    await waitFor(() => expect(screen.getByLabelText("编制日期")).toHaveValue(today));
    expect(screen.queryByRole("button", { name: /当日/ })).not.toBeInTheDocument();
  });

  it("keeps entered upgrade codes while toggling and does not repeat legacy fields in advanced options", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    expect(screen.queryByLabelText("升版起始号")).not.toBeInTheDocument();
    const upgradeBlock = screen.getByTestId("upgrade-config-section");
    const toggle = within(upgradeBlock).getByRole("button", { name: isUpgradeLabel });
    expect(toggle).toHaveAttribute("aria-pressed", "false");

    await user.click(toggle);
    const codesInput = within(upgradeBlock).getByLabelText(upgradeSheetCodesLabel);
    await user.type(codesInput, "001、003、005~009");
    await user.click(toggle);
    expect(screen.queryByLabelText(upgradeSheetCodesLabel)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "展开高级选项" }));
    expect(screen.queryByLabelText("升版起始号")).not.toBeInTheDocument();

    await user.click(toggle);
    expect(within(upgradeBlock).getByLabelText(upgradeSheetCodesLabel)).toHaveValue(
      "001、003、005~009",
    );
  });

  it("submits only the new upgrade fields and clears upgrade-related values when upgrade is disabled", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "2016-A01.dwg",
          status: "ok",
          missingFonts: [],
          detectedStyleCount: 12,
          missingStyleCount: 0,
          fontReplacementApplied: false,
          replacementFont: null,
          replacedStyleCount: 0,
          errors: [],
        },
      ],
      replacementOptions: [],
      requiresConfirmation: false,
    });
    adapter.createBatch = vi.fn().mockResolvedValue({
      batchId: "batch-deliverable-1",
      jobs: [],
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "2016-A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText("图册名称（中文）"), "示例图册");
    await user.type(screen.getByLabelText("子项名称（中文）"), "反应堆厂房");
    await user.click(screen.getByRole("button", { name: "同线宽" }));

    const upgradeBlock = screen.getByTestId("upgrade-config-section");
    const toggle = within(upgradeBlock).getByRole("button", { name: isUpgradeLabel });
    await user.click(toggle);
    await user.type(within(upgradeBlock).getByLabelText(coverRevisionLabel), "B");
    await user.type(within(upgradeBlock).getByLabelText(upgradeSheetCodesLabel), "001、003");
    await user.click(toggle);
    await user.click(screen.getByRole("button", { name: "纠错" }));
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    await waitFor(() => {
      expect(adapter.createBatch).toHaveBeenCalledTimes(1);
      expect(adapter.createBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          project_no: "2016",
          plot_style_key: "same_width",
          is_upgrade: "false",
          cover_revision: "",
          upgrade_sheet_codes: "",
          upgrade_entries: "[]",
        }),
        expect.arrayContaining([expect.objectContaining({ name: "2016-A01.dwg" })]),
        true,
      );

      const submittedValues = vi.mocked(adapter.createBatch).mock.calls[0]?.[0] ?? {};
      expect(submittedValues).not.toHaveProperty("upgrade_start_seq");
      expect(submittedValues).not.toHaveProperty("upgrade_end_seq");
      expect(submittedValues).not.toHaveProperty("upgrade_revision");
      expect(submittedValues).not.toHaveProperty("upgrade_note_text");
      expect(adapter.createAuditCheck).not.toHaveBeenCalled();
    });
  });

  it("submits through replace-plus-deliverable when a pending replace flow is attached", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.preflightFonts = vi.fn().mockResolvedValue({
      files: [
        {
          filename: "20261NH-JGS51-B合并版.dwg",
          status: "missing_fonts",
          missingFonts: [
            {
              styleName: "HZTXT",
              fontName: "missing.shx",
              bigfontName: "",
              kind: "shx",
              usedInBlock: true,
            },
          ],
          detectedStyleCount: 32,
          missingStyleCount: 1,
          fontReplacementApplied: false,
          replacementFont: null,
          replacedStyleCount: 0,
          errors: [],
        },
      ],
      replacementOptions: [
        {
          label: "simplex.shx (AutoCAD SHX)",
          value: "simplex.shx",
          family: "simplex",
          path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\simplex.shx",
          kind: "shx",
          source: "autocad_fonts",
        },
        {
          label: "Arial (TrueType) (arial.ttf)",
          value: "arial.ttf",
          family: "Arial",
          path: "C:\\Windows\\Fonts\\arial.ttf",
          kind: "ttf",
          source: "windows_fonts",
        },
      ],
      requiresConfirmation: true,
    });
    adapter.createAuditReplace = vi.fn().mockResolvedValue({
      batchId: "batch-replace-group-1",
      jobs: [],
    });

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "20261NH-JGS51-B合并版.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        pendingReplaceConfig={{
          sourceProjectNo: "1916",
          sourceIslandNo: "3",
          targetProjectNo: "2016",
          targetIslandNo: "1",
          runDeliverable: true,
        }}
        schema={schema}
      />,
    );

    expect(await screen.findByText("20261NH-JGS51-B合并版.dwg")).toBeInTheDocument();
    await user.type(screen.getByLabelText("图册名称（中文）"), "翻版后出图图册");
    await user.type(screen.getByLabelText("子项名称（中文）"), "反应堆厂房");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));
    const dialog = await screen.findByRole("dialog", { name: "缺失字体处理" });
    expect(
      within(dialog).getByRole("option", { name: "simplex.shx (AutoCAD SHX)" }),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("option", { name: "Arial (TrueType) (arial.ttf)" }),
    ).not.toBeInTheDocument();
    await user.selectOptions(within(dialog).getByLabelText("替代字体"), "simplex.shx");
    await user.click(within(dialog).getByRole("button", { name: "继续提交" }));

    await waitFor(() => {
      expect(adapter.createAuditReplace).toHaveBeenCalledWith({
        sourceProjectNo: "1916",
        sourceIslandNo: "3",
        targetProjectNo: "2016",
        targetIslandNo: "1",
        files: expect.arrayContaining([
          expect.objectContaining({ name: "20261NH-JGS51-B合并版.dwg" }),
        ]),
        runDeliverable: true,
        deliverableParams: expect.objectContaining({
          album_title_cn: "翻版后出图图册",
          subitem_name: "反应堆厂房",
          font_replace_policy: "replace_missing",
          font_replacement_font: "simplex.shx",
        }),
      });
      expect(adapter.createBatch).not.toHaveBeenCalled();
    });
  });
});
