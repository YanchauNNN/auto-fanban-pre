import { useQuery } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";

import { useApiAdapter } from "../../platform/api/useApiAdapter";
import {
  getSettlementStatusLabel,
  getWorkloadEntryDisplayTitle,
  getWorkloadRoleLabel,
} from "../../shared/task-groups/taskGroupPresentation";
import { useSession } from "../../shared/session/SessionContext";
import styles from "./AccountPage.module.css";

function formatWorkload(value: number) {
  return value.toFixed(2);
}

function formatTimestamp(value: string | null) {
  if (!value) {
    return "未结算";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function AccountPage({ onOpenWorkload }: { onOpenWorkload: () => void }) {
  const adapter = useApiAdapter();
  const { currentAccount, refreshCurrentAccount } = useSession();
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<{
    tone: "error" | "success";
    message: string;
  } | null>(null);

  const workloadQuery = useQuery({
    queryKey: ["workload", "me", "account-summary", currentAccount?.accountId ?? null],
    queryFn: () => adapter.getWorkloadMe(),
    enabled: Boolean(currentAccount?.accountId),
  });

  const recentEntries = useMemo(() => {
    return [...(workloadQuery.data?.entries ?? [])]
      .sort((left, right) => {
        const leftTime = left.settledAt ? new Date(left.settledAt).getTime() : 0;
        const rightTime = right.settledAt ? new Date(right.settledAt).getTime() : 0;
        return rightTime - leftTime;
      })
      .slice(0, 8);
  }, [workloadQuery.data?.entries]);

  if (!currentAccount) {
    return null;
  }

  const passwordsMismatch = Boolean(confirmPassword && newPassword !== confirmPassword);
  const canSubmitPassword = Boolean(
    newPassword.trim() && confirmPassword.trim() && !passwordsMismatch && !submitting,
  );

  async function handlePasswordSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmitPassword) {
      return;
    }

    setSubmitting(true);
    setFeedback(null);
    try {
      await adapter.changePassword(newPassword);
      await refreshCurrentAccount();
      setNewPassword("");
      setConfirmPassword("");
      setFeedback({ tone: "success", message: "密码已更新，下次登录请使用新密码。" });
    } catch (error) {
      setFeedback({ tone: "error", message: "密码更新失败，请稍后重试。" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section aria-label="个人账号工作区" className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <p className={styles.eyebrow}>个人工作台</p>
          <h1>我的账号</h1>
          <p className={styles.description}>查看身份、安全设置和最近已结算工作量。</p>
        </div>
        <button
          aria-label={`查看 ${currentAccount.pendingTodoCount} 项待办`}
          className={styles.todoButton}
          onClick={onOpenWorkload}
          type="button"
        >
          <span>待我处理</span>
          <strong>{currentAccount.pendingTodoCount}</strong>
          <small>进入工作量模块</small>
        </button>
      </header>

      <div className={styles.workspace}>
        <section
          aria-labelledby="account-identity-heading"
          className={`${styles.section} ${styles.identitySection}`}
        >
          <div className={styles.sectionHeader}>
            <div>
              <span className={styles.sectionIndex}>01</span>
              <h2 id="account-identity-heading">身份摘要</h2>
            </div>
            <span className={styles.statusTag}>当前会话</span>
          </div>
          <div className={styles.identityPrimary}>
            <strong>{currentAccount.displayName}</strong>
            <span>{currentAccount.accountId}</span>
          </div>
          <dl className={styles.identityList}>
            <div>
              <dt>角色</dt>
              <dd>{currentAccount.role}</dd>
            </div>
            <div>
              <dt>责任单位</dt>
              <dd>{currentAccount.officeName ?? "未配置"}</dd>
            </div>
            <div>
              <dt>单位编码</dt>
              <dd>{currentAccount.officeCode ?? "未配置"}</dd>
            </div>
          </dl>
        </section>

        <section aria-labelledby="account-security-heading" className={styles.section}>
          <div className={styles.sectionHeader}>
            <div>
              <span className={styles.sectionIndex}>02</span>
              <h2 id="account-security-heading">安全操作</h2>
            </div>
            <button
              aria-label={passwordVisible ? "隐藏密码" : "显示密码"}
              className={styles.textButton}
              onClick={() => setPasswordVisible((visible) => !visible)}
              type="button"
            >
              {passwordVisible ? "隐藏" : "显示"}
            </button>
          </div>

          <form className={styles.passwordForm} onSubmit={handlePasswordSubmit}>
            <label className={styles.field} htmlFor="account-new-password">
              <span>新密码</span>
              <input
                autoComplete="new-password"
                id="account-new-password"
                name="new_password"
                onChange={(event) => {
                  setNewPassword(event.currentTarget.value);
                  setFeedback(null);
                }}
                type={passwordVisible ? "text" : "password"}
                value={newPassword}
              />
            </label>
            <label className={styles.field} htmlFor="account-confirm-password">
              <span>确认新密码</span>
              <input
                autoComplete="new-password"
                id="account-confirm-password"
                name="confirm_password"
                onChange={(event) => {
                  setConfirmPassword(event.currentTarget.value);
                  setFeedback(null);
                }}
                type={passwordVisible ? "text" : "password"}
                value={confirmPassword}
              />
            </label>
            <div className={styles.formMessage} aria-live="polite">
              {passwordsMismatch ? (
                <p className={styles.validationError}>两次输入的密码不一致。</p>
              ) : (
                <p>密码更新后立即生效。</p>
              )}
              {feedback ? (
                <p
                  className={feedback.tone === "success" ? styles.feedbackSuccess : styles.validationError}
                  role={feedback.tone === "error" ? "alert" : "status"}
                >
                  {feedback.message}
                </p>
              ) : null}
            </div>
            <button className={styles.primaryButton} disabled={!canSubmitPassword} type="submit">
              {submitting ? "更新中..." : "更新密码"}
            </button>
          </form>
        </section>

        <section
          aria-labelledby="account-settlement-heading"
          className={`${styles.section} ${styles.settlementSection}`}
        >
          <div className={styles.sectionHeader}>
            <div>
              <span className={styles.sectionIndex}>03</span>
              <h2 id="account-settlement-heading">最近结算</h2>
            </div>
            <div className={styles.totalWorkload}>
              <span>累计 A1</span>
              <strong>{formatWorkload(workloadQuery.data?.totalWorkloadA1 ?? 0)}</strong>
            </div>
          </div>

          {workloadQuery.isLoading ? (
            <p aria-label="正在加载最近结算" className={styles.stateMessage} role="status">
              正在读取最近结算记录...
            </p>
          ) : workloadQuery.isError ? (
            <p aria-label="最近结算加载失败" className={styles.errorState} role="alert">
              最近结算加载失败，请稍后刷新重试。
            </p>
          ) : recentEntries.length > 0 ? (
            <div
              aria-label="最近结算记录"
              className={styles.settlementList}
              role="list"
              tabIndex={0}
            >
              {recentEntries.map((entry) => (
                <article
                  className={styles.settlementRow}
                  key={`${entry.groupId}-${entry.roleKey}-${entry.settledAt ?? "pending"}`}
                  role="listitem"
                >
                  <div className={styles.settlementMain}>
                    <strong>{getWorkloadEntryDisplayTitle(entry)}</strong>
                    <span>{formatTimestamp(entry.settledAt)}</span>
                  </div>
                  <div className={styles.settlementMeta}>
                    <span>{getWorkloadRoleLabel(entry.roleKey)}</span>
                    <span>{getSettlementStatusLabel(entry.settlementStatus)}</span>
                    <strong>{formatWorkload(entry.workloadA1)} A1</strong>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <p className={styles.stateMessage}>当前还没有已结算记录。</p>
          )}
        </section>
      </div>
    </section>
  );
}
