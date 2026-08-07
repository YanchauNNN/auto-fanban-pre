import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ApiAdapter,
  CurrentAccount,
  TaskGroupDetail,
} from "../../platform/api/types";
import { TaskGroupWorkflowPanel } from "./TaskGroupWorkflowPanel";

const sessionMocks = vi.hoisted(() => ({
  accountId: "creator",
  refreshCurrentAccount: vi.fn(),
}));

vi.mock("../../shared/session/SessionContext", () => ({
  useSession: () => ({
    currentAccount: {
      accountId: sessionMocks.accountId,
      displayName: sessionMocks.accountId === "creator" ? "创建人" : "复核人",
      role: "设计人员",
      officeCode: "25C0",
      officeName: "建筑结构所",
      valid: true,
      pendingTodoCount: 0,
    } satisfies CurrentAccount,
    refreshCurrentAccount: sessionMocks.refreshCurrentAccount,
  }),
}));

function makeDetail(overrides: Partial<TaskGroupDetail> = {}): TaskGroupDetail {
  return {
    groupId: "group-1",
    displayName: "2016-JG001",
    albumInternalCode: "2016-JG001",
    batchId: "batch-1",
    projectNo: "2016",
    status: "succeeded",
    createdAt: "2026-08-07T10:00:00+08:00",
    sourceFilenames: ["sample.dwg"],
    ownerSnapshot: {
      creatorAccount: "creator",
      creatorName: "创建人",
      creatorRole: "设计人员",
      creatorOffice: "建筑结构所",
      createdByScope: "self",
      submittedAt: null,
    },
    creatorName: "创建人",
    creatorAccount: "creator",
    creatorOffice: "建筑结构所",
    workflowStatus: "draft",
    currentNodeKey: null,
    archiveStatus: "pending",
    workload: {
      initialWorkloadA1: 1,
      finalWorkloadA1: 1,
      oneReviewFactor: 1,
      twoReviewFactor: 1,
      threeReviewFactor: 1,
      nodeFactors: {},
      settlementStatus: "pending",
      settledAt: null,
      contributorEntries: [],
    },
    effectiveWorkload: 1,
    canViewDetail: true,
    canSubmit: true,
    submitBlockers: [],
    canApprove: false,
    isRelatedToCurrentUser: true,
    childJobIds: ["job-1"],
    personnelSnapshot: { members: {} },
    workflow: {
      status: "draft",
      initiatedAt: null,
      initiatedByAccount: null,
      initiatedByName: null,
      duplicatePolicy: null,
      overwriteArchiveTarget: null,
      currentNodeKey: null,
      nodes: [],
      archiveStatus: null,
      archiveRetryCount: 0,
      archiveLastError: null,
      archiveLastAttemptAt: null,
    },
    archive: {
      archiveRootPath: null,
      targetDir: null,
      status: "pending",
      overwriteMode: null,
      startedAt: null,
      completedAt: null,
      lastError: null,
      retryCount: 0,
      lastAttemptAt: null,
      archivedFiles: [],
    },
    replacement: {
      albumInternalCode: null,
      revision: null,
      replacedGroupId: null,
      replacedRecordPendingDelete: false,
    },
    legacyVisibility: { scope: "creator", reason: null },
    ...overrides,
  };
}

function makeSubmittedDetail() {
  return makeDetail({
    status: "running",
    workflowStatus: "in_review",
    currentNodeKey: "one_review",
    canSubmit: false,
    submitBlockers: ["workflow_not_draft", "task_group_not_succeeded"],
    workflow: {
      ...makeDetail().workflow,
      status: "in_review",
      currentNodeKey: "one_review",
    },
  });
}

function renderPanel(
  adapterOverrides: Partial<ApiAdapter> = {},
  detail: TaskGroupDetail = makeDetail(),
) {
  const adapter = {
    getTaskGroupDetail: vi.fn().mockResolvedValue(detail),
    submitTaskGroup: vi.fn().mockResolvedValue(makeSubmittedDetail()),
    restartSubmitTaskGroup: vi.fn().mockResolvedValue(makeSubmittedDetail()),
    ...adapterOverrides,
  } as unknown as ApiAdapter;
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <TaskGroupWorkflowPanel adapter={adapter} groupId="group-1" />
    </QueryClientProvider>,
  );

  return { adapter, queryClient };
}

