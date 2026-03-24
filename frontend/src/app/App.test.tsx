import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

  it("renders the title strip, module toolbar, and primary actions", async () => {
    render(<App />);

    expect(await screen.findByTestId("title-strip")).toBeInTheDocument();
    expect(screen.getByTestId("title-strip-status")).toBeInTheDocument();
    expect(await screen.findAllByTestId("title-strip-status-item")).toHaveLength(5);
    expect(screen.getByText("中核工程—建筑结构所出图平台")).toBeInTheDocument();
    expect(screen.getByTestId("hero-watermark")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "教程" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "出图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "纠错" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "翻版" })).toHaveAttribute("aria-disabled", "true");

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

  it("shows the themed replace tooltip immediately on hover", async () => {
    const user = userEvent.setup();
    render(<App />);

    const replacePreview = await screen.findByTestId("replace-preview-wrap");
    expect(screen.queryByRole("tooltip", { name: "敬请期待" })).not.toBeInTheDocument();

    await user.hover(replacePreview);
    expect(screen.getByRole("tooltip", { name: "敬请期待" })).toHaveAttribute(
      "data-side",
      "right",
    );

    await user.unhover(replacePreview);
    expect(screen.queryByRole("tooltip", { name: "敬请期待" })).not.toBeInTheDocument();
  });

  it("opens tutorial mode and walks through the simulated deliverable flow", async () => {
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
    expect(document.body.style.paddingRight).toMatch(/\d+px|^$/);

    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByRole("dialog", { name: "教程文件选择" })).toBeInTheDocument();
    expect(screen.getByText("18185NE-JGS11.dwg")).toBeInTheDocument();
    expect(screen.getByTestId("tutorial-spotlight")).toHaveAttribute("data-target", "picker_select");

    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByRole("dialog", { name: "教程任务配置" })).toBeInTheDocument();
    expect(
      screen.getByText("若勾选纠错，系统会与出图一起创建为同一任务包；本教程仅演示流程，不会真的提交任务。"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("tutorial-spotlight")).toHaveAttribute("data-target", "config");

    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByRole("dialog", { name: "教程任务记录" })).toBeInTheDocument();
    expect(screen.getByText("18185NE-JGS11.dwg")).toBeInTheDocument();
    expect(screen.getByTestId("tutorial-spotlight")).toHaveAttribute("data-target", "record");

    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.getByRole("dialog", { name: "教程任务详情" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下载任务包" })).toBeInTheDocument();
    expect(screen.getByTestId("tutorial-spotlight")).toHaveAttribute("data-target", "detail");
    expect(screen.getByRole("button", { name: "下一步" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "退出" }));
    expect(screen.queryByRole("dialog", { name: "教程任务详情" })).not.toBeInTheDocument();
    expect(screen.queryByText("当前为演示模式，不会创建真实任务，也不会改动任务记录。")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "教程文件选择" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "教程任务配置" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "教程任务记录" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("tutorial-spotlight")).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe("");
    expect(document.body.style.paddingRight).toBe("");
  });
});

describe("recent jobs area", () => {
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
