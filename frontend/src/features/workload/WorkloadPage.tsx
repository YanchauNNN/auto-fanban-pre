import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  getCurrentNodeLabel,
  getTaskGroupDisplayTitle,
  getWorkloadEntryDisplayTitle,
  getWorkflowStatusLabel,
  type TaskGroupPresentationLabels,
} from "../../shared/task-groups/taskGroupPresentation";
import type {
  AccountCreatePayload,
  TaskGroupSummary,
  WorkflowApprovePayload,
  WorkloadQueryParams,
  WorkloadScopeResponse,
} from "../../platform/api/types";
import { useApiAdapter } from "../../platform/api/useApiAdapter";
import { useSession } from "../../shared/session/SessionContext";
import styles from "./WorkloadPage.module.css";

type WorkloadScopeKey = "me" | "office" | "institute" | "admin";
type RepairMode = "replace" | "create";

type FeedbackState = {
  tone: "error" | "success";
  message: string;
} | null;

const WORKLOAD_SCOPE_ORDER: readonly WorkloadScopeKey[] = ["me", "office", "institute", "admin"];

function buildEmptyRepairForm(role: string) {
  return {
    officeCode: "",
    officeName: "",
    accountId: "",
    displayName: "",
    role,
  };
}

function formatWorkload(value: number) {
  return value.toFixed(2);
}

