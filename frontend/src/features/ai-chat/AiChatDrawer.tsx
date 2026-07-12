import { useEffect, useMemo, useRef, useState } from "react";

import type { ApiAdapter } from "../../platform/api/types";
import styles from "./AiChatDrawer.module.css";
import { useAiChat } from "./useAiChat";

const DRAWER_OPEN_KEY = "fanban.ai.drawerOpen";

export function AiChatDrawer({ adapter }: { adapter: ApiAdapter }) {
  const [open, setOpen] = useState(() =>
    typeof window === "undefined"
      ? false
      : window.localStorage.getItem(DRAWER_OPEN_KEY) === "true",
  );
  const [draft, setDraft] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [renameDraft, setRenameDraft] = useState("");
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [lastMemoryCount, setLastMemoryCount] = useState<number | null>(null);
  const collapsedButtonRef = useRef<HTMLButtonElement | null>(null);
  const drawerRef = useRef<HTMLElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const messagesRef = useRef<HTMLElement | null>(null);
  const restoreFocusOnCloseRef = useRef(false);
  const chat = useAiChat(adapter, open);
  const selectedConversationIdRef = useRef(chat.selectedConversationId);

  const state = chat.stateQuery.data;
  const conversations = chat.conversationsQuery.data ?? [];
  const conversation = chat.conversationQuery.data;
  const activeConversation =
    conversation ??
    conversations.find((item) => item.conversationId === chat.selectedConversationId) ??
    null;
  const activeTitle = activeConversation?.title || "新会话";
  const activeMessageCount =
    conversation?.messages.length ?? activeConversation?.messageCount ?? 0;
  const enabledSkills = useMemo(
    () => (state?.skills ?? []).filter((skill) => skill.enabled && skill.readOnly),
    [state?.skills],
  );

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(DRAWER_OPEN_KEY, open ? "true" : "false");
    }
    if (open) {
      const focusTimer = window.setTimeout(() => {
        if (document.activeElement === document.body) {
          inputRef.current?.focus();
        }
      }, 120);
      return () => window.clearTimeout(focusTimer);
    }
  }, [open]);

  useEffect(() => {
    if (open || !restoreFocusOnCloseRef.current) {
      return;
    }
    const focusTimer = window.setTimeout(() => {
      collapsedButtonRef.current?.focus();
      restoreFocusOnCloseRef.current = false;
    });
    return () => window.clearTimeout(focusTimer);
  }, [open]);

  useEffect(() => {
    if (!open || typeof document === "undefined") {
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
  }, [open]);

  useEffect(() => {
    selectedConversationIdRef.current = chat.selectedConversationId;
    setRenaming(false);
    setRenameDraft("");
    setLastMemoryCount(null);
  }, [chat.selectedConversationId]);

  useEffect(() => {
    if (!open || !messagesRef.current) {
      return;
    }
    messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [conversation?.messages.length, open]);

  useEffect(() => {
    if (!state) {
      return;
    }
    setSelectedAgentId((current) => current || state.defaultAgent || state.agents[0]?.agentId || "");
    setSelectedSkillIds((current) =>
      current.length > 0 ? current : enabledSkills.map((skill) => skill.skillId),
    );
  }, [enabledSkills, state]);

  useEffect(() => {
    if (!open) {
      return;
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented) {
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        handleClose();
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) {
        return;
      }
      const focusable = Array.from(
        drawerRef.current.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [href], [tabindex]:not([tabindex='-1'])",
        ),
      ).filter((element) => !element.hasAttribute("hidden"));
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const active = document.activeElement;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && (active === first || !drawerRef.current.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !drawerRef.current.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  function handleClose() {
    restoreFocusOnCloseRef.current = true;
    setOpen(false);
  }

  async function handleNewConversation() {
    try {
      const title = draft.trim() ? draft.trim().slice(0, 24) : "新会话";
      await chat.createConversationMutation.mutateAsync(title);
      setRenaming(false);
      setLastMemoryCount(null);
    } catch {
      return;
    }
  }

  async function handleClearConversation() {
    if (!chat.selectedConversationId) {
      return;
    }
    try {
      await chat.clearConversationMutation.mutateAsync(chat.selectedConversationId);
      setLastMemoryCount(null);
    } catch {
      return;
    }
  }

  async function handleRenameConversation() {
    if (!chat.selectedConversationId) {
      return;
    }
    const title = renameDraft.trim();
    if (!title) {
      return;
    }
    try {
      await chat.renameConversationMutation.mutateAsync({
        conversationId: chat.selectedConversationId,
        title,
      });
      setRenaming(false);
    } catch {
      return;
    }
  }

  async function handleSubmit() {
    const content = draft.trim();
    if (!content || chat.sendMessageMutation.isPending) {
      return;
    }
    try {
      let conversationId = chat.selectedConversationId;
      if (!conversationId) {
        const created = await chat.createConversationMutation.mutateAsync(content.slice(0, 24));
        conversationId = created.conversationId;
        selectedConversationIdRef.current = conversationId;
      }
      const result = await chat.sendMessageMutation.mutateAsync({
        conversationId,
        payload: {
          content,
          agentId: selectedAgentId || state?.defaultAgent || null,
          skillIds: selectedSkillIds,
          mcpServerIds: [],
        },
      });
      setDraft("");
      if (selectedConversationIdRef.current === conversationId) {
        setLastMemoryCount(result.memory.usedHistoryMessages);
      }
    } catch {
      return;
    }
  }

  function toggleSkill(skillId: string) {
    setSelectedSkillIds((current) =>
      current.includes(skillId)
        ? current.filter((item) => item !== skillId)
        : [...current, skillId],
    );
  }

  if (!open) {
    return (
      <button
        aria-label="打开 AI 助手"
        className={styles.collapsedTab}
        ref={collapsedButtonRef}
        type="button"
        onClick={() => {
          restoreFocusOnCloseRef.current = false;
          setOpen(true);
        }}
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
    chat.clearConversationMutation.isPending;
  const error = [
    chat.stateQuery.error,
    chat.conversationsQuery.error,
    chat.conversationQuery.error,
    chat.sendMessageMutation.error,
    chat.createConversationMutation.error,
    chat.renameConversationMutation.error,
    chat.clearConversationMutation.error,
  ].find(Boolean);

  return (
    <aside
      aria-label="AI 助手"
      aria-modal="true"
      className={styles.drawer}
      data-ai-chat-drawer="true"
      ref={drawerRef}
      role="dialog"
    >
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
          <details className={styles.controls}>
            <summary className={styles.controlsSummary}>
              <span>能力设置</span>
              <strong>{state?.agents.find((agent) => agent.agentId === selectedAgentId)?.name}</strong>
            </summary>
            <div className={styles.controlsBody} aria-label="AI 能力选择">
              <label className={styles.fieldLabel}>
                智能体
                <select
                  className={styles.select}
                  value={selectedAgentId}
                  onChange={(event) => setSelectedAgentId(event.target.value)}
                >
                  {(state?.agents ?? []).map((agent) => (
                    <option key={agent.agentId} value={agent.agentId}>
                      {agent.name}
                    </option>
                  ))}
                </select>
              </label>

              <div className={styles.chipGroup} aria-label="技能">
                {enabledSkills.map((skill) => {
                  const active = selectedSkillIds.includes(skill.skillId);
                  return (
                    <button
                      aria-pressed={active}
                      className={`${styles.chip} ${active ? styles.chipActive : ""}`}
                      key={skill.skillId}
                      type="button"
                      onClick={() => toggleSkill(skill.skillId)}
                    >
                      {skill.name}
                    </button>
                  );
                })}
              </div>

              <div className={styles.mcpRow} aria-label="MCP 能力">
                {(state?.mcpServers ?? []).map((server) => (
                  <span
                    className={`${styles.mcpChip} ${server.enabled ? styles.mcpEnabled : ""}`}
                    key={server.serverId}
                    title={server.description}
                  >
                    {server.name}
                  </span>
                ))}
              </div>
            </div>
          </details>

          <section className={styles.conversationBar} aria-label="AI 会话">
            <div className={styles.currentConversation}>
              {renaming ? (
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
                      setRenaming(false);
                      setRenameDraft("");
                    }}
                  >
                    取消
                  </button>
                </form>
              ) : (
                <>
                  <div className={styles.currentConversationText}>
                    <span>当前会话</span>
                    <strong title={activeTitle}>{activeTitle}</strong>
                    <small>{activeMessageCount} 条消息</small>
                  </div>
                  <button
                    aria-label="重命名会话"
                    className={styles.ghostButton}
                    disabled={!chat.selectedConversationId}
                    type="button"
                    onClick={() => {
                      setRenameDraft(activeTitle);
                      setRenaming(true);
                    }}
                  >
                    重命名
                  </button>
                </>
              )}
            </div>
            <div className={styles.conversationList}>
              {conversations.map((item) => (
                <button
                  aria-pressed={chat.selectedConversationId === item.conversationId}
                  className={`${styles.conversationButton} ${
                    chat.selectedConversationId === item.conversationId
                      ? styles.conversationButtonActive
                      : ""
                  }`}
                  key={item.conversationId}
                  type="button"
                  onClick={() => {
                    selectedConversationIdRef.current = item.conversationId;
                    setLastMemoryCount(null);
                    chat.setSelectedConversationId(item.conversationId);
                  }}
                >
                  {item.title}
                </button>
              ))}
            </div>
            <div className={styles.conversationActions}>
              <button
                className={styles.ghostButton}
                disabled={busy}
                type="button"
                onClick={() => void handleNewConversation()}
              >
                新建
              </button>
              <button
                className={styles.ghostButton}
                disabled={!chat.selectedConversationId || busy}
                type="button"
                onClick={handleClearConversation}
              >
                清空
              </button>
            </div>
          </section>

          <section className={styles.messages} aria-label="AI 对话记录" ref={messagesRef}>
            <div className={styles.messagesHeader}>
              <span>对话记录</span>
              {lastMemoryCount !== null ? <strong>记忆 {lastMemoryCount}</strong> : null}
            </div>
            {chat.conversationQuery.isLoading ? (
              <div className={styles.emptyState}>正在读取对话。</div>
            ) : conversation?.messages.length ? (
              conversation.messages.map((message) => {
                const status = message.metadata?.status;
                const failed = status === "failed";
                const pending = status === "pending";
                return (
                  <article
                    className={`${styles.message} ${
                      message.role === "user" ? styles.userMessage : styles.assistantMessage
                    } ${failed ? styles.failedMessage : ""} ${
                      pending ? styles.pendingMessage : ""
                    }`}
                    key={message.messageId}
                  >
                    <span className={styles.messageRole}>
                      {message.role === "user" ? "我" : "AI"}
                      {failed ? <em className={styles.failedLabel}>发送失败</em> : null}
                      {pending ? <em className={styles.pendingLabel}>未完成</em> : null}
                    </span>
                    <p>{message.content}</p>
                  </article>
                );
              })
            ) : (
              <div className={styles.emptyState}>暂无对话。</div>
            )}
          </section>

          <footer className={styles.composer}>
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
            <div className={styles.composerActions}>
              <button
                className={styles.ghostButton}
                disabled={!draft.trim() || busy}
                type="button"
                onClick={() => setDraft("")}
              >
                取消
              </button>
              <button
                className={styles.sendButton}
                disabled={!draft.trim() || busy || !state?.enabled}
                type="button"
                onClick={() => void handleSubmit()}
              >
                {chat.sendMessageMutation.isPending ? "发送中" : "发送"}
              </button>
            </div>
          </footer>
        </>
      )}
    </aside>
  );
}

function formatError(error: unknown) {
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
