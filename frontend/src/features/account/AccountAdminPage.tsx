import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import type { AccountRecord } from "../../platform/api/types";
import { useApiAdapter } from "../../platform/api/useApiAdapter";
import { useSession } from "../../shared/session/SessionContext";
import { TaskConfigModal } from "../deliverable/TaskConfigModal";
import styles from "./AccountAdminPage.module.css";

const ROLE_OPTIONS = ["设计人员", "室主任", "所领导", "管理员"] as const;

const EMPTY_ACCOUNT_FORM = {
  officeCode: "",
  officeName: "",
  accountId: "",
  displayName: "",
  role: "设计人员",
  password: "password",
};

type FeedbackState = {
  tone: "error" | "success";
  message: string;
} | null;

export function AccountAdminPage() {
  const adapter = useApiAdapter();
  const queryClient = useQueryClient();
  const { currentAccount, refreshCurrentAccount } = useSession();
  const [mode, setMode] = useState<"create" | "edit">("create");
  const [editingAccountId, setEditingAccountId] = useState<string | null>(null);
  const [accountForm, setAccountForm] = useState(EMPTY_ACCOUNT_FORM);
  const [isAccountListOpen, setIsAccountListOpen] = useState(false);
  const [archiveRootPath, setArchiveRootPath] = useState("");
  const [archiveRootPathDirty, setArchiveRootPathDirty] = useState(false);
  const [accountSubmitting, setAccountSubmitting] = useState(false);
  const [configSubmitting, setConfigSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<FeedbackState>(null);

  const accountsQuery = useQuery({
    queryKey: ["accounts"],
    queryFn: () => adapter.listAccounts(),
  });
  const invalidRowsQuery = useQuery({
    queryKey: ["invalid-account-rows"],
    queryFn: () => adapter.listInvalidAccountRows(),
  });
  const adminConfigQuery = useQuery({
    queryKey: ["admin-config"],
    queryFn: () => adapter.getAdminConfig(),
  });

  useEffect(() => {
    if (!archiveRootPathDirty) {
      setArchiveRootPath(adminConfigQuery.data?.archiveRootPath ?? "");
    }
  }, [adminConfigQuery.data?.archiveRootPath, archiveRootPathDirty]);

  if (!currentAccount) {
    return null;
  }

  const isBootstrapping =
    (accountsQuery.isLoading && !accountsQuery.data) ||
    (invalidRowsQuery.isLoading && !invalidRowsQuery.data) ||
    (adminConfigQuery.isLoading && !adminConfigQuery.data);

  if (isBootstrapping) {
    return (
      <main className={styles.page}>
        <p className={styles.muted}>正在加载管理员配置...</p>
      </main>
    );
  }

  function switchToCreateMode() {
    setMode("create");
    setEditingAccountId(null);
    setAccountForm(EMPTY_ACCOUNT_FORM);
  }

  function switchToEditMode(account: AccountRecord) {
    setMode("edit");
    setEditingAccountId(account.accountId);
    setAccountForm({
      officeCode: account.officeCode ?? "",
      officeName: account.officeName ?? "",
      accountId: account.accountId,
      displayName: account.displayName,
      role: account.role,
      password: account.password,
    });
  }

  function openAccountList() {
    setIsAccountListOpen(true);
  }

  function closeAccountList() {
    setIsAccountListOpen(false);
  }

  function startCreatingAccount() {
    switchToCreateMode();
    closeAccountList();
  }

  function startEditingAccount(account: AccountRecord) {
    switchToEditMode(account);
    closeAccountList();
  }

  async function refreshManagementQueries() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["accounts"] }),
      queryClient.invalidateQueries({ queryKey: ["invalid-account-rows"] }),
      queryClient.invalidateQueries({ queryKey: ["admin-config"] }),
      queryClient.invalidateQueries({ queryKey: ["task-groups"] }),
      queryClient.invalidateQueries({ queryKey: ["workflow", "monitor"] }),
      refreshCurrentAccount(),
    ]);
  }

  async function handleAccountSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = {
      officeCode: accountForm.officeCode.trim() || null,
      officeName: accountForm.officeName.trim() || null,
      accountId: accountForm.accountId.trim(),
      displayName: accountForm.displayName.trim(),
      role: accountForm.role,
      password: accountForm.password.trim(),
    };

    if (!trimmed.accountId || !trimmed.displayName || !trimmed.role || !trimmed.password) {
      setFeedback({ tone: "error", message: "请先完整填写账号、姓名、角色和密码。" });
      return;
    }

    setAccountSubmitting(true);
    setFeedback(null);
    try {
      if (mode === "edit" && editingAccountId) {
        await adapter.updateAccount(editingAccountId, trimmed);
        setFeedback({ tone: "success", message: "账号信息已更新。" });
      } else {
        await adapter.createAccount(trimmed);
        setFeedback({ tone: "success", message: "账号已创建。" });
        switchToCreateMode();
      }
      await refreshManagementQueries();
    } catch (error) {
      const detail = resolveErrorMessage(error);
      if (mode === "create" && detail === "account_id already exists") {
        const existing = accountsQuery.data?.items.find((item) => item.accountId === trimmed.accountId);
        if (existing) {
          switchToEditMode(existing);
          setFeedback({ tone: "error", message: "账号已存在，已切换到编辑模式。" });
          setAccountSubmitting(false);
          return;
        }
      }
      setFeedback({ tone: "error", message: detail || "账号操作失败，请稍后重试。" });
    } finally {
      setAccountSubmitting(false);
    }
  }

  async function handleAdminConfigSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setConfigSubmitting(true);
    setFeedback(null);
    try {
      await adapter.patchAdminConfig({
        archiveRootPath: archiveRootPath.trim() || null,
      });
      await queryClient.invalidateQueries({ queryKey: ["admin-config"] });
      setFeedback({ tone: "success", message: "归档配置已更新。" });
    } catch (error) {
      setFeedback({
        tone: "error",
        message: resolveErrorMessage(error) || "归档配置保存失败，请稍后重试。",
      });
    } finally {
      setConfigSubmitting(false);
    }
  }

  const accountItems = accountsQuery.data?.items ?? [];
  const accountCount = accountItems.length;

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Admin Center</p>
          <h1>管理员配置</h1>
          <p className={styles.description}>
            这里集中处理账号管理、无效账号行检查，以及当前已落地的归档根路径配置。
          </p>
        </div>
      </header>

      {feedback ? (
        <p
          className={feedback.tone === "success" ? styles.feedbackSuccess : styles.feedbackError}
          role="status"
        >
          {feedback.message}
        </p>
      ) : null}

      <section className={styles.grid}>
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.eyebrow}>Accounts</p>
              <h2>现有账号</h2>
            </div>
            <div className={styles.panelActions}>
              <button className={styles.secondaryButton} onClick={openAccountList} type="button">
                查看现有账号
              </button>
              <button className={styles.secondaryButton} onClick={startCreatingAccount} type="button">
                新建账号
              </button>
            </div>
          </div>

          {accountsQuery.isLoading ? (
            <p className={styles.muted}>正在加载账号列表...</p>
          ) : accountsQuery.isError ? (
            <p className={styles.feedbackError}>账号列表加载失败，请稍后刷新重试。</p>
          ) : (
            <article className={styles.accountSummaryCard}>
              <div>
                <strong className={styles.summaryValue}>{`${accountCount} 个账号`}</strong>
                <p className={styles.cardMeta}>现有账号移入次级窗口浏览，主页面只保留概览和管理入口。</p>
                <p className={styles.cardMeta}>打开后列表会在窗口内部滚动，尽量避免主页面被长列表撑高。</p>
              </div>
              <div className={styles.summaryActions}>
                <button className={styles.primaryButton} onClick={openAccountList} type="button">
                  打开账号列表
                </button>
              </div>
            </article>
          )}
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.eyebrow}>Editor</p>
              <h2>{mode === "edit" ? "编辑账号" : "创建账号"}</h2>
            </div>
            {mode === "edit" ? (
              <button className={styles.secondaryButton} onClick={switchToCreateMode} type="button">
                返回创建
              </button>
            ) : null}
          </div>

          <form className={styles.form} onSubmit={handleAccountSubmit}>
            <label className={styles.label} htmlFor="admin-account-id">
              账号
            </label>
            <input
              className={styles.input}
              id="admin-account-id"
              onChange={(event) => {
                const value = event.currentTarget.value;
                setAccountForm((current) => ({ ...current, accountId: value }));
              }}
              value={accountForm.accountId}
            />

            <label className={styles.label} htmlFor="admin-display-name">
              姓名
            </label>
            <input
              className={styles.input}
              id="admin-display-name"
              onChange={(event) => {
                const value = event.currentTarget.value;
                setAccountForm((current) => ({ ...current, displayName: value }));
              }}
              value={accountForm.displayName}
            />

            <label className={styles.label} htmlFor="admin-office-code">
              科室编码
            </label>
            <input
              className={styles.input}
              id="admin-office-code"
              onChange={(event) => {
                const value = event.currentTarget.value;
                setAccountForm((current) => ({ ...current, officeCode: value }));
              }}
              value={accountForm.officeCode}
            />

            <label className={styles.label} htmlFor="admin-office-name">
              科室
            </label>
            <input
              className={styles.input}
              id="admin-office-name"
              onChange={(event) => {
                const value = event.currentTarget.value;
                setAccountForm((current) => ({ ...current, officeName: value }));
              }}
              value={accountForm.officeName}
            />

            <label className={styles.label} htmlFor="admin-role">
              角色
            </label>
            <select
              className={styles.input}
              id="admin-role"
              onChange={(event) => {
                const value = event.currentTarget.value;
                setAccountForm((current) => ({ ...current, role: value }));
              }}
              value={accountForm.role}
            >
              {ROLE_OPTIONS.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>

            <label className={styles.label} htmlFor="admin-password">
              密码
            </label>
            <input
              className={styles.input}
              id="admin-password"
              onChange={(event) => {
                const value = event.currentTarget.value;
                setAccountForm((current) => ({ ...current, password: value }));
              }}
              value={accountForm.password}
            />
            <p className={styles.helpText}>管理员创建账号时，默认密码固定为 `password`。</p>

            <button className={styles.primaryButton} disabled={accountSubmitting} type="submit">
              {accountSubmitting ? "提交中..." : mode === "edit" ? "保存修改" : "创建账号"}
            </button>
          </form>
        </section>
      </section>

      <section className={styles.panel}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.eyebrow}>Invalid Rows</p>
            <h2>无效账号行</h2>
          </div>
        </div>

        {invalidRowsQuery.isLoading ? (
          <p className={styles.muted}>正在加载无效账号行...</p>
        ) : invalidRowsQuery.isError ? (
          <p className={styles.feedbackError}>无效账号行加载失败，请稍后刷新重试。</p>
        ) : (invalidRowsQuery.data?.items.length ?? 0) > 0 ? (
          <div className={styles.invalidList}>
            {(invalidRowsQuery.data?.items ?? []).map((row) => (
              <article className={styles.invalidCard} key={row.rowNumber}>
                <strong>{`第 ${row.rowNumber} 行`}</strong>
                <p className={styles.cardMeta}>{row.errors.join(" / ")}</p>
                <pre className={styles.rawBlock}>{JSON.stringify(row.raw, null, 2)}</pre>
              </article>
            ))}
          </div>
        ) : (
          <p className={styles.muted}>当前没有无效账号行。</p>
        )}
      </section>

      <section className={styles.panel}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.eyebrow}>Archive</p>
            <h2>归档配置</h2>
          </div>
        </div>

        <form className={styles.form} onSubmit={handleAdminConfigSubmit}>
          <label className={styles.label} htmlFor="admin-archive-root-path">
            归档根路径
          </label>
          <input
            className={styles.input}
            id="admin-archive-root-path"
            onChange={(event) => {
              setArchiveRootPathDirty(true);
              setArchiveRootPath(event.currentTarget.value);
            }}
            value={archiveRootPathDirty ? archiveRootPath : (adminConfigQuery.data?.archiveRootPath ?? "")}
          />
          <button className={styles.primaryButton} disabled={configSubmitting} type="submit">
            {configSubmitting ? "保存中..." : "保存归档配置"}
          </button>
        </form>
      </section>

      {isAccountListOpen ? (
        <TaskConfigModal
          dialogClassName={styles.accountListDialog}
          dialogDataAttributes={{ "data-admin-account-list-dialog": "true" }}
          title="现有账号列表"
        >
          <section className={styles.accountListModal}>
            <div className={styles.accountListModalHeader}>
              <div>
                <p className={styles.eyebrow}>Accounts</p>
                <h2>现有账号列表</h2>
                <p className={styles.description}>
                  账号内容只在这个次级窗口内部滚动显示，主页面保留紧凑概览，减少主页面滚动。
                </p>
              </div>
              <div className={styles.panelActions}>
                <button className={styles.secondaryButton} onClick={startCreatingAccount} type="button">
                  新建账号
                </button>
                <button className={styles.secondaryButton} onClick={closeAccountList} type="button">
                  关闭
                </button>
              </div>
            </div>

            {accountsQuery.isLoading ? (
              <p className={styles.muted}>正在加载账号列表...</p>
            ) : accountsQuery.isError ? (
              <p className={styles.feedbackError}>账号列表加载失败，请稍后重试。</p>
            ) : accountItems.length > 0 ? (
              <div className={styles.accountListViewport}>
                <div className={styles.accountList}>
                  {accountItems.map((item) => (
                    <article className={styles.accountCard} key={item.accountId}>
                      <div>
                        <strong>{`${item.displayName}（${item.accountId}）`}</strong>
                        <p className={styles.cardMeta}>{`${item.accountId} · ${item.role}`}</p>
                        <p className={styles.cardMeta}>{item.officeName ?? "未配置责任单位"}</p>
                      </div>
                      <button
                        aria-label={`编辑 ${item.accountId}`}
                        className={styles.secondaryButton}
                        onClick={() => startEditingAccount(item)}
                        type="button"
                      >
                        编辑
                      </button>
                    </article>
                  ))}
                </div>
              </div>
            ) : (
              <p className={styles.muted}>当前还没有已启用账号。</p>
            )}
          </section>
        </TaskConfigModal>
      ) : null}
    </main>
  );
}

function resolveErrorMessage(error: unknown) {
  if (
    typeof error === "object" &&
    error &&
    "detail" in error &&
    typeof (error as { detail?: unknown }).detail === "string"
  ) {
    return (error as { detail: string }).detail;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "";
}
