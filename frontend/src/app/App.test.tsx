import { render, screen, within } from "@testing-library/react";
import { waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { focusManager } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { act, useEffect, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import styles from "./App.module.css";

const mockPing = vi.fn();
const mockGetHealth = vi.fn();
const mockGetFormSchema = vi.fn();
const mockPreflightFonts = vi.fn();
const mockCreateBatch = vi.fn();
const mockCreateAuditCheck = vi.fn();
const mockCreateAuditReplace = vi.fn();
const mockListJobs = vi.fn();
const mockGetJobDetail = vi.fn();
const mockFetch = vi.fn();
const mockCreateObjectURL = vi.fn();
const mockRevokeObjectURL = vi.fn();
const mockPdfDocument = vi.fn();
const mockPdfPage = vi.fn();

vi.mock("react-pdf", () => ({
  pdfjs: {
    GlobalWorkerOptions: {
      workerSrc: "",
    },
  },
  Document: ({
    children,
    file,
    onLoadSuccess,
  }: {
    children: ReactNode;
    file?: unknown;
    onLoadSuccess?: (document: { numPages: number }) => void;
  }) => {
    useEffect(() => {
      onLoadSuccess?.({ numPages: 2 });
    }, [onLoadSuccess]);

    mockPdfDocument(file);
    return <div data-testid="pdf-document">{children}</div>;
  },
  Page: ({ pageNumber, width }: { pageNumber: number; width?: number }) => {
    mockPdfPage({ pageNumber, width });
    return <div data-testid={`pdf-page-${pageNumber}`}>PDF Page {pageNumber}</div>;
  },
}));

vi.mock("../platform/api/useApiAdapter", () => ({
  useApiAdapter: () => ({
    ping: mockPing,
    getHealth: mockGetHealth,
    getFormSchema: mockGetFormSchema,
    preflightFonts: mockPreflightFonts,
    createBatch: mockCreateBatch,
    createAuditCheck: mockCreateAuditCheck,
    createAuditReplace: mockCreateAuditReplace,
    listJobs: mockListJobs,
    getJobDetail: mockGetJobDetail,
  }),
}));

beforeEach(() => {
  window.history.pushState({}, "", "/");

  mockPing.mockReset();
  mockGetHealth.mockReset();
  mockGetFormSchema.mockReset();
  mockPreflightFonts.mockReset();
  mockCreateBatch.mockReset();
  mockCreateAuditCheck.mockReset();
  mockCreateAuditReplace.mockReset();
  mockListJobs.mockReset();
  mockGetJobDetail.mockReset();

  mockPing.mockResolvedValue({
    ok: true,
    serverTime: "2026-03-08T10:20:29+08:00",
  });
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
        ],
      },
    ],
    auditReplaceProjectOptions: ["2026", "1818"],
  });

  mockListJobs.mockResolvedValue({
    total: 0,
    items: [],
  });
  mockPreflightFonts.mockResolvedValue({
    files: [],
    replacementOptions: [],
    requiresConfirmation: false,
  });

  mockFetch.mockReset();
  mockFetch.mockResolvedValue({
    ok: true,
    arrayBuffer: () => Promise.resolve(new TextEncoder().encode("pdf-data").buffer),
  });
  mockCreateObjectURL.mockReset();
  mockCreateObjectURL.mockReturnValue("blob:preview");
  mockRevokeObjectURL.mockReset();
  mockPdfDocument.mockReset();
  mockPdfPage.mockReset();
  vi.stubGlobal("fetch", mockFetch);
  URL.createObjectURL = mockCreateObjectURL;
  URL.revokeObjectURL = mockRevokeObjectURL;
});

afterEach(() => {
  vi.useRealTimers();
  focusManager.setFocused(undefined);
  vi.unstubAllGlobals();
});

function makeSingleJob(index: number, sourceFilename: string) {
  return {
    jobId: `job-${index}`,
    batchId: `batch-${index}`,
    groupId: null,
    isGroup: false,
    sourceFilename,
    sourceFilenames: [sourceFilename],
    taskKind: "deliverable" as const,
    taskRole: null,
    jobMode: "deliverable",
    projectNo: "2026",
    status: "succeeded",
    stage: "PACKAGE_ZIP",
    percent: 100,
    message: "",
    createdAt: `2026-03-16T11:${String(index).padStart(2, "0")}:30+08:00`,
    finishedAt: "2026-03-16T11:20:30+08:00",
    runAuditCheck: false,
    childJobIds: [],
    findingsCount: 0,
    affectedDrawingsCount: 0,
    artifacts: {
      packageAvailable: true,
      iedAvailable: true,
      reportAvailable: false,
      replacedDwgAvailable: false,
      packageDownloadUrl: "/download/package",
      iedDownloadUrl: "/download/ied",
    },
    retryAvailable: false,
    sharedRunId: null,
  };
}

