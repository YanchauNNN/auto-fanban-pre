import { useQuery } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";

import { useApiAdapter } from "../../platform/api/useApiAdapter";
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

export function AccountPage() {
  const adapter = useApiAdapter();
  const { currentAccount, refreshCurrentAccount } = useSession();
  const [newPassword, setNewPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<{
    tone: "error" | "success";
    message: string;
  } | null>(null);

  const workloadQuery = useQuery({
    queryKey: ["workload", "me", "account-summary"],
    queryFn: () => adapter.getWorkloadMe(),
  });

  const recentEntries = useMemo(() => {
    return [...(workloadQuery.data?.entries ?? [])]
      .sort((left, right) => {
        const leftTime = left.settledAt ? new Date(left.settledAt).getTime() : 0;
        const rightTime = right.settledAt ? new Date(right.settledAt).getTime() : 0;
        return rightTime - leftTime;
      })
      .slice(0, 5);
  }, [workloadQuery.data?.entries]);

  if (!currentAccount) {
    return null;
  }

  async function handlePasswordSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = newPassword.trim();
    if (!trimmed) {
      setFeedback({ tone: "error", message: "请输入新密码。" });
      return;
    }

    setSubmitting(true);
    setFeedback(null);
    try {
      await adapter.changePassword(trimmed);
      await refreshCurrentAccount();
      setNewPassword("");
      setFeedback({ tone: "success", message: "密码已更新，下次登录请使用新密码。" });
    } catch (error) {
      setFeedback({ tone: "error", message: "密码更新失败，请稍后重试。" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className={styles.page}>
      <div className={styles.surface}>
        <header className={styles.header}>
          <div>
            <p className={styles.eyebrow}>Account Center</p>
            <h1>账号模块</h1>
            <p className={styles.description}>
              当前登录账号、密码入口和个人已结算工作量集中在一个工作台内。
            </p>
          </div>
          <div className={styles.headerMetric}>
            <span>待办流程</span>
            <strong>{currentAccount.pendingTodoCount}</strong>
          </div>
        </header>

        <section className={styles.accountShell}>
          <aside className={styles.profilePanel}>
            <div>
              <span className={styles.profileLabel}>当前账号</span>
              <strong className={styles.profileName}>{currentAccount.displayName}</strong>
              <p className={styles.profileMeta}>{currentAccount.accountId}</p>
            </div>
            <div className={styles.identityGrid}>
              <InfoCard label="角色" value={currentAccount.role} />
              <InfoCard label="责任单位" value={currentAccount.officeName ?? "未配置"} />
              <InfoCard label="单位编码" value={currentAccount.officeCode ?? "未配置"} />
            </div>
          </aside>

          <section className={styles.panel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.eyebrow}>Security</p>
                <h2>修改密码</h2>
              </div>
              <span className={styles.panelHint}>只更新当前账号密码</span>
            </div>

            <form className={styles.form} onSubmit={handlePasswordSubmit}>
              <label className={styles.label} htmlFor="account-new-password">
                新密码
              </label>
              <input
                className={styles.input}
                id="account-new-password"
                name="new_password"
                onChange={(event) => setNewPassword(event.currentTarget.value)}
                type="password"
                value={newPassword}
              />
              <p className={styles.helpText}>提交后立即生效，后续登录请使用新密码。</p>
              {feedback ? (
                <p
                  className={feedback.tone === "success" ? styles.feedbackSuccess : styles.feedbackError}
                  role="status"
                >
                  {feedback.message}
                </p>
              ) : null}
              <button className={styles.primaryButton} disabled={submitting} type="submit">
                {submitting ? "更新中..." : "更新密码"}
              </button>
            </form>
          </section>

          <section className={styles.panel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.eyebrow}>Personal Workload</p>
                <h2>个人工作量摘要</h2>
              </div>
              <span className={styles.panelHint}>已结算记录</span>
            </div>

            {workloadQuery.isLoading ? (
              <p className={styles.muted}>正在加载个人工作量...</p>
            ) : workloadQuery.isError ? (
              <p className={styles.feedbackError}>个人工作量暂时加载失败，请稍后刷新重试。</p>
            ) : (
              <>
                <div className={styles.workloadHero}>
                  <div>
                    <span className={styles.workloadLabel}>累计工作量 A1</span>
                    <strong className={styles.workloadValue}>
                      {formatWorkload(workloadQuery.data?.totalWorkloadA1 ?? 0)}
                    </strong>
                  </div>
                  <div className={styles.workloadMeta}>
                    <span>{`${workloadQuery.data?.entries.length ?? 0} 条已结算记录`}</span>
                    <span>
                      {recentEntries[0]?.settledAt
                        ? `最近结算：${formatTimestamp(recentEntries[0].settledAt)}`
                        : "最近结算：暂无"}
                    </span>
                  </div>
                </div>

                {recentEntries.length > 0 ? (
                  <div className={styles.entryList}>
                    {recentEntries.map((entry) => (
                      <article className={styles.entryCard} key={`${entry.groupId}-${entry.roleKey}`}>
                        <div className={styles.entryHeader}>
                          <strong>{entry.groupId}</strong>
                          <span>{formatWorkload(entry.workloadA1)}</span>
                        </div>
                        <div className={styles.entryMeta}>
                          <span>{entry.roleKey}</span>
                          <span>{entry.displayName ?? currentAccount.displayName}</span>
                          <span>{formatTimestamp(entry.settledAt)}</span>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <p className={styles.muted}>当前还没有已结算的个人工作量记录。</p>
                )}
              </>
            )}
          </section>
        </section>
      </div>
    </main>
  );
}

function InfoCard({
  label,
  value,
  supporting,
}: {
  label: string;
  value: string;
  supporting?: string;
}) {
  return (
    <article className={styles.infoCard}>
      <span className={styles.cardLabel}>{label}</span>
      <strong className={styles.cardValue}>{value}</strong>
      {supporting ? <p className={styles.cardSupporting}>{supporting}</p> : null}
    </article>
  );
}
