import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const mockGetHealth = vi.fn();
const mockGetFormSchema = vi.fn();
const mockCreateBatch = vi.fn();
const mockCreateAuditCheck = vi.fn();
const mockListJobs = vi.fn();
const mockGetJobDetail = vi.fn();

vi.mock("../platform/api/useApiAdapter", () => ({
  useApiAdapter: () => ({
    getHealth: mockGetHealth,
    getFormSchema: mockGetFormSchema,
    createBatch: mockCreateBatch,
    createAuditCheck: mockCreateAuditCheck,
    listJobs: mockListJobs,
    getJobDetail: mockGetJobDetail,
  }),
}));

beforeEach(() => {
  window.history.pushState({}, "", "/");

  mockGetHealth.mockReset();
  mockGetFormSchema.mockReset();
  mockCreateBatch.mockReset();
  mockCreateAuditCheck.mockReset();
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
            required: false,
            requiredWhen: null,
            defaultValue: "",
            description: "项目号",
            options: ["2016", "1818"],
          },
          {
            key: "album_title_cn",
            label: "图册名称（中文）",
            type: "text",
            required: true,
            requiredWhen: null,
            defaultValue: "",
            description: "图册名称",
            options: [],
          },
        ],
      },
    ],
    auditReplaceProjectOptions: ["2026", "1818"],
  });
  mockListJobs.mockResolvedValue({
    total: 0,
    items: [],
  });
});

