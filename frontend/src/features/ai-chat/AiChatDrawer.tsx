import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { createPortal } from "react-dom";

import type { AiAttachment, ApiAdapter } from "../../platform/api/types";
import styles from "./AiChatDrawer.module.css";
import { AiMessageContent } from "./AiMessageContent";
import { isAiConversationNotFoundError, useAiChat } from "./useAiChat";

const DRAWER_OPEN_KEY = "fanban.ai.drawerOpen";
const DRAWER_SIZE_KEY = "fanban.ai.drawerSize";
const DRAWER_SIZE_VERSION_KEY = "fanban.ai.drawerSizeVersion";
const DRAWER_SIZE_VERSION = "3";
const DRAWER_TRANSITION_MS = 200;
const MIN_DRAWER_WIDTH = 380;
const MIN_DRAWER_HEIGHT = 460;
const DEFAULT_DRAWER_WIDTH = 720;
const DEFAULT_DRAWER_HEIGHT = 820;

type DrawerSize = {
  width: number;
  height: number;
};

type ConversationMenu = {
  conversationId: string;
  left: number;
  top: number;
};

type PendingAttachment = {
  attachment: AiAttachment;
  previewUrl?: string;
};

export function AiChatDrawer({ adapter }: { adapter: ApiAdapter }) {
  const [isDrawerVisible, setDrawerVisible] = useState(() =>
    typeof window === "undefined"
      ? false
      : window.localStorage.getItem(DRAWER_OPEN_KEY) === "true",
  );
  const [isDrawerOpen, setDrawerOpen] = useState(() =>
    typeof window === "undefined"
      ? false
      : window.localStorage.getItem(DRAWER_OPEN_KEY) === "true",
  );
  const [draft, setDraft] = useState("");
  const [renamingConversationId, setRenamingConversationId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [conversationMenu, setConversationMenu] = useState<ConversationMenu | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [lastMemoryCount, setLastMemoryCount] = useState<number | null>(null);
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const [attachmentError, setAttachmentError] = useState("");
  const [drawerSize, setDrawerSize] = useState<DrawerSize>(loadDrawerSize);
  const collapsedButtonRef = useRef<HTMLButtonElement | null>(null);
  const drawerRef = useRef<HTMLElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const messagesRef = useRef<HTMLElement | null>(null);
  const conversationMenuRef = useRef<HTMLDivElement | null>(null);
  const restoreFocusOnCloseRef = useRef(false);
  const drawerTransitionTimerRef = useRef<number | null>(null);
  const chat = useAiChat(adapter, isDrawerVisible);
  const selectedConversationIdRef = useRef(chat.selectedConversationId);
  const pendingConversationIdRef = useRef("");
  const pendingAttachmentsRef = useRef<PendingAttachment[]>([]);

  const state = chat.stateQuery.data;
  const conversations = chat.availableConversations;
  const conversation = chat.conversationQuery.data;
  const activeMessageCount =
    conversation?.messages.length ??
    conversations.find((item) => item.conversationId === chat.selectedConversationId)?.messageCount ??
    0;
  const displayedMessages = useMemo(() => {
    const messages = [...(conversation?.messages ?? [])];
    const optimistic = chat.optimisticExchange;
    if (!optimistic || optimistic.conversationId !== chat.selectedConversationId) {
      return messages;
    }
    messages.push({
      ...optimistic.userMessage,
      metadata: { ...optimistic.userMessage.metadata, status: optimistic.status },
    });
    if (optimistic.status === "thinking") {
      messages.push({
        messageId: `local-assistant-${optimistic.requestId}`,
        role: "assistant",
        content: "AI 正在思考",
        createdAt: optimistic.userMessage.createdAt,
        metadata: { status: "thinking", local: true },
      });
    }
    return messages;
  }, [chat.optimisticExchange, chat.selectedConversationId, conversation?.messages]);
  const selectableAgents = useMemo(
    () =>
      (state?.agents ?? []).filter((agent) =>
        ["general_assistant", "business_agent"].includes(agent.agentId),
      ),
    [state?.agents],
  );

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(DRAWER_OPEN_KEY, isDrawerOpen ? "true" : "false");
    }
    if (isDrawerOpen) {
      const focusTimer = window.setTimeout(() => {
        if (document.activeElement === document.body) {
          inputRef.current?.focus();
        }
      }, 120);
      return () => window.clearTimeout(focusTimer);
    }
  }, [isDrawerOpen]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(DRAWER_SIZE_KEY, JSON.stringify(drawerSize));
      window.localStorage.setItem(DRAWER_SIZE_VERSION_KEY, DRAWER_SIZE_VERSION);
    }
  }, [drawerSize]);

  useEffect(
    () => () => {
      if (drawerTransitionTimerRef.current !== null) {
        window.clearTimeout(drawerTransitionTimerRef.current);
      }
      revokePreviewUrls(pendingAttachmentsRef.current);
    },
    [],
  );

  useEffect(() => {
    pendingAttachmentsRef.current = pendingAttachments;
  }, [pendingAttachments]);

  useEffect(() => {
    function keepDrawerInViewport() {
      setDrawerSize((current) => clampDrawerSize(current));
    }
    window.addEventListener("resize", keepDrawerInViewport);
    return () => window.removeEventListener("resize", keepDrawerInViewport);
  }, []);

  useEffect(() => {
    if (isDrawerVisible || !restoreFocusOnCloseRef.current) {
      return;
    }
    const focusTimer = window.setTimeout(() => {
      collapsedButtonRef.current?.focus();
      restoreFocusOnCloseRef.current = false;
    });
    return () => window.clearTimeout(focusTimer);
  }, [isDrawerVisible]);

  useEffect(() => {
    if (!isDrawerVisible || typeof document === "undefined") {
      return;
    }
    const previousBodyOverflow = document.body.style.overflow;
    const previousScrollbarGutter = document.documentElement.style.scrollbarGutter;
    document.body.style.overflow = "hidden";
    document.documentElement.style.scrollbarGutter = "stable";
    return () => {
      document.body.style.overflow = previousBodyOverflow;
      document.documentElement.style.scrollbarGutter = previousScrollbarGutter;
    };
  }, [isDrawerVisible]);

  useEffect(() => {
    selectedConversationIdRef.current = chat.selectedConversationId;
    if (
      pendingConversationIdRef.current &&
      pendingConversationIdRef.current !== chat.selectedConversationId
    ) {
      revokePreviewUrls(pendingAttachmentsRef.current);
      pendingAttachmentsRef.current = [];
      pendingConversationIdRef.current = "";
      setPendingAttachments([]);
      setAttachmentError("");
    }
    setRenamingConversationId(null);
    setRenameDraft("");
    setConversationMenu(null);
    setLastMemoryCount(null);
  }, [chat.selectedConversationId]);

  useEffect(() => {
    if (!conversationMenu) {
      return;
    }
    const closeOnOutsidePress = (event: MouseEvent) => {
      if (!conversationMenuRef.current?.contains(event.target as Node)) {
        setConversationMenu(null);
      }
    };
    document.addEventListener("mousedown", closeOnOutsidePress);
    return () => document.removeEventListener("mousedown", closeOnOutsidePress);
  }, [conversationMenu]);

  useEffect(() => {
    if (!conversationMenu) {
      return;
    }
    const focusTimer = window.setTimeout(() => {
      conversationMenuRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    });
    return () => window.clearTimeout(focusTimer);
  }, [conversationMenu]);

  useEffect(() => {
    if (!isDrawerOpen || !messagesRef.current) {
      return;
    }
    messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [displayedMessages.length, isDrawerOpen]);

  useEffect(() => {
    if (!state) {
      return;
    }
    setSelectedAgentId((current) => {
      if (selectableAgents.some((agent) => agent.agentId === current)) {
        return current;
      }
      if (selectableAgents.some((agent) => agent.agentId === state.defaultAgent)) {
        return state.defaultAgent;
      }
      return selectableAgents[0]?.agentId || "";
    });
  }, [selectableAgents, state]);

  useEffect(() => {
    if (!isDrawerOpen) {
      return;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented) {
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        if (conversationMenu) {
          setConversationMenu(null);
          return;
        }
        handleClose();
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) {
        return;
      }
      const focusRoots = [drawerRef.current, conversationMenuRef.current].filter(
        (root): root is HTMLElement => Boolean(root),
      );
      const focusable = focusRoots.flatMap((root) =>
        Array.from(
          root.querySelectorAll<HTMLElement>(
            "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [href], [tabindex]:not([tabindex='-1'])",
          ),
        ).filter((element) => !element.hasAttribute("hidden")),
      );
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const active = document.activeElement;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeInsideFocusTrap = focusRoots.some((root) => root.contains(active));
      if (event.shiftKey && (active === first || !activeInsideFocusTrap)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !activeInsideFocusTrap)) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [conversationMenu, isDrawerOpen]);

  function handleClose() {
    if (!isDrawerVisible) {
      return;
    }
    restoreFocusOnCloseRef.current = true;
    setConversationMenu(null);
    setDrawerOpen(false);
    if (drawerTransitionTimerRef.current !== null) {
      window.clearTimeout(drawerTransitionTimerRef.current);
    }
    drawerTransitionTimerRef.current = window.setTimeout(() => {
      setDrawerVisible(false);
      drawerTransitionTimerRef.current = null;
    }, DRAWER_TRANSITION_MS);
  }

  function handleOpen() {
    restoreFocusOnCloseRef.current = false;
    if (drawerTransitionTimerRef.current !== null) {
      window.clearTimeout(drawerTransitionTimerRef.current);
      drawerTransitionTimerRef.current = null;
    }
    setDrawerVisible(true);
    setDrawerOpen(true);
  }

  async function handleNewConversation() {
    try {
      const title = draft.trim() ? draft.trim().slice(0, 24) : "新会话";
      await chat.createConversationMutation.mutateAsync(title);
      setRenamingConversationId(null);
      setLastMemoryCount(null);
    } catch {
      return;
    }
  }

  async function handleClearConversation(conversationId: string) {
    if (!conversationId) {
      return;
    }
    try {
      await chat.clearConversationMutation.mutateAsync(conversationId);
      if (conversationId === chat.selectedConversationId) {
        setLastMemoryCount(null);
      }
    } catch {
      return;
    }
  }

  async function handleRenameConversation() {
    if (!renamingConversationId) {
      return;
    }
    const title = renameDraft.trim();
    if (!title) {
      return;
    }
    try {
      await chat.renameConversationMutation.mutateAsync({
        conversationId: renamingConversationId,
        title,
      });
      setRenamingConversationId(null);
    } catch {
      return;
    }
  }

  async function handleAttachmentSelection(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    const capabilities = state?.attachments;
    if (!files.length || !capabilities?.enabled) {
      return;
    }
    setAttachmentError("");
    if (pendingAttachments.length + files.length > capabilities.maxFilesPerMessage) {
      setAttachmentError(`每条消息最多上传 ${capabilities.maxFilesPerMessage} 个附件。`);
      return;
    }
    const allowedExtensions = new Set(
      capabilities.allowedExtensions.map((extension) => extension.toLowerCase()),
    );
    const pendingBytes = pendingAttachments.reduce(
      (total, item) => total + item.attachment.sizeBytes,
      0,
    );
    const selectedBytes = files.reduce((total, file) => total + file.size, 0);
    if (
      pendingBytes + selectedBytes >
      capabilities.maxTotalSizeMbPerMessage * 1024 * 1024
    ) {
      setAttachmentError("本条消息的附件总容量超过限制。");
      return;
    }
    for (const file of files) {
      const extension = fileExtension(file.name);
      const isImage = [".png", ".jpg", ".jpeg", ".webp"].includes(extension);
      const fileLimitMb = isImage
        ? capabilities.maxImageSizeMb
        : capabilities.maxFileSizeMb;
      if (!allowedExtensions.has(extension)) {
        setAttachmentError(`不支持附件类型：${file.name}`);
        return;
      }
      if (file.size > fileLimitMb * 1024 * 1024) {
        setAttachmentError(`${file.name} 超过 ${fileLimitMb} MB 限制。`);
        return;
      }
    }

    let conversationId = selectedConversationIdRef.current;
    if (!conversationId) {
      try {
        const created = await chat.createConversationMutation.mutateAsync(
          files[0]?.name.slice(0, 24) || "附件会话",
        );
        conversationId = created.conversationId;
        selectedConversationIdRef.current = conversationId;
      } catch (error) {
        setAttachmentError(formatError(error));
        return;
      }
    }
    pendingConversationIdRef.current = conversationId;

    for (const file of files) {
      try {
        const uploaded = await chat.uploadAttachmentMutation.mutateAsync({
          conversationId,
          file,
        });
        const previewUrl =
          uploaded.kind === "image" && typeof URL.createObjectURL === "function"
            ? URL.createObjectURL(file)
            : undefined;
        setPendingAttachments((current) => [...current, { attachment: uploaded, previewUrl }]);
      } catch (error) {
        setAttachmentError(formatError(error));
        return;
      }
    }
  }

  async function handleRemoveAttachment(item: PendingAttachment) {
    const conversationId = pendingConversationIdRef.current;
    if (!conversationId) {
      return;
    }
    try {
      await chat.deleteAttachmentMutation.mutateAsync({
        conversationId,
        attachmentId: item.attachment.attachmentId,
      });
      revokePreviewUrls([item]);
      setPendingAttachments((current) =>
        current.filter(
          (candidate) =>
            candidate.attachment.attachmentId !== item.attachment.attachmentId,
        ),
      );
    } catch (error) {
      setAttachmentError(formatError(error));
    }
  }

  function clearPendingAttachments() {
    revokePreviewUrls(pendingAttachmentsRef.current);
    pendingAttachmentsRef.current = [];
    pendingConversationIdRef.current = "";
    setPendingAttachments([]);
  }

  async function handleSubmit() {
    const content = draft.trim();
    if (
      (!content && pendingAttachments.length === 0) ||
      chat.sendMessageMutation.isPending ||
      chat.uploadAttachmentMutation.isPending
    ) {
      return;
    }
    try {
      let conversationId = chat.selectedConversationId;
      if (!conversationId) {
        const created = await chat.createConversationMutation.mutateAsync(content.slice(0, 24));
        conversationId = created.conversationId;
        selectedConversationIdRef.current = conversationId;
      }
      setDraft("");
      const result = await chat.sendMessage({
        conversationId,
        payload: {
          content,
          agentId: selectedAgentId || state?.defaultAgent || null,
          skillIds: [],
          mcpServerIds: [],
          ...(pendingAttachments.length
            ? {
                attachmentIds: pendingAttachments.map(
                  (item) => item.attachment.attachmentId,
                ),
              }
            : {}),
        },
      });
      clearPendingAttachments();
      if (selectedConversationIdRef.current === conversationId) {
        setLastMemoryCount(result.memory.usedHistoryMessages);
      }
    } catch {
      setDraft((current) => current || content);
      return;
    }
  }

  async function handleDeleteConversation(conversationId: string) {
    if (!conversationId) {
      return;
    }
    try {
      await chat.deleteConversationMutation.mutateAsync(conversationId);
      if (conversationId === chat.selectedConversationId) {
        setLastMemoryCount(null);
      }
    } catch {
      return;
    }
  }

  function openConversationMenu(conversationId: string, left: number, top: number) {
    const menuWidth = 180;
    const menuHeight = 132;
    setConversationMenu({
      conversationId,
      left: Math.max(8, Math.min(left, window.innerWidth - menuWidth - 8)),
      top: Math.max(8, Math.min(top, window.innerHeight - menuHeight - 8)),
    });
  }

  function handleConversationContextMenu(
    event: ReactMouseEvent<HTMLButtonElement>,
    conversationId: string,
  ) {
    event.preventDefault();
    openConversationMenu(conversationId, event.clientX, event.clientY);
  }

  function handleConversationKeyDown(
    event: ReactKeyboardEvent<HTMLButtonElement>,
    conversationId: string,
  ) {
    if (event.key !== "ContextMenu" && !(event.shiftKey && event.key === "F10")) {
      return;
    }
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    openConversationMenu(conversationId, rect.left, rect.bottom);
  }

  function handleResizePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    event.currentTarget.focus();
    const start = { x: event.clientX, y: event.clientY, size: drawerSize };
    const handlePointerMove = (moveEvent: PointerEvent) => {
      setDrawerSize(
        clampDrawerSize({
          width: start.size.width + start.x - moveEvent.clientX,
          height: start.size.height + start.y - moveEvent.clientY,
        }),
      );
    };
    const handlePointerUp = () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp, { once: true });
  }

  function handleResizeKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const step = event.shiftKey ? 48 : 24;
    const deltaByKey: Record<string, Partial<DrawerSize>> = {
      ArrowLeft: { width: step },
      ArrowRight: { width: -step },
      ArrowUp: { height: step },
      ArrowDown: { height: -step },
    };
    const delta = deltaByKey[event.key];
    if (!delta) {
      return;
    }
    event.preventDefault();
    setDrawerSize((current) =>
      clampDrawerSize({
        width: current.width + (delta.width ?? 0),
        height: current.height + (delta.height ?? 0),
      }),
    );
  }

  if (!isDrawerVisible) {
    return (
      <button
        aria-label="打开 AI 助手"
        className={styles.collapsedTab}
        ref={collapsedButtonRef}
        type="button"
        onClick={handleOpen}
      >
        <span>AI</span>
        <span aria-hidden="true">‹</span>
      </button>
    );
  }

  const busy =
    chat.sendMessageMutation.isPending ||
    chat.createConversationMutation.isPending ||
    chat.renameConversationMutation.isPending ||
    chat.clearConversationMutation.isPending ||
    chat.deleteConversationMutation.isPending ||
    chat.deleteAttachmentMutation.isPending;
  const attachmentUploading = chat.uploadAttachmentMutation.isPending;
  const canSend = Boolean(draft.trim() || pendingAttachments.length);
  const attachmentAccept = state?.attachments?.allowedExtensions.join(",") || undefined;
  const error = [
    attachmentError,
    chat.stateQuery.error,
    chat.conversationsQuery.error,
    chat.conversationQuery.error,
    chat.isSendCancelled ? null : chat.sendMessageMutation.error,
    chat.createConversationMutation.error,
    chat.renameConversationMutation.error,
    chat.clearConversationMutation.error,
    chat.deleteConversationMutation.error,
    chat.uploadAttachmentMutation.error,
    chat.deleteAttachmentMutation.error,
  ].find((candidate) => Boolean(candidate) && !isAiConversationNotFoundError(candidate));

  return (
    <aside
      aria-label="AI 助手"
      aria-modal="true"
      className={`${styles.drawer} ${isDrawerOpen ? styles.drawerOpen : styles.drawerClosing}`}
      data-ai-chat-drawer="true"
      data-animation-state={isDrawerOpen ? "open" : "closing"}
      ref={drawerRef}
      role="dialog"
      style={
        {
          "--ai-drawer-width": `${drawerSize.width}px`,
          "--ai-drawer-height": `${drawerSize.height}px`,
        } as CSSProperties
      }
    >
      <div
        aria-label="调整 AI 助手窗口大小"
        aria-valuemax={Math.max(MIN_DRAWER_WIDTH, window.innerWidth)}
        aria-valuemin={MIN_DRAWER_WIDTH}
        aria-valuenow={drawerSize.width}
        className={styles.resizeHandle}
        role="separator"
        tabIndex={0}
        onKeyDown={handleResizeKeyDown}
        onPointerDown={handleResizePointerDown}
      >
        <span aria-hidden="true" />
      </div>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>AI Assistant</p>
          <h2>AI 助手</h2>
        </div>
        <div className={styles.headerActions}>
          <span className={styles.modelBadge}>{state?.model || "读取中"}</span>
          <button
            aria-label="关闭 AI 助手"
            className={styles.iconButton}
            type="button"
            onClick={handleClose}
          >
            <span aria-hidden="true">›</span>
          </button>
        </div>
      </header>

      <div className={styles.metaRow}>
        <span>{state?.profile || "AI profile"}</span>
        {lastMemoryCount !== null ? <strong>已使用 {lastMemoryCount} 条历史消息</strong> : null}
      </div>

      {error ? (
        <div className={styles.errorBanner} role="alert">
          {formatError(error)}
        </div>
      ) : null}

      {state && !state.enabled ? (
        <div className={styles.emptyState}>AI 对话未启用。</div>
      ) : (
        <>
          <label className={styles.modeBar}>
            <span>对话模式</span>
            <select
              aria-label="对话模式"
              className={styles.select}
              value={selectedAgentId}
              onChange={(event) => setSelectedAgentId(event.target.value)}
            >
              {selectableAgents.map((agent) => (
                <option key={agent.agentId} value={agent.agentId}>
                  {agent.name}
                </option>
              ))}
            </select>
          </label>

          <section className={styles.conversationBar} aria-label="AI 会话">
            <span className={styles.conversationLabel}>会话</span>
            <div className={styles.conversationList}>
              {conversations.map((item) => {
                const selected = chat.selectedConversationId === item.conversationId;
                const messageCount = selected ? activeMessageCount : item.messageCount;
                return (
                  <div className={styles.conversationItem} key={item.conversationId}>
                    <button
                      aria-label={item.title}
                      aria-pressed={selected}
                      className={`${styles.conversationButton} ${
                        selected ? styles.conversationButtonActive : ""
                      }`}
                      type="button"
                      onClick={() => {
                        selectedConversationIdRef.current = item.conversationId;
                        setLastMemoryCount(null);
                        chat.setSelectedConversationId(item.conversationId);
                      }}
                      onContextMenu={(event) => handleConversationContextMenu(event, item.conversationId)}
                      onKeyDown={(event) => handleConversationKeyDown(event, item.conversationId)}
                    >
                      <span>{item.title}</span>
                      <small aria-hidden="true">{messageCount} 条消息</small>
                    </button>
                  </div>
                );
              })}
            </div>
            <button
              aria-label="新建会话"
              className={styles.newConversationButton}
              disabled={busy}
              type="button"
              onClick={() => void handleNewConversation()}
            >
              <span aria-hidden="true">+</span>
            </button>
            {renamingConversationId ? (
              <form
                className={styles.renameForm}
                onSubmit={(event) => {
                  event.preventDefault();
                  void handleRenameConversation();
                }}
              >
                <input
                  aria-label="会话标题"
                  className={styles.titleInput}
                  maxLength={80}
                  value={renameDraft}
                  onChange={(event) => setRenameDraft(event.target.value)}
                />
                <button
                  aria-label="保存会话标题"
                  className={styles.ghostButton}
                  disabled={!renameDraft.trim() || chat.renameConversationMutation.isPending}
                  type="submit"
                >
                  保存
                </button>
                <button
                  aria-label="取消重命名"
                  className={styles.ghostButton}
                  type="button"
                  onClick={() => {
                    setRenamingConversationId(null);
                    setRenameDraft("");
                  }}
                >
                  取消
                </button>
              </form>
            ) : null}
          </section>

          {conversationMenu && typeof document !== "undefined"
            ? createPortal(
                <div
                  aria-label="会话操作"
                  className={styles.conversationMenu}
                  ref={conversationMenuRef}
                  role="menu"
                  style={{ left: `${conversationMenu.left}px`, top: `${conversationMenu.top}px` }}
                >
                  <button
                    role="menuitem"
                    type="button"
                    onClick={() => {
                      const target = conversations.find(
                        (item) => item.conversationId === conversationMenu.conversationId,
                      );
                      setRenameDraft(target?.title || "新会话");
                      setRenamingConversationId(conversationMenu.conversationId);
                      setConversationMenu(null);
                    }}
                  >
                    重命名会话
                  </button>
                  <button
                    disabled={busy}
                    role="menuitem"
                    type="button"
                    onClick={() => {
                      const conversationId = conversationMenu.conversationId;
                      setConversationMenu(null);
                      void handleClearConversation(conversationId);
                    }}
                  >
                    清空消息
                  </button>
                  <button
                    className={styles.dangerMenuItem}
                    disabled={busy}
                    role="menuitem"
                    type="button"
                    onClick={() => {
                      const conversationId = conversationMenu.conversationId;
                      setConversationMenu(null);
                      void handleDeleteConversation(conversationId);
                    }}
                  >
                    删除会话
                  </button>
                </div>,
                document.body,
              )
            : null}

          <section className={styles.messages} aria-label="AI 对话记录" ref={messagesRef}>
            <div className={styles.messagesHeader}>
              <span>对话记录</span>
              {lastMemoryCount !== null ? <strong>记忆 {lastMemoryCount}</strong> : null}
            </div>
            {chat.conversationQuery.isLoading ? (
              <div className={styles.emptyState}>正在读取对话。</div>
            ) : displayedMessages.length ? (
              displayedMessages.map((message) => {
                const status = typeof message.metadata?.status === "string" ? message.metadata.status : "";
                const messageAttachments = extractMessageAttachments(message.metadata);
                const failed = status === "failed";
                const pending = status === "pending";
                const thinking = status === "thinking";
                const cancelled = status === "cancelled";
                const renderAssistantMarkdown =
                  message.role === "assistant" &&
                  !failed &&
                  !pending &&
                  !thinking &&
                  !cancelled;
                return (
                  <article
                    className={`${styles.message} ${
                      message.role === "user" ? styles.userMessage : styles.assistantMessage
                    } ${failed ? styles.failedMessage : ""} ${
                      pending ? styles.pendingMessage : ""
                    } ${thinking ? styles.thinkingMessage : ""} ${
                      cancelled ? styles.cancelledMessage : ""
                    }`}
                    key={message.messageId}
                  >
                    <span className={styles.messageRole}>
                      {message.role === "user" ? "我" : "AI"}
                      {failed ? <em className={styles.failedLabel}>发送失败</em> : null}
                      {pending ? <em className={styles.pendingLabel}>未完成</em> : null}
                      {thinking ? <em className={styles.thinkingLabel}>思考中</em> : null}
                      {cancelled ? <em className={styles.cancelledLabel}>已停止等待</em> : null}
                    </span>
                    {renderAssistantMarkdown && message.content ? (
                      <div className={styles.assistantContent}>
                        <AiMessageContent content={message.content} />
                      </div>
                    ) : message.content ? (
                      <p>{message.content}</p>
                    ) : null}
                    {messageAttachments.length ? (
                      <div
                        aria-label="消息附件"
                        className={styles.messageAttachments}
                      >
                        {messageAttachments.map((attachment) => (
                          <span
                            className={styles.messageAttachment}
                            key={attachment.attachmentId}
                            title={attachment.mediaType}
                          >
                            <strong>{attachment.originalName}</strong>
                            <small>{formatFileSize(attachment.sizeBytes)}</small>
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </article>
                );
              })
            ) : (
              <div className={styles.emptyState}>暂无对话。</div>
            )}
          </section>

          <footer className={styles.composer}>
            {pendingAttachments.length || attachmentUploading ? (
              <div aria-label="待发送附件" className={styles.pendingAttachments}>
                {pendingAttachments.map((item) => (
                  <div className={styles.pendingAttachment} key={item.attachment.attachmentId}>
                    {item.previewUrl ? (
                      <img alt="" src={item.previewUrl} />
                    ) : (
                      <span aria-hidden="true" className={styles.fileGlyph}>
                        {item.attachment.kind === "drawing" ? "DWG" : "FILE"}
                      </span>
                    )}
                    <span className={styles.pendingAttachmentName}>
                      <strong>{item.attachment.originalName}</strong>
                      <small>{formatFileSize(item.attachment.sizeBytes)} · 已就绪</small>
                    </span>
                    <button
                      aria-label={`移除附件 ${item.attachment.originalName}`}
                      className={styles.removeAttachmentButton}
                      disabled={busy || attachmentUploading}
                      title="移除附件"
                      type="button"
                      onClick={() => void handleRemoveAttachment(item)}
                    >
                      <span aria-hidden="true">×</span>
                    </button>
                  </div>
                ))}
                {attachmentUploading ? (
                  <span className={styles.uploadingStatus} role="status">
                    正在上传并解析附件
                  </span>
                ) : null}
              </div>
            ) : null}
            <div className={styles.composerInputRow}>
              {state?.attachments?.enabled ? (
                <>
                  <input
                    accept={attachmentAccept}
                    aria-label="选择 AI 对话附件"
                    className={styles.hiddenFileInput}
                    disabled={busy || attachmentUploading}
                    multiple
                    ref={fileInputRef}
                    type="file"
                    onChange={(event) => void handleAttachmentSelection(event)}
                  />
                  <button
                    aria-label="添加附件"
                    className={styles.addAttachmentButton}
                    disabled={busy || attachmentUploading}
                    title="添加附件"
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <span aria-hidden="true">+</span>
                  </button>
                </>
              ) : null}
              <textarea
                aria-label="输入 AI 对话内容"
                className={styles.textarea}
                disabled={busy || !state?.enabled}
                ref={inputRef}
                rows={2}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void handleSubmit();
                  }
                }}
              />
            </div>
            <div className={styles.composerActions}>
              <button
                className={styles.ghostButton}
                disabled={!canSend || busy || attachmentUploading}
                type="button"
                onClick={() => {
                  setDraft("");
                  setAttachmentError("");
                }}
              >
                取消
              </button>
              {chat.sendMessageMutation.isPending ? (
                <button
                  className={styles.stopButton}
                  type="button"
                  onClick={chat.cancelSendMessage}
                >
                  停止等待
                </button>
              ) : (
                <button
                  className={styles.sendButton}
                  disabled={!canSend || busy || attachmentUploading || !state?.enabled}
                  type="button"
                  onClick={() => void handleSubmit()}
                >
                  发送
                </button>
              )}
            </div>
          </footer>
        </>
      )}
    </aside>
  );
}

function loadDrawerSize(): DrawerSize {
  if (typeof window === "undefined") {
    return { width: DEFAULT_DRAWER_WIDTH, height: DEFAULT_DRAWER_HEIGHT };
  }
  const defaultSize = { width: DEFAULT_DRAWER_WIDTH, height: window.innerHeight };
  try {
    if (window.localStorage.getItem(DRAWER_SIZE_VERSION_KEY) !== DRAWER_SIZE_VERSION) {
      return clampDrawerSize(defaultSize);
    }
    const stored = window.localStorage.getItem(DRAWER_SIZE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored) as Partial<DrawerSize>;
      if (typeof parsed.width === "number" && typeof parsed.height === "number") {
        return clampDrawerSize(parsed as DrawerSize);
      }
    }
  } catch {
    // Invalid local settings should not stop the drawer from opening.
  }
  return clampDrawerSize(defaultSize);
}

