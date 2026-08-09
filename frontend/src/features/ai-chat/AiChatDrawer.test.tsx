import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AiAttachment, ApiAdapter } from "../../platform/api/types";
import { AiChatDrawer } from "./AiChatDrawer";

const attachment: AiAttachment = {
  attachmentId: "attachment-1",
  conversationId: "conversation-1",
  messageId: null,
  originalName: "说明.txt",
  mediaType: "text/plain",
  kind: "document",
  sizeBytes: 12,
  sha256: "abc123",
  status: "ready",
  metadata: {},
  errorCode: null,
  createdAt: "2026-07-22T10:00:00+08:00",
};

function createAdapter(options?: { historicalAttachment?: boolean }) {
  const uploadAiAttachment = vi.fn().mockResolvedValue(attachment);
  const deleteAiAttachment = vi.fn().mockResolvedValue(undefined);
  const sendAiMessage = vi.fn().mockResolvedValue({
    conversationId: "conversation-1",
    userMessage: {
      messageId: "user-new",
      role: "user",
      content: "",
      createdAt: "2026-07-22T10:00:01+08:00",
      metadata: {
        status: "succeeded",
        attachments: [
          {
            attachment_id: "attachment-1",
            original_name: "说明.txt",
            media_type: "text/plain",
            kind: "document",
            size_bytes: 12,
            status: "ready",
          },
        ],
      },
    },
    assistantMessage: {
      messageId: "assistant-new",
      role: "assistant",
      content: "已读取附件",
      createdAt: "2026-07-22T10:00:02+08:00",
      metadata: { status: "succeeded" },
    },
    memory: { usedHistoryMessages: 0 },
  });
  const adapter = {
    getAiState: vi.fn().mockResolvedValue({
      enabled: true,
      profile: "development_minimax",
      model: "MiniMax-M3",
      ownerKey: "ip:127.0.0.1",
      defaultAgent: "general_assistant",
      attachments: {
        enabled: true,
        allowedExtensions: [".png", ".txt", ".pdf"],
        maxFilesPerMessage: 5,
        maxImageSizeMb: 10,
        maxFileSizeMb: 50,
        maxTotalSizeMbPerMessage: 100,
      },
      agents: [
        {
          agentId: "general_assistant",
          name: "通用对话",
          description: "",
        },
      ],
      skills: [],
      mcpServers: [],
    }),
    listAiConversations: vi.fn().mockResolvedValue([
      {
        conversationId: "conversation-1",
        title: "附件测试",
        createdAt: "2026-07-22T10:00:00+08:00",
        updatedAt: "2026-07-22T10:00:00+08:00",
        messageCount: options?.historicalAttachment ? 1 : 0,
      },
    ]),
    getAiConversation: vi.fn().mockResolvedValue({
      conversationId: "conversation-1",
      title: "附件测试",
      createdAt: "2026-07-22T10:00:00+08:00",
      updatedAt: "2026-07-22T10:00:00+08:00",
      messageCount: options?.historicalAttachment ? 1 : 0,
      messages: options?.historicalAttachment
        ? [
            {
              messageId: "user-old",
              role: "user",
              content: "请读取",
              createdAt: "2026-07-22T10:00:00+08:00",
              metadata: {
                status: "succeeded",
                attachments: [
                  {
                    attachment_id: "old-attachment",
                    original_name: "历史图纸.dxf",
                    media_type: "application/dxf",
                    kind: "drawing",
                    size_bytes: 2048,
                    status: "ready",
                  },
                ],
              },
            },
          ]
        : [],
    }),
    createAiConversation: vi.fn(),
    renameAiConversation: vi.fn(),
    clearAiConversation: vi.fn(),
    deleteAiConversation: vi.fn(),
    uploadAiAttachment,
    listAiAttachments: vi.fn().mockResolvedValue([]),
    deleteAiAttachment,
    sendAiMessage,
  } as unknown as ApiAdapter;
  return { adapter, uploadAiAttachment, deleteAiAttachment, sendAiMessage };
}

function renderDrawer(adapter: ApiAdapter) {
  window.localStorage.setItem("fanban.ai.drawerOpen", "true");
  window.localStorage.setItem("fanban.ai.selectedConversationId", "conversation-1");
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AiChatDrawer adapter={adapter} />
    </QueryClientProvider>,
  );
}

function renderClosedDrawer(adapter: ApiAdapter) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AiChatDrawer adapter={adapter} />
    </QueryClientProvider>,
  );
}

describe("AiChatDrawer attachments", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("opens the existing AI drawer from the mascot instead of the vertical AI label", async () => {
    const user = userEvent.setup();
    const { adapter } = createAdapter();
    renderClosedDrawer(adapter);

    expect(screen.getByText("点我进入AI功能")).toBeInTheDocument();
    expect(screen.queryByText("AI", { selector: "button span" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "打开 AI 助手" }));

    expect(await screen.findByRole("dialog", { name: "AI 助手" })).toBeInTheDocument();
  });

  it("uploads, displays, removes, and sends a ready attachment", async () => {
    const user = userEvent.setup();
    const { adapter, uploadAiAttachment, deleteAiAttachment, sendAiMessage } = createAdapter();
    renderDrawer(adapter);

    const chooser = await screen.findByLabelText("选择 AI 对话附件");
    const file = new File(["AI-FILE-0711"], "说明.txt", { type: "text/plain" });
    await user.upload(chooser, file);

    await screen.findByText("说明.txt");
    expect(uploadAiAttachment).toHaveBeenCalledWith("conversation-1", file);
    expect(screen.getByRole("button", { name: "发送" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() =>
      expect(sendAiMessage).toHaveBeenCalledWith(
        "conversation-1",
        expect.objectContaining({ content: "", attachmentIds: ["attachment-1"] }),
        expect.any(AbortSignal),
      ),
    );

    await user.upload(chooser, file);
    await screen.findByRole("button", { name: "移除附件 说明.txt" });
    await user.click(screen.getByRole("button", { name: "移除附件 说明.txt" }));
    expect(deleteAiAttachment).toHaveBeenCalledWith("conversation-1", "attachment-1");
  });

  it("renders attachment labels on historical user messages", async () => {
    const { adapter } = createAdapter({ historicalAttachment: true });
    renderDrawer(adapter);

    expect(await screen.findByText("历史图纸.dxf")).toBeInTheDocument();
    expect(screen.getByText("2 KB")).toBeInTheDocument();
  });
});