beforeEach(() => {
  sessionMocks.accountId = "creator";
  sessionMocks.refreshCurrentAccount.mockReset();
  sessionMocks.refreshCurrentAccount.mockResolvedValue(null);
});

describe("TaskGroupWorkflowPanel", () => {
  it("submits with no conflict flags and refreshes every dependent view", async () => {
    const user = userEvent.setup();
    const { adapter, queryClient } = renderPanel();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    await user.click(await screen.findByRole("button", { name: "提交审批" }));

    await waitFor(() => {
      expect(adapter.submitTaskGroup).toHaveBeenCalledWith("group-1", {
        overwriteArchiveExisting: false,
        cancelExistingInProgress: false,
      });
    });
    expect(queryClient.getQueryData(["task-group-detail", "group-1"])).toMatchObject({
      workflowStatus: "in_review",
    });
    for (const queryKey of [
      ["job-detail", "group-1"],
      ["jobs"],
      ["jobs-activity"],
      ["task-groups"],
      ["workflow", "monitor"],
      ["workload"],
    ]) {
      expect(invalidate).toHaveBeenCalledWith({ queryKey });
    }
    expect(sessionMocks.refreshCurrentAccount).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("审批流程已提交。")).toBeInTheDocument();
  });

  it("shows a clear owner restriction to non-creators without a submit action", async () => {
    sessionMocks.accountId = "reviewer";

    renderPanel({}, makeDetail({ canSubmit: false }));

    expect(
      await screen.findByText("仅任务创建人 创建人（creator）可以提交审批。"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "提交审批" })).not.toBeInTheDocument();
  });

  it("maps backend readiness codes to readable Chinese blockers", async () => {
    renderPanel(
      {},
      makeDetail({
        canSubmit: false,
        submitBlockers: ["deliverable_package_not_found", "shared_prep_invalid"],
      }),
    );

    expect(await screen.findByText("交付压缩包文件不存在")).toBeInTheDocument();
    expect(screen.getByText("共享预处理数据无效或不完整")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提交审批" })).toBeDisabled();
  });

  it("accumulates archive and duplicate confirmations across restart attempts", async () => {
    const user = userEvent.setup();
    const archiveConflict = { status: 422, detail: "archive_target_exists" };
    const duplicateConflict = { status: 422, detail: "duplicate_in_progress_exists" };
    const submitTaskGroup = vi.fn().mockRejectedValueOnce(archiveConflict);
    const restartSubmitTaskGroup = vi
      .fn()
      .mockRejectedValueOnce(duplicateConflict)
      .mockResolvedValueOnce(makeSubmittedDetail());
    renderPanel({ submitTaskGroup, restartSubmitTaskGroup });

    await user.click(await screen.findByRole("button", { name: "提交审批" }));
    await user.click(await screen.findByRole("button", { name: "继续提交" }));

    expect(restartSubmitTaskGroup).toHaveBeenNthCalledWith(1, "group-1", {
      overwriteArchiveExisting: true,
      cancelExistingInProgress: false,
    });
    await user.click(await screen.findByRole("button", { name: "取消旧流程并重提" }));

    await waitFor(() => {
      expect(restartSubmitTaskGroup).toHaveBeenNthCalledWith(2, "group-1", {
        overwriteArchiveExisting: true,
        cancelExistingInProgress: true,
      });
    });
  });

  it("returns focus to submit after canceling a conflict", async () => {
    const user = userEvent.setup();
    renderPanel({
      submitTaskGroup: vi
        .fn()
        .mockRejectedValueOnce({ status: 422, detail: "archive_target_exists" }),
    });

    const submitButton = await screen.findByRole("button", { name: "提交审批" });
    await user.click(submitButton);
    await user.click(await screen.findByRole("button", { name: "取消" }));

    await waitFor(() => expect(submitButton).toHaveFocus());
  });

  it("contains management failures inside the panel", async () => {
    renderPanel({ getTaskGroupDetail: vi.fn().mockRejectedValue(new Error("offline")) });

    expect(
      await screen.findByText("审批信息暂时无法加载，任务产物仍可正常查看。"),
    ).toBeInTheDocument();
  });
});
