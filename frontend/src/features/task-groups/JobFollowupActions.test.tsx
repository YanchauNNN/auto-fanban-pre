import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiAdapter, JobWorkloadSubmission, TaskGroupDetail } from "../../platform/api/types";
import { JobFollowupActions } from "./JobFollowupActions";

const refreshCurrentAccount = vi.fn();
vi.mock("../../shared/session/SessionContext", () => ({
  useSession: () => ({ currentAccount: { accountId: "creator" }, refreshCurrentAccount }),
}));

const initial: JobWorkloadSubmission = {
  supported: true, canSubmit: true, blockers: [], groupId: null, workflowStatus: "draft",
  initialWorkloadA1: 3.25, group: null,
  personnelFields: [
    { key: "ied_checked_by", label: "一审", value: "", required: true },
    { key: "ied_reviewed_by", label: "二审", value: "王工@wang", required: true },
    { key: "ied_approved_by", label: "三审", value: "张工@zhang", required: true },
  ],
};

function approvedGroup(): TaskGroupDetail {
  return {
    groupId: "group-created", displayName: "测试图册", albumInternalCode: "TEST", batchId: null,
    projectNo: "2016", status: "succeeded", createdAt: "2026-09-03T12:00:00Z", sourceFilenames: ["sample.dwg"],
    ownerSnapshot: null, creatorName: "设计人", creatorAccount: "creator", creatorOffice: "结构室",
    workflowStatus: "in_review", currentNodeKey: "one_review", archiveStatus: "pending",
    workload: { initialWorkloadA1: 3.25, finalWorkloadA1: 3.25, oneReviewFactor: 1, twoReviewFactor: 1, threeReviewFactor: 1, nodeFactors: {}, settlementStatus: "pending", settledAt: null, contributorEntries: [] },
    effectiveWorkload: 3.25, canViewDetail: true, canSubmit: false, submitBlockers: [], canApprove: false,
    isRelatedToCurrentUser: true, childJobIds: ["job-1"], personnelSnapshot: { members: {} },
    workflow: { status: "in_review", initiatedAt: "2026-09-03T12:00:00Z", initiatedByAccount: "creator", initiatedByName: "设计人", duplicatePolicy: null, overwriteArchiveTarget: null, currentNodeKey: "one_review", nodes: [], archiveStatus: null, archiveRetryCount: 0, archiveLastError: null, archiveLastAttemptAt: null },
    archive: { archiveRootPath: null, targetDir: null, status: "pending", overwriteMode: null, startedAt: null, completedAt: null, lastError: null, retryCount: 0, lastAttemptAt: null, archivedFiles: [] },
    replacement: { albumInternalCode: null, revision: null, replacedGroupId: null, replacedRecordPendingDelete: false },
    legacyVisibility: { scope: "creator", reason: null },
  };
}

function setup(overrides: Partial<ApiAdapter> = {}, preview = initial) {
  const adapter = {
    getJobWorkloadSubmission: vi.fn().mockResolvedValue(preview),
    submitJobWorkload: vi.fn().mockResolvedValue(approvedGroup()),
    getJobExecutionActions: vi.fn().mockResolvedValue({ canCancel: false, canRetry: false, cancelRequested: false, cancelReason: "任务已完成", retryReason: "任务已成功" }),
    cancelJob: vi.fn(), retryJob: vi.fn(), ...overrides,
  } as unknown as ApiAdapter;
  const onOpenWorkload = vi.fn();
  const onOpenJob = vi.fn();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={queryClient}><JobFollowupActions adapter={adapter} jobId="job-1" onOpenWorkload={onOpenWorkload} onOpenJob={onOpenJob} /></QueryClientProvider>);
  return { adapter, onOpenWorkload, onOpenJob, queryClient };
}

async function openForm() {
  await userEvent.click(await screen.findByRole("button", { name: "提交工作量填报" }));
  return screen.getByRole("dialog", { name: "提交工作量填报" });
}

beforeEach(() => { vi.clearAllMocks(); });