function formatTimestamp(value: string | null) {
  if (!value) {
    return "暂未记录";
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

function getAvailableScopes(
  role: string,
  scopeRoles: Record<string, readonly string[]>,
): WorkloadScopeKey[] {
  const scopes: WorkloadScopeKey[] = ["me"];
  for (const scope of WORKLOAD_SCOPE_ORDER) {
    if (scope === "me") {
      continue;
    }
    if ((scopeRoles[scope] ?? []).includes(role)) {
      scopes.push(scope);
    }
  }
  return scopes;
}

function getMonitorTone(item: TaskGroupSummary) {
  if (item.archiveStatus === "failed") {
    return "failed";
  }
  if (item.canApprove) {
    return "approvable";
  }
  if (item.isRelatedToCurrentUser) {
    return "related";
  }
  return "default";
}

function getMonitorHint(item: TaskGroupSummary) {
  if (item.archiveStatus === "failed") {
    return "归档失败，请优先检查异常。";
  }
  if (item.canApprove) {
    return "当前已轮到你审批。";
  }
  if (item.isRelatedToCurrentUser) {
    return "与你有关，但当前还未轮到你处理。";
  }
  return "当前仅作流程监视。";
}

function buildInitialScope(
  requestedScope: string | null,
  availableScopes: readonly WorkloadScopeKey[],
): WorkloadScopeKey {
  if (requestedScope && availableScopes.includes(requestedScope as WorkloadScopeKey)) {
    return requestedScope as WorkloadScopeKey;
  }
  return availableScopes[0] ?? "me";
}

function normalizeFilters(filters: {
  startDate: string;
  endDate: string;
  status: string;
  validOnly: boolean;
}): WorkloadQueryParams {
  return {
    startDate: filters.startDate || undefined,
    endDate: filters.endDate || undefined,
    status: filters.status || undefined,
    validOnly: filters.validOnly || undefined,
  };
}

function getWorkloadLoader(scope: WorkloadScopeKey, adapter: ReturnType<typeof useApiAdapter>) {
  switch (scope) {
    case "office":
      return adapter.getWorkloadOffice.bind(adapter);
    case "institute":
      return adapter.getWorkloadInstitute.bind(adapter);
    case "admin":
      return adapter.getWorkloadAdmin.bind(adapter);
    case "me":
    default:
      return adapter.getWorkloadMe.bind(adapter);
  }
}

export function WorkloadPage() {
  const adapter = useApiAdapter();
  const queryClient = useQueryClient();
  const { currentAccount, refreshCurrentAccount } = useSession();
  const [searchParams, setSearchParams] = useSearchParams();
  const [filters, setFilters] = useState({
    startDate: "",
    endDate: "",
    status: "",
    validOnly: false,
  });
  const [feedback, setFeedback] = useState<FeedbackState>(null);
  const [approvalTarget, setApprovalTarget] = useState<TaskGroupSummary | null>(null);
  const [approvalFactor, setApprovalFactor] = useState("");
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [approvalSubmitting, setApprovalSubmitting] = useState(false);
  const [repairTarget, setRepairTarget] = useState<TaskGroupSummary | null>(null);
  const [repairMode, setRepairMode] = useState<RepairMode>("replace");
  const [repairReplaceAccountId, setRepairReplaceAccountId] = useState("");
  const [repairForm, setRepairForm] = useState(() => buildEmptyRepairForm(""));
  const [repairError, setRepairError] = useState<string | null>(null);
  const [repairSubmitting, setRepairSubmitting] = useState(false);

  const schemaQuery = useQuery({
    queryKey: ["form-schema", "management"],
    queryFn: () => adapter.getFormSchema(),
  });
  const managementSchema = schemaQuery.data?.management;
  const roleOptions = managementSchema?.account.validRoles ?? [];
  const defaultRepairRole = roleOptions[0] ?? "";
  const workloadScopeRoles = managementSchema?.workload.scopeRoles ?? {};
  const workloadScopeLabels = managementSchema?.workload.scopeLabels ?? {};
  const workloadStatusOptions = managementSchema?.workload.statusOptions ?? [];
  const taskGroupPresentationLabels = useMemo<TaskGroupPresentationLabels>(
    () => ({
      workflowStatusLabels: managementSchema?.workflow.statusLabels ?? {},
      archiveStatusLabels: managementSchema?.archive?.statusLabels ?? {},
      nodeLabels: managementSchema?.workflow.nodeLabels ?? {},
      emptyCurrentNodeLabel: managementSchema?.workflow.emptyCurrentNodeLabel ?? "",
    }),
    [managementSchema],
  );

  const availableScopes = useMemo(
    () =>
      managementSchema
        ? getAvailableScopes(currentAccount?.role ?? "", workloadScopeRoles)
        : [...WORKLOAD_SCOPE_ORDER],
    [currentAccount?.role, managementSchema, workloadScopeRoles],
  );
  const [selectedScope, setSelectedScope] = useState<WorkloadScopeKey>(() =>
    buildInitialScope(searchParams.get("scope"), availableScopes),
  );
  const isAdmin = availableScopes.includes("admin");

  useEffect(() => {
    const nextScope = buildInitialScope(searchParams.get("scope"), availableScopes);
    if (!availableScopes.includes(selectedScope)) {
      setSelectedScope(nextScope);
      return;
    }
    if (searchParams.get("scope") !== selectedScope) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set("scope", selectedScope);
      setSearchParams(nextParams, { replace: true });
    }
  }, [availableScopes, searchParams, selectedScope, setSearchParams]);

  const normalizedFilters = useMemo(() => normalizeFilters(filters), [filters]);

  const monitorQuery = useQuery({
    queryKey: ["workflow", "monitor"],
    queryFn: () => adapter.getWorkflowMonitor(),
  });

  const historyQuery = useQuery({
    queryKey: ["workload", selectedScope, normalizedFilters],
    queryFn: () => getWorkloadLoader(selectedScope, adapter)(normalizedFilters),
  });

  const accountsQuery = useQuery({
    queryKey: ["accounts", "repair-options"],
    queryFn: () => adapter.listAccounts(),
    enabled: isAdmin && repairTarget !== null,
  });

  const historyEntries = useMemo(() => {
    return [...(historyQuery.data?.entries ?? [])].sort((left, right) => {
      const leftTime = left.settledAt ? new Date(left.settledAt).getTime() : 0;
      const rightTime = right.settledAt ? new Date(right.settledAt).getTime() : 0;
      return rightTime - leftTime;
    });
  }, [historyQuery.data?.entries]);
  const cockpitStats = useMemo(() => {
    const items = monitorQuery.data?.items ?? [];
    return {
      totalFlow: items.length,
      approvable: items.filter((item) => item.canApprove).length,
      related: items.filter((item) => item.isRelatedToCurrentUser).length,
      failed: items.filter((item) => item.archiveStatus === "failed").length,
      historyCount: historyQuery.data?.entries.length ?? 0,
      totalWorkload: historyQuery.data?.totalWorkloadA1 ?? 0,
    };
  }, [historyQuery.data, monitorQuery.data?.items]);

  useEffect(() => {
    if (repairTarget && !repairReplaceAccountId) {
      setRepairReplaceAccountId(accountsQuery.data?.items[0]?.accountId ?? "");
    }
  }, [accountsQuery.data?.items, repairReplaceAccountId, repairTarget]);

  if (!currentAccount) {
    return null;
  }
  if (schemaQuery.isLoading && !schemaQuery.data) {
    return (
      <main className={styles.page}>
        <p className={styles.muted}>正在加载管理参数...</p>
      </main>
    );
  }
  if (!managementSchema) {
    return (
      <main className={styles.page}>
        <p className={styles.feedbackError}>管理参数未加载，无法进入工作量模块。</p>
      </main>
    );
  }
  const account = currentAccount;
  const workflowFactor = managementSchema.workflow.factor;
  const defaultAccountPassword = managementSchema.account.adminCreatedDefaultPassword;

  function openApprovalDialog(item: TaskGroupSummary) {
    setApprovalTarget(item);
    setApprovalFactor(formatApprovalFactor(workflowFactor.default, workflowFactor.precision));
    setApprovalError(null);
    setFeedback(null);
  }

  function openRepairDialog(item: TaskGroupSummary) {
    setRepairTarget(item);
    setRepairMode("replace");
    setRepairReplaceAccountId(accountsQuery.data?.items[0]?.accountId ?? "");
    setRepairForm({
      ...buildEmptyRepairForm(defaultRepairRole),
      officeCode: account.officeCode ?? "",
      officeName: account.officeName ?? "",
    });
    setRepairError(null);
    setFeedback(null);
  }

  function closeRepairDialog() {
    setRepairTarget(null);
    setRepairMode("replace");
    setRepairReplaceAccountId("");
    setRepairForm(buildEmptyRepairForm(defaultRepairRole));
    setRepairError(null);
  }

  async function invalidateWorkflowViews(groupId?: string) {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["workflow", "monitor"] }),
      queryClient.invalidateQueries({ queryKey: ["task-groups"] }),
      queryClient.invalidateQueries({ queryKey: ["workload"] }),
      ...(groupId
        ? [queryClient.invalidateQueries({ queryKey: ["task-group-detail", groupId] })]
        : []),
      refreshCurrentAccount(),
    ]);
  }

  async function handleApprovalSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!approvalTarget) {
      return;
    }

    const trimmed = approvalFactor.trim();
    const factorPrecision = workflowFactor.precision;
    const factorPattern =
      factorPrecision <= 0
        ? /^\d+$/
        : new RegExp(`^\\d+(\\.\\d{1,${factorPrecision}})?$`);
    if (!factorPattern.test(trimmed)) {
      setApprovalError(`审批系数请保留 ${factorPrecision} 位以内小数。`);
      return;
    }

    const factor = Number.parseFloat(trimmed);
    const minFactor = workflowFactor.min;
    const maxFactor = workflowFactor.max;
    if (Number.isNaN(factor) || factor < minFactor || factor > maxFactor) {
      setApprovalError(
        `审批系数需在 ${formatApprovalFactor(minFactor, factorPrecision)} 到 ${formatApprovalFactor(
          maxFactor,
          factorPrecision,
        )} 之间。`,
      );
      return;
    }

    setApprovalSubmitting(true);
    setApprovalError(null);
    setFeedback(null);
    try {
      const payload: WorkflowApprovePayload = {
        factor,
        nodeKey: approvalTarget.currentNodeKey,
      };
      await adapter.approveWorkflow(approvalTarget.groupId, payload);
      await invalidateWorkflowViews();
      setApprovalTarget(null);
      setFeedback({ tone: "success", message: "审批已提交，列表已刷新。" });
    } catch (error) {
      setApprovalError(resolveErrorMessage(error, "审批提交失败，请稍后重试。"));
    } finally {
      setApprovalSubmitting(false);
    }
  }

  async function handleRepairSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!repairTarget) {
      return;
    }

    setRepairSubmitting(true);
    setRepairError(null);
    setFeedback(null);
    try {
      if (repairMode === "replace") {
        if (!repairReplaceAccountId) {
          setRepairError("请先选择替换账号。");
          setRepairSubmitting(false);
          return;
        }
        await adapter.repairCurrentNode(repairTarget.groupId, {
          replaceWithAccountId: repairReplaceAccountId,
        });
      } else {
        const payload: AccountCreatePayload = {
          officeCode: repairForm.officeCode.trim() || null,
          officeName: repairForm.officeName.trim() || null,
          accountId: repairForm.accountId.trim(),
          displayName: repairForm.displayName.trim(),
          role: repairForm.role,
          password: defaultAccountPassword,
        };
        if (!payload.accountId || !payload.displayName) {
          setRepairError("请先完整填写新账号和姓名。");
          setRepairSubmitting(false);
          return;
        }
        await adapter.repairCurrentNode(repairTarget.groupId, {
          createAccountPayload: payload,
        });
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["accounts"] }),
          queryClient.invalidateQueries({ queryKey: ["invalid-account-rows"] }),
          queryClient.invalidateQueries({ queryKey: ["accounts", "repair-options"] }),
        ]);
      }

      await invalidateWorkflowViews(repairTarget.groupId);
      closeRepairDialog();
      setFeedback({ tone: "success", message: "当前节点已修复并刷新。" });
    } catch (error) {
      setRepairError(resolveErrorMessage(error, "修复当前节点失败，请稍后重试。"));
    } finally {
      setRepairSubmitting(false);
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Workflow & Workload</p>
          <h1>工作量模块</h1>
          <p className={styles.description}>
            这里集中承接当前流程监视、节点审批和按角色可见范围的历史工作量统计。
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

      <section className={styles.cockpit}>
        <div className={styles.cockpitHero} aria-hidden="true" />
        <div className={styles.metricStrip}>
          <MetricTile label="可见流程" value={`${cockpitStats.totalFlow}`} />
          <MetricTile label="待我审批" value={`${cockpitStats.approvable}`} tone="hot" />
          <MetricTile label="相关流程" value={`${cockpitStats.related}`} />
          <MetricTile label="异常归档" value={`${cockpitStats.failed}`} tone="danger" />
          <MetricTile label="历史记录" value={`${cockpitStats.historyCount}`} />
          <MetricTile label="累计 A1" value={`${formatWorkload(cockpitStats.totalWorkload)} A1`} tone="strong" />
        </div>
      </section>

      <div className={styles.dashboardGrid}>
      <section className={styles.sectionPrimary}>
        <div className={styles.sectionHeader}>
          <div>
            <p className={styles.eyebrow}>Current Flow</p>
            <h2>当前流程监视</h2>
          </div>
          <span className={styles.sectionHint}>{`${monitorQuery.data?.total ?? 0} 条流程`}</span>
        </div>

        {monitorQuery.isLoading ? (
          <p className={styles.muted}>正在加载流程监视...</p>
        ) : monitorQuery.isError ? (
          <p className={styles.feedbackError}>流程监视加载失败，请稍后刷新重试。</p>
        ) : (monitorQuery.data?.items.length ?? 0) > 0 ? (
          <div className={styles.monitorGrid}>
            {(monitorQuery.data?.items ?? []).map((item) => {
              const tone = getMonitorTone(item);
              return (
                <article className={styles[`monitorCard${capitalize(tone)}`]} key={item.groupId}>
                  <div className={styles.monitorHeader}>
                    <div>
                      <strong>{getTaskGroupDisplayTitle(item)}</strong>
                      <p className={styles.monitorHint}>{getMonitorHint(item)}</p>
                    </div>
                    <span className={styles.monitorBadge}>
                      {getWorkflowStatusLabel(item.workflowStatus, taskGroupPresentationLabels)}
                    </span>
                  </div>
                  <dl className={styles.monitorMeta}>
                    <div>
                      <dt>发起人</dt>
                      <dd>{item.creatorName ?? item.ownerSnapshot?.creatorName ?? "未记录"}</dd>
                    </div>
                    <div>
                      <dt>责任单位</dt>
                      <dd>{item.creatorOffice ?? item.ownerSnapshot?.creatorOffice ?? "未记录"}</dd>
                    </div>
                    <div>
                      <dt>当前节点</dt>
                      <dd>{getCurrentNodeLabel(item.currentNodeKey, taskGroupPresentationLabels)}</dd>
                    </div>
                    <div>
                      <dt>有效工作量</dt>
                      <dd>{formatWorkload(item.effectiveWorkload)}</dd>
                    </div>
                  </dl>
                  <WorkflowRail
                    archiveStatus={item.archiveStatus}
                    currentNodeKey={item.currentNodeKey}
                    labels={taskGroupPresentationLabels}
                    workflowStatus={item.workflowStatus}
                  />
                  <div className={styles.monitorActions}>
                    <Link className={styles.secondaryLink} to={`/task-groups/${item.groupId}`}>
                      查看任务包
                    </Link>
                    {item.canApprove ? (
                      <button
                        className={styles.primaryButton}
                        onClick={() => openApprovalDialog(item)}
                        type="button"
                      >
                        审批
                      </button>
                    ) : null}
                    {isAdmin && item.currentNodeKey ? (
                      <button
                        className={styles.secondaryButton}
                        onClick={() => openRepairDialog(item)}
                        type="button"
                      >
                        修复当前节点
                      </button>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <p className={styles.muted}>当前没有可见流程。</p>
        )}
      </section>

      <section className={styles.sectionSecondary}>
        <div className={styles.sectionHeader}>
          <div>
            <p className={styles.eyebrow}>History</p>
            <h2>历史与统计</h2>
          </div>
          <span className={styles.sectionHint}>按当前角色可见范围查询</span>
        </div>

        <div className={styles.scopeTabs}>
          {availableScopes.map((scope) => (
            <button
              aria-pressed={selectedScope === scope}
              className={selectedScope === scope ? styles.scopeTabActive : styles.scopeTab}
              key={scope}
              onClick={() => setSelectedScope(scope)}
              type="button"
            >
              {workloadScopeLabels[scope] ?? scope}
            </button>
          ))}
        </div>

        <form
          className={styles.filterBar}
          onSubmit={(event) => {
            event.preventDefault();
            setFeedback(null);
          }}
        >
          <label className={styles.filterField}>
            <span>开始日期</span>
            <input
              className={styles.input}
              onChange={(event) => {
                const value = event.currentTarget.value;
                setFilters((current) => ({ ...current, startDate: value }));
              }}
              type="date"
              value={filters.startDate}
            />
          </label>
          <label className={styles.filterField}>
            <span>结束日期</span>
            <input
              className={styles.input}
              onChange={(event) => {
                const value = event.currentTarget.value;
                setFilters((current) => ({ ...current, endDate: value }));
              }}
              type="date"
              value={filters.endDate}
            />
          </label>
          <label className={styles.filterField}>
            <span>结算状态</span>
            <select
              className={styles.input}
              onChange={(event) => {
                const value = event.currentTarget.value;
                setFilters((current) => ({ ...current, status: value }));
              }}
              value={filters.status}
            >
              {workloadStatusOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className={styles.checkboxField}>
            <input
              checked={filters.validOnly}
              onChange={(event) => {
                const checked = event.currentTarget.checked;
                setFilters((current) => ({ ...current, validOnly: checked }));
              }}
              type="checkbox"
            />
            <span>仅看有效记录</span>
          </label>
        </form>

        {historyQuery.isLoading ? (
          <p className={styles.muted}>正在加载统计...</p>
        ) : historyQuery.isError ? (
          <p className={styles.feedbackError}>统计加载失败，请稍后刷新重试。</p>
        ) : (
          <HistoryPanel
            currentAccountName={account.displayName}
            data={historyQuery.data}
            entries={historyEntries}
          />
        )}
      </section>
      </div>

      {approvalTarget ? (
        <div
          aria-label="审批当前节点"
          aria-modal="true"
          className={styles.modalBackdrop}
          role="dialog"
        >
          <div className={styles.modalCard}>
            <div className={styles.modalHeader}>
              <div>
                <p className={styles.eyebrow}>Approval</p>
                <h3>审批当前节点</h3>
              </div>
              <button className={styles.closeButton} onClick={() => setApprovalTarget(null)} type="button">
                关闭
              </button>
            </div>

            <p className={styles.modalDescription}>
              {`${getTaskGroupDisplayTitle(approvalTarget)} 当前处于 ${getCurrentNodeLabel(
                approvalTarget.currentNodeKey,
                taskGroupPresentationLabels,
              )}。`}
            </p>

            <form className={styles.form} onSubmit={handleApprovalSubmit}>
              <label className={styles.label} htmlFor="workflow-approval-factor">
                审批系数
              </label>
              <input
                className={styles.input}
                id="workflow-approval-factor"
                onChange={(event) => setApprovalFactor(event.currentTarget.value)}
                type="text"
                value={approvalFactor}
              />
              <p className={styles.helpText}>
                {`允许范围 ${formatApprovalFactor(
                  workflowFactor.min,
                  workflowFactor.precision,
                )} 到 ${formatApprovalFactor(
                  workflowFactor.max,
                  workflowFactor.precision,
                )}，最多 ${workflowFactor.precision} 位小数。`}
              </p>
              {approvalError ? <p className={styles.feedbackError}>{approvalError}</p> : null}
              <div className={styles.modalActions}>
                <button className={styles.secondaryButton} onClick={() => setApprovalTarget(null)} type="button">
                  取消
                </button>
                <button className={styles.primaryButton} disabled={approvalSubmitting} type="submit">
                  {approvalSubmitting ? "提交中..." : "确认审批"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {repairTarget ? (
        <div
          aria-label="修复当前节点"
          aria-modal="true"
          className={styles.modalBackdrop}
          role="dialog"
        >
          <div className={styles.modalCard}>
            <div className={styles.modalHeader}>
              <div>
                <p className={styles.eyebrow}>Repair</p>
                <h3>修复当前节点</h3>
              </div>
              <button className={styles.closeButton} onClick={closeRepairDialog} type="button">
                关闭
              </button>
            </div>

            <p className={styles.modalDescription}>
              {`${getTaskGroupDisplayTitle(repairTarget)} 当前卡在 ${getCurrentNodeLabel(
                repairTarget.currentNodeKey,
                taskGroupPresentationLabels,
              )}，请选择修复方式。`}
            </p>

            <div className={styles.scopeTabs}>
              <button
                aria-pressed={repairMode === "replace"}
                className={repairMode === "replace" ? styles.scopeTabActive : styles.scopeTab}
                onClick={() => setRepairMode("replace")}
                type="button"
              >
                更换现有账号
              </button>
              <button
                aria-pressed={repairMode === "create"}
                className={repairMode === "create" ? styles.scopeTabActive : styles.scopeTab}
                onClick={() => setRepairMode("create")}
                type="button"
              >
                新增账号并修复
              </button>
            </div>

            <form className={styles.form} onSubmit={handleRepairSubmit}>
              {repairMode === "replace" ? (
                <>
                  <label className={styles.label} htmlFor="workflow-repair-account">
                    替换账号
                  </label>
                  <select
                    className={styles.input}
                    id="workflow-repair-account"
                    onChange={(event) => setRepairReplaceAccountId(event.currentTarget.value)}
                    value={repairReplaceAccountId}
                  >
                    <option value="">请选择替换账号</option>
                    {(accountsQuery.data?.items ?? []).map((account) => (
                      <option key={account.accountId} value={account.accountId}>
                        {`${account.displayName} (${account.accountId})`}
                      </option>
                    ))}
                  </select>
                  {accountsQuery.isLoading ? <p className={styles.helpText}>正在加载账号候选...</p> : null}
                </>
              ) : (
                <>
                  <label className={styles.label} htmlFor="workflow-repair-new-account">
                    新账号
                  </label>
                  <input
                    className={styles.input}
                    id="workflow-repair-new-account"
                    onChange={(event) => {
                      const value = event.currentTarget.value;
                      setRepairForm((current) => ({ ...current, accountId: value }));
                    }}
                    value={repairForm.accountId}
                  />

                  <label className={styles.label} htmlFor="workflow-repair-display-name">
                    姓名
                  </label>
                  <input
                    className={styles.input}
                    id="workflow-repair-display-name"
                    onChange={(event) => {
                      const value = event.currentTarget.value;
                      setRepairForm((current) => ({ ...current, displayName: value }));
                    }}
                    value={repairForm.displayName}
                  />

                  <label className={styles.label} htmlFor="workflow-repair-office-code">
                    科室编码
                  </label>
                  <input
                    className={styles.input}
                    id="workflow-repair-office-code"
                    onChange={(event) => {
                      const value = event.currentTarget.value;
                      setRepairForm((current) => ({ ...current, officeCode: value }));
                    }}
                    value={repairForm.officeCode}
                  />

                  <label className={styles.label} htmlFor="workflow-repair-office-name">
                    科室
                  </label>
                  <input
                    className={styles.input}
                    id="workflow-repair-office-name"
                    onChange={(event) => {
                      const value = event.currentTarget.value;
                      setRepairForm((current) => ({ ...current, officeName: value }));
                    }}
                    value={repairForm.officeName}
                  />

                  <label className={styles.label} htmlFor="workflow-repair-role">
                    角色
                  </label>
                  <select
                    className={styles.input}
                    id="workflow-repair-role"
                    onChange={(event) => {
                      const value = event.currentTarget.value;
                      setRepairForm((current) => ({ ...current, role: value }));
                    }}
                    value={repairForm.role}
                  >
                    {roleOptions.map((role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    ))}
                  </select>
                  <p className={styles.helpText}>
                    {`新建修复账号时，默认密码来自参数规范：${defaultAccountPassword || "未配置"}。`}
                  </p>
                </>
              )}

              {repairError ? <p className={styles.feedbackError}>{repairError}</p> : null}
              <div className={styles.modalActions}>
                <button className={styles.secondaryButton} onClick={closeRepairDialog} type="button">
                  取消
                </button>
                <button className={styles.primaryButton} disabled={repairSubmitting} type="submit">
                  {repairSubmitting ? "提交中..." : "确认修复"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </main>
  );
}

function HistoryPanel({
  currentAccountName,
  data,
  entries,
}: {
  currentAccountName: string;
  data: WorkloadScopeResponse | undefined;
  entries: WorkloadScopeResponse["entries"];
}) {
  const topAccounts = useMemo(() => {
    return Object.entries(data?.totalsByAccount ?? {})
      .sort((left, right) => right[1] - left[1])
      .slice(0, 6);
  }, [data?.totalsByAccount]);

  return (
    <div className={styles.historyLayout}>
      <div className={styles.historyHero}>
        <div>
          <span className={styles.heroLabel}>累计工作量 A1</span>
          <strong className={styles.heroValue}>{formatWorkload(data?.totalWorkloadA1 ?? 0)}</strong>
        </div>
        <div className={styles.heroMeta}>
          <span>{`${data?.entries.length ?? 0} 条记录`}</span>
          <span>
            {data?.officeName ? `当前科室：${data.officeName}` : `当前账号：${currentAccountName}`}
          </span>
        </div>
      </div>

      {topAccounts.length > 0 ? (
        <section className={styles.rankPanel}>
          <div className={styles.rankHeader}>
            <strong>人员累计</strong>
            <span>管理员视角</span>
          </div>
          <div className={styles.rankList}>
            {topAccounts.map(([accountId, total]) => (
              <div className={styles.rankItem} key={accountId}>
                <span>{accountId}</span>
                <strong>{formatWorkload(total)}</strong>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {(data?.entries.length ?? 0) > 0 ? (
        <div className={styles.historyList}>
          {entries.map((entry) => (
            <article className={styles.historyCard} key={`${entry.groupId}-${entry.roleKey}`}>
              <div className={styles.historyCardHeader}>
                <strong>{getWorkloadEntryDisplayTitle(entry)}</strong>
                <span>{formatWorkload(entry.workloadA1)}</span>
              </div>
              <div className={styles.historyCardMeta}>
                <span>{entry.roleKey}</span>
                <span>{entry.displayName ?? entry.accountId ?? "未记录"}</span>
                <span>{entry.settlementStatus}</span>
                <span>{formatTimestamp(entry.settledAt)}</span>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className={styles.muted}>当前筛选条件下没有历史记录。</p>
      )}
    </div>
  );
}

function MetricTile({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "hot" | "danger" | "strong";
}) {
  return (
    <article className={styles[`metricTile${capitalize(tone)}`]}>
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function WorkflowRail({
  archiveStatus,
  currentNodeKey,
  labels,
  workflowStatus,
}: {
  archiveStatus: string;
  currentNodeKey: string | null;
  labels: TaskGroupPresentationLabels;
  workflowStatus: string;
}) {
  const stages = [
    { key: "one_review", label: labels.nodeLabels?.one_review ?? "一审" },
    { key: "two_review", label: labels.nodeLabels?.two_review ?? "二审" },
    { key: "three_review", label: labels.nodeLabels?.three_review ?? "三审" },
    { key: "archive", label: "归档" },
  ];
  const currentIndex = currentNodeKey
    ? stages.findIndex((stage) => stage.key === currentNodeKey)
    : -1;
  const isTerminal =
    workflowStatus === "three_review_approved" ||
    workflowStatus === "archived" ||
    archiveStatus === "succeeded";
  const hasFailed = archiveStatus === "failed" || workflowStatus === "archive_failed";

  return (
    <ol className={styles.flowRail} aria-label="任务流程图">
      {stages.map((stage, index) => {
        let state = "pending";
        if (hasFailed && stage.key === "archive") {
          state = "failed";
        } else if (isTerminal) {
          state = "done";
        } else if (index < currentIndex) {
          state = "done";
        } else if (index === currentIndex) {
          state = "current";
        }
        return (
          <li className={styles[`flowNode${capitalize(state)}`]} key={stage.key}>
            <span className={styles.flowDot} />
            <span>{stage.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function resolveErrorMessage(error: unknown, fallback: string) {
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
  return fallback;
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatApprovalFactor(value: number, precision: number) {
  const safePrecision = Math.max(0, Math.trunc(precision));
  return value.toFixed(safePrecision);
}
