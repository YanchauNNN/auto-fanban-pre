import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
  auditReplaceProjectOptions: ["2026", "2016", "1916", "1818"],
};

function createAdapter(): ApiAdapter {
  return {
    getHealth: vi.fn(),
    getFormSchema: vi.fn(),
    preflightFonts: vi.fn(),
    createBatch: vi.fn(),
    createAuditCheck: vi.fn(),
    createAuditReplace: vi.fn(),
    createSplitOnlyBatch: vi.fn(),
    listJobs: vi.fn(),
    getJobDetail: vi.fn(),
  };
}

describe("ReplaceWorkspace", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("shows an active state for the selected replace mode", async () => {
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

    const replaceOnlyButton = screen.getByRole("button", { name: "仅翻版" });
    const replaceWithDeliverableButton = screen.getByRole("button", {
      name: "同步出图和翻版",
    });

    expect(replaceOnlyButton).toHaveAttribute("aria-pressed", "true");
    expect(replaceWithDeliverableButton).toHaveAttribute("aria-pressed", "false");

    await user.click(replaceWithDeliverableButton);

    expect(replaceOnlyButton).toHaveAttribute("aria-pressed", "false");
    expect(replaceWithDeliverableButton).toHaveAttribute("aria-pressed", "true");
  });

  it("restores the persisted replace draft after remounting", async () => {
    const user = userEvent.setup();
    const firstRender = render(
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

    await user.click(screen.getByRole("button", { name: "同步出图和翻版" }));
    await user.type(screen.getByLabelText("原始项目号"), "2016");
    await user.selectOptions(screen.getByLabelText("来源机组号"), "2");
    await user.type(screen.getByLabelText("目标项目号"), "1916");
    await user.selectOptions(screen.getByLabelText("目标岛号"), "3");

    firstRender.unmount();

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

    expect(screen.getByLabelText("原始项目号")).toHaveValue("2016");
    expect(screen.getByLabelText("来源机组号")).toHaveValue("2");
    expect(screen.getByLabelText("目标项目号")).toHaveValue("1916");
    expect(screen.getByLabelText("目标岛号")).toHaveValue("3");
    expect(screen.getByRole("button", { name: "同步出图和翻版" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("shows the target island selector only for 1916 and 2016 targets", async () => {
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

    expect(screen.queryByLabelText("目标岛号")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("目标项目号"), "1916");
    expect(screen.getByLabelText("目标岛号")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "3号岛" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "4号岛" })).toBeInTheDocument();

    await user.clear(screen.getByLabelText("目标项目号"));
    await user.type(screen.getByLabelText("目标项目号"), "1818");
    expect(screen.queryByLabelText("目标岛号")).not.toBeInTheDocument();
  });

  it("shows the source unit or island selector only for 1916 and 2016 sources", async () => {
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

    expect(screen.queryByLabelText("来源机组号")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("来源岛号")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("原始项目号"), "2016");
    expect(screen.getByLabelText("来源机组号")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "1号机组" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "2号机组" })).toBeInTheDocument();

    await user.clear(screen.getByLabelText("原始项目号"));
    await user.type(screen.getByLabelText("原始项目号"), "1916");
    expect(screen.getByLabelText("来源岛号")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "3号岛" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "4号岛" })).toBeInTheDocument();

    await user.clear(screen.getByLabelText("原始项目号"));
    await user.type(screen.getByLabelText("原始项目号"), "2026");
    expect(screen.queryByLabelText("来源机组号")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("来源岛号")).not.toBeInTheDocument();
  });

  it("clears the persisted replace draft after a successful submit", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.createAuditReplace = vi.fn().mockResolvedValue({
      batchId: "batch-replace-1",
      jobs: [],
    });

    const firstRender = render(
      <ReplaceWorkspace
        adapter={adapter}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onContinueToDeliverable={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText("原始项目号"), "2016");
    await user.selectOptions(screen.getByLabelText("来源机组号"), "2");
    await user.type(screen.getByLabelText("目标项目号"), "1916");
    await user.selectOptions(screen.getByLabelText("目标岛号"), "3");
    await user.upload(
      screen.getByLabelText("选择翻版 DWG 文件"),
      new File(["dwg"], "20261NH-JGS51-B合并版.dwg", { type: "application/acad" }),
    );
    await user.click(screen.getByRole("button", { name: "开始翻版" }));

    await waitFor(() => {
      expect(adapter.createAuditReplace).toHaveBeenCalledTimes(1);
    });

    firstRender.unmount();

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

    expect(screen.getByLabelText("原始项目号")).toHaveValue("");
    expect(screen.getByLabelText("目标项目号")).toHaveValue("");
    expect(screen.queryByLabelText("目标岛号")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "仅翻版" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

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

    await user.type(screen.getByLabelText("原始项目号"), "2016");
    await user.selectOptions(screen.getByLabelText("来源机组号"), "2");
    await user.type(screen.getByLabelText("目标项目号"), "1916");
    await user.selectOptions(screen.getByLabelText("目标岛号"), "3");
    await user.upload(
      screen.getByLabelText("选择翻版 DWG 文件"),
      new File(["dwg"], "20261NH-JGS51-B合并版.dwg", { type: "application/acad" }),
    );
    await user.click(screen.getByRole("button", { name: "开始翻版" }));

    await waitFor(() => {
      expect(adapter.createAuditReplace).toHaveBeenCalledWith({
        sourceProjectNo: "2016",
        sourceIslandNo: "2",
        targetProjectNo: "1916",
        targetIslandNo: "3",
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
    await user.type(screen.getByLabelText("原始项目号"), "2016");
    await user.selectOptions(screen.getByLabelText("来源机组号"), "1");
    await user.type(screen.getByLabelText("目标项目号"), "1916");
    await user.selectOptions(screen.getByLabelText("目标岛号"), "3");
    await user.upload(
      screen.getByLabelText("选择翻版 DWG 文件"),
      new File(["dwg"], "20261NH-JGS51-B合并版.dwg", { type: "application/acad" }),
    );
    await user.click(screen.getByRole("button", { name: "出图" }));

    expect(adapter.createAuditReplace).not.toHaveBeenCalled();
    expect(onContinueToDeliverable).toHaveBeenCalledWith({
      files: expect.any(Array),
      replaceConfig: {
        sourceProjectNo: "2016",
        sourceIslandNo: "1",
        targetProjectNo: "1916",
        targetIslandNo: "3",
        runDeliverable: true,
      },
    });
  });
});
