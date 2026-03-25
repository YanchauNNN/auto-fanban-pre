import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App, isBackendUnavailable } from "./App";

const mockLogin = vi.fn();
const mockLogout = vi.fn();
const mockGetMe = vi.fn();
const mockChangePassword = vi.fn();
const mockNormalizePersonnel = vi.fn();
const mockGetWorkloadMe = vi.fn();
const mockGetWorkloadOffice = vi.fn();
const mockGetWorkloadInstitute = vi.fn();
const mockGetWorkloadAdmin = vi.fn();
const mockGetWorkflowMonitor = vi.fn();
const mockApproveWorkflow = vi.fn();
const mockRepairCurrentNode = vi.fn();
const mockListAccounts = vi.fn();
const mockListInvalidAccountRows = vi.fn();
const mockCreateAccount = vi.fn();
const mockUpdateAccount = vi.fn();
const mockGetAdminConfig = vi.fn();
const mockPatchAdminConfig = vi.fn();
const mockGetHealth = vi.fn();
const mockGetFormSchema = vi.fn();
const mockPreflightFonts = vi.fn();
const mockCreateBatch = vi.fn();
const mockCreateAuditCheck = vi.fn();
const mockCreateAuditReplace = vi.fn();
const mockListTaskGroups = vi.fn();
const mockGetTaskGroupDetail = vi.fn();
const mockSubmitTaskGroup = vi.fn();
const mockRestartSubmitTaskGroup = vi.fn();
const mockListJobs = vi.fn();
const mockGetJobDetail = vi.fn();

vi.mock("../platform/api/useApiAdapter", () => ({
  useApiAdapter: () => ({
    login: mockLogin,
    logout: mockLogout,
    getMe: mockGetMe,
    changePassword: mockChangePassword,
    normalizePersonnel: mockNormalizePersonnel,
    getWorkloadMe: mockGetWorkloadMe,
    getWorkloadOffice: mockGetWorkloadOffice,
    getWorkloadInstitute: mockGetWorkloadInstitute,
    getWorkloadAdmin: mockGetWorkloadAdmin,
    getWorkflowMonitor: mockGetWorkflowMonitor,
    approveWorkflow: mockApproveWorkflow,
    repairCurrentNode: mockRepairCurrentNode,
    listAccounts: mockListAccounts,
    listInvalidAccountRows: mockListInvalidAccountRows,
    createAccount: mockCreateAccount,
    updateAccount: mockUpdateAccount,
    getAdminConfig: mockGetAdminConfig,
    patchAdminConfig: mockPatchAdminConfig,
    getHealth: mockGetHealth,
    getFormSchema: mockGetFormSchema,
    preflightFonts: mockPreflightFonts,
    createBatch: mockCreateBatch,
    createAuditCheck: mockCreateAuditCheck,
    createAuditReplace: mockCreateAuditReplace,
    listTaskGroups: mockListTaskGroups,
    getTaskGroupDetail: mockGetTaskGroupDetail,
    submitTaskGroup: mockSubmitTaskGroup,
    restartSubmitTaskGroup: mockRestartSubmitTaskGroup,
    listJobs: mockListJobs,
    getJobDetail: mockGetJobDetail,
  }),
}));

