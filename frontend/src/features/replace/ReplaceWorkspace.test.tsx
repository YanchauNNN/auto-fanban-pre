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
  auditReplaceSourceUnitOptions: {
    "1916": [
      { value: "3", label: "3号机组/岛" },
      { value: "4", label: "4号机组/岛" },
    ],
    "2016": [
      { value: "1", label: "1号机组/岛" },
      { value: "2", label: "2号机组/岛" },
    ],
  },
  auditReplaceTargetUnitOptions: {
    "1916": [
      { value: "3", label: "3号机组/岛" },
      { value: "4", label: "4号机组/岛" },
    ],
    "2016": [
      { value: "1", label: "1号机组/岛" },
      { value: "2", label: "2号机组/岛" },
    ],
  },
  auditReplaceFactoryIndexMaps: {
    sourceVariantOptions: {
      "1916": ["3", "4"],
      "2016": ["1", "2"],
    },
    targetVariantOptions: {
      "1916": ["3", "4"],
      "2016": ["1", "2"],
    },
  },
};

function createAdapter(): ApiAdapter {
  return {
    ping: vi.fn(),
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

  it("uses a directly clickable file input for the replace DWG picker", () => {
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

    const fileInput = screen.getByTestId("replace-file-input");
    expect(fileInput).toHaveAttribute("type", "file");
    expect(fileInput).not.toHaveAttribute("hidden");
    expect(fileInput).not.toHaveAttribute("aria-hidden");
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
    await user.selectOptions(screen.getByLabelText("来源机组号/岛号"), "2");
    await user.type(screen.getByLabelText("目标项目号"), "1916");
    await user.selectOptions(screen.getByLabelText("目标机组号/岛号"), "3");

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
    expect(screen.getByLabelText("来源机组号/岛号")).toHaveValue("2");
    expect(screen.getByLabelText("目标项目号")).toHaveValue("1916");
    expect(screen.getByLabelText("目标机组号/岛号")).toHaveValue("3");
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

    expect(screen.queryByLabelText("目标机组号/岛号")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("目标项目号"), "1916");
    expect(screen.getByLabelText("目标机组号/岛号")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "3号机组/岛" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "4号机组/岛" })).toBeInTheDocument();

    await user.clear(screen.getByLabelText("目标项目号"));
    await user.type(screen.getByLabelText("目标项目号"), "1818");
    expect(screen.queryByLabelText("目标机组号/岛号")).not.toBeInTheDocument();
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

    expect(screen.queryByLabelText("来源机组号/岛号")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("原始项目号"), "2016");
    expect(screen.getByLabelText("来源机组号/岛号")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "1号机组/岛" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "2号机组/岛" })).toBeInTheDocument();

    await user.clear(screen.getByLabelText("原始项目号"));
    await user.type(screen.getByLabelText("原始项目号"), "1916");
    expect(screen.getByLabelText("来源机组号/岛号")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "3号机组/岛" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "4号机组/岛" })).toBeInTheDocument();

    await user.clear(screen.getByLabelText("原始项目号"));
    await user.type(screen.getByLabelText("原始项目号"), "2026");
    expect(screen.queryByLabelText("来源机组号/岛号")).not.toBeInTheDocument();
  });

  it("uses backend schema for source and target variant selectors", async () => {
    const user = userEvent.setup();
    const schemaWithRuntimeVariants = {
      ...schema,
      auditReplaceFactoryIndexMaps: {
        sourceVariantOptions: {
          "3000": ["7", "8"],
        },
        targetVariantOptions: {
          "4000": ["5", "6"],
        },
      },
    } as unknown as FormSchema;

    render(
      <ReplaceWorkspace
        adapter={createAdapter()}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onContinueToDeliverable={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schemaWithRuntimeVariants}
      />,
    );

    await user.type(screen.getByLabelText("原始项目号"), "3000");
    expect(screen.getByLabelText("来源机组号/岛号")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "7号机组/岛" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "8号机组/岛" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("目标项目号"), "4000");
    expect(screen.getByLabelText("目标机组号/岛号")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "5号机组/岛" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "6号机组/岛" })).toBeInTheDocument();
  });

  it("uses backend unit option labels for replace targets outside factory-index templates", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();
    adapter.createAuditReplace = vi.fn().mockResolvedValue({
      batchId: "batch-replace-unit-1",
      jobs: [],
    });
    const schemaWithRuntimeUnitOptions = {
      ...schema,
      auditReplaceSourceUnitOptions: {
        "2016": [
          { value: "1", label: "1号机组/岛" },
          { value: "2", label: "2号机组/岛" },
        ],
      },
      auditReplaceTargetUnitOptions: {
        "1915": [
          { value: "1", label: "1号机组/岛" },
          { value: "2", label: "2号机组/岛" },
        ],
      },
    } as unknown as FormSchema;

    render(
      <ReplaceWorkspace
        adapter={adapter}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onContinueToDeliverable={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schemaWithRuntimeUnitOptions}
      />,
    );

    await user.type(screen.getByLabelText("原始项目号"), "2016");
    await user.selectOptions(screen.getByLabelText("来源机组号/岛号"), "1");
    await user.type(screen.getByLabelText("目标项目号"), "1915");
    await user.selectOptions(screen.getByLabelText("目标机组号/岛号"), "2");
    await user.upload(
      screen.getByTestId("replace-file-input"),
      new File(["dwg"], "20161RC-JGS09-A.dwg", { type: "application/acad" }),
    );
    await user.click(screen.getByRole("button", { name: "开始翻版" }));

    await waitFor(() => {
      expect(adapter.createAuditReplace).toHaveBeenCalledWith({
        sourceProjectNo: "2016",
        sourceIslandNo: "1",
        targetProjectNo: "1915",
        targetIslandNo: "2",
        files: expect.any(Array),
        runDeliverable: false,
      });
    });
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
    await user.selectOptions(screen.getByLabelText("来源机组号/岛号"), "2");
    await user.type(screen.getByLabelText("目标项目号"), "1916");
    await user.selectOptions(screen.getByLabelText("目标机组号/岛号"), "3");
    await user.upload(
      screen.getByTestId("replace-file-input"),
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
    expect(screen.queryByLabelText("目标机组号/岛号")).not.toBeInTheDocument();
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
      screen.getByTestId("replace-file-input"),
      new File(["dwg"], "20261NH-JGS51-B合并版.dwg", { type: "application/acad" }),
    );

    expect(screen.getByLabelText("原始项目号")).toHaveValue("2026");
  });

  it("infers source project and source unit from uploaded album-code dwg names", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(
      "auto-fanban.replace-draft",
      JSON.stringify({
        mode: "replace_only",
        sourceProjectNo: "1916",
        sourceIslandNo: "3",
        targetProjectNo: "2026",
        targetIslandNo: "",
      }),
    );

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
      screen.getByTestId("replace-file-input"),
      new File(["dwg"], "20162RC-JGS09-A.dwg", { type: "application/acad" }),
    );

    expect(screen.getByLabelText("原始项目号")).toHaveValue("2016");
    expect(screen.getByLabelText("来源机组号/岛号")).toHaveValue("2");
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
    await user.selectOptions(screen.getByLabelText("来源机组号/岛号"), "2");
    await user.type(screen.getByLabelText("目标项目号"), "1916");
    await user.selectOptions(screen.getByLabelText("目标机组号/岛号"), "3");
    await user.upload(
      screen.getByTestId("replace-file-input"),
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
    await user.selectOptions(screen.getByLabelText("来源机组号/岛号"), "1");
    await user.type(screen.getByLabelText("目标项目号"), "1916");
    await user.selectOptions(screen.getByLabelText("目标机组号/岛号"), "3");
    await user.upload(
      screen.getByTestId("replace-file-input"),
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