describe("homepage shell", () => {
  it("shows a clear loading state before form schema is ready", async () => {
    mockGetFormSchema.mockImplementation(() => new Promise(() => {}));

    render(<App />);

    const loadingButtons = await screen.findAllByRole("button", { name: "正在加载配置" });
    expect(loadingButtons).toHaveLength(2);
    loadingButtons.forEach((button) => {
      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("aria-busy", "true");
    });
  });

  it("does not show maintenance when a transient health check failure recovers", async () => {
    mockGetHealth
      .mockRejectedValueOnce(new Error("backend offline"))
      .mockResolvedValue({
        status: "ok",
        ready: true,
        storageWritable: true,
        workerAlive: true,
        queueDepth: 1,
        autocadReady: true,
        officeReady: true,
        serverTime: "2026-03-08T10:20:31+08:00",
      });

    render(<App />);

    expect(await screen.findByTestId("title-strip")).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.queryByText("后台维护升级中，为您带来的不便十分抱歉（＞人＜；）"),
      ).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "出图" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "纠错" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "翻版" })).toBeEnabled();
  });

  it("keeps entries available when ping succeeds but backend business health is not ready", async () => {
    mockGetHealth.mockResolvedValueOnce({
      status: "maintenance",
      ready: false,
      storageWritable: true,
      workerAlive: true,
      queueDepth: 0,
      autocadReady: true,
      officeReady: true,
      serverTime: "2026-03-24T10:20:30+08:00",
    });

    render(<App />);

    expect(await screen.findByText("后台业务健康异常")).toBeInTheDocument();
    expect(
      screen.queryByText("后台服务连接中断，请检查后端服务或代理配置。"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "出图" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "纠错" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "翻版" })).toBeEnabled();
  });

  it("shows connection interruption only after repeated ping failures without a recent success", async () => {
    mockPing.mockRejectedValue(new Error("backend offline"));

    render(<App />);

    expect(
      await screen.findByText("后台服务连接中断，请检查后端服务或代理配置。"),
    ).toBeInTheDocument();
    expect(mockPing).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("button", { name: "出图" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "纠错" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "翻版" })).toBeDisabled();
  });

  it("does not escalate a health probe failure while ping still succeeds", async () => {
    mockGetHealth.mockRejectedValue(new Error("health probe reset"));

    render(<App />);

    expect(await screen.findByText("后台健康检查重试中")).toBeInTheDocument();
    expect(screen.queryByText("后台业务健康异常")).not.toBeInTheDocument();
    expect(
      screen.queryByText("后台服务连接中断，请检查后端服务或代理配置。"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "出图" })).toBeEnabled();
  });

  it("renders the title strip, module toolbar, and primary actions", async () => {
    render(<App />);

    expect(await screen.findByTestId("title-strip")).toBeInTheDocument();
    expect(screen.getByTestId("title-strip-status")).toBeInTheDocument();
    expect(await screen.findAllByTestId("title-strip-status-item")).toHaveLength(5);
    expect(screen.getByText("中核工程-河北分公司-建筑结构所出图平台")).toBeInTheDocument();
    expect(screen.getByTestId("hero-watermark")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "教程" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "出图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "纠错" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "翻版" })).toBeInTheDocument();

    const toolbar = screen.getByTestId("module-toolbar");
    expect(within(toolbar).getByRole("button", { name: "业务模块" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(toolbar).getByRole("button", { name: "账号模块" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(within(toolbar).getByRole("button", { name: "工作量模块" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByTestId("module-business-panel")).toBeInTheDocument();
    expect(screen.getByTestId("recent-jobs-section")).toBeInTheDocument();
    expect(screen.queryByText("平台概览")).not.toBeInTheDocument();
    expect(screen.queryByText("账号模块预留")).not.toBeInTheDocument();
    expect(screen.queryByText("工作量模块预留")).not.toBeInTheDocument();
  });

  it("switches visible module panels from the toolbar", async () => {
    const user = userEvent.setup();
    render(<App />);

    const toolbar = await screen.findByTestId("module-toolbar");
    const accountButton = within(toolbar).getByRole("button", { name: "账号模块" });
    const workloadButton = within(toolbar).getByRole("button", { name: "工作量模块" });

    await user.click(accountButton);
    expect(screen.getByTestId("module-account-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("module-business-panel")).not.toBeInTheDocument();

    await user.click(workloadButton);
    expect(screen.getByTestId("module-workload-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("module-account-panel")).not.toBeInTheDocument();
  });

  it("shows task record labels and refresh feedback", async () => {
    render(<App />);

    expect(await screen.findByText("Task Record")).toBeInTheDocument();
    expect(screen.getByText("任务记录")).toBeInTheDocument();

    const user = userEvent.setup();
    const refreshButton = screen.getAllByRole("button", { name: "刷新" })[0];
    await user.click(refreshButton);

    expect(await screen.findByRole("button", { name: "已刷新" })).toBeInTheDocument();
  });

  it("opens the real replace workspace from the homepage", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "翻版" }));
    expect(await screen.findByRole("dialog", { name: "翻版配置" })).toBeInTheDocument();
  });

  it("opens tutorial mode and walks through the real deliverable flow preview", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "教程" }));

    expect(screen.getByText("当前为演示模式，不会创建真实任务，也不会改动任务记录。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一步" })).toBeInTheDocument();
    expect(screen.getByTestId("tutorial-target-entry")).toHaveAttribute(
      "data-tutorial-active",
      "true",
    );
    expect(screen.getByTestId("tutorial-spotlight")).toHaveAttribute("data-target", "entry");
    expect(document.body.style.overflow).toBe("hidden");
    expect(document.documentElement.style.scrollbarGutter).toBe("stable");

    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.queryByRole("dialog", { name: "教程文件选择" })).not.toBeInTheDocument();
    expect(screen.getByText(/点击“出图”后，浏览器会拉起系统文件选择窗口/)).toBeInTheDocument();
    expect(screen.getByTestId("tutorial-spotlight")).toHaveAttribute("data-target", "picker_select");

    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.queryByRole("dialog", { name: "教程任务配置" })).not.toBeInTheDocument();
    expect(await screen.findByRole("dialog", { name: "任务配置" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "创建交付任务" })).toBeInTheDocument();
    expect(
      screen.getByText("上传文件后直接在弹窗内完成配置。关闭不会丢失草稿；只有手动清空或提交成功后才会重置。"),
    ).toBeInTheDocument();
    await waitFor(() => {
      const spotlight = screen.queryByTestId("tutorial-spotlight");
      const dimmer = screen.queryByTestId("tutorial-dimmer");
      expect(spotlight || dimmer).not.toBeNull();
      if (spotlight) {
        expect(spotlight).toHaveAttribute("data-target", "config");
      }
    });

    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.queryByRole("dialog", { name: "教程任务记录" })).not.toBeInTheDocument();
    expect(screen.getByText("demo-2026-structural-package.dwg")).toBeInTheDocument();
    expect(screen.getByText("查看任务包")).toBeInTheDocument();
    expect(screen.getByTestId("tutorial-spotlight")).toHaveAttribute("data-target", "record");

    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.queryByRole("dialog", { name: "教程任务详情" })).not.toBeInTheDocument();
    expect(screen.getByText("任务包概览")).toBeInTheDocument();
    expect(screen.getByText("快捷下载")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载任务包" })).toBeInTheDocument();
    expect(screen.getByTestId("tutorial-spotlight")).toHaveAttribute("data-target", "detail");
    expect(screen.getByRole("button", { name: "下一步" })).toBeDisabled();

    await user.keyboard("{Escape}");
    expect(screen.queryByText("任务包概览")).not.toBeInTheDocument();
    expect(screen.queryByText("当前为演示模式，不会创建真实任务，也不会改动任务记录。")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tutorial-spotlight")).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe("");
    expect(document.documentElement.style.scrollbarGutter).toBe("");

    await user.click(screen.getByRole("button", { name: "教程" }));
    await user.click(screen.getByRole("button", { name: "下一步" }));
    await user.click(screen.getByRole("button", { name: "下一步" }));
    await user.click(screen.getByRole("button", { name: "下一步" }));
    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByText("任务包概览")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "退出" }));
    expect(screen.queryByText("任务包概览")).not.toBeInTheDocument();
    expect(screen.queryByText("当前为演示模式，不会创建真实任务，也不会改动任务记录。")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "教程文件选择" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "教程任务配置" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "教程任务记录" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("tutorial-spotlight")).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe("");
    expect(document.documentElement.style.scrollbarGutter).toBe("");
  });
});

describe("recent jobs area", () => {
  it("filters recent jobs by status and refreshes totals from the backend", async () => {
    const allJobs = [
      {
        ...makeSingleJob(1, "queued-job.dwg"),
        status: "queued" as const,
      },
      {
        ...makeSingleJob(2, "running-job.dwg"),
        status: "running" as const,
      },
      {
        ...makeSingleJob(3, "success-job.dwg"),
        status: "succeeded" as const,
      },
      {
        ...makeSingleJob(4, "failed-job.dwg"),
        status: "failed" as const,
      },
    ];
    mockListJobs.mockImplementation(async (status?: string) => {
      const items = status ? allJobs.filter((job) => job.status === status) : allJobs;
      return {
        total: items.length,
        items,
      };
    });

    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("success-job.dwg")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "排队中" }));
    expect(screen.getByRole("button", { name: "排队中" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText("queued-job.dwg")).toBeInTheDocument();
    expect(screen.queryByText("running-job.dwg")).not.toBeInTheDocument();
    expect(screen.queryByText("success-job.dwg")).not.toBeInTheDocument();
    expect(screen.queryByText("failed-job.dwg")).not.toBeInTheDocument();
    expect(mockListJobs).toHaveBeenCalledWith("queued", 0, 100);

    await user.click(screen.getByRole("button", { name: "成功" }));
    expect(screen.getByRole("button", { name: "成功" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText("success-job.dwg")).toBeInTheDocument();
    expect(screen.queryByText("queued-job.dwg")).not.toBeInTheDocument();
    expect(screen.queryByText("running-job.dwg")).not.toBeInTheDocument();
    expect(screen.queryByText("failed-job.dwg")).not.toBeInTheDocument();
    expect(mockListJobs).toHaveBeenCalledWith("succeeded", 0, 100);
  });

  it("shows eight cards by default and opens the rest in a modal", async () => {
    const jobs = Array.from({ length: 10 }, (_, index) =>
      makeSingleJob(index + 1, `sample-${index + 1}.dwg`),
    );
    mockListJobs.mockImplementation(async (_status?: string, offset = 0, limit = 100) => ({
      total: jobs.length,
      items: jobs.slice(offset, offset + limit),
    }));

    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findAllByTestId("recent-job-card")).toHaveLength(8);
    expect(screen.getByText("sample-10.dwg")).toBeInTheDocument();
    expect(screen.queryByText("sample-2.dwg")).not.toBeInTheDocument();

    const expandButton = screen.getByRole("button", { name: /2/ });
    await user.click(expandButton);

    const modal = await screen.findByRole("dialog");
    expect(within(modal).getByText("sample-2.dwg")).toBeInTheDocument();
    expect(within(modal).getByText("sample-1.dwg")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "全部任务浏览器" })).not.toBeInTheDocument();
  });

  it("uses total instead of fetched item count for the expand button", async () => {
    const jobs = Array.from({ length: 100 }, (_, index) =>
      makeSingleJob(index + 1, `sample-${index + 1}.dwg`),
    );
    mockListJobs.mockImplementation(async (_status?: string, offset = 0, limit = 100) => ({
      total: 369,
      items: jobs.slice(offset, offset + limit),
    }));

    render(<App />);

    expect(await screen.findAllByTestId("recent-job-card")).toHaveLength(8);
    expect(screen.getByRole("button", { name: "展开其余 361 个" })).toBeInTheDocument();
  });

  it("loads more jobs inside the modal so records after the first 100 are reachable", async () => {
    const jobs = Array.from({ length: 120 }, (_, index) =>
      makeSingleJob(index + 1, `sample-${index + 1}.dwg`),
    );
    mockListJobs.mockImplementation(async (_status?: string, offset = 0, limit = 100) => ({
      total: jobs.length,
      items: jobs.slice(offset, offset + limit),
    }));

    const user = userEvent.setup();
    render(<App />);

    await screen.findAllByTestId("recent-job-card");
    await user.click(screen.getByRole("button", { name: "展开其余 112 个" }));

    const modal = await screen.findByRole("dialog");
    expect(within(modal).queryByText("sample-120.dwg")).not.toBeInTheDocument();

    await user.click(within(modal).getByRole("button", { name: "加载更多（剩余 70 条）" }));
    await user.click(await within(modal).findByRole("button", { name: "加载更多（剩余 20 条）" }));

    await waitFor(() => {
      expect(within(modal).getByText("sample-120.dwg")).toBeInTheDocument();
    });
  });

  it("shows all matching jobs while searching", async () => {
    mockListJobs.mockResolvedValue({
      total: 8,
      items: [
        makeSingleJob(1, "sample-1.dwg"),
        makeSingleJob(2, "20261RS-JGS65.dwg"),
        makeSingleJob(3, "sample-3.dwg"),
        makeSingleJob(4, "18185NE-JGS11.dwg"),
        makeSingleJob(5, "sample-5.dwg"),
        makeSingleJob(6, "20261RS-JGS66.dwg"),
        makeSingleJob(7, "sample-7.dwg"),
        makeSingleJob(8, "sample-8.dwg"),
      ],
    });

    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("20261RS-JGS66.dwg")).toBeInTheDocument();

    await user.type(screen.getByRole("searchbox", { name: "搜索任务名称" }), "20261RS");

    expect(screen.getByText("20261RS-JGS65.dwg")).toBeInTheDocument();
    expect(screen.getByText("20261RS-JGS66.dwg")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /展开其余/ })).not.toBeInTheDocument();
  });
});

