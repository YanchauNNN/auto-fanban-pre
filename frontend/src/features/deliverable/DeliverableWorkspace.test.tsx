import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DeliverableWorkspace } from "./DeliverableWorkspace";
import type { ApiAdapter, FormSchema } from "../../platform/api/types";

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

function createAdapter(): ApiAdapter {
  return {
    getHealth: vi.fn(),
    getFormSchema: vi.fn(),
    createAuditCheck: vi.fn(),
    createAuditReplace: vi.fn(),
    listJobs: vi.fn(),
    getJobDetail: vi.fn(),
    createBatch: vi.fn(),
  };
}

describe("DeliverableWorkspace", () => {
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
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
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
          sourceProjectNo: "2026",
          targetProjectNo: "2016",
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
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
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
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
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
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
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

  it("maps 422 param errors into field and form messages", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
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

    await user.type(screen.getByLabelText("图册名称（中文）"), "示例图册");
    await user.type(screen.getByLabelText("子项名称（中文）"), "反应堆厂房");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    await waitFor(() => {
      expect(screen.getByText("only .dwg files are allowed")).toBeInTheDocument();
      expect(screen.getByText("required")).toBeInTheDocument();
    });
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

  it("defaults IED dates to today without rendering a shortcut button", () => {
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

    const today = new Date().toISOString().slice(0, 10);
    expect(screen.getByLabelText("编制日期")).toHaveValue(today);
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
          sourceProjectNo: "2026",
          targetProjectNo: "2016",
          runDeliverable: true,
        }}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText("图册名称（中文）"), "翻版后出图图册");
    await user.type(screen.getByLabelText("子项名称（中文）"), "反应堆厂房");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    await waitFor(() => {
      expect(adapter.createAuditReplace).toHaveBeenCalledWith({
        sourceProjectNo: "2026",
        targetProjectNo: "2016",
        files: expect.arrayContaining([
          expect.objectContaining({ name: "20261NH-JGS51-B合并版.dwg" }),
        ]),
        runDeliverable: true,
        deliverableParams: expect.objectContaining({
          album_title_cn: "翻版后出图图册",
          subitem_name: "反应堆厂房",
        }),
      });
      expect(adapter.createBatch).not.toHaveBeenCalled();
    });
  });
});