beforeEach(() => {
  window.history.pushState({}, "", "/");
  window.localStorage.clear();
  window.localStorage.setItem("auth_token", "persisted-token");

  mockLogin.mockReset();
  mockLogout.mockReset();
  mockGetMe.mockReset();
  mockChangePassword.mockReset();
  mockNormalizePersonnel.mockReset();
  mockGetWorkloadMe.mockReset();
  mockGetWorkloadOffice.mockReset();
  mockGetWorkloadInstitute.mockReset();
  mockGetWorkloadAdmin.mockReset();
  mockGetWorkflowMonitor.mockReset();
  mockApproveWorkflow.mockReset();
  mockRepairCurrentNode.mockReset();
  mockListAccounts.mockReset();
  mockListInvalidAccountRows.mockReset();
  mockCreateAccount.mockReset();
  mockUpdateAccount.mockReset();
  mockGetAdminConfig.mockReset();
  mockPatchAdminConfig.mockReset();
  mockGetHealth.mockReset();
  mockGetFormSchema.mockReset();
  mockPreflightFonts.mockReset();
  mockCreateBatch.mockReset();
  mockCreateAuditCheck.mockReset();
  mockCreateAuditReplace.mockReset();
  mockListTaskGroups.mockReset();
  mockGetTaskGroupDetail.mockReset();
  mockSubmitTaskGroup.mockReset();
  mockRestartSubmitTaskGroup.mockReset();
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
  mockGetMe.mockResolvedValue({
    accountId: "zhangsan",
    displayName: "张三",
    role: "设计人员",
    officeCode: "HB-JG",
    officeName: "河北分公司-建筑结构所",
    valid: true,
    pendingTodoCount: 2,
  });
  mockLogin.mockResolvedValue({
    token: "new-login-token",
    account: {
      accountId: "zhangsan",
      displayName: "张三",
      role: "设计人员",
      officeCode: "HB-JG",
      officeName: "河北分公司-建筑结构所",
      valid: true,
      pendingTodoCount: 2,
    },
  });
  mockLogout.mockResolvedValue({ ok: true });
  mockChangePassword.mockResolvedValue({
    accountId: "zhangsan",
    displayName: "张三",
    role: "设计人员",
    officeCode: "HB-JG",
    officeName: "河北分公司-建筑结构所",
    valid: true,
    pendingTodoCount: 2,
  });
  mockGetWorkloadMe.mockResolvedValue({
    scope: "me",
    filters: {
      startDate: null,
      endDate: null,
      status: null,
      validOnly: false,
    },
    totalWorkloadA1: 2.6,
    officeName: null,
    totalsByAccount: {},
    entries: [
      {
        roleKey: "ied_prepared_by",
        accountId: "zhangsan",
        displayName: "张三",
        workloadA1: 1.4,
        settledAt: "2026-03-20T10:20:30+08:00",
        groupId: "group-1",
        settlementStatus: "settled",
      },
      {
        roleKey: "ied_checked_by",
        accountId: "zhangsan",
        displayName: "张三",
        workloadA1: 1.2,
        settledAt: "2026-03-22T10:20:30+08:00",
        groupId: "group-2",
        settlementStatus: "settled",
      },
    ],
  });
  mockGetWorkloadOffice.mockResolvedValue({
    scope: "office",
    filters: {
      startDate: null,
      endDate: null,
      status: null,
      validOnly: false,
    },
    totalWorkloadA1: 5.1,
    officeName: "河北分公司-建筑结构所",
    totalsByAccount: {},
    entries: [
      {
        roleKey: "ied_prepared_by",
        accountId: "lisi",
        displayName: "李四",
        workloadA1: 2.5,
        settledAt: "2026-03-23T10:20:30+08:00",
        groupId: "group-office-1",
        settlementStatus: "settled",
      },
    ],
  });
  mockGetWorkloadInstitute.mockResolvedValue({
    scope: "institute",
    filters: {
      startDate: null,
      endDate: null,
      status: null,
      validOnly: false,
    },
    totalWorkloadA1: 8.8,
    officeName: null,
    totalsByAccount: {},
    entries: [
      {
        roleKey: "ied_checked_by",
        accountId: "wangwu",
        displayName: "王五",
        workloadA1: 3.2,
        settledAt: "2026-03-21T10:20:30+08:00",
        groupId: "group-inst-1",
        settlementStatus: "settled",
      },
    ],
  });
  mockGetWorkloadAdmin.mockResolvedValue({
    scope: "admin",
    filters: {
      startDate: null,
      endDate: null,
      status: null,
      validOnly: false,
    },
    totalWorkloadA1: 12.3,
    officeName: null,
    totalsByAccount: {
      zhangsan: 2.6,
      lisi: 5.1,
    },
    entries: [
      {
        roleKey: "ied_approved_by",
        accountId: "zhaoliu",
        displayName: "赵六",
        workloadA1: 4.1,
        settledAt: "2026-03-24T10:20:30+08:00",
        groupId: "group-admin-1",
        settlementStatus: "settled",
      },
    ],
  });
  mockGetWorkflowMonitor.mockResolvedValue({
    total: 1,
    items: [
      {
        ...makeTaskGroupSummary(99, "20261RS-JGS99.dwg"),
        workflowStatus: "in_review",
        currentNodeKey: "one_review",
        canApprove: true,
        isRelatedToCurrentUser: true,
      },
    ],
  });
  mockApproveWorkflow.mockResolvedValue(undefined);
  mockRepairCurrentNode.mockResolvedValue(undefined);
  mockListAccounts.mockResolvedValue({
    items: [
      {
        officeCode: "HB-JG",
        officeName: "河北分公司-建筑结构所",
        accountId: "existing-user",
        displayName: "现有账号",
        role: "设计人员",
        password: "password",
        valid: true,
        rowNumber: 8,
        errors: [],
      },
    ],
  });
  mockListInvalidAccountRows.mockResolvedValue({
    items: [
      {
        rowNumber: 18,
        raw: {
          account_id: "",
          display_name: "缺失账号",
          role: "设计人员",
        },
        errors: ["missing_account_id"],
      },
    ],
  });
  mockCreateAccount.mockResolvedValue({
    officeCode: "HB-JG",
    officeName: "河北分公司-建筑结构所",
    accountId: "new-user",
    displayName: "新账号",
    role: "设计人员",
    password: "password",
    valid: true,
    rowNumber: 19,
    errors: [],
  });
  mockUpdateAccount.mockResolvedValue({
    officeCode: "HB-JG",
    officeName: "河北分公司-建筑结构所",
    accountId: "existing-user",
    displayName: "现有账号-更新",
    role: "设计人员",
    password: "new-password",
    valid: true,
    rowNumber: 8,
    errors: [],
  });
  mockGetAdminConfig.mockResolvedValue({
    archiveRootPath: "\\\\fileserver\\archive\\drawings",
  });
  mockPatchAdminConfig.mockResolvedValue({
    archiveRootPath: "\\\\fileserver\\archive\\next",
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
  mockListTaskGroups.mockResolvedValue({
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
  window.localStorage.clear();
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

function makeTaskGroupSummary(index: number, sourceFilename: string) {
  return {
    groupId: `group-${index}`,
    batchId: `batch-${index}`,
    projectNo: "2026",
    status: "succeeded",
    createdAt: `2026-03-16T11:${String(index).padStart(2, "0")}:30+08:00`,
    sourceFilenames: [sourceFilename],
    ownerSnapshot: {
      creatorAccount: "zhangsan",
      creatorName: "张三",
      creatorRole: "设计人员",
      creatorOffice: "河北分公司-建筑结构所",
      createdByScope: "current_login_user",
      submittedAt: null,
    },
    creatorName: "张三",
    creatorAccount: "zhangsan",
    creatorOffice: "河北分公司-建筑结构所",
    workflowStatus: "draft",
    currentNodeKey: null,
    archiveStatus: "pending",
    workload: {
      initialWorkloadA1: 1.2,
      finalWorkloadA1: 1.2,
      oneReviewFactor: 1,
      twoReviewFactor: 1,
      threeReviewFactor: 1,
      settlementStatus: "pending",
      settledAt: null,
      contributorEntries: [],
    },
    effectiveWorkload: 1.2,
    canViewDetail: true,
    canSubmit: false,
    canApprove: false,
    isRelatedToCurrentUser: true,
  };
}

describe("homepage shell", () => {
  it("renders the login page when there is no persisted session token", async () => {
    window.localStorage.clear();

    render(<App />);

    expect(await screen.findByRole("heading", { name: "账号登录" })).toBeInTheDocument();
    expect(screen.getByText("中核工程-河北分公司-建筑结构所出图平台")).toBeInTheDocument();
    expect(screen.getByText("默认密码password")).toBeInTheDocument();
    expect(screen.getByLabelText("账号")).toBeInTheDocument();
    expect(screen.getByLabelText("密码")).toBeInTheDocument();
    expect(mockGetMe).not.toHaveBeenCalled();
  });

  it("submits login and transitions into the protected business page", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();

    render(<App />);

    await user.type(await screen.findByLabelText("账号"), "zhangsan");
    await user.type(screen.getByLabelText("密码"), "password");
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(mockLogin).toHaveBeenCalledWith({
      accountId: "zhangsan",
      password: "password",
    });
    expect(await screen.findByTestId("title-strip")).toBeInTheDocument();
    expect(window.localStorage.getItem("auth_token")).toBe("new-login-token");
  });

  it("clears an invalid persisted session and returns to login", async () => {
    mockGetMe.mockRejectedValueOnce({
      status: 401,
      detail: "authentication required",
    });

    render(<App />);

    expect(await screen.findByRole("heading", { name: "账号登录" })).toBeInTheDocument();
    expect(window.localStorage.getItem("auth_token")).toBeNull();
  });

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

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "后台维护升级中，为您带来的不便十分抱歉（＞人＜；）",
    );
    within(screen.getByTestId("tutorial-target-entry"))
      .getAllByRole("button")
      .forEach((button) => expect(button).toBeDisabled());
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

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "后台维护升级中，为您带来的不便十分抱歉（＞人＜；）",
    );
    within(screen.getByTestId("tutorial-target-entry"))
      .getAllByRole("button")
      .forEach((button) => expect(button).toBeDisabled());
  });

  it("does not treat a background refresh error as maintenance when the last health snapshot is ready", () => {
    expect(
      isBackendUnavailable({
        hasError: true,
        health: {
          ready: true,
        },
      }),
    ).toBe(false);
    expect(
      isBackendUnavailable({
        hasError: true,
        health: undefined,
      }),
    ).toBe(true);
    expect(
      isBackendUnavailable({
        hasError: false,
        health: {
          ready: false,
        },
      }),
    ).toBe(true);
  });

  it("renders the title strip, module toolbar, and primary actions", async () => {
    render(<App />);

    expect(await screen.findByTestId("title-strip")).toBeInTheDocument();
    expect(screen.getByTestId("title-strip-status")).toBeInTheDocument();
    expect(await screen.findAllByTestId("title-strip-status-item")).toHaveLength(5);
    expect(screen.getByText("中核工程-河北分公司-建筑结构所出图平台")).toBeInTheDocument();
    expect(screen.getByTestId("hero-watermark")).toBeInTheDocument();
    expect(
      screen.getByTestId("title-strip").compareDocumentPosition(screen.getByTestId("module-toolbar")) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).not.toBe(0);
    expect(screen.getByRole("button", { name: "教程" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "出图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "纠错" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "翻版" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "业务" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "账号" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "工作量 (2)" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "账号模块" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "工作量模块" })).toHaveLength(1);

    const shellToolbarRow = screen.getByTestId("shell-toolbar-row");
    const toolbar = screen.getByTestId("module-toolbar");
    const sessionToolbar = screen.getByTestId("protected-app-nav");
    expect(shellToolbarRow).toContainElement(toolbar);
    expect(shellToolbarRow).toContainElement(sessionToolbar);
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

  it("navigates between the real module routes from the toolbar", async () => {
    const user = userEvent.setup();
    render(<App />);

    const toolbar = await screen.findByTestId("module-toolbar");
    const accountButton = within(toolbar).getByRole("button", { name: "账号模块" });
    const workloadButton = within(toolbar).getByRole("button", { name: "工作量模块" });
    const businessButton = within(toolbar).getByRole("button", { name: "业务模块" });

    await user.click(accountButton);
    await waitFor(() => expect(window.location.pathname).toBe("/account"));
    expect(await screen.findByText("2 条已结算记录")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/account");
    expect(screen.queryByTestId("module-business-panel")).not.toBeInTheDocument();

    await user.click(workloadButton);
    expect(await screen.findByText("当前流程监视")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/workload");

    await user.click(businessButton);
    expect(await screen.findByTestId("module-business-panel")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/business");
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

    await user.click(await screen.findByRole("button", { name: "教程" }));

    expect(screen.getByText("当前为演示模式，不会创建真实任务，也不会改动任务记录。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一步" })).toBeInTheDocument();
    expect(screen.getByTestId("tutorial-target-entry")).toHaveAttribute(
      "data-tutorial-active",
      "true",
    );
    expect(
      (await screen.findByTestId("tutorial-spotlight").catch(() => screen.findByTestId("tutorial-dimmer"))),
    ).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");
    expect(document.documentElement.style.scrollbarGutter).toBe("stable");

    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.queryByRole("dialog", { name: "教程文件选择" })).not.toBeInTheDocument();
    expect(screen.getByText(/点击“出图”后，浏览器会拉起系统文件选择窗口/)).toBeInTheDocument();
    expect(
      (await screen.findByTestId("tutorial-spotlight").catch(() => screen.findByTestId("tutorial-dimmer"))),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.queryByRole("dialog", { name: "教程任务配置" })).not.toBeInTheDocument();
    expect(await screen.findByRole("dialog", { name: "任务配置" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "创建交付任务" })).toBeInTheDocument();
    expect(
      screen.getByText("上传文件后直接在弹窗内完成配置。关闭不会丢失草稿；只有手动清空或提交成功后才会重置。"),
    ).toBeInTheDocument();
    expect(
      (await screen.findByTestId("tutorial-spotlight").catch(() => screen.findByTestId("tutorial-dimmer"))),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.queryByRole("dialog", { name: "教程任务记录" })).not.toBeInTheDocument();
    expect(screen.getByText("demo-2026-structural-package.dwg")).toBeInTheDocument();
    expect(screen.getByText("查看任务包")).toBeInTheDocument();
    expect(
      (await screen.findByTestId("tutorial-spotlight").catch(() => screen.findByTestId("tutorial-dimmer"))),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(screen.queryByRole("dialog", { name: "教程任务详情" })).not.toBeInTheDocument();
    expect(screen.getByText("任务包概览")).toBeInTheDocument();
    expect(screen.getByText("聚合下载")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载任务包" })).toBeInTheDocument();
    expect(
      (await screen.findByTestId("tutorial-spotlight").catch(() => screen.findByTestId("tutorial-dimmer"))),
    ).toBeInTheDocument();
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

  it("renders the real account page and supports password changes", async () => {
    window.history.pushState({}, "", "/account");
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByTestId("title-strip")).toBeInTheDocument();
    expect(await screen.findByText("2 条已结算记录")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "账号模块" })).toBeInTheDocument();
    expect(screen.getAllByText("张三").length).toBeGreaterThan(0);
    expect(screen.getByText("设计人员")).toBeInTheDocument();
    expect(screen.getByText("河北分公司-建筑结构所")).toBeInTheDocument();
    expect(screen.getByText("2.60")).toBeInTheDocument();

    await user.type(screen.getByLabelText("新密码"), "new-password");
    await user.click(screen.getByRole("button", { name: "更新密码" }));

    expect(mockChangePassword).toHaveBeenCalledWith("new-password");
    expect(await screen.findByText("密码已更新，下次登录请使用新密码。")).toBeInTheDocument();
  });

  it("renders the real workload page instead of the placeholder route", async () => {
    window.history.pushState({}, "", "/workload");

    render(<App />);

    expect(await screen.findByTestId("title-strip")).toBeInTheDocument();
    expect(await screen.findByText("当前流程监视")).toBeInTheDocument();
    expect(screen.getByText("历史与统计")).toBeInTheDocument();
    expect(screen.queryByText("流程监视、审批与统计将在下一批接入。")).not.toBeInTheDocument();
  });

  it("shows role-aware workload scopes and lets approvable users submit approvals", async () => {
    window.history.pushState({}, "", "/workload");
    mockGetMe.mockResolvedValue({
      accountId: "admin",
      displayName: "管理员",
      role: "管理员",
      officeCode: "ADMIN",
      officeName: "平台管理",
      valid: true,
      pendingTodoCount: 4,
    });
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByRole("button", { name: "个人" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "科室" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "全所" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "管理员" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "管理员" }));
    expect(mockGetWorkloadAdmin).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "审批" }));
    expect(await screen.findByRole("dialog", { name: "审批当前节点" })).toBeInTheDocument();
    expect(screen.getByLabelText("审批系数")).toHaveValue("1.00");

    await user.click(screen.getByRole("button", { name: "确认审批" }));
    expect(mockApproveWorkflow).toHaveBeenCalledWith("group-99", {
      factor: 1,
      nodeKey: "one_review",
    });
  });

  it("loads repair account options lazily only when the admin opens repair dialog", async () => {
    window.history.pushState({}, "", "/workload");
    mockGetMe.mockResolvedValue({
      accountId: "admin",
      displayName: "管理员",
      role: "管理员",
      officeCode: "ADMIN",
      officeName: "平台管理",
      valid: true,
      pendingTodoCount: 4,
    });
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByText("当前流程监视")).toBeInTheDocument();
    expect(mockListAccounts).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "修复当前节点" }));

    expect(await screen.findByRole("dialog", { name: "修复当前节点" })).toBeInTheDocument();
    expect(mockListAccounts).toHaveBeenCalledTimes(1);
  });

  it("renders the real admin account page with account, invalid-row, and archive config sections", async () => {
    window.history.pushState({}, "", "/account/admin");
    mockGetMe.mockResolvedValue({
      accountId: "admin",
      displayName: "管理员",
      role: "管理员",
      officeCode: "ADMIN",
      officeName: "平台管理",
      valid: true,
      pendingTodoCount: 4,
    });

    render(<App />);

    expect(await screen.findByTestId("title-strip")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "管理员配置" })).toBeInTheDocument();
    expect(screen.getByText("现有账号")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查看现有账号" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "现有账号列表" })).not.toBeInTheDocument();
    expect(screen.queryByText("现有账号（existing-user）")).not.toBeInTheDocument();
    expect(screen.getByText("无效账号行")).toBeInTheDocument();
    expect(screen.getByDisplayValue("\\\\fileserver\\archive\\drawings")).toBeInTheDocument();
    expect(screen.queryByText("管理员账号管理与归档配置将在下一批接入。")).not.toBeInTheDocument();
  });

  it("switches duplicate account creation into edit mode on the admin page", async () => {
    window.history.pushState({}, "", "/account/admin");
    mockGetMe.mockResolvedValue({
      accountId: "admin",
      displayName: "管理员",
      role: "管理员",
      officeCode: "ADMIN",
      officeName: "平台管理",
      valid: true,
      pendingTodoCount: 4,
    });
    mockCreateAccount.mockRejectedValue({
      status: 422,
      detail: "account_id already exists",
    });
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByRole("heading", { name: "管理员配置" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看现有账号" }));
    expect(await screen.findByRole("dialog", { name: "现有账号列表" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "编辑 existing-user" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "关闭" }));
    await user.clear(screen.getByLabelText("账号"));
    await user.type(screen.getByLabelText("账号"), "existing-user");
    await user.clear(screen.getByLabelText("姓名"));
    await user.type(screen.getByLabelText("姓名"), "重复账号");
    await user.click(screen.getByRole("button", { name: "创建账号" }));

    expect(await screen.findByText("账号已存在，已切换到编辑模式。")).toBeInTheDocument();
    expect(screen.getByText("编辑账号")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("姓名"));
    await user.type(screen.getByLabelText("姓名"), "现有账号-更新");
    await user.click(screen.getByRole("button", { name: "保存修改" }));

    expect(mockUpdateAccount).toHaveBeenCalledWith("existing-user", {
      officeCode: "HB-JG",
      officeName: "河北分公司-建筑结构所",
      accountId: "existing-user",
      displayName: "现有账号-更新",
      role: "设计人员",
      password: "password",
    });
  });

  it("lets admins repair the current workflow node with a newly created account", async () => {
    window.history.pushState({}, "", "/workload");
    mockGetMe.mockResolvedValue({
      accountId: "admin",
      displayName: "管理员",
      role: "管理员",
      officeCode: "ADMIN",
      officeName: "平台管理",
      valid: true,
      pendingTodoCount: 4,
    });
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByRole("button", { name: "修复当前节点" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "修复当前节点" }));
    expect(await screen.findByRole("dialog", { name: "修复当前节点" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "新增账号并修复" }));
    await user.clear(screen.getByLabelText("新账号"));
    await user.type(screen.getByLabelText("新账号"), "repair-user");
    await user.clear(screen.getByLabelText("姓名"));
    await user.type(screen.getByLabelText("姓名"), "修复账号");
    await user.clear(screen.getByLabelText("科室编码"));
    await user.type(screen.getByLabelText("科室编码"), "HB-JG");
    await user.clear(screen.getByLabelText("科室"));
    await user.type(screen.getByLabelText("科室"), "河北分公司-建筑结构所");
    await user.selectOptions(screen.getByLabelText("角色"), "设计人员");
    await user.click(screen.getByRole("button", { name: "确认修复" }));

    expect(mockRepairCurrentNode).toHaveBeenCalledWith("group-99", {
      createAccountPayload: {
        officeCode: "HB-JG",
        officeName: "河北分公司-建筑结构所",
        accountId: "repair-user",
        displayName: "修复账号",
        role: "设计人员",
        password: "password",
      },
    });
  });
});