describe("job cards", () => {
  it("renders a task group as one package card with child links", async () => {
    mockListJobs.mockResolvedValue({
      total: 1,
      items: [
        {
          jobId: "group-1",
          batchId: "batch-1",
          groupId: "group-1",
          isGroup: true,
          sourceFilename: "18185NE-JGS11.dwg",
          sourceFilenames: ["18185NE-JGS11.dwg"],
          taskKind: null,
          taskRole: null,
          jobMode: null,
          projectNo: "1818",
          status: "running",
          stage: "DELIVERABLE_BRANCH",
          percent: 45,
          message: "",
          createdAt: "2026-03-16T10:20:30+08:00",
          finishedAt: null,
          runAuditCheck: true,
          childJobIds: ["deliverable-1", "audit-1"],
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

    mockGetJobDetail.mockResolvedValue({
      jobId: "group-1",
      batchId: "batch-1",
      groupId: "group-1",
      isGroup: true,
      sourceFilename: "18185NE-JGS11.dwg",
      sourceFilenames: ["18185NE-JGS11.dwg"],
      taskKind: null,
      taskRole: null,
      jobMode: null,
      projectNo: "1818",
      status: "running",
      stage: "DELIVERABLE_BRANCH",
      percent: 45,
      message: "",
      createdAt: "2026-03-16T10:20:30+08:00",
      finishedAt: null,
      runAuditCheck: true,
      childJobIds: ["deliverable-1", "audit-1"],
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
      startedAt: "2026-03-16T10:20:32+08:00",
      currentFile: null,
      topWrongTexts: [],
      topInternalCodes: [],
      flags: [],
      errors: [],
      children: [
        {
          ...makeSingleJob(1, "18185NE-JGS11.dwg"),
          jobId: "deliverable-1",
          batchId: "batch-1",
          groupId: "group-1",
          taskKind: "deliverable",
          taskRole: "deliverable_main",
          status: "running",
          stage: "GENERATE_DOCS",
          percent: 45,
          finishedAt: null,
        },
        {
          ...makeSingleJob(2, "18185NE-JGS11.dwg"),
          jobId: "audit-1",
          batchId: "batch-1",
          groupId: "group-1",
          taskKind: "audit_check",
          taskRole: "audit_check",
          status: "queued",
          stage: "AUDIT_CHECK",
          percent: 0,
          finishedAt: null,
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
    });

    render(<App />);

    expect(await screen.findByText("包含 2 个子任务")).toBeInTheDocument();
    expect(screen.getByText("任务包")).toBeInTheDocument();
    expect(screen.getAllByText("交付").length).toBeGreaterThan(0);
    expect(screen.getAllByText("纠错").length).toBeGreaterThan(0);
  });

  it("returns from a task group detail page with Escape", async () => {
    window.history.pushState({}, "", "/jobs/group-esc");
    mockGetJobDetail.mockResolvedValue({
      jobId: "group-esc",
      batchId: "batch-esc",
      groupId: "group-esc",
      isGroup: true,
      sourceFilename: "20261RC-JGS10-B - 副本.dwg",
      sourceFilenames: ["20261RC-JGS10-B - 副本.dwg"],
      taskKind: null,
      taskRole: null,
      jobMode: null,
      projectNo: "2026",
      status: "succeeded",
      stage: "GROUP_COMPLETE",
      percent: 100,
      message: "",
      createdAt: "2026-05-19T09:00:00+08:00",
      finishedAt: "2026-05-19T09:10:00+08:00",
      startedAt: "2026-05-19T09:00:10+08:00",
      currentFile: null,
      runAuditCheck: true,
      childJobIds: [],
      findingsCount: 0,
      affectedDrawingsCount: 0,
      artifacts: {
        packageAvailable: true,
        iedAvailable: true,
        previewAvailable: true,
        previewMode: "annotated",
        packageDownloadUrl: "/api/jobs/group-esc/download/package",
        iedDownloadUrl: "/api/jobs/group-esc/download/ied",
        previewDownloadUrl: "/api/jobs/group-esc/download/preview",
        reportAvailable: true,
        reportDownloadUrl: "/api/jobs/group-esc/download/report",
        replacedDwgAvailable: false,
      },
      retryAvailable: false,
      sharedRunId: null,
      flags: [],
      errors: [],
      topWrongTexts: [],
      topInternalCodes: [],
      children: [],
    });

    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("任务包概览")).toBeInTheDocument();
    await user.keyboard("{Escape}");

    expect(screen.queryByText("任务包概览")).not.toBeInTheDocument();
    expect(await screen.findByTestId("module-business-panel")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");
  });

  it("renders categorized diagnostics on task group detail pages", async () => {
    window.history.pushState({}, "", "/jobs/group-diagnostics");
    mockGetJobDetail.mockResolvedValue({
      jobId: "group-diagnostics",
      batchId: "batch-diagnostics",
      groupId: "group-diagnostics",
      isGroup: true,
      sourceFilename: "18185NP-JGS44仅拆图.dwg",
      sourceFilenames: ["18185NP-JGS44仅拆图.dwg"],
      taskKind: null,
      taskRole: null,
      jobMode: null,
      projectNo: "1818",
      status: "failed",
      stage: "GROUP_COMPLETE",
      percent: 100,
      message: "",
      createdAt: "2026-06-17T17:46:26+08:00",
      finishedAt: "2026-06-17T17:47:34+08:00",
      startedAt: "2026-06-17T17:46:26+08:00",
      currentFile: null,
      runAuditCheck: false,
      childJobIds: [],
      findingsCount: 0,
      affectedDrawingsCount: 0,
      artifacts: {
        packageAvailable: true,
        iedAvailable: false,
        reportAvailable: false,
        replacedDwgAvailable: false,
      },
      retryAvailable: false,
      sharedRunId: null,
      flags: ["CAD结果错误:检测到重复编码"],
      errors: [],
      diagnostics: [
        {
          kind: "duplicate_code",
          severity: "error",
          title: "检测到重复编码",
          summary: "发现 0 个重复内部编码、2 个重复外部编码。",
          suggestion: "请检查图签中的内部编码/外部编码。",
          details: [
            {
              label: "外部编码 PC5NPM12004B25C42SD",
              items: ["18185NP-JGS44-024", "18185NP-JGS44-026"],
            },
            {
              label: "外部编码 PC5NPM12004B25C42MD",
              items: ["18185NP-JGS44-025", "18185NP-JGS44-027"],
            },
          ],
          rawItems: ["CAD结果错误:检测到重复编码"],
        },
      ],
      topWrongTexts: [],
      topInternalCodes: [],
      children: [],
    });

    render(<App />);

    expect(await screen.findByRole("heading", { level: 2, name: "问题原因" })).toBeInTheDocument();
    expect(screen.getByText("检测到重复编码")).toBeInTheDocument();
    expect(screen.getByText("外部编码 PC5NPM12004B25C42SD")).toBeInTheDocument();
    expect(screen.getByText("18185NP-JGS44-024")).toBeInTheDocument();
    expect(screen.getByText("18185NP-JGS44-026")).toBeInTheDocument();
  });

  it("shows a completed single deliverable job with a detail link", async () => {
    mockListJobs.mockResolvedValue({
      total: 1,
      items: [makeSingleJob(1, "20261RS-JGS65.dwg")],
    });

    render(<App />);

    expect(await screen.findByText("出图完成")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看任务" })).toBeInTheDocument();
  });

  it("prioritizes the real failure reason over the last completed stage", async () => {
    mockListJobs.mockResolvedValue({
      total: 1,
      items: [
        {
          ...makeSingleJob(1, "20162SD-JGS03-出图.dwg"),
          status: "failed",
          stage: "A4_MULTIPAGE_GROUPING",
          percent: 60,
          message: "完成阶段: A4_MULTIPAGE_GROUPING",
          failureReason: "服务重启/中断，任务未完成",
          stageContext: "中断前最后完成阶段：A4 多页合并",
        },
      ],
    });

    render(<App />);

    expect(await screen.findByText("服务重启/中断，任务未完成")).toBeInTheDocument();
    expect(screen.getByText("中断前最后完成阶段：A4 多页合并")).toBeInTheDocument();
    expect(screen.queryByText("完成阶段: A4_MULTIPAGE_GROUPING")).not.toBeInTheDocument();
  });
});

describe("job detail pages", () => {
  it("moves merged annotated PDF download to group quick downloads and hides child download buttons", async () => {
    window.history.pushState({}, "", "/jobs/group-downloads");
    const clipboardWrite = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: clipboardWrite },
    });
    const groupDetail = {
      jobId: "group-downloads",
      batchId: "batch-downloads",
      groupId: "group-downloads",
      isGroup: true,
      sourceFilename: "20261RC-JGS10-B.dwg",
      sourceFilenames: ["20261RC-JGS10-B.dwg"],
      taskKind: null,
      taskRole: null,
      jobMode: null,
      projectNo: "2026",
      status: "succeeded",
      stage: "GROUP_COMPLETE",
      percent: 100,
      message: "",
      createdAt: "2026-05-28T09:00:00+08:00",
      finishedAt: "2026-05-28T09:10:00+08:00",
      startedAt: "2026-05-28T09:00:10+08:00",
      currentFile: null,
      runAuditCheck: true,
      childJobIds: ["deliverable-child", "audit-child"],
      findingsCount: 2,
      affectedDrawingsCount: 1,
      artifacts: {
        packageAvailable: true,
        iedAvailable: true,
        previewAvailable: true,
        previewMode: "annotated",
        packageDownloadUrl: "/api/jobs/group-downloads/download/package",
        iedDownloadUrl: "/api/jobs/group-downloads/download/ied",
        previewDownloadUrl: "/api/jobs/group-downloads/download/preview",
        reportAvailable: true,
        reportDownloadUrl: "/api/jobs/group-downloads/download/report",
        replacedDwgAvailable: false,
      },
      retryAvailable: false,
      sharedRunId: null,
      workload: {
        initialWorkloadA1: 3.25,
        finalWorkloadA1: 3.25,
        oneReviewFactor: 1,
        twoReviewFactor: 1,
        threeReviewFactor: 1,
        settlementStatus: "pending",
        settledAt: null,
      },
      effectiveWorkload: 3.25,
      flags: [],
      errors: [],
      topWrongTexts: [],
      topInternalCodes: [],
      children: [
        {
          ...makeSingleJob(1, "20261RC-JGS10-B.dwg"),
          jobId: "deliverable-child",
          batchId: "batch-downloads",
          groupId: "group-downloads",
          taskKind: "deliverable" as const,
          taskRole: "deliverable_main",
          artifacts: {
            packageAvailable: true,
            iedAvailable: true,
            previewAvailable: true,
            previewMode: "plain",
            packageDownloadUrl: "/api/jobs/deliverable-child/download/package",
            iedDownloadUrl: "/api/jobs/deliverable-child/download/ied",
            previewDownloadUrl: "/api/jobs/deliverable-child/download/preview",
            reportAvailable: false,
            replacedDwgAvailable: false,
          },
        },
        {
          ...makeSingleJob(2, "20261RC-JGS10-B.dwg"),
          jobId: "audit-child",
          batchId: "batch-downloads",
          groupId: "group-downloads",
          taskKind: "audit_check" as const,
          taskRole: "audit_check",
          findingsCount: 2,
          affectedDrawingsCount: 1,
          artifacts: {
            packageAvailable: false,
            iedAvailable: false,
            previewAvailable: true,
            previewMode: "annotated",
            previewDownloadUrl: "/api/jobs/audit-child/download/preview",
            reportAvailable: true,
            reportDownloadUrl: "/api/jobs/audit-child/download/report",
            replacedDwgAvailable: false,
          },
        },
      ],
    };

    mockGetJobDetail.mockImplementation((jobId: string) => {
      if (jobId === "deliverable-child") {
        return Promise.resolve(groupDetail.children[0]);
      }
      if (jobId === "audit-child") {
        return Promise.resolve(groupDetail.children[1]);
      }
      return Promise.resolve(groupDetail);
    });

    render(<App />);

    expect(await screen.findByRole("heading", { level: 2, name: "快捷下载" })).toBeInTheDocument();
    const mergedPdfDownload = screen.getByRole("link", { name: "下载合并版PDF" });
    expect(mergedPdfDownload).toHaveAttribute(
      "href",
      "/api/jobs/group-downloads/download/preview",
    );
    expect(screen.getByRole("button", { name: "预览 PDF（纠错标注）" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载任务包" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载 IED" })).toBeInTheDocument();
    expect(screen.getByText("图纸量（A1等效）")).toBeInTheDocument();
    expect(screen.getByText("3.25")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "复制张数" }));
    expect(clipboardWrite).toHaveBeenCalledWith("3.25");
    expect(screen.getByRole("button", { name: "已复制" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "查看子任务 deliverable_main" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看子任务 audit_check" })).toBeInTheDocument();

    expect(screen.queryByRole("button", { name: "预览子任务 PDF" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "预览子任务 PDF（纠错标注）" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "下载子任务 package.zip" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "下载子任务 IED计划.xlsx" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "下载子任务 report.xlsx" })).not.toBeInTheDocument();
  });

  it("shows drawing quantity for deliverable-only groups from child workload", async () => {
    window.history.pushState({}, "", "/jobs/group-deliverable-quantity");
    const clipboardWrite = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: clipboardWrite },
    });

    const deliverableChild = {
      ...makeSingleJob(11, "18185NF-JGS19-A.dwg"),
      jobId: "deliverable-only-child",
      batchId: "batch-deliverable-only",
      groupId: "group-deliverable-quantity",
      taskKind: "deliverable" as const,
      taskRole: "deliverable_main",
      workload: {
        initialWorkloadA1: 6.5,
        finalWorkloadA1: 6.5,
        oneReviewFactor: 1,
        twoReviewFactor: 1,
        threeReviewFactor: 1,
        settlementStatus: "pending",
        settledAt: null,
      },
      effectiveWorkload: 6.5,
    };

    const groupDetail = {
      ...makeSingleJob(10, "18185NF-JGS19-A.dwg"),
      jobId: "group-deliverable-quantity",
      batchId: "batch-deliverable-only",
      groupId: "group-deliverable-quantity",
      isGroup: true,
      taskKind: null,
      taskRole: null,
      jobMode: null,
      stage: "GROUP_COMPLETE",
      runAuditCheck: false,
      childJobIds: ["deliverable-only-child"],
      artifacts: {
        packageAvailable: true,
        iedAvailable: true,
        previewAvailable: false,
        packageDownloadUrl: "/api/jobs/group-deliverable-quantity/download/package",
        iedDownloadUrl: "/api/jobs/group-deliverable-quantity/download/ied",
        reportAvailable: false,
        replacedDwgAvailable: false,
      },
      workload: null,
      effectiveWorkload: 0,
      children: [deliverableChild],
      startedAt: "2026-05-28T09:00:10+08:00",
      currentFile: null,
      flags: [],
      errors: [],
      topWrongTexts: [],
      topInternalCodes: [],
    };

    mockGetJobDetail.mockImplementation((jobId: string) =>
      Promise.resolve(jobId === "deliverable-only-child" ? deliverableChild : groupDetail),
    );

    render(<App />);

    expect(await screen.findByRole("heading", { level: 2, name: "快捷下载" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载任务包" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载 IED" })).toBeInTheDocument();
    expect(screen.getByText("图纸量（A1等效）")).toBeInTheDocument();
    expect(screen.getByText("6.5")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "复制张数" }));
    expect(clipboardWrite).toHaveBeenCalledWith("6.5");
  });

  it("shows drawing quantity in single split-only job quick downloads", async () => {
    window.history.pushState({}, "", "/jobs/split-only-quantity");
    const clipboardWrite = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: clipboardWrite },
    });
    mockGetJobDetail.mockResolvedValue({
      ...makeSingleJob(1, "18185NF-JGS19-A.dwg"),
      jobId: "split-only-quantity",
      batchId: "batch-split-only-quantity",
      taskKind: "deliverable",
      jobMode: "split_only",
      taskRole: "仅拆图",
      artifacts: {
        packageAvailable: true,
        iedAvailable: false,
        reportAvailable: false,
        replacedDwgAvailable: false,
        packageDownloadUrl: "/api/jobs/split-only-quantity/download/package",
      },
      workload: {
        initialWorkloadA1: 6.5,
        finalWorkloadA1: 6.5,
        oneReviewFactor: 1,
        twoReviewFactor: 1,
        threeReviewFactor: 1,
        settlementStatus: "pending",
        settledAt: null,
      },
      effectiveWorkload: 6.5,
      startedAt: "2026-05-28T09:00:10+08:00",
      currentFile: null,
      flags: [],
      errors: [],
      topWrongTexts: [],
      topInternalCodes: [],
      deliverableOutputs: {
        dwgCount: 1,
        pdfCount: 1,
        documents: [],
        drawings: [
          {
            name: "18185NF-JGS19-001",
            internalCode: "18185NF-JGS19-001",
            dwgName: "18185NF-JGS19-001.dwg",
            pdfName: "18185NF-JGS19-001.pdf",
            pageTotal: 1,
          },
        ],
      },
    });

    render(<App />);

    expect(await screen.findByRole("heading", { level: 2, name: "快捷下载" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载 package.zip" })).toBeInTheDocument();
    expect(screen.getByText("图纸量（A1等效）")).toBeInTheDocument();
    expect(screen.getByText("6.5")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "复制张数" }));
    expect(clipboardWrite).toHaveBeenCalledWith("6.5");
  });

  it("shows drawing quantity in single audit-check job quick downloads", async () => {
    window.history.pushState({}, "", "/jobs/audit-check-quantity");
    mockGetJobDetail.mockResolvedValue({
      ...makeSingleJob(2, "18185NF-JGS19-A.dwg"),
      jobId: "audit-check-quantity",
      batchId: "batch-audit-check-quantity",
      taskKind: "audit_check",
      jobMode: "check",
      taskRole: "audit_check",
      artifacts: {
        packageAvailable: false,
        iedAvailable: false,
        previewAvailable: true,
        previewMode: "annotated",
        previewDownloadUrl: "/api/jobs/audit-check-quantity/download/preview",
        reportAvailable: true,
        reportDownloadUrl: "/api/jobs/audit-check-quantity/download/report",
        replacedDwgAvailable: false,
      },
      workload: {
        initialWorkloadA1: 1,
        finalWorkloadA1: 1,
        oneReviewFactor: 1,
        twoReviewFactor: 1,
        threeReviewFactor: 1,
        settlementStatus: "pending",
        settledAt: null,
      },
      effectiveWorkload: 1,
      startedAt: "2026-05-28T09:00:10+08:00",
      currentFile: null,
      flags: [],
      errors: [],
      topWrongTexts: [],
      topInternalCodes: [],
      findingGroups: [],
    });

    render(<App />);

    expect(await screen.findByRole("heading", { level: 2, name: "快捷下载" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "预览 PDF（纠错标注）" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载 report.xlsx" })).toBeInTheDocument();
    expect(screen.getByText("图纸量（A1等效）")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("shows a clean font summary when no missing fonts were detected for deliverable jobs", async () => {
    window.history.pushState({}, "", "/jobs/deliverable-font-ok");
    mockGetJobDetail.mockResolvedValue({
      jobId: "deliverable-font-ok",
      batchId: "batch-deliverable-font-ok",
      groupId: null,
      isGroup: false,
      sourceFilename: "A01.dwg",
      sourceFilenames: ["A01.dwg"],
      taskKind: "deliverable",
      taskRole: null,
      jobMode: "deliverable",
      projectNo: "2016",
      status: "succeeded",
      stage: "PACKAGE_ZIP",
      percent: 100,
      message: "",
      createdAt: "2026-03-24T14:00:00+08:00",
      finishedAt: "2026-03-24T14:05:00+08:00",
      startedAt: "2026-03-24T14:00:10+08:00",
      currentFile: null,
      runAuditCheck: false,
      childJobIds: [],
      findingsCount: 0,
      affectedDrawingsCount: 0,
      artifacts: {
        packageAvailable: true,
        iedAvailable: true,
        reportAvailable: false,
        replacedDwgAvailable: false,
        packageDownloadUrl: "/api/jobs/deliverable-font-ok/download/package",
        iedDownloadUrl: "/api/jobs/deliverable-font-ok/download/ied",
      },
      retryAvailable: false,
      sharedRunId: null,
      flags: [],
      errors: [],
      topWrongTexts: [],
      topInternalCodes: [],
      deliverableOutputs: {
        dwgCount: 1,
        pdfCount: 1,
        documents: [{ name: "IED.xlsx", kind: "xlsx" }],
        drawings: [
          {
            name: "A01",
            internalCode: "20161RS-JGS01-001",
            dwgName: "A01.dwg",
            pdfName: "A01.pdf",
            pageTotal: 1,
          },
        ],
      },
      fontPreflightSummary: {
        files: [
          {
            filename: "A01.dwg",
            status: "ok",
            missingFonts: [],
            detectedStyleCount: 12,
            missingStyleCount: 0,
            fontReplacementApplied: false,
            replacementFont: null,
            replacedStyleCount: 0,
            errors: [],
          },
        ],
        policy: "none",
      },
      missingFontsDetected: false,
      fontReplacementApplied: false,
      replacementFont: null,
      replacedStyleCount: 0,
    });

    render(<App />);

    expect(await screen.findByText("字体处理摘要")).toBeInTheDocument();
    expect(screen.getAllByText("未检测到缺失字体").length).toBeGreaterThan(0);
  });

  it("shows replacement font details when deliverable jobs applied missing-font replacement", async () => {
    window.history.pushState({}, "", "/jobs/deliverable-font-replaced");
    mockGetJobDetail.mockResolvedValue({
      jobId: "deliverable-font-replaced",
      batchId: "batch-deliverable-font-replaced",
      groupId: null,
      isGroup: false,
      sourceFilename: "A01.dwg",
      sourceFilenames: ["A01.dwg"],
      taskKind: "deliverable",
      taskRole: null,
      jobMode: "deliverable",
      projectNo: "2016",
      status: "succeeded",
      stage: "PACKAGE_ZIP",
      percent: 100,
      message: "",
      createdAt: "2026-03-24T14:10:00+08:00",
      finishedAt: "2026-03-24T14:20:00+08:00",
      startedAt: "2026-03-24T14:10:10+08:00",
      currentFile: null,
      runAuditCheck: false,
      childJobIds: [],
      findingsCount: 0,
      affectedDrawingsCount: 0,
      artifacts: {
        packageAvailable: true,
        iedAvailable: true,
        reportAvailable: false,
        replacedDwgAvailable: false,
        packageDownloadUrl: "/api/jobs/deliverable-font-replaced/download/package",
        iedDownloadUrl: "/api/jobs/deliverable-font-replaced/download/ied",
      },
      retryAvailable: false,
      sharedRunId: null,
      errors: [],
      topWrongTexts: [],
      topInternalCodes: [],
      deliverableOutputs: {
        dwgCount: 1,
        pdfCount: 1,
        documents: [{ name: "IED.xlsx", kind: "xlsx" }],
        drawings: [
          {
            name: "A01",
            internalCode: "20161RS-JGS01-001",
            dwgName: "A01.dwg",
            pdfName: "A01.pdf",
            pageTotal: 1,
          },
        ],
      },
      fontPreflightSummary: {
        files: [
          {
            filename: "A01.dwg",
            status: "missing_fonts",
            missingFonts: [
              {
                styleName: "HZTXT",
                fontName: "missing.shx",
                bigfontName: "",
                kind: "shx",
                usedInBlock: true,
              },
            ],
            detectedStyleCount: 12,
            missingStyleCount: 1,
            replacedStyleCount: 3,
            replacementFont: "simplex.shx",
            replacementFonts: {
              shx: "simplex.shx",
              ttf: "simsun.ttc",
            },
            fontReplacementApplied: true,
            verifyAfterReplace: {
              status: "missing_fonts",
              missingStyleCount: 1,
              missingFonts: [
                {
                  styleName: "正文",
                  fontName: "missing.ttf",
                  bigfontName: "",
                  kind: "ttf",
                  usedInBlock: false,
                },
              ],
            },
            fontReplacementIncomplete: true,
            errors: [],
          },
        ],
        policy: "replace_missing",
        replacementFonts: {
          shx: "simplex.shx",
          ttf: "simsun.ttc",
        },
        fontMapPath: "E:/cache/font_map.json",
        fontAlt: "use_simsun_for_ttf",
      },
      missingFontsDetected: true,
      fontReplacementApplied: true,
      replacementFont: "simplex.shx",
      replacementFonts: {
        shx: "simplex.shx",
        ttf: "simsun.ttc",
      },
      replacedStyleCount: 3,
      flags: ["FONT_REPLACEMENT_INCOMPLETE"],
    });

    render(<App />);

    expect(await screen.findByText("字体处理摘要")).toBeInTheDocument();
    expect(screen.getByText("已执行缺失字体替代")).toBeInTheDocument();
    expect(screen.getByText("simplex.shx")).toBeInTheDocument();
    expect(screen.getByText("simsun.ttc")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(
      screen.getByText("字体已尝试替代，但关键字体可能仍未完全恢复，建议优先补齐原始字体文件。"),
    ).toBeInTheDocument();
    expect(screen.getByText("E:/cache/font_map.json")).toBeInTheDocument();
  });

  it("opens an in-page preview modal when preview pdf is available", async () => {
    window.history.pushState({}, "", "/jobs/audit-preview");
    mockGetJobDetail.mockResolvedValue({
      jobId: "audit-preview",
      batchId: "batch-audit-preview",
      groupId: null,
      isGroup: false,
      sourceFilename: "A01.dwg",
      sourceFilenames: ["A01.dwg"],
      taskKind: "audit_check",
      taskRole: null,
      jobMode: "check",
      projectNo: "2016",
      status: "succeeded",
      stage: "EXPORT_REPORT",
      percent: 100,
      message: "",
      createdAt: "2026-04-17T10:00:00+08:00",
      finishedAt: "2026-04-17T10:03:00+08:00",
      startedAt: "2026-04-17T10:00:10+08:00",
      currentFile: null,
      runAuditCheck: false,
      childJobIds: [],
      findingsCount: 2,
      affectedDrawingsCount: 1,
      artifacts: {
        packageAvailable: false,
        iedAvailable: false,
        previewAvailable: true,
        previewMode: "annotated",
        previewDownloadUrl: "/api/jobs/audit-preview/download/preview",
        reportAvailable: true,
        replacedDwgAvailable: false,
        reportDownloadUrl: "/api/jobs/audit-preview/download/report",
      },
      retryAvailable: false,
      sharedRunId: null,
      flags: [],
      errors: [],
      topWrongTexts: ["JD"],
      topInternalCodes: ["20261RS-JGS65-001"],
      findingGroups: [
        {
          matchedText: "JD",
          count: 2,
          internalCodes: ["20261RS-JGS65-001"],
        },
      ],
    });

    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "预览 PDF（纠错标注）" }));

    expect(await screen.findByRole("dialog", { name: "预览 PDF（纠错标注）" })).toBeInTheDocument();
    const downloadLink = screen.getByRole("link", { name: "下载预览 PDF" });
    expect(downloadLink).toHaveAttribute("href", "/api/jobs/audit-preview/download/preview");
    expect(downloadLink).toHaveAttribute("download");
    expect(mockFetch).toHaveBeenCalledWith("/api/jobs/audit-preview/download/preview", expect.any(Object));
    expect(await screen.findByTestId("pdf-document")).toBeInTheDocument();
    expect(mockPdfDocument).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.any(Uint8Array),
      }),
    );
    expect(screen.getByText("共 2 页")).toBeInTheDocument();
    const zoomControls = within(screen.getByLabelText("PDF 局部缩放"));
    expect(zoomControls.getByText("局部缩放")).toBeInTheDocument();
    expect(zoomControls.getByText("100%")).toBeInTheDocument();
    expect(mockPdfPage).toHaveBeenCalledWith(expect.objectContaining({ pageNumber: 1, width: 320 }));
    await user.click(zoomControls.getByRole("button", { name: "放大" }));
    expect(zoomControls.getByText("125%")).toBeInTheDocument();
    await waitFor(() => {
      expect(mockPdfPage).toHaveBeenCalledWith(
        expect.objectContaining({ pageNumber: 1, width: 400 }),
      );
    });
    await user.click(zoomControls.getByRole("button", { name: "放大" }));
    expect(zoomControls.getByText("150%")).toBeInTheDocument();
    await waitFor(() => {
      expect(mockPdfPage).toHaveBeenCalledWith(
        expect.objectContaining({ pageNumber: 1, width: 480 }),
      );
    });
    await user.click(zoomControls.getByRole("button", { name: "缩小" }));
    expect(zoomControls.getByText("125%")).toBeInTheDocument();
    fireEvent.wheel(screen.getByTestId("pdf-page-1"), { deltaY: -120 });
    expect(zoomControls.getByText("125%")).toBeInTheDocument();
    fireEvent.wheel(screen.getByLabelText("PDF 预览页面"), { ctrlKey: true, deltaY: -120 });
    expect(zoomControls.getByText("150%")).toBeInTheDocument();
    fireEvent.wheel(screen.getByLabelText("PDF 预览页面"), { ctrlKey: true, deltaY: 120 });
    expect(zoomControls.getByText("125%")).toBeInTheDocument();
    expect(screen.getByLabelText("PDF 横向拖动条")).toBeDisabled();
    const previewPages = screen.getByLabelText("PDF 预览页面");
    Object.defineProperties(previewPages, {
      clientWidth: { configurable: true, value: 300 },
      scrollWidth: { configurable: true, value: 900 },
    });
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });
    fireEvent.scroll(previewPages);
    const horizontalSlider = await screen.findByLabelText("PDF 横向拖动条");
    expect(
      horizontalSlider.compareDocumentPosition(previewPages) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(horizontalSlider).toHaveAttribute("max", "600");
    expect(horizontalSlider).not.toBeDisabled();
    fireEvent.change(horizontalSlider, { target: { value: "260" } });
    expect(previewPages.scrollLeft).toBe(260);
    expect(screen.getByTestId("pdf-page-1")).toBeInTheDocument();
    expect(screen.queryByTitle("预览 PDF（纠错标注）")).not.toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "预览 PDF（纠错标注）" })).not.toBeInTheDocument();
  });

  it("shows an explicit fallback message when the preview PDF cannot be loaded", async () => {
    window.history.pushState({}, "", "/jobs/audit-preview");
    mockGetJobDetail.mockResolvedValue({
      jobId: "audit-preview",
      batchId: "batch-audit-preview",
      groupId: null,
      isGroup: false,
      sourceFilename: "Drawing2.dwg",
      sourceFilenames: ["Drawing2.dwg"],
      taskKind: "audit_check",
      taskRole: null,
      jobMode: "check",
      projectNo: "2026",
      status: "succeeded",
      stage: "EXPORT_REPORT",
      percent: 100,
      message: "",
      createdAt: "2026-04-08T09:00:00+08:00",
      finishedAt: "2026-04-08T09:02:00+08:00",
      startedAt: "2026-04-08T09:00:10+08:00",
      currentFile: null,
      runAuditCheck: false,
      childJobIds: [],
      findingsCount: 2,
      affectedDrawingsCount: 1,
      artifacts: {
        packageAvailable: false,
        iedAvailable: false,
        previewAvailable: true,
        previewMode: "annotated",
        previewDownloadUrl: "/api/jobs/audit-preview/download/preview",
        reportAvailable: true,
        replacedDwgAvailable: false,
        reportDownloadUrl: "/api/jobs/audit-preview/download/report",
      },
      retryAvailable: false,
      sharedRunId: null,
      flags: [],
      errors: [],
      topWrongTexts: ["JD"],
      topInternalCodes: ["20261RS-JGS65-001"],
      findingGroups: [
        {
          matchedText: "JD",
          count: 2,
          internalCodes: ["20261RS-JGS65-001"],
        },
      ],
    });
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      blob: () => Promise.resolve(new Blob()),
    });

    const user = userEvent.setup();
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    try {
      render(<App />);

      await user.click(await screen.findByRole("button", { name: "预览 PDF（纠错标注）" }));

      expect(await screen.findByText("预览加载失败")).toBeInTheDocument();
      expect(await screen.findByText("PDF 预览加载失败，请使用新窗口打开查看。")).toBeInTheDocument();
    } finally {
      consoleError.mockRestore();
    }
  });

  it("shows standard review category, summary, and details in audit results", async () => {
    window.history.pushState({}, "", "/jobs/audit-standard-review");
    mockGetJobDetail.mockResolvedValue({
      jobId: "audit-standard-review",
      batchId: "batch-audit-standard-review",
      groupId: null,
      isGroup: false,
      sourceFilename: "A01.dwg",
      sourceFilenames: ["A01.dwg"],
      taskKind: "audit_check",
      taskRole: null,
      jobMode: "check",
      projectNo: "2016",
      status: "succeeded",
      stage: "EXPORT_REPORT",
      percent: 100,
      message: "",
      createdAt: "2026-04-17T10:00:00+08:00",
      finishedAt: "2026-04-17T10:03:00+08:00",
      startedAt: "2026-04-17T10:00:10+08:00",
      currentFile: null,
      runAuditCheck: false,
      childJobIds: [],
      findingsCount: 1,
      affectedDrawingsCount: 1,
      artifacts: {
        packageAvailable: false,
        iedAvailable: false,
        previewAvailable: false,
        reportAvailable: true,
        reportDownloadUrl: "/api/jobs/audit-standard-review/download/report",
        replacedDwgAvailable: false,
      },
      retryAvailable: false,
      sharedRunId: null,
      flags: [],
      errors: [],
      topWrongTexts: ["GB 51058-2011"],
      topInternalCodes: ["18185NF-JGS19-003"],
      findingGroups: [
        {
          matchedText: "GB 51058-2011",
          count: 1,
          internalCodes: ["18185NF-JGS19-003"],
          category: "规范审查",
          contextKind: "standard_review_year",
          issueType: "year_mismatch",
          summary: "标准号年限不一致：GB 51058-2011 应为 GB 51058-2014",
          details: [
            "实际标准号：GB 51058-2011",
            "期望标准号：GB 51058-2014",
            "期望标准名称：核电厂抗震设计标准",
          ],
        },
      ],
    });

    render(<App />);

    expect(await screen.findByRole("heading", { level: 3, name: "错误与图纸编号" })).toBeInTheDocument();
    expect(screen.getByText("规范审查")).toBeInTheDocument();
    expect(screen.getByText("标准号年限不一致：GB 51058-2011 应为 GB 51058-2014")).toBeInTheDocument();
    expect(screen.getByText("实际标准号：GB 51058-2011")).toBeInTheDocument();
    expect(screen.getByText("期望标准号：GB 51058-2014")).toBeInTheDocument();
    expect(screen.getByText("期望标准名称：核电厂抗震设计标准")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "规范审查" })).not.toBeInTheDocument();
  });

  it("shows same-code multipage guidance and preserves X@Y filenames in deliverable results", async () => {
    window.history.pushState({}, "", "/jobs/deliverable-multipage");
    mockGetJobDetail.mockResolvedValue({
      jobId: "deliverable-multipage",
      batchId: "batch-deliverable-multipage",
      groupId: null,
      isGroup: false,
      sourceFilename: "Drawing2.dwg",
      sourceFilenames: ["Drawing2.dwg"],
      taskKind: "deliverable",
      taskRole: null,
      jobMode: "deliverable",
      projectNo: "2016",
      status: "succeeded",
      stage: "PACKAGE_ZIP",
      percent: 100,
      message: "",
      createdAt: "2026-04-02T09:00:00+08:00",
      finishedAt: "2026-04-02T09:10:00+08:00",
      startedAt: "2026-04-02T09:00:10+08:00",
      currentFile: null,
      runAuditCheck: false,
      childJobIds: [],
      findingsCount: 0,
      affectedDrawingsCount: 0,
      artifacts: {
        packageAvailable: true,
        iedAvailable: true,
        reportAvailable: false,
        replacedDwgAvailable: false,
        packageDownloadUrl: "/api/jobs/deliverable-multipage/download/package",
        iedDownloadUrl: "/api/jobs/deliverable-multipage/download/ied",
      },
      retryAvailable: false,
      sharedRunId: null,
      flags: [],
      errors: [],
      topWrongTexts: [],
      topInternalCodes: [],
      deliverableOutputs: {
        dwgCount: 1,
        pdfCount: 1,
        documents: [],
        drawings: [
          {
            name: "JD2RSG11005B25C42SDACFC1@2 (20162RS-JGS03-005)",
            internalCode: "20162RS-JGS03-005",
            dwgName: "JD2RSG11005B25C42SDACFC1@2 (20162RS-JGS03-005).dwg",
            pdfName: "JD2RSG11005B25C42SDACFC1@2 (20162RS-JGS03-005).pdf",
            pageTotal: 1,
          },
        ],
      },
      missingFontsDetected: false,
      fontReplacementApplied: false,
      replacementFont: null,
      replacedStyleCount: 0,
    });

    render(<App />);

    expect(await screen.findByText("出图结果")).toBeInTheDocument();
    expect(
      screen.getByText("同编码多页：目录合并为一行，物理文件按页分别输出"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/JD2RSG11005B25C42SDACFC1@2 \(20162RS-JGS03-005\)\.dwg/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/JD2RSG11005B25C42SDACFC1@2 \(20162RS-JGS03-005\)\.pdf/),
    ).toBeInTheDocument();
    expect(screen.getByText(/页数：1 页/)).toBeInTheDocument();
  });

  it("hides IED download actions entirely when the backend marks IED as unavailable", async () => {
    window.history.pushState({}, "", "/jobs/deliverable-no-ied");
    mockGetJobDetail.mockResolvedValue({
      jobId: "deliverable-no-ied",
      batchId: "batch-deliverable-no-ied",
      groupId: null,
      isGroup: false,
      sourceFilename: "A01.dwg",
      sourceFilenames: ["A01.dwg"],
      taskKind: "deliverable",
      taskRole: null,
      jobMode: "deliverable",
      projectNo: "2016",
      status: "succeeded",
      stage: "PACKAGE_ZIP",
      percent: 100,
      message: "",
      createdAt: "2026-04-16T10:00:00+08:00",
      finishedAt: "2026-04-16T10:05:00+08:00",
      startedAt: "2026-04-16T10:00:10+08:00",
      currentFile: null,
      runAuditCheck: false,
      childJobIds: [],
      findingsCount: 0,
      affectedDrawingsCount: 0,
      artifacts: {
        packageAvailable: true,
        iedAvailable: false,
        reportAvailable: false,
        replacedDwgAvailable: false,
        packageDownloadUrl: "/api/jobs/deliverable-no-ied/download/package",
        iedDownloadUrl: null,
      },
      retryAvailable: false,
      sharedRunId: null,
      flags: [],
      errors: [],
      topWrongTexts: [],
      topInternalCodes: [],
      deliverableOutputs: {
        dwgCount: 1,
        pdfCount: 1,
        documents: [],
        drawings: [
          {
            name: "A01",
            internalCode: "20161RS-JGS01-001",
            dwgName: "A01.dwg",
            pdfName: "A01.pdf",
            pageTotal: 1,
          },
        ],
      },
      missingFontsDetected: false,
      fontReplacementApplied: false,
      replacementFont: null,
      replacedStyleCount: 0,
    });

    render(<App />);

    const quickDownloadHeading = await screen.findByRole("heading", { level: 2, name: "快捷下载" });
    const resultHeading = await screen.findByRole("heading", { level: 2, name: "出图结果" });

    expect(quickDownloadHeading.compareDocumentPosition(resultHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: "下载 package.zip" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "下载 IED计划.xlsx" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "下载 IED计划.xlsx" })).not.toBeInTheDocument();
  });

  it("renders flags and errors inside padded list blocks on detail pages", async () => {
    window.history.pushState({}, "", "/jobs/audit-flags-layout");
    mockGetJobDetail.mockResolvedValue({
      jobId: "audit-flags-layout",
      batchId: "batch-audit-flags-layout",
      groupId: null,
      isGroup: false,
      sourceFilename: "19076RS-JGS01.dwg",
      sourceFilenames: ["19076RS-JGS01.dwg"],
      taskKind: "audit_check",
      taskRole: "audit_check",
      jobMode: "audit_check",
      projectNo: "1907",
      status: "succeeded",
      stage: "EXPORT_REPORT",
      percent: 100,
      message: "",
      createdAt: "2026-04-07T10:00:00+08:00",
      finishedAt: "2026-04-07T10:05:00+08:00",
      startedAt: "2026-04-07T10:00:10+08:00",
      currentFile: null,
      runAuditCheck: true,
      childJobIds: [],
      findingsCount: 3,
      affectedDrawingsCount: 2,
      artifacts: {
        packageAvailable: false,
        iedAvailable: false,
        reportAvailable: true,
        replacedDwgAvailable: false,
        reportDownloadUrl: "/api/jobs/audit-flags-layout/download/report",
      },
      retryAvailable: false,
      sharedRunId: null,
      flags: ["[DRAW001] PAPER_SIZE_AUTO_FIXED", "[DRAW001] PLOT_MULTIPAGE_USED"],
      errors: ["暂无实际错误，仅用于布局验证"],
      topWrongTexts: [],
      topInternalCodes: [],
    });

    render(<App />);

    const flagsHeading = await screen.findByRole("heading", { level: 3, name: "Flags" });
    const errorsHeading = screen.getByRole("heading", { level: 3, name: "Errors" });

    expect(flagsHeading.parentElement).toHaveClass(styles.listBlock);
    expect(errorsHeading.parentElement).toHaveClass(styles.listBlock);
  });

  it("shows replace summary plus both report and replaced dwg downloads for replace jobs", async () => {
    window.history.pushState({}, "", "/jobs/replace-job-1");
    mockGetJobDetail.mockResolvedValue({
      jobId: "replace-job-1",
      batchId: "batch-replace-1",
      groupId: null,
      isGroup: false,
      sourceFilename: "20261NH-JGS51-B合并版.dwg",
      sourceFilenames: ["20261NH-JGS51-B合并版.dwg"],
      taskKind: "audit_replace",
      taskRole: null,
      jobMode: "replace",
      projectNo: "2026",
      status: "succeeded",
      stage: "EXPORT_REPORT",
      percent: 100,
      message: "",
      createdAt: "2026-03-24T09:00:00+08:00",
      finishedAt: "2026-03-24T09:10:00+08:00",
      startedAt: "2026-03-24T09:00:10+08:00",
      currentFile: null,
      runAuditCheck: false,
      childJobIds: [],
      findingsCount: 0,
      affectedDrawingsCount: 10,
      artifacts: {
        packageAvailable: false,
        iedAvailable: false,
        reportAvailable: true,
        replacedDwgAvailable: true,
        reportDownloadUrl: "/api/jobs/replace-job-1/download/report",
        replacedDwgDownloadUrl: "/api/jobs/replace-job-1/download/replaced",
      },
      retryAvailable: false,
      sharedRunId: null,
      flags: [],
      errors: [],
      topWrongTexts: [],
      topInternalCodes: [],
      replaceSummary: {
        replacementCount: 51,
        skippedCount: 0,
        affectedDrawingsCount: 10,
        sourceProjectNo: "2016",
        sourceIslandNo: "2",
        targetProjectNo: "1916",
        targetIslandNo: "3",
        topReplacedTexts: ["2026", "2026XNI-JGS02"],
        topInternalCodes: ["20261NH-JGS51-001"],
      },
      factoryIndexMap: {
        applied: true,
        actionCount: 1,
        reportJson: "factory-index-map.json",
        message: "",
      },
    });

    render(<App />);

    expect(await screen.findByText("翻版摘要")).toBeInTheDocument();
    expect(screen.getByText("51")).toBeInTheDocument();
    expect(screen.getByText("2016")).toBeInTheDocument();
    expect(screen.getByText("2号机组/岛")).toBeInTheDocument();
    expect(screen.getByText("1916")).toBeInTheDocument();
    expect(screen.getByText("3号机组/岛")).toBeInTheDocument();
    expect(screen.getByText("厂房索引图替换")).toBeInTheDocument();
    expect(screen.getByText("是")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载 report.xlsx" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载替换后 DWG" })).toBeInTheDocument();
  });

  it("shows aggregate replaced dwg downloads for replace-plus-deliverable groups", async () => {
    window.history.pushState({}, "", "/jobs/group-replace-1");
    mockGetJobDetail
      .mockResolvedValueOnce({
        jobId: "group-replace-1",
        batchId: "batch-replace-group-1",
        groupId: "group-replace-1",
        isGroup: true,
        sourceFilename: "20261NH-JGS51-B合并版.dwg",
        sourceFilenames: ["20261NH-JGS51-B合并版.dwg"],
        taskKind: null,
        taskRole: null,
        jobMode: null,
        projectNo: "2016",
        status: "succeeded",
        stage: "GROUP_COMPLETE",
        percent: 100,
        message: "",
        createdAt: "2026-03-24T09:01:00+08:00",
        finishedAt: "2026-03-24T09:20:00+08:00",
        startedAt: "2026-03-24T09:01:10+08:00",
        currentFile: null,
        runAuditCheck: false,
        childJobIds: ["replace-job-1", "deliverable-job-1"],
        findingsCount: 0,
        affectedDrawingsCount: 10,
        artifacts: {
          packageAvailable: true,
          iedAvailable: true,
          reportAvailable: true,
          replacedDwgAvailable: true,
          packageDownloadUrl: "/api/jobs/group-replace-1/download/package",
          iedDownloadUrl: "/api/jobs/group-replace-1/download/ied",
          reportDownloadUrl: "/api/jobs/group-replace-1/download/report",
          replacedDwgDownloadUrl: "/api/jobs/group-replace-1/download/replaced",
        },
        retryAvailable: false,
        sharedRunId: "shared-run-1",
        flags: [],
        errors: [],
        topWrongTexts: [],
        topInternalCodes: [],
        children: [
          {
            ...makeSingleJob(1, "20261NH-JGS51-B合并版.dwg"),
            jobId: "replace-job-1",
            batchId: "batch-replace-group-1",
            groupId: "group-replace-1",
            taskKind: "audit_replace",
            taskRole: "audit_replace",
            jobMode: "replace",
            projectNo: "2026",
            status: "succeeded",
            stage: "EXPORT_REPORT",
            artifacts: {
              packageAvailable: false,
              iedAvailable: false,
              reportAvailable: true,
              replacedDwgAvailable: true,
              reportDownloadUrl: "/api/jobs/replace-job-1/download/report",
              replacedDwgDownloadUrl: "/api/jobs/replace-job-1/download/replaced",
            },
          },
          {
            ...makeSingleJob(2, "20261NH-JGS51-B合并版.dwg"),
            jobId: "deliverable-job-1",
            batchId: "batch-replace-group-1",
            groupId: "group-replace-1",
            taskKind: "deliverable",
            taskRole: "deliverable_main",
            jobMode: "deliverable",
          },
        ],
      })
      .mockResolvedValueOnce({
        jobId: "replace-job-1",
        batchId: "batch-replace-group-1",
        groupId: "group-replace-1",
        isGroup: false,
        sourceFilename: "20261NH-JGS51-B合并版.dwg",
        sourceFilenames: ["20261NH-JGS51-B合并版.dwg"],
        taskKind: "audit_replace",
        taskRole: "audit_replace",
        jobMode: "replace",
        projectNo: "2026",
        status: "succeeded",
        stage: "EXPORT_REPORT",
        percent: 100,
        message: "",
        createdAt: "2026-03-24T09:01:00+08:00",
        finishedAt: "2026-03-24T09:10:00+08:00",
        startedAt: "2026-03-24T09:01:10+08:00",
        currentFile: null,
        runAuditCheck: false,
        childJobIds: [],
        findingsCount: 0,
        affectedDrawingsCount: 10,
        artifacts: {
          packageAvailable: false,
          iedAvailable: false,
          reportAvailable: true,
          replacedDwgAvailable: true,
          reportDownloadUrl: "/api/jobs/replace-job-1/download/report",
          replacedDwgDownloadUrl: "/api/jobs/replace-job-1/download/replaced",
        },
        retryAvailable: false,
        sharedRunId: "shared-run-1",
        flags: [],
        errors: [],
        topWrongTexts: [],
        topInternalCodes: [],
        replaceSummary: {
          replacementCount: 51,
          skippedCount: 0,
          affectedDrawingsCount: 10,
          sourceProjectNo: "2026",
          targetProjectNo: "2016",
          topReplacedTexts: ["2026"],
          topInternalCodes: ["20261NH-JGS51-001"],
        },
      })
      .mockResolvedValueOnce({
        ...makeSingleJob(2, "20261NH-JGS51-B合并版.dwg"),
        jobId: "deliverable-job-1",
        batchId: "batch-replace-group-1",
        groupId: "group-replace-1",
        taskKind: "deliverable",
        taskRole: "deliverable_main",
        jobMode: "deliverable",
      });

    render(<App />);

    expect(await screen.findByRole("link", { name: "下载替换后 DWG" })).toBeInTheDocument();
  });
});
