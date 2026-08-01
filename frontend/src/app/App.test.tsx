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
const mockCreateCalculationBook = vi.fn();
const mockListJobs = vi.fn();
const mockGetJobsActivity = vi.fn();
const mockSubscribeJobsActivity = vi.fn();
const mockGetJobDetail = vi.fn();
const mockGetMe = vi.fn();
const mockLogin = vi.fn();
const mockLogout = vi.fn();
const mockReadArtifact = vi.fn();
const mockGetAiState = vi.fn();
const mockListAiConversations = vi.fn();
const mockCreateAiConversation = vi.fn();
const mockGetAiConversation = vi.fn();
const mockRenameAiConversation = vi.fn();
const mockSendAiMessage = vi.fn();
const mockClearAiConversation = vi.fn();
const mockDeleteAiConversation = vi.fn();
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
    login: mockLogin,
    logout: mockLogout,
    getMe: mockGetMe,
    readArtifact: mockReadArtifact,
    ping: mockPing,
    getHealth: mockGetHealth,
    getFormSchema: mockGetFormSchema,
    preflightFonts: mockPreflightFonts,
    createBatch: mockCreateBatch,
    createAuditCheck: mockCreateAuditCheck,
    createAuditReplace: mockCreateAuditReplace,
    createCalculationBook: mockCreateCalculationBook,
    listJobs: mockListJobs,
    getJobsActivity: mockGetJobsActivity,
    subscribeJobsActivity: mockSubscribeJobsActivity,
    getJobDetail: mockGetJobDetail,
    getAiState: mockGetAiState,
    listAiConversations: mockListAiConversations,
    createAiConversation: mockCreateAiConversation,
    getAiConversation: mockGetAiConversation,
    renameAiConversation: mockRenameAiConversation,
    sendAiMessage: mockSendAiMessage,
    clearAiConversation: mockClearAiConversation,
    deleteAiConversation: mockDeleteAiConversation,
  }),
}));

