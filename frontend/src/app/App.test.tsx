import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const mockGetHealth = vi.fn();
const mockGetFormSchema = vi.fn();
const mockCreateBatch = vi.fn();
const mockListJobs = vi.fn();
const mockGetJobDetail = vi.fn();

vi.mock("../platform/api/useApiAdapter", () => ({
  useApiAdapter: () => ({
    getHealth: mockGetHealth,
    getFormSchema: mockGetFormSchema,
    createBatch: mockCreateBatch,
    listJobs: mockListJobs,
    getJobDetail: mockGetJobDetail,
  }),
}));

beforeEach(() => {
  mockGetHealth.mockReset();
  mockGetFormSchema.mockReset();
  mockCreateBatch.mockReset();
  mockListJobs.mockReset();
  mockGetJobDetail.mockReset();

  mockGetHealth.mockResolvedValue({
    status: "ok",
    ready: true,
    storageWritable: true,
    workerAlive: true,
    queueDepth: 1,
    autocadReady: true,
    officeReady: true,
    serverTime: "2026-03-08T10:20:30+08:00",
  });
  mockGetFormSchema.mockResolvedValue({
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
            required: true,
            requiredWhen: null,
            defaultValue: "",
            description: "项目号",
            options: ["2016", "1818"],
          },
        ],
      },
    ],
  });
  mockListJobs.mockResolvedValue({
    total: 0,
    items: [],
  });
});

describe("App", () => {
  it("renders three task cards and marks unavailable tasks", async () => {
    render(<App />);

    expect(await screen.findByRole("button", { name: "交付处理" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "纠错" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "翻版" })).toBeDisabled();
    expect(screen.getAllByText("接口未开放")).toHaveLength(2);
  });

  it("switches deliverable workspace panel into focus", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "交付处理" }));

    expect(screen.getByRole("heading", { name: "交付处理任务" })).toBeInTheDocument();
  });

  it("filters jobs by selected status", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "失败" }));

    await waitFor(() => {
      expect(mockListJobs).toHaveBeenLastCalledWith("failed");
    });
  });

  it("renders localized job status labels in the recent jobs list", async () => {
    mockListJobs.mockResolvedValue({
      total: 1,
      items: [
        {
          jobId: "job-1",
          batchId: "batch-1",
          sourceFilename: "A01.dwg",
          taskKind: "deliverable",
          jobMode: "deliverable",
          projectNo: "2016",
          status: "failed",
          stage: "GENERATE_DOCS",
          percent: 70,
          message: "任务失败",
          createdAt: "2026-03-08T10:20:30+08:00",
          finishedAt: null,
          artifacts: {
            packageAvailable: false,
            iedAvailable: false,
            reportAvailable: false,
            replacedDwgAvailable: false,
          },
          retryAvailable: false,
        },
      ],
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getAllByText("失败")).toHaveLength(2);
    });
  });

  it("shows a warning banner for succeeded jobs that still contain flags or errors", async () => {
    window.history.pushState({}, "", "/jobs/job-1");
    mockGetJobDetail.mockResolvedValue({
      jobId: "job-1",
      batchId: "batch-1",
      sourceFilename: "A01.dwg",
      taskKind: "deliverable",
      jobMode: "deliverable",
      projectNo: "2016",
      status: "succeeded",
      stage: "PACKAGE_ZIP",
      percent: 100,
      message: "任务完成",
      createdAt: "2026-03-08T10:20:30+08:00",
      finishedAt: "2026-03-08T10:25:30+08:00",
      startedAt: "2026-03-08T10:21:30+08:00",
      currentFile: "A01.dwg",
      flags: ["转换失败:A01.dwg"],
      errors: ["文档参数缺失: engineering_no"],
      artifacts: {
        packageAvailable: true,
        iedAvailable: false,
        reportAvailable: false,
        replacedDwgAvailable: false,
        packageDownloadUrl: "http://127.0.0.1:8000/api/jobs/job-1/download/package",
        iedDownloadUrl: null,
        reportDownloadUrl: null,
        replacedDwgDownloadUrl: null,
      },
      retryAvailable: false,
    });

    render(<App />);

    expect(
      await screen.findByText("任务已完成，但仍有告警或缺失项需要处理。"),
    ).toBeInTheDocument();
  });
});
