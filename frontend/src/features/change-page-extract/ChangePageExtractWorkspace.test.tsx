import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ApiAdapter, JobDetail, JobSummary } from "../../platform/api/types";
import { ChangePageExtractWorkspace } from "./ChangePageExtractWorkspace";

function jobSummary(jobId: string, sourceFilename: string): JobSummary {
  return {
    jobId,
    batchId: "batch-change-pages",
    isGroup: false,
    groupId: null,
    sourceFilename,
    sourceFilenames: [sourceFilename],
    taskKind: "change_page_extract",
    jobMode: "extract",
    projectNo: null,
    status: "queued",
    stage: "INIT",
    percent: 0,
    message: "",
    createdAt: "2026-08-10T10:00:00+08:00",
    finishedAt: null,
    runAuditCheck: false,
    childJobIds: [],
    findingsCount: 0,
    affectedDrawingsCount: 0,
    artifacts: {
      packageAvailable: false,
      iedAvailable: false,
      previewAvailable: false,
      previewMode: null,
      reportAvailable: false,
      replacedDwgAvailable: false,
      packageDownloadUrl: null,
      iedDownloadUrl: null,
      previewDownloadUrl: null,
      reportDownloadUrl: null,
      replacedDwgDownloadUrl: null,
    },
    retryAvailable: false,
    taskRole: "change_page_extract",
    sharedRunId: null,
  };
}

function jobDetail(summary: JobSummary, text: string): JobDetail {
  return {
    ...summary,
    status: "succeeded",
    stage: "CHANGE_PAGE_COMPLETE",
    percent: 100,
    message: "变更页码提取完成",
    finishedAt: "2026-08-10T10:00:02+08:00",
    startedAt: "2026-08-10T10:00:01+08:00",
    currentFile: null,
    flags: [],
    errors: [],
    topWrongTexts: [],
    topInternalCodes: [],
    changePageResult: {
      archiveName: summary.sourceFilename,
      items: [{ name: "附图1：布置图.pdf", relativePath: "附图1：布置图.pdf", pages: 1 }],
      text,
      pdfCount: 1,
      totalPages: 1,
      ignoredFileCount: 0,
    },
  };
}

describe("ChangePageExtractWorkspace", () => {
  it("creates one batch and renders one selectable result section per archive", async () => {
    const first = jobSummary("job-a", "第一批.zip");
    const second = jobSummary("job-b", "第二批.7z");
    const createChangePageExtract = vi.fn().mockResolvedValue({
      batchId: "batch-change-pages",
      jobs: [first, second],
    });
    const getJobDetail = vi.fn(async (jobId: string) =>
      jobId === first.jobId
        ? jobDetail(first, "附图1：布置图，共1页；")
        : jobDetail(second, "附图2：剖面图，共3页；"),
    );
    const adapter = {
      createChangePageExtract,
      getJobDetail,
    } as unknown as ApiAdapter;
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <ChangePageExtractWorkspace
          adapter={adapter}
          isOpen
          onBatchCreated={() => {}}
          onClose={() => {}}
        />
      </QueryClientProvider>,
    );

    await user.upload(screen.getByLabelText("选择变更页码压缩包"), [
      new File(["zip"], "第一批.zip", { type: "application/zip" }),
      new File(["7z"], "第二批.7z", { type: "application/x-7z-compressed" }),
    ]);
    await user.click(screen.getByRole("button", { name: "开始提取" }));

    expect(createChangePageExtract).toHaveBeenCalledTimes(1);
    expect(createChangePageExtract).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({ name: "第一批.zip" }),
        expect.objectContaining({ name: "第二批.7z" }),
      ]),
    );
    expect(await screen.findByRole("heading", { name: "第一批.zip" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "第二批.7z" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("附图1：布置图，共1页；")).toBeInTheDocument();
      expect(screen.getByText("附图2：剖面图，共3页；")).toBeInTheDocument();
    });
    expect(screen.getAllByTestId("change-page-result-text")).toHaveLength(2);
  });

  it("rejects unsupported archive extensions before submitting", async () => {
    const createChangePageExtract = vi.fn();
    const adapter = { createChangePageExtract } as unknown as ApiAdapter;
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <ChangePageExtractWorkspace
          adapter={adapter}
          isOpen
          onBatchCreated={() => {}}
          onClose={() => {}}
        />
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByLabelText("选择变更页码压缩包"), {
      target: {
        files: [new File(["tar"], "错误格式.tar", { type: "application/x-tar" })],
      },
    });
    await user.click(screen.getByRole("button", { name: "开始提取" }));

    expect(await screen.findByText("仅支持 ZIP、RAR、7z 压缩包。")).toBeInTheDocument();
    expect(createChangePageExtract).not.toHaveBeenCalled();
  });
});
