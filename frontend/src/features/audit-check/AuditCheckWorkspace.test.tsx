import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AuditCheckWorkspace } from "./AuditCheckWorkspace";
import type { ApiAdapter } from "../../platform/api/types";

const schema = {
  schemaVersion: "frontend-form@1",
  uploadLimits: {
    maxFiles: 50,
    allowedExts: [".dwg"],
    maxTotalMb: 2048,
  },
  sections: [
    {
      id: "project",
      title: "project",
      fields: [
        {
          key: "unit_no",
          label: "unit_no",
          type: "select",
          required: false,
          requiredWhen: null,
          defaultValue: "",
          description: "",
          options: ["1", "2", "3", "4", "5", "6"],
        },
      ],
    },
  ],
  auditReplaceProjectOptions: ["2026", "1818", "2035"],
} as const;

function createAdapter(): ApiAdapter {
  return {
    ping: vi.fn(),
    getHealth: vi.fn(),
    getFormSchema: vi.fn(),
    preflightFonts: vi.fn(),
    createBatch: vi.fn(),
    createAuditCheck: vi.fn(),
    createAuditReplace: vi.fn(),
    createChangePageExtract: vi.fn(),
    rememberAuditReplaceFactoryCodes: vi.fn().mockResolvedValue({ factoryCodes: [] }),
    createSplitOnlyBatch: vi.fn(),
    listJobs: vi.fn(),
    getJobsActivity: vi.fn(),
    getJobDetail: vi.fn(),
    getAiState: vi.fn(),
    listAiConversations: vi.fn(),
    createAiConversation: vi.fn(),
    getAiConversation: vi.fn(),
    renameAiConversation: vi.fn(),
    sendAiMessage: vi.fn(),
    clearAiConversation: vi.fn(),
  };
}

describe("AuditCheckWorkspace", () => {
  it("renders a searchable project number combobox from audit replace options", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();

    render(
      <AuditCheckWorkspace
        adapter={adapter}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByRole("combobox", { name: "项目号" }), "20");

    expect(screen.getByRole("option", { name: "2026" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "2035" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "1818" })).not.toBeInTheDocument();
  });

  it("maps backend 422 project errors under the project number field", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.createAuditCheck = vi.fn().mockRejectedValue({
      status: 422,
      detail: {
        upload_errors: {},
        param_errors: {
          project_no: ["required_for_audit_check"],
        },
      },
    });

    render(
      <AuditCheckWorkspace
        adapter={adapter}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.upload(
      screen.getByLabelText("选择纠错 DWG 文件"),
      new File(["dwg"], "A01.dwg", { type: "application/acad" }),
    );
    await user.click(screen.getByRole("button", { name: "创建纠错任务" }));

    expect(await screen.findByText("required_for_audit_check")).toBeInTheDocument();
  });

  it("infers and submits unit number for audit checks", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.createAuditCheck = vi.fn().mockResolvedValue({
      batchId: "batch-audit-1",
      jobs: [],
    });

    const { container } = render(
      <AuditCheckWorkspace
        adapter={adapter}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.upload(
      screen.getByLabelText("选择纠错 DWG 文件"),
      new File(["dwg"], "20261NH-JGS51-B合并版.dwg", { type: "application/acad" }),
    );
    await user.click(screen.getByRole("button", { name: "2026" }));
    expect(await screen.findByLabelText("机组号")).toHaveValue("1");

    await user.click(screen.getByRole("button", { name: "创建纠错任务" }));

    await waitFor(() => {
      expect(adapter.createAuditCheck).toHaveBeenCalledWith(
        "2026",
        "1",
        expect.arrayContaining([
          expect.objectContaining({ name: "20261NH-JGS51-B合并版.dwg" }),
        ]),
      );
    });
  });

  it("allows manually entered unit numbers outside schema suggestions", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.createAuditCheck = vi.fn().mockResolvedValue({
      batchId: "batch-audit-1907-7",
      jobs: [],
    });

    const { container } = render(
      <AuditCheckWorkspace
        adapter={adapter}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(container.querySelector("#audit-project-no") as HTMLInputElement, "1907");
    await user.type(container.querySelector("#audit-unit-no") as HTMLInputElement, "7");
    await user.upload(
      container.querySelector('input[type="file"]') as HTMLInputElement,
      new File(["dwg"], "19077NH-JGS01.dwg", { type: "application/acad" }),
    );
    await user.click(container.querySelector('button[type="submit"]') as HTMLButtonElement);

    await waitFor(() => {
      expect(adapter.createAuditCheck).toHaveBeenCalledWith(
        "1907",
        "7",
        expect.arrayContaining([expect.objectContaining({ name: "19077NH-JGS01.dwg" })]),
      );
    });
  });

  it("fills project number from uploaded DWG filename without manual selection", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    const { container } = render(
      <AuditCheckWorkspace
        adapter={adapter}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(
      fileInput,
      new File(["dwg"], "20261RB-JGS11-校审图A版-2026.05.20.dwg", {
        type: "application/acad",
      }),
    );

    expect(container.querySelector("#audit-project-no")).toHaveValue("2026");
    expect(container.querySelector("#audit-unit-no")).toHaveValue("1");
  });

  it("preserves the audit draft after closing and reopening", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    const onClose = vi.fn();
    const { rerender } = render(
      <AuditCheckWorkspace
        adapter={adapter}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={onClose}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.upload(
      screen.getByLabelText("选择纠错 DWG 文件"),
      new File(["dwg"], "20261NH-JGS51-B合并版.dwg", { type: "application/acad" }),
    );
    await user.click(screen.getByRole("button", { name: "2026" }));
    await user.click(screen.getByRole("button", { name: "关闭纠错配置" }));

    expect(onClose).toHaveBeenCalledTimes(1);

    rerender(
      <AuditCheckWorkspace
        adapter={adapter}
        isOpen={false}
        onBatchCreated={vi.fn()}
        onClose={onClose}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    rerender(
      <AuditCheckWorkspace
        adapter={adapter}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={onClose}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    expect(await screen.findByDisplayValue("2026")).toBeInTheDocument();
    expect(screen.getByText("20261NH-JGS51-B合并版.dwg")).toBeInTheDocument();
  });

  it("submits audit check jobs and clears the draft after success", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.createAuditCheck = vi.fn().mockResolvedValue({
      batchId: "batch-audit-1",
      jobs: [],
    });
    const onBatchCreated = vi.fn();
    const onClose = vi.fn();

    render(
      <AuditCheckWorkspace
        adapter={adapter}
        isOpen
        onBatchCreated={onBatchCreated}
        onClose={onClose}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.upload(
      screen.getByLabelText("选择纠错 DWG 文件"),
      new File(["dwg"], "20261NH-JGS51-B合并版.dwg", { type: "application/acad" }),
    );
    await user.click(screen.getByRole("button", { name: "2026" }));
    await user.click(screen.getByRole("button", { name: "创建纠错任务" }));

    await waitFor(() => {
      expect(adapter.createAuditCheck).toHaveBeenCalledWith(
        "2026",
        "1",
        expect.arrayContaining([
          expect.objectContaining({ name: "20261NH-JGS51-B合并版.dwg" }),
        ]),
      );
    });

    expect(onBatchCreated).toHaveBeenCalledWith({
      batchId: "batch-audit-1",
      jobs: [],
    });
    expect(onClose).toHaveBeenCalled();
  });
});
