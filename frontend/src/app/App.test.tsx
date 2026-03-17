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
            description: "可留空，会优先从DWG文件名自动推断",
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

describe("recent jobs sidebar", () => {
  it("shows only the latest four recent jobs by default and can expand the rest", async () => {
    mockListJobs.mockResolvedValue({
      total: 6,
      items: Array.from({ length: 6 }, (_, index) => ({
        jobId: `job-${index + 1}`,
        batchId: `batch-${index + 1}`,
        groupId: null,
        isGroup: false,
        sourceFilename: `sample-${index + 1}.dwg`,
        sourceFilenames: [`sample-${index + 1}.dwg`],
        taskKind: "deliverable",
        taskRole: null,
        jobMode: "deliverable",
        projectNo: "2026",
        status: "succeeded",
        stage: "PACKAGE_ZIP",
        percent: 100,
        message: "",
        createdAt: `2026-03-16T10:2${index}:30+08:00`,
        finishedAt: null,
        runAuditCheck: false,
        childJobIds: [],
        findingsCount: 0,
        affectedDrawingsCount: 0,
        artifacts: {
          packageAvailable: true,
          iedAvailable: true,
          reportAvailable: false,
          replacedDwgAvailable: false,
        },
        retryAvailable: false,
        sharedRunId: null,
      })),
    });

    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("sample-6.dwg")).toBeInTheDocument();
    expect(screen.getByText("sample-3.dwg")).toBeInTheDocument();
    expect(screen.queryByText("sample-2.dwg")).not.toBeInTheDocument();
    expect(screen.getByText(/展开其余/)).toBeInTheDocument();

    await user.click(screen.getByText(/展开其余/));

    expect(screen.getByText("sample-2.dwg")).toBeInTheDocument();
    expect(screen.getByText("sample-1.dwg")).toBeInTheDocument();
    expect(screen.getByText("收起")).toBeInTheDocument();

    await user.click(screen.getByText("收起"));

    expect(screen.queryByText("sample-2.dwg")).not.toBeInTheDocument();
  });

  it("shows all matching jobs while searching and bypasses the collapsed recent jobs limit", async () => {
    mockListJobs.mockResolvedValue({
      total: 6,
      items: [
        "sample-1.dwg",
        "20261RS-JGS65.dwg",
        "sample-3.dwg",
        "18185NE-JGS11.dwg",
        "sample-5.dwg",
        "20261RS-JGS66.dwg",
      ].map((name, index) => ({
        jobId: `job-${index + 1}`,
        batchId: `batch-${index + 1}`,
        groupId: null,
        isGroup: false,
        sourceFilename: name,
        sourceFilenames: [name],
        taskKind: "deliverable",
        taskRole: null,
        jobMode: "deliverable",
        projectNo: "2026",
        status: "succeeded",
        stage: "PACKAGE_ZIP",
        percent: 100,
        message: "",
        createdAt: `2026-03-16T11:1${index}:30+08:00`,
        finishedAt: null,
        runAuditCheck: false,
        childJobIds: [],
        findingsCount: 0,
        affectedDrawingsCount: 0,
        artifacts: {
          packageAvailable: true,
          iedAvailable: true,
          reportAvailable: false,
          replacedDwgAvailable: false,
        },
        retryAvailable: false,
        sharedRunId: null,
      })),
    });

    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("20261RS-JGS66.dwg")).toBeInTheDocument();
    expect(screen.queryByText("sample-1.dwg")).not.toBeInTheDocument();

    await user.type(screen.getByRole("searchbox"), "20261RS");

    expect(screen.getByText("20261RS-JGS65.dwg")).toBeInTheDocument();
    expect(screen.getByText("20261RS-JGS66.dwg")).toBeInTheDocument();
    expect(screen.queryByText("sample-1.dwg")).not.toBeInTheDocument();
    expect(screen.queryByText(/展开其余/)).not.toBeInTheDocument();
  });
});