function clampDrawerSize(size: DrawerSize): DrawerSize {
  if (typeof window === "undefined") {
    return size;
  }
  return {
    width: Math.min(
      Math.max(size.width, MIN_DRAWER_WIDTH),
      Math.max(MIN_DRAWER_WIDTH, window.innerWidth),
    ),
    height: Math.min(
      Math.max(size.height, MIN_DRAWER_HEIGHT),
      Math.max(MIN_DRAWER_HEIGHT, window.innerHeight),
    ),
  };
}

type MessageAttachment = {
  attachmentId: string;
  originalName: string;
  mediaType: string;
  sizeBytes: number;
};

function extractMessageAttachments(
  metadata: Record<string, unknown> | undefined,
): MessageAttachment[] {
  const value = metadata?.attachments;
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item, index) => {
    if (!item || typeof item !== "object") {
      return [];
    }
    const record = item as Record<string, unknown>;
    const originalName = record.original_name ?? record.originalName;
    if (typeof originalName !== "string" || !originalName) {
      return [];
    }
    const attachmentId = record.attachment_id ?? record.attachmentId;
    const mediaType = record.media_type ?? record.mediaType;
    const sizeBytes = record.size_bytes ?? record.sizeBytes;
    return [
      {
        attachmentId:
          typeof attachmentId === "string" && attachmentId
            ? attachmentId
            : `${originalName}-${index}`,
        originalName,
        mediaType: typeof mediaType === "string" ? mediaType : "",
        sizeBytes: typeof sizeBytes === "number" ? sizeBytes : 0,
      },
    ];
  });
}

function formatFileSize(sizeBytes: number) {
  if (sizeBytes < 1024) {
    return `${sizeBytes} B`;
  }
  if (sizeBytes < 1024 * 1024) {
    return `${Math.round(sizeBytes / 1024)} KB`;
  }
  return `${(sizeBytes / 1024 / 1024).toFixed(1)} MB`;
}

function fileExtension(filename: string) {
  const index = filename.lastIndexOf(".");
  return index >= 0 ? filename.slice(index).toLowerCase() : "";
}

function revokePreviewUrls(items: PendingAttachment[]) {
  if (typeof URL.revokeObjectURL !== "function") {
    return;
  }
  for (const item of items) {
    if (item.previewUrl) {
      URL.revokeObjectURL(item.previewUrl);
    }
  }
}

function formatError(error: unknown) {
  if (typeof error === "string") {
    return error;
  }
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (detail && typeof detail === "object" && "message" in detail) {
      return String((detail as { message?: unknown }).message);
    }
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "AI 请求失败。";
}
