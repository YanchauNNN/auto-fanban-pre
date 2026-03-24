import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReplaceWorkspace } from "./ReplaceWorkspace";
import type { ApiAdapter, FormSchema } from "../../platform/api/types";

const schema: FormSchema = {
  schemaVersion: "frontend-form@1",
  uploadLimits: {
    maxFiles: 50,
    allowedExts: [".dwg"],
    maxTotalMb: 2048,
  },
  sections: [],
  auditReplaceProjectOptions: ["2026", "2016", "1818"],
};

function createAdapter(): ApiAdapter {
  return {
    getHealth: vi.fn(),
    getFormSchema: vi.fn(),
    createBatch: vi.fn(),
    createAuditCheck: vi.fn(),
    createAuditReplace: vi.fn(),
    listJobs: vi.fn(),
    getJobDetail: vi.fn(),
  };
}

describe("ReplaceWorkspace", () => {
  it("infers the source project number from uploaded dwg names", async () => {
    const user = userEvent.setup();

    render(
      <ReplaceWorkspace
        adapter={createAdapter()}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onContinueToDeliverable={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.upload(
      screen.getByLabelText("选择翻版 DWG 文件"),
      new File(["dwg"], "20261NH-JGS51-B合并版.dwg", { type: "application/acad" }),
    );

    expect(screen.getByLabelText("原始项目号")).toHaveValue("2026");
  });

  it("submits replace-only jobs through the replace endpoint", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    const onBatchCreated = vi.fn();
    const onClose = vi.fn();
    adapter.createAuditReplace = vi.fn().mockResolvedValue({
      batchId: "batch-replace-1",
      jobs: [],
    });

    render(
      <ReplaceWorkspace
        adapter={adapter}
        isOpen
        onBatchCreated={onBatchCreated}
        onClose={onClose}
        onContinueToDeliverable={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText("原始项目号"), "2026");
    await user.type(screen.getByLabelText("目标项目号"), "2016");
    await user.upload(
      screen.getByLabelText("选择翻版 DWG 文件"),
      new File(["dwg"], "20261NH-JGS51-B合并版.dwg", { type: "application/acad" }),
    );
    await user.click(screen.getByRole("button", { name: "开始翻版" }));

    await waitFor(() => {
      expect(adapter.createAuditReplace).toHaveBeenCalledWith({
        sourceProjectNo: "2026",
        targetProjectNo: "2016",
        files: expect.any(Array),
        runDeliverable: false,
      });
    });
    expect(onBatchCreated).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("hands off to the existing deliverable flow when sync mode is selected", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    const onContinueToDeliverable = vi.fn();

    render(
      <ReplaceWorkspace
        adapter={adapter}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onContinueToDeliverable={onContinueToDeliverable}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.click(screen.getByRole("button", { name: "同步出图和翻版" }));
    await user.type(screen.getByLabelText("原始项目号"), "2026");
    await user.type(screen.getByLabelText("目标项目号"), "2016");
    await user.upload(
      screen.getByLabelText("选择翻版 DWG 文件"),
      new File(["dwg"], "20261NH-JGS51-B合并版.dwg", { type: "application/acad" }),
    );
    await user.click(screen.getByRole("button", { name: "出图" }));

    expect(adapter.createAuditReplace).not.toHaveBeenCalled();
    expect(onContinueToDeliverable).toHaveBeenCalledWith({
      files: expect.any(Array),
      replaceConfig: {
        sourceProjectNo: "2026",
        targetProjectNo: "2016",
        runDeliverable: true,
      },
    });
  });
});