describe("recent task groups area", () => {
  it("filters recent task groups locally by status without refetching the list", async () => {
    mockListTaskGroups.mockResolvedValue({
      total: 4,
      items: [
        {
          ...makeTaskGroupSummary(1, "queued-job.dwg"),
          status: "queued",
        },
        {
          ...makeTaskGroupSummary(2, "running-job.dwg"),
          status: "running",
        },
        {
          ...makeTaskGroupSummary(3, "success-job.dwg"),
          status: "succeeded",
        },
        {
          ...makeTaskGroupSummary(4, "failed-job.dwg"),
          status: "failed",
        },
      ],
    });

    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("success-job.dwg")).toBeInTheDocument();
    expect(mockListTaskGroups).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "排队中" }));
    expect(screen.getByRole("button", { name: "排队中" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("queued-job.dwg")).toBeInTheDocument();
    expect(screen.queryByText("running-job.dwg")).not.toBeInTheDocument();
    expect(screen.queryByText("success-job.dwg")).not.toBeInTheDocument();
    expect(screen.queryByText("failed-job.dwg")).not.toBeInTheDocument();
    expect(mockListTaskGroups).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "成功" }));
    expect(screen.getByRole("button", { name: "成功" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("success-job.dwg")).toBeInTheDocument();
    expect(screen.queryByText("queued-job.dwg")).not.toBeInTheDocument();
    expect(screen.queryByText("running-job.dwg")).not.toBeInTheDocument();
    expect(screen.queryByText("failed-job.dwg")).not.toBeInTheDocument();
    expect(mockListTaskGroups).toHaveBeenCalledTimes(1);
  });

  it("shows eight task-group cards by default and opens the rest in a modal", async () => {
    mockListTaskGroups.mockResolvedValue({
      total: 10,
      items: Array.from({ length: 10 }, (_, index) =>
        makeTaskGroupSummary(index + 1, `sample-${index + 1}.dwg`),
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

  it("shows all matching task groups while searching", async () => {
    mockListTaskGroups.mockResolvedValue({
      total: 8,
      items: [
        makeTaskGroupSummary(1, "sample-1.dwg"),
        makeTaskGroupSummary(2, "20261RS-JGS65.dwg"),
        makeTaskGroupSummary(3, "sample-3.dwg"),
        makeTaskGroupSummary(4, "18185NE-JGS11.dwg"),
        makeTaskGroupSummary(5, "sample-5.dwg"),
        makeTaskGroupSummary(6, "20261RS-JGS66.dwg"),
        makeTaskGroupSummary(7, "sample-7.dwg"),
        makeTaskGroupSummary(8, "sample-8.dwg"),
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

describe("task group management", () => {
  it("loads recent task groups from the management endpoint and links to task-group details", async () => {
    mockListTaskGroups.mockResolvedValue({
      total: 1,
      items: [
        {
          ...makeTaskGroupSummary(1, "album-1.dwg"),
          status: "running",
          workflowStatus: "in_review",
          currentNodeKey: "one_review",
          canSubmit: true,
        },
      ],
    });

    render(<App />);

    expect(await screen.findByText("album-1.dwg")).toBeInTheDocument();
    expect(mockListTaskGroups).toHaveBeenCalledTimes(1);
    expect(mockListJobs).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "查看任务包" })).toHaveAttribute(
      "href",
      "/task-groups/group-1",
    );
  });

  it("retries submit after confirming archive overwrite conflicts", async () => {
    mockListTaskGroups.mockResolvedValue({
      total: 1,
      items: [
        {
          ...makeTaskGroupSummary(1, "album-1.dwg"),
          status: "queued",
          canSubmit: true,
        },
      ],
    });
    mockSubmitTaskGroup
      .mockRejectedValueOnce({
        status: 422,
        detail: "archive_target_exists",
      })
      .mockResolvedValueOnce({
        ...makeTaskGroupSummary(1, "album-1.dwg"),
        status: "running",
        workflowStatus: "submitted",
        canSubmit: false,
      });

    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "提交" }));
    expect(
      await screen.findByText("归档目标已存在，是否覆盖归档后继续提交？"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "继续提交" }));

    expect(mockSubmitTaskGroup).toHaveBeenNthCalledWith(1, "group-1", {
      overwriteArchiveExisting: false,
      cancelExistingInProgress: false,
    });
    expect(mockSubmitTaskGroup).toHaveBeenNthCalledWith(2, "group-1", {
      overwriteArchiveExisting: true,
      cancelExistingInProgress: false,
    });
  });

  it("retries submit after confirming duplicate workflow cancellation", async () => {
    mockListTaskGroups.mockResolvedValue({
      total: 1,
      items: [
        {
          ...makeTaskGroupSummary(1, "album-1.dwg"),
          status: "queued",
          canSubmit: true,
        },
      ],
    });
    mockSubmitTaskGroup
      .mockRejectedValueOnce({
        status: 422,
        detail: "duplicate_in_progress_exists",
      })
      .mockResolvedValueOnce({
        ...makeTaskGroupSummary(1, "album-1.dwg"),
        status: "running",
        workflowStatus: "submitted",
        canSubmit: false,
      });

    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "提交" }));
    expect(
      await screen.findByText("已有同图册流程在执行中，是否取消旧流程并重新提交？"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "取消旧流程并重提" }));

    expect(mockSubmitTaskGroup).toHaveBeenNthCalledWith(1, "group-1", {
      overwriteArchiveExisting: false,
      cancelExistingInProgress: false,
    });
    expect(mockSubmitTaskGroup).toHaveBeenNthCalledWith(2, "group-1", {
      overwriteArchiveExisting: false,
      cancelExistingInProgress: true,
    });
  });

  it("shows a clear message when a non-creator tries to submit", async () => {
    mockListTaskGroups.mockResolvedValue({
      total: 1,
      items: [
        {
          ...makeTaskGroupSummary(1, "album-1.dwg"),
          status: "queued",
          canSubmit: true,
        },
      ],
    });
    mockSubmitTaskGroup.mockRejectedValueOnce({
      status: 422,
      detail: "submitter_must_match_creator",
    });

    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "提交" }));
    expect(await screen.findByText("仅创建者本人可提交")).toBeInTheDocument();
  });

  it("renders the task-group detail route instead of the placeholder page", async () => {
    window.history.pushState({}, "", "/task-groups/group-1");
    mockGetTaskGroupDetail.mockResolvedValue({
      ...makeTaskGroupSummary(1, "album-1.dwg"),
      childJobIds: ["deliverable-1", "audit-1"],
      personnelSnapshot: {
        members: {
          ied_prepared_by: {
            fieldName: "ied_prepared_by",
            rawValue: "张三",
            normalizedValue: "张三@zhangsan",
            matchedAccount: "zhangsan",
            matchedName: "张三",
            matchStrategy: "exact",
            status: "matched",
            errors: [],
          },
        },
      },
      workflow: {
        status: "submitted",
        initiatedAt: "2026-03-25T10:20:30+08:00",
        initiatedByAccount: "zhangsan",
        initiatedByName: "张三",
        duplicatePolicy: null,
        overwriteArchiveTarget: null,
        currentNodeKey: "one_review",
        nodes: [
          {
            nodeKey: "one_review",
            nodeLabel: "一审",
            assigneeAccount: "lisi",
            assigneeName: "李四",
            status: "current",
            factor: 1,
            approvedAt: null,
            actedByAccount: null,
            actedByName: null,
          },
        ],
        archiveStatus: null,
        archiveRetryCount: 0,
        archiveLastError: null,
        archiveLastAttemptAt: null,
      },
      archive: {
        archiveRootPath: "D:\\Archive",
        targetDir: "D:\\Archive\\2026\\album-1",
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
      legacyVisibility: {
        scope: "owner_only",
        reason: null,
      },
    });
    mockGetJobDetail
      .mockResolvedValueOnce({
        ...makeSingleJob(1, "album-1.dwg"),
        jobId: "deliverable-1",
        groupId: "group-1",
        taskKind: "deliverable",
      })
      .mockResolvedValueOnce({
        ...makeSingleJob(2, "album-1.dwg"),
        jobId: "audit-1",
        groupId: "group-1",
        taskKind: "audit_check",
      });

    render(<App />);

    expect(await screen.findByText("任务包概览")).toBeInTheDocument();
    expect(screen.getAllByText("归档状态").length).toBeGreaterThan(0);
    expect(screen.getByText("一审")).toBeInTheDocument();
    expect(mockGetTaskGroupDetail).toHaveBeenCalledWith("group-1");
  });
});

describe("task group cards", () => {
  it("renders submit and detail actions from backend permissions", async () => {
    mockListTaskGroups.mockResolvedValue({
      total: 1,
      items: [
        {
          ...makeTaskGroupSummary(1, "18185NE-JGS11.dwg"),
          status: "running",
          workflowStatus: "in_review",
          currentNodeKey: "one_review",
          canSubmit: true,
        },
      ],
    });

    render(<App />);

    expect(await screen.findByText("流程：审批中")).toBeInTheDocument();
    expect(screen.getByText("任务包")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看任务包" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提交" })).toBeInTheDocument();
  });

  it("renders an approval shortcut when the backend marks a group as approvable", async () => {
    mockListTaskGroups.mockResolvedValue({
      total: 1,
      items: [
        {
          ...makeTaskGroupSummary(1, "20261RS-JGS65.dwg"),
          status: "running",
          workflowStatus: "in_review",
          currentNodeKey: "one_review",
          canApprove: true,
        },
      ],
    });

    render(<App />);

    expect(await screen.findByRole("link", { name: "前往审批" })).toHaveAttribute(
      "href",
      "/workload",
    );
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
