import { render, screen, waitFor } from "@testing-library/react";
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
          key: "cover_revision",
          label: "封面版次",
          type: "text",
          required: false,
          requiredWhen: null,
          defaultValue: "",
          description: "封面版次",
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
    listJobs: vi.fn(),
    getJobDetail: vi.fn(),
    createBatch: vi.fn(),
  };
}

describe("DeliverableWorkspace", () => {
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

  it("fills inferred project number and keeps full project/cover menus visible while typing", async () => {
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

  it("shows schema helper copy and defaults plot style to red_wider", () => {
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

  it("submits plot_style_key and runAuditCheck together when audit is enabled", async () => {
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
    await user.click(screen.getByRole("button", { name: "纠错" }));
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    await waitFor(() => {
      expect(adapter.createBatch).toHaveBeenCalledTimes(1);
      expect(adapter.createBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          project_no: "2016",
          plot_style_key: "same_width",
        }),
        expect.arrayContaining([expect.objectContaining({ name: "2016-A01.dwg" })]),
        true,
      );
      expect(adapter.createAuditCheck).not.toHaveBeenCalled();
    });
  });
});
