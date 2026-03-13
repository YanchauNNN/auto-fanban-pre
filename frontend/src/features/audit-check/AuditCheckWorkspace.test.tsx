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
  sections: [],
  auditReplaceProjectOptions: ["2026", "1818", "2035"],
} as const;

function createAdapter(): ApiAdapter {
  return {
    getHealth: vi.fn(),
    getFormSchema: vi.fn(),
    createBatch: vi.fn(),
    createAuditCheck: vi.fn(),
    listJobs: vi.fn(),
    getJobDetail: vi.fn(),
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