describe("JobFollowupActions", () => {
  it("requires explicit confirmation and validates every empty person locally", async () => {
    const { adapter } = setup();
    const dialog = await openForm();
    expect(adapter.submitJobWorkload).not.toHaveBeenCalled();
    expect(within(dialog).getByText("3.25 A1")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "确认并提交" }));
    expect(screen.getByLabelText(/一审/)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("请填写一审")).toBeInTheDocument();
    expect(adapter.submitJobWorkload).not.toHaveBeenCalled();
  });

  it("posts once despite repeated clicks and opens the existing workload module after success", async () => {
    let resolve: (value: TaskGroupDetail) => void = () => {};
    const pending = new Promise<TaskGroupDetail>((done) => { resolve = done; });
    const group = approvedGroup();
    const read = vi.fn().mockResolvedValue(initial);
    const submit = vi.fn().mockImplementation(() => pending);
    const { onOpenWorkload } = setup({ getJobWorkloadSubmission: read, submitJobWorkload: submit });
    await openForm();
    await userEvent.type(screen.getByLabelText(/一审/), "李工@li");
    await userEvent.dblClick(screen.getByRole("button", { name: "确认并提交" }));
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit).toHaveBeenCalledWith("job-1", { personnel: { ied_checked_by: "李工@li", ied_reviewed_by: "王工@wang", ied_approved_by: "张工@zhang" }, overwriteArchiveExisting: false, cancelExistingInProgress: false });
    read.mockResolvedValue({ ...initial, canSubmit: false, workflowStatus: "in_review", groupId: group.groupId, group });
    await act(async () => resolve(group));
    await userEvent.click(await screen.findByRole("button", { name: "查看工作量流程" }));
    expect(onOpenWorkload).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "提交审批" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(refreshCurrentAccount).toHaveBeenCalled();
  });

  it.each([
    [403, "当前账号无权提交此任务，请使用任务创建人账号。"],
    [422, "一审账号不存在"],
  ])("keeps the form and shows a useful %i error", async (status, message) => {
    const detail = status === 422 ? { field_errors: { ied_checked_by: message }, message: "请修正审批人员" } : "forbidden";
    setup({ submitJobWorkload: vi.fn().mockRejectedValue({ status, detail }) });
    await openForm();
    await userEvent.type(screen.getByLabelText(/一审/), "李工@li");
    await userEvent.click(screen.getByRole("button", { name: "确认并提交" }));
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    if (status === 422) expect(screen.getByLabelText(/一审/)).toHaveAttribute("aria-invalid", "true");
  });

  it("restores focus and never posts when Escape dismisses confirmation", async () => {
    const { adapter } = setup();
    await openForm();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提交工作量填报" })).toHaveFocus();
    expect(adapter.submitJobWorkload).not.toHaveBeenCalled();
  });

  it("keeps all entered personnel and accumulates the two explicit conflict confirmations", async () => {
    const submit = vi.fn()
      .mockRejectedValueOnce({ status: 422, detail: "archive_target_exists" })
      .mockRejectedValueOnce({ status: 422, detail: "duplicate_in_progress_exists" })
      .mockResolvedValue(approvedGroup());
    setup({ submitJobWorkload: submit });
    await openForm();
    await userEvent.type(screen.getByLabelText(/一审/), "李工@li");
    await userEvent.click(screen.getByRole("button", { name: "确认并提交" }));
    expect(await screen.findByRole("dialog", { name: "归档冲突确认" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "继续提交" }));
    expect(await screen.findByRole("dialog", { name: "重复流程确认" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "取消旧流程并重提" }));
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(3));
    expect(submit.mock.calls[2][1]).toEqual({ personnel: { ied_checked_by: "李工@li", ied_reviewed_by: "王工@wang", ied_approved_by: "张工@zhang" }, overwriteArchiveExisting: true, cancelExistingInProgress: true });
  });

  it("marks every invalid personnel field and traps Tab inside the form", async () => {
    setup({}, { ...initial, personnelFields: initial.personnelFields.map((field) => ({ ...field, value: "" })) });
    await openForm();
    const submit = screen.getByRole("button", { name: "确认并提交" });
    await userEvent.click(submit);
    for (const label of [/一审/, /二审/, /三审/]) {
      expect(screen.getByLabelText(label)).toHaveAttribute("aria-invalid", "true");
    }
    submit.focus();
    await userEvent.tab();
    expect(screen.getByLabelText(/一审/)).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(submit).toHaveFocus();
  });

  it("does not offer submission when the server rejects availability", async () => {
    setup({}, { ...initial, supported: false, canSubmit: false, blockers: [{ code: "unsupported", message: "计算书暂无工作量计量规则" }] });
    expect(await screen.findByText("计算书暂无工作量计量规则")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "提交工作量填报" })).not.toBeInTheDocument();
  });

  it("disables cached actions if their availability refresh fails", async () => {
    const getWorkload = vi.fn().mockResolvedValue(initial);
    const getActions = vi.fn().mockResolvedValue({ canCancel: true, canRetry: true, cancelRequested: false, cancelReason: null, retryReason: null });
    const { queryClient } = setup({ getJobWorkloadSubmission: getWorkload, getJobExecutionActions: getActions });
    expect(await screen.findByRole("button", { name: "提交工作量填报" })).toBeEnabled();
    expect(await screen.findByRole("button", { name: "取消任务" })).toBeEnabled();
    getWorkload.mockRejectedValue(new Error("offline"));
    getActions.mockRejectedValue(new Error("offline"));
    await act(async () => { await queryClient.invalidateQueries(); });
    await waitFor(() => expect(screen.getByRole("button", { name: "提交工作量填报" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "取消任务" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重试任务" })).toBeDisabled();
  });

  it("confirms cancellation and shows that the worker is safely stopping", async () => {
    const cancelled = { canCancel: false, canRetry: false, cancelRequested: true, cancelReason: "取消请求已提交", retryReason: "等待停止" };
    const read = vi.fn().mockResolvedValue({ ...cancelled, canCancel: true, cancelRequested: false });
    const cancel = vi.fn().mockImplementation(async () => { read.mockResolvedValue(cancelled); return cancelled; });
    setup({ getJobExecutionActions: read, cancelJob: cancel });
    await userEvent.click(await screen.findByRole("button", { name: "取消任务" }));
    expect(cancel).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "确认取消任务" }));
    expect(await screen.findByRole("button", { name: "正在安全取消…" })).toBeDisabled();
    expect(cancel).toHaveBeenCalledOnce();
  });

  it("creates a retry job only on confirmation and keeps a link to its new details", async () => {
    const retry = vi.fn().mockResolvedValue({ jobId: "new-job", groupId: null });
    const { onOpenJob } = setup({
      retryJob: retry,
      getJobExecutionActions: vi.fn().mockResolvedValue({ canCancel: false, canRetry: true, cancelRequested: false, cancelReason: "已失败", retryReason: null }),
    });
    await userEvent.click(await screen.findByRole("button", { name: "重试任务" }));
    expect(retry).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "确认重试" }));
    await userEvent.click(await screen.findByRole("button", { name: "查看重试任务" }));
    expect(onOpenJob).toHaveBeenCalledWith("new-job");
  });
});