describe("App", () => {
  it("renders dual primary entry buttons for deliverable and audit check", async () => {
    render(<App />);

    expect(await screen.findByRole("button", { name: "出图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "纠错" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "交付处理" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "翻版" })).not.toBeInTheDocument();
  });

  it("opens the task config modal after selecting files and reopens the preserved draft", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.upload(
      await screen.findByLabelText("选择出图 DWG 文件"),
      new File(["dwg"], "A01.dwg", { type: "application/acad" }),
    );

    expect(await screen.findByRole("dialog", { name: "任务配置" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("图册名称（中文）"), "示例图册");
    await user.click(screen.getByRole("button", { name: "关闭任务配置" }));

    expect(screen.queryByRole("dialog", { name: "任务配置" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "继续草稿" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "继续草稿" }));

    expect(await screen.findByDisplayValue("示例图册")).toBeInTheDocument();
    expect(screen.getByText("A01.dwg")).toBeInTheDocument();
  });

  it("filters jobs by selected status", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "失败" }));

    await waitFor(() => {
      expect(mockListJobs).toHaveBeenLastCalledWith("failed");
    });
  });

  it("renders audit check job cards with kind badge and summary metrics", async () => {
    mockListJobs.mockResolvedValue({
      total: 1,
      items: [
        {
          jobId: "job-1",
          batchId: "batch-1",
          sourceFilename: "20261NH-JGS51-B合并版.dwg",
          taskKind: "audit_check",
          jobMode: "check",
          projectNo: "2026",
          status: "succeeded",
          stage: "EXPORT_REPORT",
          percent: 100,
          message: "纠错完成",
          createdAt: "2026-03-08T10:20:30+08:00",
          finishedAt: null,
          findingsCount: 12,
          affectedDrawingsCount: 4,
          artifacts: {
            packageAvailable: false,
            iedAvailable: false,
            reportAvailable: true,
            replacedDwgAvailable: false,
          },
          retryAvailable: false,
        },
      ],
    });

    render(<App />);

    expect(await screen.findByText("20261NH-JGS51-B合并版.dwg")).toBeInTheDocument();
    expect(screen.getByText("错误数 12")).toBeInTheDocument();
    expect(screen.getByText("受影响图纸 4")).toBeInTheDocument();
  });

  it("shows an audit summary modal when an audit job completes with findings", async () => {
    const user = userEvent.setup();
    const detail = {
      jobId: "job-1",
      batchId: "batch-1",
      sourceFilename: "20261NH-JGS51-B合并版.dwg",
      taskKind: "audit_check" as const,
      jobMode: "check",
      projectNo: "2026",
      status: "succeeded",
      stage: "EXPORT_REPORT",
      percent: 100,
      message: "纠错完成",
      createdAt: "2026-03-08T10:20:30+08:00",
      finishedAt: "2026-03-08T10:25:30+08:00",
      startedAt: "2026-03-08T10:21:30+08:00",
      currentFile: "20261NH-JGS51-B合并版.dwg",
      findingsCount: 6,
      affectedDrawingsCount: 3,
      topWrongTexts: ["错字A", "错字B"],
      topInternalCodes: ["20261NH-JGS51-001"],
      flags: [],
      errors: [],
      artifacts: {
        packageAvailable: false,
        iedAvailable: false,
        reportAvailable: true,
        replacedDwgAvailable: false,
        packageDownloadUrl: null,
        iedDownloadUrl: null,
        reportDownloadUrl: "http://127.0.0.1:8000/api/jobs/job-1/download/report",
        replacedDwgDownloadUrl: null,
      },
      retryAvailable: false,
    };

    mockListJobs
      .mockResolvedValueOnce({
        total: 1,
        items: [
          {
            ...detail,
            status: "running",
            percent: 60,
            findingsCount: 0,
            affectedDrawingsCount: 0,
            topWrongTexts: undefined,
            topInternalCodes: undefined,
            artifacts: {
              packageAvailable: false,
              iedAvailable: false,
              reportAvailable: false,
              replacedDwgAvailable: false,
            },
          },
        ],
      })
      .mockResolvedValue({
        total: 1,
        items: [
          {
            ...detail,
            artifacts: {
              packageAvailable: false,
              iedAvailable: false,
              reportAvailable: true,
              replacedDwgAvailable: false,
            },
          },
        ],
      });
    mockGetJobDetail.mockResolvedValue(detail);

    render(<App />);

    expect(await screen.findByText("20261NH-JGS51-B合并版.dwg")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "刷新" }));

    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: "纠错结果摘要" })).toBeInTheDocument();
    });

    expect(screen.getByText("总错误数")).toBeInTheDocument();
    expect(screen.getByText("6")).toBeInTheDocument();
    expect(screen.getByText("错字A")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载完整报告" })).toHaveAttribute(
      "href",
      "http://127.0.0.1:8000/api/jobs/job-1/download/report",
    );
  });

  it("renders audit check details with summary fields and report download only", async () => {
    window.history.pushState({}, "", "/jobs/job-1");
    mockGetJobDetail.mockResolvedValue({
      jobId: "job-1",
      batchId: "batch-1",
      sourceFilename: "20261NH-JGS51-B合并版.dwg",
      taskKind: "audit_check",
      jobMode: "check",
      projectNo: "2026",
      status: "succeeded",
      stage: "EXPORT_REPORT",
      percent: 100,
      message: "纠错完成",
      createdAt: "2026-03-08T10:20:30+08:00",
      finishedAt: "2026-03-08T10:25:30+08:00",
      startedAt: "2026-03-08T10:21:30+08:00",
      currentFile: "20261NH-JGS51-B合并版.dwg",
      findingsCount: 9,
      affectedDrawingsCount: 5,
      topWrongTexts: ["错字A", "错字B"],
      topInternalCodes: ["20261NH-JGS51-001", "20261NH-JGS51-002"],
      flags: [],
      errors: [],
      artifacts: {
        packageAvailable: false,
        iedAvailable: false,
        reportAvailable: true,
        replacedDwgAvailable: false,
        packageDownloadUrl: null,
        iedDownloadUrl: null,
        reportDownloadUrl: "http://127.0.0.1:8000/api/jobs/job-1/download/report",
        replacedDwgDownloadUrl: null,
      },
      retryAvailable: false,
    });

    render(<App />);

    expect(await screen.findByText("总错误数")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载 report.xlsx" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "下载 package.zip" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "下载 IED计划.xlsx" })).not.toBeInTheDocument();
    expect(screen.getByText("错字A")).toBeInTheDocument();
    expect(screen.getByText("20261NH-JGS51-001")).toBeInTheDocument();
  });
});