describe("App", () => {
  it("renders dual primary entry buttons for deliverable and audit check", async () => {
    render(<App />);

    expect(await screen.findByRole("button", { name: "出图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "纠错" })).toBeInTheDocument();
  });

  it("renders a real backend task group as one package card with two child chips", async () => {
    mockListJobs.mockResolvedValue({
      total: 1,
      items: [
        {
          jobId: "group-1",
          groupId: "group-1",
          batchId: "batch-1",
          isGroup: true,
          sourceFilename: "18185NE-JGS11.dwg",
          sourceFilenames: ["18185NE-JGS11.dwg"],
          taskKind: null,
          jobMode: null,
          projectNo: "1818",
          status: "running",
          stage: "DELIVERABLE_BRANCH",
          percent: 45,
          message: "",
          createdAt: "2026-03-16T10:20:30+08:00",
          finishedAt: null,
          runAuditCheck: true,
          childJobIds: ["job-deliverable-1", "job-audit-1"],
          findingsCount: 0,
          affectedDrawingsCount: 0,
          artifacts: {
            packageAvailable: false,
            iedAvailable: false,
            reportAvailable: false,
            replacedDwgAvailable: false,
          },
          retryAvailable: false,
          taskRole: null,
          sharedRunId: null,
        },
      ],
    });
    mockGetJobDetail.mockResolvedValue({
      jobId: "group-1",
      groupId: "group-1",
      batchId: "batch-1",
      isGroup: true,
      sourceFilename: "18185NE-JGS11.dwg",
      sourceFilenames: ["18185NE-JGS11.dwg"],
      taskKind: null,
      jobMode: null,
      projectNo: "1818",
      status: "running",
      stage: "DELIVERABLE_BRANCH",
      percent: 45,
      message: "",
      createdAt: "2026-03-16T10:20:30+08:00",
      finishedAt: null,
      startedAt: "2026-03-16T10:20:32+08:00",
      currentFile: null,
      runAuditCheck: true,
      childJobIds: ["job-deliverable-1", "job-audit-1"],
      findingsCount: 0,
      affectedDrawingsCount: 0,
      topWrongTexts: [],
      topInternalCodes: [],
      flags: [],
      errors: [],
      artifacts: {
        packageAvailable: false,
        iedAvailable: false,
        reportAvailable: false,
        replacedDwgAvailable: false,
      },
      retryAvailable: false,
      taskRole: null,
      sharedRunId: null,
      children: [
        {
          jobId: "job-deliverable-1",
          batchId: "batch-1",
          groupId: "group-1",
          isGroup: false,
          sourceFilename: "18185NE-JGS11.dwg",
          sourceFilenames: ["18185NE-JGS11.dwg"],
          taskKind: "deliverable",
          taskRole: "deliverable_main",
          jobMode: "deliverable",
          projectNo: "1818",
          status: "running",
          stage: "GENERATE_DOCS",
          percent: 45,
          message: "",
          createdAt: "2026-03-16T10:20:30+08:00",
          finishedAt: null,
          runAuditCheck: false,
          childJobIds: [],
          findingsCount: 0,
          affectedDrawingsCount: 0,
          artifacts: {
            packageAvailable: false,
            iedAvailable: false,
            reportAvailable: false,
            replacedDwgAvailable: false,
          },
          retryAvailable: false,
          sharedRunId: null,
        },
        {
          jobId: "job-audit-1",
          batchId: "batch-1",
          groupId: "group-1",
          isGroup: false,
          sourceFilename: "18185NE-JGS11.dwg",
          sourceFilenames: ["18185NE-JGS11.dwg"],
          taskKind: "audit_check",
          taskRole: "audit_check",
          jobMode: "check",
          projectNo: "1818",
          status: "queued",
          stage: "INIT",
          percent: 0,
          message: "",
          createdAt: "2026-03-16T10:20:31+08:00",
          finishedAt: null,
          runAuditCheck: false,
          childJobIds: [],
          findingsCount: 0,
          affectedDrawingsCount: 0,
          artifacts: {
            packageAvailable: false,
            iedAvailable: false,
            reportAvailable: false,
            replacedDwgAvailable: false,
          },
          retryAvailable: false,
          sharedRunId: null,
        },
      ],
    });

    render(<App />);

    expect(await screen.findByText("18185NE-JGS11.dwg")).toBeInTheDocument();
    expect(screen.getAllByText("18185NE-JGS11.dwg")).toHaveLength(1);
    expect(screen.getByText("包含 2 个子任务")).toBeInTheDocument();
    expect(screen.getByText("任务包")).toBeInTheDocument();
    expect(screen.getAllByText("交付")[0]).toBeInTheDocument();
    expect(screen.getAllByText("纠错")[0]).toBeInTheDocument();
    expect(screen.getByText("执行出图子任务")).toBeInTheDocument();
    expect(screen.getByText("正在执行出图任务")).toBeInTheDocument();
  });

  it("groups historical child-only deliverable and audit jobs into one synthetic package card", async () => {
    mockListJobs.mockResolvedValue({
      total: 4,
      items: [
        {
          jobId: "job-deliverable-1",
          batchId: "batch-shared-1",
          groupId: null,
          isGroup: false,
          sourceFilename: "20261RS-JGS65.dwg",
          sourceFilenames: ["20261RS-JGS65.dwg"],
          taskKind: "deliverable",
          taskRole: null,
          jobMode: "deliverable",
          projectNo: "2026",
          status: "succeeded",
          stage: "PACKAGE_ZIP",
          percent: 100,
          message: "????",
          createdAt: "2026-03-16T10:20:30+08:00",
          finishedAt: null,
          runAuditCheck: false,
          childJobIds: [],
          findingsCount: 0,
          affectedDrawingsCount: 0,
          artifacts: {
            packageAvailable: true,
            iedAvailable: true,
            reportAvailable: false,
            replacedDwgAvailable: false,
          },
          retryAvailable: false,
          sharedRunId: null,
        },
        {
          jobId: "job-audit-1",
          batchId: "batch-shared-1",
          groupId: null,
          isGroup: false,
          sourceFilename: "20261RS-JGS65.dwg",
          sourceFilenames: ["20261RS-JGS65.dwg"],
          taskKind: "audit_check",
          taskRole: null,
          jobMode: "check",
          projectNo: "2026",
          status: "succeeded",
          stage: "AUDIT_CHECK",
          percent: 100,
          message: "auditing",
          createdAt: "2026-03-16T10:20:31+08:00",
          finishedAt: null,
          runAuditCheck: false,
          childJobIds: [],
          findingsCount: 15,
          affectedDrawingsCount: 6,
          artifacts: {
            packageAvailable: false,
            iedAvailable: false,
            reportAvailable: true,
            replacedDwgAvailable: false,
          },
          retryAvailable: false,
          sharedRunId: null,
        },
      ],
    });

    render(<App />);

    expect(await screen.findByText("20261RS-JGS65.dwg")).toBeInTheDocument();
    expect(screen.getAllByText("20261RS-JGS65.dwg")).toHaveLength(1);
    expect(screen.getByText("包含 2 个子任务")).toBeInTheDocument();
    expect(screen.getByText("错误数 15")).toBeInTheDocument();
    expect(screen.getByText("受影响图纸 6")).toBeInTheDocument();
    expect(screen.queryByText("????")).not.toBeInTheDocument();
    expect(screen.queryByText("auditing")).not.toBeInTheDocument();
    expect(screen.getByText("任务包已完成")).toBeInTheDocument();
    expect(screen.getAllByText("交付")[0]).toBeInTheDocument();
    expect(screen.getAllByText("纠错")[0]).toBeInTheDocument();
  });

  it("shows an audit summary modal when an audit job completes with findings", async () => {
    const user = userEvent.setup();
    const detail = {
      jobId: "job-1",
      batchId: "batch-1",
      groupId: null,
      isGroup: false,
      sourceFilename: "20261NH-JGS51-B合并版.dwg",
      sourceFilenames: ["20261NH-JGS51-B合并版.dwg"],
      taskKind: "audit_check" as const,
      taskRole: null,
      jobMode: "check",
      projectNo: "2026",
      status: "succeeded",
      stage: "EXPORT_REPORT",
      percent: 100,
      message: "",
      createdAt: "2026-03-08T10:20:30+08:00",
      finishedAt: "2026-03-08T10:25:30+08:00",
      startedAt: "2026-03-08T10:21:30+08:00",
      currentFile: "20261NH-JGS51-B合并版.dwg",
      runAuditCheck: false,
      childJobIds: [],
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
      sharedRunId: null,
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

  it("renders group details with result-focused child cards", async () => {
    window.history.pushState({}, "", "/jobs/group-1");
    mockGetJobDetail.mockImplementation(async (jobId: string) => {
      if (jobId === "job-deliverable-1") {
        return {
          jobId: "job-deliverable-1",
          batchId: "batch-1",
          groupId: "group-1",
          isGroup: false,
          sourceFilename: "20261NH-JGS51-B合并版.dwg",
          sourceFilenames: ["20261NH-JGS51-B合并版.dwg"],
          taskKind: "deliverable",
          taskRole: "deliverable_main",
          jobMode: "deliverable",
          projectNo: "2026",
          status: "succeeded",
          stage: "PACKAGE_ZIP",
          percent: 100,
          message: "",
          createdAt: "2026-03-08T10:20:30+08:00",
          finishedAt: "2026-03-08T10:25:00+08:00",
          startedAt: "2026-03-08T10:20:32+08:00",
          currentFile: null,
          runAuditCheck: false,
          childJobIds: [],
          findingsCount: 0,
          affectedDrawingsCount: 0,
          topWrongTexts: [],
          topInternalCodes: [],
          flags: [],
          errors: [],
          deliverableOutputs: {
            dwgCount: 2,
            pdfCount: 2,
            drawings: [
              {
                name: "A01",
                internalCode: "20261NH-JGS51-001",
                dwgName: "A01.dwg",
                pdfName: "A01.pdf",
                pageTotal: 1,
              },
              {
                name: "A02",
                internalCode: "20261NH-JGS51-002",
                dwgName: "A02.dwg",
                pdfName: "A02.pdf",
                pageTotal: 2,
              },
            ],
            documents: [
              { name: "封面.docx", kind: "docx" },
              { name: "目录.xlsx", kind: "xlsx" },
            ],
          },
          artifacts: {
            packageAvailable: true,
            iedAvailable: true,
            reportAvailable: false,
            replacedDwgAvailable: false,
            packageDownloadUrl: "http://127.0.0.1:8000/api/jobs/job-deliverable-1/download/package",
            iedDownloadUrl: "http://127.0.0.1:8000/api/jobs/job-deliverable-1/download/ied",
          },
          retryAvailable: false,
          sharedRunId: null,
        };
      }

      if (jobId === "job-audit-1") {
        return {
          jobId: "job-audit-1",
          batchId: "batch-1",
          groupId: "group-1",
          isGroup: false,
          sourceFilename: "20261NH-JGS51-B合并版.dwg",
          sourceFilenames: ["20261NH-JGS51-B合并版.dwg"],
          taskKind: "audit_check",
          taskRole: "audit_check",
          jobMode: "check",
          projectNo: "2026",
          status: "succeeded",
          stage: "EXPORT_REPORT",
          percent: 100,
          message: "",
          createdAt: "2026-03-08T10:20:40+08:00",
          finishedAt: "2026-03-08T10:25:30+08:00",
          startedAt: "2026-03-08T10:20:45+08:00",
          currentFile: null,
          runAuditCheck: false,
          childJobIds: [],
          findingsCount: 9,
          affectedDrawingsCount: 5,
          topWrongTexts: ["2016"],
          topInternalCodes: ["20261NH-JGS51-001"],
          findingGroups: [
            {
              matchedText: "2016",
              count: 3,
              internalCodes: ["20261NH-JGS51-001", "20261NH-JGS51-003"],
            },
          ],
          flags: [],
          errors: [],
          artifacts: {
            packageAvailable: false,
            iedAvailable: false,
            reportAvailable: true,
            replacedDwgAvailable: false,
            reportDownloadUrl: "http://127.0.0.1:8000/api/jobs/job-audit-1/download/report",
          },
          retryAvailable: false,
          sharedRunId: null,
        };
      }

      return {
      jobId: "group-1",
      groupId: "group-1",
      batchId: "batch-1",
      isGroup: true,
      sourceFilename: "20261NH-JGS51-B合并版.dwg",
      sourceFilenames: ["20261NH-JGS51-B合并版.dwg"],
      taskKind: null,
      taskRole: null,
      jobMode: null,
      projectNo: "2026",
      status: "succeeded",
      stage: "GROUP_COMPLETE",
      percent: 100,
      message: "",
      createdAt: "2026-03-08T10:20:30+08:00",
      finishedAt: "2026-03-08T10:25:30+08:00",
      startedAt: "2026-03-08T10:21:30+08:00",
      currentFile: null,
      runAuditCheck: true,
      childJobIds: ["job-deliverable-1", "job-audit-1"],
      findingsCount: 9,
      affectedDrawingsCount: 5,
      topWrongTexts: [],
      topInternalCodes: [],
      flags: [],
      errors: [],
      artifacts: {
        packageAvailable: true,
        iedAvailable: true,
        reportAvailable: true,
        replacedDwgAvailable: false,
        packageDownloadUrl: "http://127.0.0.1:8000/api/jobs/group-1/download/package",
        iedDownloadUrl: "http://127.0.0.1:8000/api/jobs/group-1/download/ied",
        reportDownloadUrl: "http://127.0.0.1:8000/api/jobs/group-1/download/report",
        replacedDwgDownloadUrl: null,
      },
      retryAvailable: false,
      sharedRunId: null,
      children: [
        {
          jobId: "job-deliverable-1",
          batchId: "batch-1",
          groupId: "group-1",
          isGroup: false,
          sourceFilename: "20261NH-JGS51-B合并版.dwg",
          sourceFilenames: ["20261NH-JGS51-B合并版.dwg"],
          taskKind: "deliverable",
          taskRole: "deliverable_main",
          jobMode: "deliverable",
          projectNo: "2026",
          status: "succeeded",
          stage: "PACKAGE_ZIP",
          percent: 100,
          message: "",
          createdAt: "2026-03-08T10:20:30+08:00",
          finishedAt: "2026-03-08T10:25:00+08:00",
          runAuditCheck: false,
          childJobIds: [],
          findingsCount: 0,
          affectedDrawingsCount: 0,
          artifacts: {
            packageAvailable: true,
            iedAvailable: true,
            reportAvailable: false,
            replacedDwgAvailable: false,
            packageDownloadUrl: "http://127.0.0.1:8000/api/jobs/job-deliverable-1/download/package",
            iedDownloadUrl: "http://127.0.0.1:8000/api/jobs/job-deliverable-1/download/ied",
          },
          retryAvailable: false,
          sharedRunId: null,
          plotStyleKey: "same_width",
          plotResourceMode: "slot_private_with_shared_mirror",
          slotId: "slot-02",
          cadVersion: "AutoCAD 2024",
          accoreconsoleExe: "C:/Program Files/Autodesk/accoreconsole.exe",
          profileArg: "C:/slots/slot-02/profile.arg",
          pc3Path: "C:/slots/slot-02/pc3/fanban.pc3",
          pmpPath: "C:/slots/slot-02/pmp/fanban.pmp",
          ctbPath: "C:/slots/slot-02/plot styles/fanban_monochrome-same width.ctb",
        },
        {
          jobId: "job-audit-1",
          batchId: "batch-1",
          groupId: "group-1",
          isGroup: false,
          sourceFilename: "20261NH-JGS51-B合并版.dwg",
          sourceFilenames: ["20261NH-JGS51-B合并版.dwg"],
          taskKind: "audit_check",
          taskRole: "audit_check",
          jobMode: "check",
          projectNo: "2026",
          status: "succeeded",
          stage: "EXPORT_REPORT",
          percent: 100,
          message: "",
          createdAt: "2026-03-08T10:20:40+08:00",
          finishedAt: "2026-03-08T10:25:30+08:00",
          runAuditCheck: false,
          childJobIds: [],
          findingsCount: 9,
          affectedDrawingsCount: 5,
          artifacts: {
            packageAvailable: false,
            iedAvailable: false,
            reportAvailable: true,
            replacedDwgAvailable: false,
            reportDownloadUrl: "http://127.0.0.1:8000/api/jobs/job-audit-1/download/report",
          },
          retryAvailable: false,
          sharedRunId: null,
        },
      ],
    };
    });

    render(<App />);

    expect(await screen.findByText("任务包概览")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载任务包" })).toHaveAttribute(
      "href",
      "http://127.0.0.1:8000/api/jobs/group-1/download/package",
    );
    expect(screen.getByRole("link", { name: "下载 IED" })).toHaveAttribute(
      "href",
      "http://127.0.0.1:8000/api/jobs/group-1/download/ied",
    );
    expect(screen.getByRole("link", { name: "下载纠错报告" })).toHaveAttribute(
      "href",
      "http://127.0.0.1:8000/api/jobs/group-1/download/report",
    );
    expect(await screen.findByText("拆图结果")).toBeInTheDocument();
    expect(await screen.findByText(/A01\.dwg/)).toBeInTheDocument();
    expect(await screen.findByText(/A02\.pdf/)).toBeInTheDocument();
    expect(await screen.findByText(/2 页/)).toBeInTheDocument();
    expect(await screen.findByText("封面.docx")).toBeInTheDocument();
    expect(await screen.findByText("错误与图纸编号")).toBeInTheDocument();
    expect(await screen.findByText("2016")).toBeInTheDocument();
    expect(await screen.findByText("20261NH-JGS51-003")).toBeInTheDocument();
    expect(screen.queryByText("same_width")).not.toBeInTheDocument();
    expect(screen.queryByText(/fanban_monochrome-same width\.ctb/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看子任务 deliverable_main" })).toHaveAttribute(
      "href",
      "/jobs/job-deliverable-1",
    );
  });
});
