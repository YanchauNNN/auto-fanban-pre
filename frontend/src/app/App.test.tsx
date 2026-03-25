import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const mockGetHealth = vi.fn();
const mockGetFormSchema = vi.fn();
const mockPreflightFonts = vi.fn();
const mockCreateBatch = vi.fn();
const mockCreateAuditCheck = vi.fn();
const mockCreateAuditReplace = vi.fn();
const mockListJobs = vi.fn();
const mockGetJobDetail = vi.fn();

vi.mock("../platform/api/useApiAdapter", () => ({
  useApiAdapter: () => ({
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

  mockGetHealth.mockReset();
  mockGetFormSchema.mockReset();
  mockPreflightFonts.mockReset();
  mockCreateBatch.mockReset();
  mockCreateAuditCheck.mockReset();
  mockCreateAuditReplace.mockReset();
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
});

afterEach(() => {
  vi.useRealTimers();
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

  it("shows a maintenance warning and disables main entries when health check fails", async () => {
    mockGetHealth.mockRejectedValueOnce(new Error("backend offline"));

    render(<App />);

    expect(
      await screen.findByText("后台维护升级中，为您带来的不便十分抱歉（＞人＜；）"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "出图" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "纠错" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "翻版" })).toBeDisabled();
  });

  it("shows a maintenance warning when backend health is not ready", async () => {
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

    expect(
      await screen.findByText("后台维护升级中，为您带来的不便十分抱歉（＞人＜；）"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "出图" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "纠错" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "翻版" })).toBeDisabled();
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
    expect(screen.getByRole("dialog", { name: "翻版配置" })).toBeInTheDocument();
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
    expect(screen.getByRole("dialog", { name: "任务配置" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建交付任务" })).toBeInTheDocument();
    expect(
      screen.getByText("上传文件后直接在弹窗内完成配置。关闭不会丢失草稿；只有手动清空或提交成功后才会重置。"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("tutorial-spotlight")).toHaveAttribute("data-target", "config");

    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.queryByRole("dialog", { name: "教程任务记录" })).not.toBeInTheDocument();
    expect(screen.getByText("demo-2026-structural-package.dwg")).toBeInTheDocument();
    expect(screen.getByText("查看任务包")).toBeInTheDocument();
    expect(screen.getByTestId("tutorial-spotlight")).toHaveAttribute("data-target", "record");

    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.queryByRole("dialog", { name: "教程任务详情" })).not.toBeInTheDocument();
    expect(screen.getByText("任务包概览")).toBeInTheDocument();
    expect(screen.getByText("聚合下载")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载任务包" })).toBeInTheDocument();
    expect(screen.getByTestId("tutorial-spotlight")).toHaveAttribute("data-target", "detail");
    expect(screen.getByRole("button", { name: "下一步" })).toBeDisabled();

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
  it("filters recent jobs locally by status without refetching the list", async () => {
    mockListJobs.mockResolvedValue({
      total: 4,
      items: [
        {
          ...makeSingleJob(1, "queued-job.dwg"),
          status: "queued",
        },
        {
          ...makeSingleJob(2, "running-job.dwg"),
          status: "running",
        },
        {
          ...makeSingleJob(3, "success-job.dwg"),
          status: "succeeded",
        },
        {
          ...makeSingleJob(4, "failed-job.dwg"),
          status: "failed",
        },
      ],
    });

    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("success-job.dwg")).toBeInTheDocument();
    expect(mockListJobs).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "排队中" }));
    expect(screen.getByRole("button", { name: "排队中" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("queued-job.dwg")).toBeInTheDocument();
    expect(screen.queryByText("running-job.dwg")).not.toBeInTheDocument();
    expect(screen.queryByText("success-job.dwg")).not.toBeInTheDocument();
    expect(screen.queryByText("failed-job.dwg")).not.toBeInTheDocument();
    expect(mockListJobs).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "成功" }));
    expect(screen.getByRole("button", { name: "成功" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("success-job.dwg")).toBeInTheDocument();
    expect(screen.queryByText("queued-job.dwg")).not.toBeInTheDocument();
    expect(screen.queryByText("running-job.dwg")).not.toBeInTheDocument();
    expect(screen.queryByText("failed-job.dwg")).not.toBeInTheDocument();
    expect(mockListJobs).toHaveBeenCalledTimes(1);
  });

  it("shows eight cards by default and opens the rest in a modal", async () => {
    mockListJobs.mockResolvedValue({
      total: 10,
      items: Array.from({ length: 10 }, (_, index) =>
        makeSingleJob(index + 1, `sample-${index + 1}.dwg`),
      ),
    });

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

  it("shows a completed single deliverable job with a detail link", async () => {
    mockListJobs.mockResolvedValue({
      total: 1,
      items: [makeSingleJob(1, "20261RS-JGS65.dwg")],
    });

    render(<App />);

    expect(await screen.findByText("出图完成")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看任务" })).toBeInTheDocument();
  });
});

describe("job detail pages", () => {
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
            fontReplacementApplied: true,
            errors: [],
          },
        ],
        policy: "replace_missing",
      },
      missingFontsDetected: true,
      fontReplacementApplied: true,
      replacementFont: "simplex.shx",
      replacedStyleCount: 3,
    });

    render(<App />);

    expect(await screen.findByText("字体处理摘要")).toBeInTheDocument();
    expect(screen.getByText("已执行缺失字体替代")).toBeInTheDocument();
    expect(screen.getByText("simplex.shx")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
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
        sourceProjectNo: "2026",
        targetProjectNo: "2016",
        topReplacedTexts: ["2026", "2026XNI-JGS02"],
        topInternalCodes: ["20261NH-JGS51-001"],
      },
    });

    render(<App />);

    expect(await screen.findByText("翻版摘要")).toBeInTheDocument();
    expect(screen.getByText("51")).toBeInTheDocument();
    expect(screen.getByText("2026")).toBeInTheDocument();
    expect(screen.getByText("2016")).toBeInTheDocument();
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
