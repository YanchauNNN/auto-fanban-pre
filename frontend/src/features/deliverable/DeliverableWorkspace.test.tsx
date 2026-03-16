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
          description: "项目号",
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
          description: "编制日期",
          options: [],
        },
      ],
    },
  ],
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
  it("fills inferred project number into the project field and uses a single combobox for select fields", async () => {
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

    expect(await screen.findByDisplayValue("2016")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "项目号" })).toHaveValue("2016");
    expect(screen.getByRole("combobox", { name: "封面模板" })).toHaveValue("通用");
    expect(screen.queryByLabelText("项目号筛选")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("封面模板筛选")).not.toBeInTheDocument();
  });

  it("uses the revised field helper copy from schema descriptions", () => {
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
  });

  it("maps 422 param errors into field and form level messages inside the modal", async () => {
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

  it("preserves the draft when the modal is closed and reopened", async () => {
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

  it("defaults IED signature dates to today without rendering a shortcut button", () => {
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
    expect(screen.queryByRole("button", { name: "编制日期 当日" })).not.toBeInTheDocument();
  });

  it("opens the replace modal with inferred source project number and allows filling target from recommendations", async () => {
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

    await user.click(screen.getByRole("button", { name: "翻版" }));

    expect(await screen.findByRole("dialog", { name: "翻版配置" })).toBeInTheDocument();
    expect(screen.getByLabelText("原始项目号")).toHaveValue("2016");

    await user.click(screen.getByRole("button", { name: "将 2020 填入目标项目号" }));

    expect(screen.getByLabelText("目标项目号")).toHaveValue("2020");
  });

  it("uses audit replace project options as additional recommendations in the replace modal", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    const replaceSchema = {
      ...schema,
      auditReplaceProjectOptions: ["2016", "2035"],
      sections: schema.sections.map((section) =>
        section.id === "project"
          ? {
              ...section,
              fields: section.fields.map((field) =>
                field.key === "project_no"
                  ? {
                      ...field,
                      options: ["2016"],
                    }
                  : field,
              ),
            }
          : section,
      ),
    } as const;

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "2016-A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={replaceSchema}
      />,
    );

    await user.click(screen.getByRole("button", { name: "翻版" }));

    await waitFor(() => {
      expect(screen.getAllByRole("dialog")).toHaveLength(2);
    });
    expect(
      screen
        .getAllByRole("button")
        .some((button) => button.textContent?.includes("2035")),
    ).toBe(true);
  });

  it("keeps the deliverable modal focused on delivery, audit and replace controls", () => {
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

    expect(screen.getByRole("button", { name: "纠错" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "翻版" })).toBeInTheDocument();
  });

  it("can queue an additional audit check job from the deliverable modal", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.createBatch = vi.fn().mockResolvedValue({
      batchId: "batch-deliverable-1",
      jobs: [],
    });
    adapter.createAuditCheck = vi.fn().mockResolvedValue({
      batchId: "batch-audit-1",
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
    const auditButton = screen.getByRole("button", { name: "纠错" });
    await user.click(auditButton);

    expect(auditButton).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    await waitFor(() => {
      expect(adapter.createBatch).toHaveBeenCalledTimes(1);
      expect(adapter.createAuditCheck).toHaveBeenCalledWith(
        "2016",
        expect.arrayContaining([expect.objectContaining({ name: "2016-A01.dwg" })]),
        "batch-deliverable-1",
      );
    });
  });

  it("keeps project number and cover template menus fully visible while typing", async () => {
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
    await user.clear(projectNo);
    await user.type(projectNo, "zzz");

    expect(await screen.findByRole("option", { name: "2016" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "1818" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "2020" })).toBeInTheDocument();

    const coverVariant = screen.getByRole("combobox", { name: "封面模板" });
    await user.clear(coverVariant);
    await user.type(coverVariant, "zzz");
    await user.click(coverVariant);

    expect(await screen.findByRole("option", { name: "通用" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "压力容器" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "核安全设备" })).toBeInTheDocument();
  });
});