beforeEach(() => {
  window.history.pushState({}, "", "/");
  window.localStorage.clear();

  mockPing.mockReset();
  mockGetHealth.mockReset();
  mockGetFormSchema.mockReset();
  mockPreflightFonts.mockReset();
  mockCreateBatch.mockReset();
  mockCreateAuditCheck.mockReset();
  mockCreateAuditReplace.mockReset();
  mockCreateCalculationBook.mockReset();
  mockListJobs.mockReset();
  mockGetJobsActivity.mockReset();
  mockSubscribeJobsActivity.mockReset();
  mockGetJobDetail.mockReset();
  mockGetMe.mockReset();
  mockLogin.mockReset();
  mockLogout.mockReset();
  mockReadArtifact.mockReset();
  window.localStorage.setItem("auth_token", "test-access-token");
  mockGetAiState.mockReset();
  mockListAiConversations.mockReset();
  mockCreateAiConversation.mockReset();
  mockGetAiConversation.mockReset();
  mockRenameAiConversation.mockReset();
  mockSendAiMessage.mockReset();
  mockClearAiConversation.mockReset();
  mockDeleteAiConversation.mockReset();

  mockPing.mockResolvedValue({
    ok: true,
    serverTime: "2026-03-08T10:20:29+08:00",
  });
  mockGetMe.mockResolvedValue({
    accountId: "test-user",
    displayName: "测试用户",
    role: "管理员",
    officeCode: "25C0",
    officeName: "建筑结构所",
    valid: true,
    pendingTodoCount: 0,
  });
  mockReadArtifact.mockResolvedValue({
    arrayBuffer: () => Promise.resolve(new TextEncoder().encode("pdf-data").buffer),
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
    calculationBook: {
      templates: [{ value: "internal_structure", label: "内部结构计算书" }],
      projectOptions: [{ value: "2016", label: "浙江金七门核电厂1、2号机组" }],
      fields: [
        {
          key: "template_type",
          label: "计算书模板",
          type: "select",
          required: true,
          defaultValue: "internal_structure",
          options: [],
        },
      ],
      archive: {
        accept: [".zip"],
        requiredRootFigures: ["X", "Y", "Z"],
        requiredDirectories: ["01", "02"],
        description: "保留目录结构",
      },
    },
  });

  mockListJobs.mockResolvedValue({
    total: 0,
    items: [],
  });
  mockGetJobsActivity.mockResolvedValue({
    total: 0,
    active: 0,
    lastChangedAt: null,
  });
  mockSubscribeJobsActivity.mockReturnValue(() => {});
  mockPreflightFonts.mockResolvedValue({
    files: [],
    replacementOptions: [],
    requiresConfirmation: false,
  });
  mockGetAiState.mockResolvedValue({
    enabled: true,
    profile: "development_minimax",
    model: "MiniMax-M3",
    ownerKey: "ip:127.0.0.1",
    defaultAgent: "general_assistant",
    agents: [
      {
        agentId: "general_assistant",
        name: "通用对话",
        description: "自由对话与只读信息查询",
      },
      {
        agentId: "business_agent",
        name: "业务 Agent",
        description: "统一处理图纸、任务与模板业务",
      },
    ],
    skills: [],
    mcpServers: [],
  });
  mockListAiConversations.mockResolvedValue([
    {
      conversationId: "conv-1",
      title: "记忆验证",
      createdAt: "2026-07-11T10:00:00+08:00",
      updatedAt: "2026-07-11T10:02:00+08:00",
      messageCount: 2,
    },
  ]);
  mockGetAiConversation.mockResolvedValue({
    conversationId: "conv-1",
    title: "记忆验证",
    createdAt: "2026-07-11T10:00:00+08:00",
    updatedAt: "2026-07-11T10:02:00+08:00",
    messages: [
      {
        messageId: "msg-1",
        role: "user",
        content: "请记住我的测试编号是 AI-0711",
        createdAt: "2026-07-11T10:01:00+08:00",
      },
      {
        messageId: "msg-2",
        role: "assistant",
        content: "我已记住 AI-0711",
        createdAt: "2026-07-11T10:01:04+08:00",
      },
    ],
  });
  mockCreateAiConversation.mockResolvedValue({
    conversationId: "conv-new",
    title: "新会话",
    createdAt: "2026-07-11T10:03:00+08:00",
    updatedAt: "2026-07-11T10:03:00+08:00",
    messageCount: 0,
  });
  mockRenameAiConversation.mockResolvedValue({
    conversationId: "conv-1",
    title: "规则提炼会话",
    createdAt: "2026-07-11T10:00:00+08:00",
    updatedAt: "2026-07-11T10:04:00+08:00",
    messageCount: 2,
  });
  mockSendAiMessage.mockResolvedValue({
    conversationId: "conv-1",
    userMessage: {
      messageId: "msg-3",
      role: "user",
      content: "我刚才的测试编号是什么？",
      createdAt: "2026-07-11T10:03:00+08:00",
    },
    assistantMessage: {
      messageId: "msg-4",
      role: "assistant",
      content: "你的测试编号是 AI-0711。",
      createdAt: "2026-07-11T10:03:02+08:00",
    },
    memory: {
      usedHistoryMessages: 2,
    },
  });
  mockClearAiConversation.mockResolvedValue(undefined);
  mockDeleteAiConversation.mockResolvedValue(undefined);

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
    expect(screen.getByRole("button", { name: "标准化出图" })).toBeEnabled();
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
    expect(screen.getByRole("button", { name: "标准化出图" })).toBeEnabled();
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
    expect(screen.getByRole("button", { name: "标准化出图" })).toBeDisabled();
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
    expect(screen.getByRole("button", { name: "标准化出图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "计算书" })).toBeInTheDocument();

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
    expect(within(toolbar).queryByRole("button", { name: "AI 助手" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开 AI 助手" })).toBeInTheDocument();
  });

  it("opens calculation-book creation as a same-level business action", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("button", { name: "打开 AI 助手" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "计算书" }));

    expect(await screen.findByRole("dialog", { name: "创建计算书" })).toBeInTheDocument();
    expect(screen.getByLabelText("压缩包必需结构")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "打开 AI 助手" })).not.toBeInTheDocument();
  });

  it("opens the floating AI drawer and sends a message with conversation memory", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(document.body.style.overflow).toBe("");
    await user.click(await screen.findByRole("button", { name: "打开 AI 助手" }));
    expect(document.body.style.overflow).toBe("hidden");

    const drawer = await screen.findByRole("dialog", { name: "AI 助手" });
    expect(within(drawer).getByText("MiniMax-M3")).toBeInTheDocument();
    expect(within(drawer).getByText("development_minimax")).toBeInTheDocument();
    const modeSelect = within(drawer).getByRole("combobox", { name: "对话模式" });
    expect(within(modeSelect).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "通用对话",
      "业务 Agent",
    ]);
    expect(within(drawer).queryByText("能力设置")).not.toBeInTheDocument();
    expect(within(drawer).queryByLabelText("技能")).not.toBeInTheDocument();
    expect(within(drawer).queryByLabelText("MCP 能力")).not.toBeInTheDocument();
    expect(within(drawer).getAllByText("记忆验证")).toHaveLength(1);
    expect(within(drawer).getByText("请记住我的测试编号是 AI-0711")).toBeInTheDocument();
    expect(within(drawer).getByText("我已记住 AI-0711")).toBeInTheDocument();

    await user.type(within(drawer).getByRole("textbox", { name: "输入 AI 对话内容" }), "我刚才的测试编号是什么？");
    await user.click(within(drawer).getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(mockSendAiMessage).toHaveBeenCalledWith(
        "conv-1",
        {
          content: "我刚才的测试编号是什么？",
          agentId: "general_assistant",
          skillIds: [],
          mcpServerIds: [],
        },
        expect.any(AbortSignal),
      );
    });
    expect(await within(drawer).findByText("你的测试编号是 AI-0711。")).toBeInTheDocument();
    expect(within(drawer).getByText("已使用 2 条历史消息")).toBeInTheDocument();

    await user.click(within(drawer).getByRole("button", { name: "关闭 AI 助手" }));
    await screen.findByRole("button", { name: "打开 AI 助手" });
    expect(document.body.style.overflow).toBe("");
  });

  it("renders assistant Markdown while keeping user messages as literal text", async () => {
    const user = userEvent.setup();
    mockGetAiConversation.mockResolvedValueOnce({
      conversationId: "conv-1",
      title: "格式验证",
      createdAt: "2026-07-20T09:00:00+08:00",
      updatedAt: "2026-07-20T09:01:00+08:00",
      messages: [
        {
          messageId: "format-user",
          role: "user",
          content: "**用户输入不加粗**",
          createdAt: "2026-07-20T09:00:00+08:00",
        },
        {
          messageId: "format-assistant",
          role: "assistant",
          content: [
            "## APDL 示例",
            "",
            "- 保留列表",
            "",
            "```apdl",
            "/PREP7",
            "ET,1,SOLID185",
            "```",
          ].join("\n"),
          createdAt: "2026-07-20T09:01:00+08:00",
        },
      ],
    });

    render(<App />);
    await user.click(await screen.findByRole("button", { name: "打开 AI 助手" }));
    const drawer = await screen.findByRole("dialog", { name: "AI 助手" });

    const userText = await within(drawer).findByText("**用户输入不加粗**");
    expect(userText.tagName).toBe("P");
    expect(userText.closest("article")?.querySelector("strong")).not.toBeInTheDocument();
    expect(within(drawer).getByRole("heading", { name: "APDL 示例" })).toBeInTheDocument();
    expect(within(drawer).getByText("保留列表").closest("li")).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "复制 APDL 代码" })).toBeInTheDocument();
  });

  it("keeps keyboard focus in the AI dialog and restores the collapsed trigger", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "打开 AI 助手" }));
    const drawer = await screen.findByRole("dialog", { name: "AI 助手" });
    expect(drawer).toHaveAttribute("aria-modal", "true");

    const backgroundButton = screen.getByRole("button", { name: "教程" });
    backgroundButton.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(drawer).toContainElement(document.activeElement as HTMLElement);

    backgroundButton.focus();
    fireEvent.keyDown(document, { key: "Escape" });
    const collapsedTrigger = await screen.findByRole("button", { name: "打开 AI 助手" });
    await waitFor(() => expect(collapsedTrigger).toHaveFocus());
  });

  it("resizes the AI drawer from its accessible resize handle and remembers the size", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "打开 AI 助手" }));
    const drawer = await screen.findByRole("dialog", { name: "AI 助手" });
    const handle = within(drawer).getByRole("separator", { name: "调整 AI 助手窗口大小" });
    const initialWidth = drawer.style.getPropertyValue("--ai-drawer-width");
    const initialHeight = drawer.style.getPropertyValue("--ai-drawer-height");

    expect(Number.parseInt(initialWidth, 10)).toBeGreaterThanOrEqual(700);
    expect(Number.parseInt(initialHeight, 10)).toBe(window.innerHeight);

    fireEvent.pointerDown(handle, { clientX: 960, clientY: 80 });
    expect(handle).toHaveFocus();
    fireEvent.keyDown(handle, { key: "ArrowLeft" });

    expect(drawer.style.getPropertyValue("--ai-drawer-width")).not.toBe(initialWidth);
    expect(window.localStorage.getItem("fanban.ai.drawerSize")).toContain("width");
  });

  it("shows a user message and thinking state immediately and cancels the browser wait", async () => {
    const user = userEvent.setup();
    let requestSignal: AbortSignal | undefined;
    mockSendAiMessage.mockImplementation(
      (_conversationId: string, _payload: unknown, signal?: AbortSignal) => {
        requestSignal = signal;
        return new Promise((_, reject) => {
          signal?.addEventListener(
            "abort",
            () => reject(new DOMException("The request was aborted.", "AbortError")),
            { once: true },
          );
        });
      },
    );

    render(<App />);
    await user.click(await screen.findByRole("button", { name: "打开 AI 助手" }));
    const drawer = await screen.findByRole("dialog", { name: "AI 助手" });
    const composer = within(drawer).getByRole("textbox", { name: "输入 AI 对话内容" });
    await user.type(composer, "请立即显示这条消息");
    await user.click(within(drawer).getByRole("button", { name: "发送" }));

    expect(await within(drawer).findByText("请立即显示这条消息")).toBeInTheDocument();
    expect(within(drawer).getByText("AI 正在思考")).toBeInTheDocument();
    await user.click(within(drawer).getByRole("button", { name: "停止等待" }));

    await waitFor(() => expect(requestSignal?.aborted).toBe(true));
    expect(within(drawer).queryByText("AI 正在思考")).not.toBeInTheDocument();
    expect(within(drawer).getByText("已停止等待")).toBeInTheDocument();
    await waitFor(() => expect(composer).not.toBeDisabled());
    expect(mockGetAiConversation).toHaveBeenCalledTimes(1);
  });

  it("clears the displayed memory count when switching AI conversations", async () => {
    const user = userEvent.setup();
    const firstConversation = await mockGetAiConversation();
    mockListAiConversations.mockResolvedValue([
      {
        conversationId: "conv-1",
        title: "会话一",
        createdAt: "2026-07-11T10:00:00+08:00",
        updatedAt: "2026-07-11T10:02:00+08:00",
        messageCount: 2,
      },
      {
        conversationId: "conv-2",
        title: "会话二",
        createdAt: "2026-07-11T11:00:00+08:00",
        updatedAt: "2026-07-11T11:01:00+08:00",
        messageCount: 1,
      },
    ]);
    mockGetAiConversation.mockReset();
    mockGetAiConversation.mockImplementation((conversationId: string) =>
      Promise.resolve(
        conversationId === "conv-2"
          ? {
              conversationId: "conv-2",
              title: "会话二",
              createdAt: "2026-07-11T11:00:00+08:00",
              updatedAt: "2026-07-11T11:01:00+08:00",
              messageCount: 1,
              messages: [
                {
                  messageId: "conv-2-msg",
                  role: "assistant",
                  content: "第二个会话",
                  createdAt: "2026-07-11T11:01:00+08:00",
                },
              ],
            }
          : { ...firstConversation, title: "会话一" },
      ),
    );

    render(<App />);
    await user.click(await screen.findByRole("button", { name: "打开 AI 助手" }));
    const drawer = await screen.findByRole("dialog", { name: "AI 助手" });
    await user.type(
      within(drawer).getByRole("textbox", { name: "输入 AI 对话内容" }),
      "记忆测试",
    );
    await user.click(within(drawer).getByRole("button", { name: "发送" }));
    expect(await within(drawer).findByText("已使用 2 条历史消息")).toBeInTheDocument();

    await user.click(within(drawer).getByRole("button", { name: "会话二" }));
    expect(await within(drawer).findByText("第二个会话")).toBeInTheDocument();
    expect(within(drawer).queryByText("已使用 2 条历史消息")).not.toBeInTheDocument();
    expect(within(drawer).queryByText("记忆 2")).not.toBeInTheDocument();
  });

  it("does not apply an old in-flight response memory count to a newly selected conversation", async () => {
    const user = userEvent.setup();
    const firstConversation = await mockGetAiConversation();
    mockListAiConversations.mockResolvedValue([
      {
        conversationId: "conv-1",
        title: "会话一",
        createdAt: "2026-07-11T10:00:00+08:00",
        updatedAt: "2026-07-11T10:02:00+08:00",
        messageCount: 2,
      },
      {
        conversationId: "conv-2",
        title: "会话二",
        createdAt: "2026-07-11T11:00:00+08:00",
        updatedAt: "2026-07-11T11:01:00+08:00",
        messageCount: 1,
      },
    ]);
    mockGetAiConversation.mockReset();
    mockGetAiConversation.mockImplementation((conversationId: string) =>
      Promise.resolve(
        conversationId === "conv-2"
          ? {
              conversationId: "conv-2",
              title: "会话二",
              createdAt: "2026-07-11T11:00:00+08:00",
              updatedAt: "2026-07-11T11:01:00+08:00",
              messageCount: 1,
              messages: [
                {
                  messageId: "conv-2-msg",
                  role: "assistant",
                  content: "第二个会话",
                  createdAt: "2026-07-11T11:01:00+08:00",
                },
              ],
            }
          : { ...firstConversation, title: "会话一" },
      ),
    );

    let resolveSend!: (value: Awaited<ReturnType<typeof mockSendAiMessage>>) => void;
    mockSendAiMessage.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveSend = resolve;
        }),
    );

    render(<App />);
    await user.click(await screen.findByRole("button", { name: "打开 AI 助手" }));
    const drawer = await screen.findByRole("dialog", { name: "AI 助手" });
    await user.type(
      within(drawer).getByRole("textbox", { name: "输入 AI 对话内容" }),
      "仍在生成的会话一问题",
    );
    await user.click(within(drawer).getByRole("button", { name: "发送" }));
    await waitFor(() => expect(mockSendAiMessage).toHaveBeenCalledTimes(1));

    await user.click(within(drawer).getByRole("button", { name: "会话二" }));
    expect(await within(drawer).findByText("第二个会话")).toBeInTheDocument();

    await act(async () => {
      resolveSend({
        conversationId: "conv-1",
        userMessage: {
          messageId: "msg-late-user",
          role: "user",
          content: "仍在生成的会话一问题",
          createdAt: "2026-07-11T11:02:00+08:00",
        },
        assistantMessage: {
          messageId: "msg-late-assistant",
          role: "assistant",
          content: "会话一的迟到回复",
          createdAt: "2026-07-11T11:02:01+08:00",
        },
        memory: { usedHistoryMessages: 2 },
      });
    });

    expect(within(drawer).queryByText("已使用 2 条历史消息")).not.toBeInTheDocument();
    expect(within(drawer).queryByText("记忆 2")).not.toBeInTheDocument();
  });

  it("manages an AI conversation from its context menu without adding a module tab", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "打开 AI 助手" }));

    const drawer = await screen.findByRole("dialog", { name: "AI 助手" });
    expect(within(drawer).queryByRole("button", { name: "重命名会话" })).not.toBeInTheDocument();
    expect(within(drawer).queryByRole("button", { name: "清空" })).not.toBeInTheDocument();

    fireEvent.contextMenu(await within(drawer).findByRole("button", { name: "记忆验证" }), {
      clientX: 240,
      clientY: 160,
    });
    const menu = await screen.findByRole("menu", { name: "会话操作" });
    expect(drawer).not.toContainElement(menu);
    await user.click(within(menu).getByRole("menuitem", { name: "重命名会话" }));
    const titleInput = within(drawer).getByRole("textbox", { name: "会话标题" });
    await user.clear(titleInput);
    await user.type(titleInput, "规则提炼会话");
    await user.click(within(drawer).getByRole("button", { name: "保存会话标题" }));

    await waitFor(() => {
      expect(mockRenameAiConversation).toHaveBeenCalledWith("conv-1", "规则提炼会话");
    });
    await waitFor(() => {
      expect(within(drawer).getAllByText("规则提炼会话").length).toBeGreaterThan(0);
    });
    expect(
      within(screen.getByTestId("module-toolbar")).queryByRole("button", { name: "AI 助手" }),
    ).not.toBeInTheDocument();
  });

  it("keeps conversation management in the context menu without a visible ellipsis button", async () => {
    render(<App />);

    await userEvent.setup().click(await screen.findByRole("button", { name: "打开 AI 助手" }));
    const drawer = await screen.findByRole("dialog", { name: "AI 助手" });

    expect(
      within(drawer).queryByRole("button", { name: "打开 记忆验证 会话操作" }),
    ).not.toBeInTheDocument();

    fireEvent.contextMenu(await within(drawer).findByRole("button", { name: "记忆验证" }), {
      clientX: 240,
      clientY: 160,
    });

    const menu = await screen.findByRole("menu", { name: "会话操作" });
    expect(drawer).not.toContainElement(menu);
  });

  it("clears an AI conversation from its context menu", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "打开 AI 助手" }));
    const drawer = await screen.findByRole("dialog", { name: "AI 助手" });

    fireEvent.contextMenu(await within(drawer).findByRole("button", { name: "记忆验证" }), {
      clientX: 240,
      clientY: 160,
    });
    const menu = await screen.findByRole("menu", { name: "会话操作" });
    await user.click(within(menu).getByRole("menuitem", { name: "清空消息" }));

    await waitFor(() => expect(mockClearAiConversation).toHaveBeenCalledWith("conv-1"));
  });

  it("deletes an AI conversation from its context menu", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "打开 AI 助手" }));
    const drawer = await screen.findByRole("dialog", { name: "AI 助手" });

    fireEvent.contextMenu(await within(drawer).findByRole("button", { name: "记忆验证" }), {
      clientX: 240,
      clientY: 160,
    });
    const menu = await screen.findByRole("menu", { name: "会话操作" });
    await user.click(within(menu).getByRole("menuitem", { name: "删除会话" }));

    await waitFor(() => expect(mockDeleteAiConversation).toHaveBeenCalledWith("conv-1"));
    expect(within(drawer).queryByRole("button", { name: "记忆验证" })).not.toBeInTheDocument();
  });

  it("recovers from a stale listed AI conversation without exposing a not-found error", async () => {
    window.localStorage.setItem("fanban.ai.selectedConversationId", "conv-stale");
    mockListAiConversations
      .mockResolvedValueOnce([
        {
          conversationId: "conv-stale",
          title: "已失效会话",
          createdAt: "2026-07-11T10:00:00+08:00",
          updatedAt: "2026-07-11T10:01:00+08:00",
          messageCount: 2,
        },
      ])
      .mockResolvedValue([
        {
          conversationId: "conv-live",
          title: "仍可用会话",
          createdAt: "2026-07-11T10:02:00+08:00",
          updatedAt: "2026-07-11T10:03:00+08:00",
          messageCount: 1,
        },
      ]);
    mockGetAiConversation.mockImplementation((conversationId: string) => {
      if (conversationId === "conv-stale") {
        return Promise.reject({ status: 404, detail: "conversation_not_found" });
      }
      return Promise.resolve({
        conversationId: "conv-live",
        title: "仍可用会话",
        createdAt: "2026-07-11T10:02:00+08:00",
        updatedAt: "2026-07-11T10:03:00+08:00",
        messageCount: 1,
        messages: [
          {
            messageId: "live-message",
            role: "assistant",
            content: "这是可恢复的会话。",
            createdAt: "2026-07-11T10:03:00+08:00",
          },
        ],
      });
    });

    render(<App />);
    await userEvent.setup().click(await screen.findByRole("button", { name: "打开 AI 助手" }));
    const drawer = await screen.findByRole("dialog", { name: "AI 助手" });

    expect(await within(drawer).findByText("这是可恢复的会话。")).toBeInTheDocument();
    await waitFor(() => {
      expect(mockListAiConversations).toHaveBeenCalledTimes(2);
      expect(window.localStorage.getItem("fanban.ai.selectedConversationId")).toBe("conv-live");
    });
    expect(within(drawer).queryByText("conversation_not_found")).not.toBeInTheDocument();
  });

  it("drops a stale stored AI conversation before sending for a new owner", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem("fanban.ai.selectedConversationId", "conv-from-old-ip");
    mockListAiConversations.mockResolvedValue([]);
    mockGetAiConversation.mockRejectedValue({ status: 404, detail: "conversation_not_found" });
    mockSendAiMessage.mockResolvedValue({
      conversationId: "conv-new",
      userMessage: {
        messageId: "msg-new-user",
        role: "user",
        content: "新用户的问题",
        createdAt: "2026-07-12T12:00:00+08:00",
      },
      assistantMessage: {
        messageId: "msg-new-assistant",
        role: "assistant",
        content: "新用户回复",
        createdAt: "2026-07-12T12:00:01+08:00",
      },
      memory: { usedHistoryMessages: 0 },
    });

    render(<App />);
    await user.click(await screen.findByRole("button", { name: "打开 AI 助手" }));
    const drawer = await screen.findByRole("dialog", { name: "AI 助手" });
    await user.type(
      within(drawer).getByRole("textbox", { name: "输入 AI 对话内容" }),
      "新用户的问题",
    );
    await user.click(within(drawer).getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(mockCreateAiConversation).toHaveBeenCalledWith("新用户的问题");
    });
    expect(mockSendAiMessage).toHaveBeenCalledWith(
      "conv-new",
      expect.objectContaining({ content: "新用户的问题" }),
      expect.any(AbortSignal),
    );
    expect(mockGetAiConversation).not.toHaveBeenCalledWith("conv-from-old-ip");
  });

  it("refreshes and marks a persisted AI message after a gateway failure", async () => {
    const user = userEvent.setup();
    const initialConversation = await mockGetAiConversation();
    mockGetAiConversation.mockReset();
    mockGetAiConversation
      .mockResolvedValueOnce(initialConversation)
      .mockResolvedValue({
        ...initialConversation,
        messageCount: 4,
        messages: [
          ...initialConversation.messages,
          {
            messageId: "msg-failed",
            role: "user",
            content: "这条消息发送失败",
            createdAt: "2026-07-12T12:10:00+08:00",
            metadata: { status: "failed", error_code: "ai_gateway_error" },
          },
          {
            messageId: "msg-pending",
            role: "user",
            content: "进程中断时未完成",
            createdAt: "2026-07-12T12:10:01+08:00",
            metadata: { status: "pending" },
          },
        ],
      });
    mockSendAiMessage.mockRejectedValue({
      status: 502,
      detail: { code: "ai_gateway_error", message: "model gateway request failed" },
    });

    render(<App />);
    await user.click(await screen.findByRole("button", { name: "打开 AI 助手" }));
    const drawer = await screen.findByRole("dialog", { name: "AI 助手" });
    const composer = within(drawer).getByRole("textbox", { name: "输入 AI 对话内容" });
    await user.type(composer, "这条消息发送失败");
    await user.click(within(drawer).getByRole("button", { name: "发送" }));

    expect(await within(drawer).findByText("model gateway request failed")).toBeInTheDocument();
    expect((await within(drawer).findAllByText("发送失败")).length).toBeGreaterThan(0);
    expect(await within(drawer).findByText("未完成")).toBeInTheDocument();
    expect(composer).toHaveValue("这条消息发送失败");
    expect(mockGetAiConversation).toHaveBeenCalledTimes(2);
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

    await user.click(await screen.findByRole("button", { name: "标准化出图" }));
    expect(await screen.findByRole("dialog", { name: "标准化出图配置" })).toBeInTheDocument();
  });

  it("removes the continue-draft entry immediately after clearing a deliverable draft", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.upload(
      await screen.findByLabelText("选择出图 DWG 文件"),
      new File(["dwg"], "20261PC-JGS01-A.dwg", { type: "application/acad" }),
    );

    expect(await screen.findByRole("dialog", { name: "任务配置" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "继续草稿" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "清空草稿" }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "任务配置" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "继续草稿" })).not.toBeInTheDocument();
    });
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

    const tutorialPanel = screen.getByText("当前为演示模式，不会创建真实任务，也不会改动任务记录。").closest("aside");
    expect(tutorialPanel).not.toBeNull();
    await user.click(within(tutorialPanel!).getByRole("button", { name: "退出" }));
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
  it("opens a bounded jobs activity SSE stream only while jobs are active", async () => {
    let onActivity: ((activity: { total: number; active: number; lastChangedAt: string | null }) => void) | null =
      null;
    const unsubscribe = vi.fn();
    mockSubscribeJobsActivity.mockImplementation((activityHandler) => {
      onActivity = activityHandler;
      return unsubscribe;
    });
    mockListJobs.mockResolvedValue({
      total: 1,
      items: [
        {
          ...makeSingleJob(1, "sse-active.dwg"),
          status: "running",
          stage: "EXPORT_PDF_AND_DWG",
          percent: 60,
          finishedAt: null,
        },
      ],
    });
    mockGetJobsActivity.mockResolvedValue({
      total: 1,
      active: 1,
      lastChangedAt: "2026-07-10T08:00:00+08:00",
    });

    render(<App />);

    expect(await screen.findByText("sse-active.dwg")).toBeInTheDocument();
    expect(mockGetJobsActivity).toHaveBeenCalled();
    await waitFor(() => expect(mockSubscribeJobsActivity).toHaveBeenCalledTimes(1));

    mockListJobs.mockResolvedValue({
      total: 1,
      items: [makeSingleJob(1, "sse-active.dwg")],
    });
    act(() => {
      onActivity?.({
        total: 1,
        active: 0,
        lastChangedAt: "2026-07-10T08:00:03+08:00",
      });
    });

    await waitFor(() => expect(mockListJobs).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(unsubscribe).toHaveBeenCalledTimes(1));
  });

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
    expect(mockListJobs).toHaveBeenCalledWith("queued", 0, 100, "created_at");

    await user.click(screen.getByRole("button", { name: "成功" }));
    expect(screen.getByRole("button", { name: "成功" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByText("success-job.dwg")).toBeInTheDocument();
    expect(screen.queryByText("queued-job.dwg")).not.toBeInTheDocument();
    expect(screen.queryByText("running-job.dwg")).not.toBeInTheDocument();
    expect(screen.queryByText("failed-job.dwg")).not.toBeInTheDocument();
    expect(mockListJobs).toHaveBeenCalledWith("succeeded", 0, 100, "created_at");
  });

  it("shows the developer contact notice inside failed cards in the all-jobs view", async () => {
    mockListJobs.mockResolvedValue({
      total: 2,
      items: [
        {
          ...makeSingleJob(1, "failed-job.dwg"),
          status: "failed" as const,
        },
        makeSingleJob(2, "success-job.dwg"),
      ],
    });

    render(<App />);

    await screen.findAllByTestId("recent-job-card");
    const failedCard = screen
      .getByText("failed-job.dwg")
      .closest<HTMLElement>('[data-testid="recent-job-card"]');
    const succeededCard = screen
      .getByText("success-job.dwg")
      .closest<HTMLElement>('[data-testid="recent-job-card"]');
    if (!failedCard || !succeededCard) {
      throw new Error("expected recent job cards");
    }

    expect(
      within(failedCard).getByText(
        "点击“查看任务”查看错误原因进行检查，如有需要请联系开发人员：王任超。",
      ),
    ).toBeInTheDocument();
    expect(within(succeededCard).queryByRole("note")).not.toBeInTheDocument();
  });

  it("does not duplicate the developer contact notice when failed jobs are selected", async () => {
    mockListJobs.mockResolvedValue({
      total: 1,
      items: [
        {
          ...makeSingleJob(1, "failed-job.dwg"),
          status: "failed" as const,
        },
      ],
    });

    const user = userEvent.setup();
    render(<App />);

    await screen.findAllByTestId("recent-job-card");
    await user.click(screen.getByRole("button", { name: "失败" }));
    expect(
      await screen.findAllByText(
        "点击“查看任务”查看错误原因进行检查，如有需要请联系开发人员：王任超。",
      ),
    ).toHaveLength(1);
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

  it("uses loaded card count instead of backend total for the expand button", async () => {
    const jobs = Array.from({ length: 100 }, (_, index) =>
      makeSingleJob(index + 1, `sample-${index + 1}.dwg`),
    );
    mockListJobs.mockImplementation(async (_status?: string, offset = 0, limit = 100) => ({
      total: 369,
      items: jobs.slice(offset, offset + limit),
    }));

    render(<App />);

    expect(await screen.findAllByTestId("recent-job-card")).toHaveLength(8);
    expect(screen.getByRole("button", { name: "展开其余 92 个" })).toBeInTheDocument();
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
    await user.click(screen.getByRole("button", { name: "展开其余 92 个" }));

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
    window.history.pushState({}, "", "/task-groups/group-esc");
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

    const diagnosticsHeading = await screen.findByRole("heading", {
      level: 2,
      name: "问题原因",
    });
    const quickDownloadsHeading = screen.getByRole("heading", {
      level: 2,
      name: "快捷下载",
    });
    const overviewHeading = screen.getByRole("heading", {
      level: 2,
      name: "任务包概览",
    });
    expect(
      diagnosticsHeading.compareDocumentPosition(quickDownloadsHeading) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      diagnosticsHeading.compareDocumentPosition(overviewHeading) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
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
  it("shows failure diagnostics before quick downloads on single-job detail pages", async () => {
    window.history.pushState({}, "", "/jobs/failed-single-job");
    mockGetJobDetail.mockResolvedValue({
      ...makeSingleJob(20, "18185HL.dwg"),
      jobId: "failed-single-job",
      status: "failed",
      stage: "PACKAGE_ZIP",
      message: "CAD 导出失败",
      startedAt: "2026-07-27T09:00:10+08:00",
      currentFile: "18185HL.dwg",
      flags: ["CAD结果错误:打印媒体缺失"],
      errors: [],
      diagnostics: [
        {
          kind: "cad_output_missing",
          severity: "error",
          title: "CAD 导出或产物缺失",
          summary: "1 张图纸存在 CAD 导出、PDF 或 DWG 产物缺失问题。",
          suggestion: "请检查 CAD 环境和打印资源。",
          details: [],
          rawItems: ["CAD结果错误:打印媒体缺失"],
        },
      ],
      topWrongTexts: [],
      topInternalCodes: [],
    });

    render(<App />);

    const diagnosticsHeading = await screen.findByRole("heading", {
      level: 2,
      name: "问题原因",
    });
    const quickDownloadsHeading = screen.getByRole("heading", {
      level: 2,
      name: "快捷下载",
    });
    expect(
      diagnosticsHeading.compareDocumentPosition(quickDownloadsHeading) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("shows calculation-book results and the exact DOCX download action", async () => {
    window.history.pushState({}, "", "/jobs/calculation-book-1");
    mockGetJobDetail.mockResolvedValue({
      jobId: "calculation-book-1",
      batchId: "batch-calculation-book-1",
      groupId: null,
      isGroup: false,
      sourceFilename: "计算图片.zip",
      sourceFilenames: ["计算图片.zip"],
      taskKind: "calculation_book",
      taskRole: null,
      jobMode: "calculation_book",
      projectNo: "2016",
      status: "succeeded",
      stage: "CALCULATION_BOOK_COMPLETE",
      percent: 100,
      message: "",
      createdAt: "2026-07-23T10:00:00+08:00",
      finishedAt: "2026-07-23T10:05:00+08:00",
      startedAt: "2026-07-23T10:00:10+08:00",
      currentFile: null,
      runAuditCheck: false,
      childJobIds: [],
      findingsCount: 0,
      affectedDrawingsCount: 0,
      artifacts: {
        packageAvailable: false,
        iedAvailable: false,
        reportAvailable: false,
        replacedDwgAvailable: false,
        calculationDocxAvailable: true,
        calculationDocxDownloadUrl:
          "/api/jobs/calculation-book-1/download/calculation-book",
      },
      retryAvailable: false,
      sharedRunId: null,
      flags: [],
      errors: [],
      topWrongTexts: [],
      topInternalCodes: [],
      calculationBookOutput: {
        figureCount: 5,
        templateType: "internal_structure",
        outputFilename: "20160RX-JGS01-001-A计算书.docx",
        aiNormalized: false,
        warningCount: 0,
        warnings: [],
        aiNormalization: null,
      },
    });

    render(<App />);

    expect(await screen.findByRole("heading", { name: "计算书结果" })).toBeInTheDocument();
    expect(screen.getByText("内部结构计算书")).toBeInTheDocument();
    expect(screen.getByText("5 张")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "下载计算书 DOCX" }),
    ).toHaveAttribute("href", "/api/jobs/calculation-book-1/download/calculation-book");
    expect(
      screen.queryByRole("region", { name: "配筋表人工补充提醒" }),
    ).not.toBeInTheDocument();
  });

  it("keeps an AI-normalized calculation task successful while showing grouped supplement reminders", async () => {
    window.history.pushState({}, "", "/jobs/calculation-book-ai-1");
    mockGetJobDetail.mockResolvedValue({
      jobId: "calculation-book-ai-1",
      batchId: "batch-calculation-book-ai-1",
      groupId: null,
      isGroup: false,
      sourceFilename: "非标准配筋表.rar",
      sourceFilenames: ["非标准配筋表.rar"],
      taskKind: "calculation_book",
      taskRole: null,
      jobMode: "calculation_book",
      projectNo: "2016",
      status: "succeeded",
      stage: "CALCULATION_BOOK_COMPLETE",
      percent: 100,
      message: "",
      createdAt: "2026-08-01T10:00:00+08:00",
      finishedAt: "2026-08-01T10:05:00+08:00",
      startedAt: "2026-08-01T10:00:10+08:00",
      currentFile: null,
      runAuditCheck: false,
      childJobIds: [],
      findingsCount: 0,
      affectedDrawingsCount: 0,
      artifacts: {
        packageAvailable: false,
        iedAvailable: false,
        reportAvailable: false,
        replacedDwgAvailable: false,
        calculationDocxAvailable: true,
        calculationDocxDownloadUrl:
          "/api/jobs/calculation-book-ai-1/download/calculation-book",
      },
      retryAvailable: false,
      sharedRunId: null,
      flags: [],
      errors: [],
      topWrongTexts: [],
      topInternalCodes: [],
      calculationBookOutput: {
        figureCount: 174,
        templateType: "internal_structure",
        outputFilename: "AI规范化计算书.docx",
        aiNormalized: true,
        warningCount: 1,
        warnings: [
          {
            code: "image_only_wall",
            scope: "wall",
            identity: "N5012",
            direction: null,
            sourceSheet: null,
            sourceRow: null,
            sourceCells: {},
            reason: "应力图中存在该墙体，但配筋表没有对应数据，相关配筋字段已留空",
            blankFields: ["X", "Y", "Z"],
          },
        ],
        aiNormalization: {
          skillId: "reinforcement_table_normalizer",
          model: "structured-test",
          profile: "intranet-test",
          callCount: 1,
          sourceRowCount: 315,
          normalizedWallCount: 314,
          normalizedSlabCount: 0,
          reviewWarningCount: 1,
          durationMs: 125,
          validation: "passed",
        },
      },
    });

    render(<App />);

    expect(await screen.findByText("AI 已规范化非标准配筋表")).toBeInTheDocument();
    expect(screen.getByText("需人工补充 1 项")).toBeInTheDocument();
    expect(screen.getByText("墙体 N5012")).toBeInTheDocument();
    expect(screen.getByText("成功")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载计算书 DOCX" })).toHaveAttribute(
      "href",
      "/api/jobs/calculation-book-ai-1/download/calculation-book",
    );
    expect(
      screen.queryByText("任务已完成，但仍有告警或缺失项需要处理。"),
    ).not.toBeInTheDocument();
  });

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
    expect(screen.getByRole("button", { name: "下载预览 PDF" })).toBeEnabled();
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
    mockReadArtifact.mockRejectedValue(new Error("preview request failed with status 500"));

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

    expect(await screen.findByText("标准化出图摘要")).toBeInTheDocument();
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
