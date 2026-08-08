import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  getCurrentNodeLabel,
  getSettlementStatusLabel,
  getTaskGroupDisplayTitle,
  getWorkloadEntryDisplayTitle,
  getWorkloadRoleLabel,
  getWorkflowStatusLabel,
  type TaskGroupPresentationLabels,
} from "../../shared/task-groups/taskGroupPresentation";
import type {
  AccountCreatePayload,
  TaskGroupSummary,
  WorkflowNodeSchema,
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
const ACTIVE_WORKFLOW_STATUSES = new Set([
  "submitted",
  "in_review",
  "three_review_approved",
  "archiving",
]);
const WORKFLOW_ERROR_MESSAGES: Readonly<Record<string, string>> = {
  "account not found": "未找到指定账号，请刷新后重新选择。",
  "factor out of range": "审批系数超出允许范围，请检查后重试。",
  "no current workflow node": "当前任务没有可处理的审批节点，请刷新后确认。",
  "only current assignee can approve": "当前账号不是该节点审批人，无法提交审批。",
  node_key_mismatch: "当前审批节点已变化，请刷新后重试。",
  repair_target_required: "请选择有效的节点修复账号。",
};

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

function hasArchiveFailure(item: Pick<TaskGroupSummary, "archiveStatus" | "workflowStatus">) {
  return item.archiveStatus === "failed" || item.workflowStatus === "archive_failed";
}

function getMonitorTone(item: TaskGroupSummary) {
  if (hasArchiveFailure(item)) {
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

function getMonitorPriority(item: TaskGroupSummary) {
  if (item.canApprove) {
    return 0;
  }
  if (hasArchiveFailure(item)) {
    return 1;
  }
  if (item.isRelatedToCurrentUser) {
    return 2;
  }
  return 3;
}

function getMonitorHint(item: TaskGroupSummary) {
  if (hasArchiveFailure(item)) {
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
  const approvalFactorInputRef = useRef<HTMLInputElement>(null);
  const [repairTarget, setRepairTarget] = useState<TaskGroupSummary | null>(null);
  const [repairMode, setRepairMode] = useState<RepairMode>("replace");
  const [repairReplaceAccountId, setRepairReplaceAccountId] = useState("");
  const [repairForm, setRepairForm] = useState(() => buildEmptyRepairForm(""));
  const [repairError, setRepairError] = useState<string | null>(null);
  const [repairSubmitting, setRepairSubmitting] = useState(false);
  const repairAccountSelectRef = useRef<HTMLSelectElement>(null);

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
  const monitorItems = useMemo(
    () =>
      (monitorQuery.data?.items ?? [])
        .map((item, originalIndex) => ({ item, originalIndex }))
        .sort(
          (left, right) =>
            getMonitorPriority(left.item) - getMonitorPriority(right.item) ||
            left.originalIndex - right.originalIndex,
        )
        .map(({ item }) => item),
    [monitorQuery.data?.items],
  );
  const cockpitStats = useMemo(() => {
    const items = monitorQuery.data?.items ?? [];
    return {
      approvable: items.filter((item) => item.canApprove).length,
      active: items.filter((item) => ACTIVE_WORKFLOW_STATUSES.has(item.workflowStatus)).length,
      failed: items.filter(hasArchiveFailure).length,
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
      <section aria-label="工作量模块加载状态" className={styles.page}>
        <p className={styles.muted}>正在加载管理参数...</p>
      </section>
    );
  }
  if (!managementSchema) {
    return (
      <section aria-label="工作量模块错误状态" className={styles.page}>
        <p className={styles.feedbackError}>管理参数未加载，无法进入工作量模块。</p>
      </section>
    );
  }
  const account = currentAccount;
  const workflowFactor = managementSchema.workflow.factor;
  const defaultAccountPolicyConfigured =
    managementSchema.account.adminCreatedDefaultPasswordConfigured;
  const approvalPreview = approvalTarget
    ? buildApprovalPreview(approvalTarget, approvalFactor)
    : null;

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
        if (!defaultAccountPolicyConfigured) {
          setRepairError("后台尚未配置默认策略，请联系管理员完成配置后再操作。");
          setRepairSubmitting(false);
          return;
        }
        const payload: AccountCreatePayload = {
          officeCode: repairForm.officeCode.trim() || null,
          officeName: repairForm.officeName.trim() || null,
          accountId: repairForm.accountId.trim(),
          displayName: repairForm.displayName.trim(),
          role: repairForm.role,
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
    <section aria-label="工作量模块" className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>流程与工作量</p>
          <h1>工作量模块</h1>
        </div>
        <p className={styles.description}>优先处理待办与归档异常，并按权限范围核对已结算工作量。</p>
      </header>

      {feedback ? (
        <p
          className={feedback.tone === "success" ? styles.feedbackSuccess : styles.feedbackError}
          role={feedback.tone === "error" ? "alert" : "status"}
        >
          {feedback.message}
        </p>
      ) : null}

      <section aria-label="工作量概览" className={styles.metricStrip} role="region">
        <MetricTile label="待我审批" value={`${cockpitStats.approvable}`} tone="hot" />
        <MetricTile label="流程中" value={`${cockpitStats.active}`} />
        <MetricTile label="归档异常" value={`${cockpitStats.failed}`} tone="danger" />
        <MetricTile
          label="当前范围累计 A1"
          value={`${formatWorkload(cockpitStats.totalWorkload)} A1`}
          tone="strong"
        />
      </section>

      <div className={styles.dashboardGrid}>
        <section className={styles.sectionPrimary}>
          <div className={styles.sectionHeader}>
            <div>
              <p className={styles.eyebrow}>流程监控</p>
              <h2>待我处理</h2>
            </div>
            <span className={styles.sectionHint}>{`${monitorQuery.data?.total ?? 0} 条流程`}</span>
          </div>

          {monitorQuery.isLoading ? (
            <p aria-label="正在加载流程监控" className={styles.muted} role="status">
              正在加载流程监控...
            </p>
          ) : monitorQuery.isError ? (
            <p aria-label="流程监控加载失败" className={styles.feedbackError} role="alert">
              流程监控加载失败，请稍后刷新重试。
            </p>
          ) : monitorItems.length > 0 ? (
            <div
              aria-label="流程监控列表"
              className={styles.monitorGrid}
              role="region"
              tabIndex={0}
            >
              {monitorItems.map((item) => {
                const tone = getMonitorTone(item);
                return (
                  <article
                    className={styles[`monitorCard${capitalize(tone)}`]}
                    data-testid="workflow-item"
                    key={item.groupId}
                  >
                    <div className={styles.monitorHeader}>
                      <div>
                        <strong>{getTaskGroupDisplayTitle(item)}</strong>
                        <p className={styles.monitorHint}>{getMonitorHint(item)}</p>
                      </div>
                      <span className={styles.monitorBadge}>
                        {hasArchiveFailure(item)
                          ? "归档异常"
                          : getWorkflowStatusLabel(
                              item.workflowStatus,
                              taskGroupPresentationLabels,
                            )}
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
                        <dd>{formatWorkload(item.effectiveWorkload)} A1</dd>
                      </div>
                    </dl>
                    <WorkflowRail
                      archiveStatus={item.archiveStatus}
                      currentNodeKey={item.currentNodeKey}
                      nodes={managementSchema.workflow.nodes ?? []}
                      terminalStatus={managementSchema.workflow.terminalStatus}
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
              <p className={styles.eyebrow}>范围筛选</p>
              <h2>工作量台账</h2>
            </div>
            <span className={styles.sectionHint}>只显示当前角色可见记录</span>
          </div>

          <div aria-label="统计范围" className={styles.scopeTabs} role="group">
            {availableScopes.map((scope) => (
              <button
                aria-pressed={selectedScope === scope}
                className={selectedScope === scope ? styles.scopeTabActive : styles.scopeTab}
                key={scope}
                onClick={() => setSelectedScope(scope)}
                type="button"
              >
                {workloadScopeLabels[scope] ?? "其他范围"}
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
            <p aria-label="正在加载工作量台账" className={styles.muted} role="status">
              正在加载工作量台账...
            </p>
          ) : historyQuery.isError ? (
            <p aria-label="工作量台账加载失败" className={styles.feedbackError} role="alert">
              工作量台账加载失败，请稍后刷新重试。
            </p>
          ) : (
            <HistoryPanel
              currentAccountName={account.displayName}
              data={historyQuery.data}
              entries={historyEntries}
              labels={taskGroupPresentationLabels}
            />
          )}
        </section>
      </div>

      {approvalTarget ? (
        <AccessibleModal
          ariaLabel="审批当前节点"
          descriptionId="workflow-approval-description"
          initialFocusRef={approvalFactorInputRef}
          onClose={() => setApprovalTarget(null)}
        >
          <div className={styles.modalHeader}>
            <div>
              <p className={styles.eyebrow}>审批</p>
              <h3>审批当前节点</h3>
            </div>
            <button className={styles.closeButton} onClick={() => setApprovalTarget(null)} type="button">
              关闭
            </button>
          </div>

          <p className={styles.modalDescription} id="workflow-approval-description">
            {`${getTaskGroupDisplayTitle(approvalTarget)} 当前处于 ${getCurrentNodeLabel(
              approvalTarget.currentNodeKey,
              taskGroupPresentationLabels,
            )}。`}
          </p>

          {approvalPreview ? (
            <dl className={styles.approvalSummary}>
              <div>
                <dt>初始 A1</dt>
                <dd>{formatWorkload(approvalPreview.initialWorkload)} A1</dd>
              </div>
              <div>
                <dt>已应用系数</dt>
                <dd>{formatFactorProduct(approvalPreview.appliedFactor)}</dd>
              </div>
              <div>
                <dt>当前输入系数</dt>
                <dd>{approvalPreview.inputFactorLabel}</dd>
              </div>
              <div>
                <dt>预计最终 A1</dt>
                <dd>{approvalPreview.projectedWorkloadLabel}</dd>
              </div>
            </dl>
          ) : null}

          <form className={styles.form} onSubmit={handleApprovalSubmit}>
            <label className={styles.label} htmlFor="workflow-approval-factor">
              当前输入系数
            </label>
            <input
              className={styles.input}
              id="workflow-approval-factor"
              onChange={(event) => setApprovalFactor(event.currentTarget.value)}
              ref={approvalFactorInputRef}
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
            {approvalError ? (
              <p className={styles.feedbackError} role="alert">
                {approvalError}
              </p>
            ) : null}
            <div className={styles.modalActions}>
              <button className={styles.secondaryButton} onClick={() => setApprovalTarget(null)} type="button">
                取消
              </button>
              <button className={styles.primaryButton} disabled={approvalSubmitting} type="submit">
                {approvalSubmitting ? "提交中..." : "确认审批"}
              </button>
            </div>
          </form>
        </AccessibleModal>
      ) : null}

      {repairTarget ? (
        <AccessibleModal
          ariaLabel="修复当前节点"
          descriptionId="workflow-repair-description"
          initialFocusRef={repairAccountSelectRef}
          onClose={closeRepairDialog}
        >
            <div className={styles.modalHeader}>
              <div>
                <p className={styles.eyebrow}>节点修复</p>
                <h3>修复当前节点</h3>
              </div>
              <button className={styles.closeButton} onClick={closeRepairDialog} type="button">
                关闭
              </button>
            </div>

            <p className={styles.modalDescription} id="workflow-repair-description">
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
                    ref={repairAccountSelectRef}
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
                  <p
                    className={styles.helpText}
                    role={defaultAccountPolicyConfigured ? undefined : "alert"}
                  >
                    {defaultAccountPolicyConfigured
                      ? "新建修复账号时，将采用后台已配置默认策略。"
                      : "后台尚未配置默认策略，请联系管理员完成配置后再操作。"}
                  </p>
                </>
              )}

              {repairError ? (
                <p className={styles.feedbackError} role="alert">
                  {repairError}
                </p>
              ) : null}
              <div className={styles.modalActions}>
                <button className={styles.secondaryButton} onClick={closeRepairDialog} type="button">
                  取消
                </button>
                <button
                  className={styles.primaryButton}
                  disabled={
                    repairSubmitting ||
                    (repairMode === "create" && !defaultAccountPolicyConfigured)
                  }
                  type="submit"
                >
                  {repairSubmitting ? "提交中..." : "确认修复"}
                </button>
              </div>
            </form>
        </AccessibleModal>
      ) : null}
    </section>
  );
}

function HistoryPanel({
  currentAccountName,
  data,
  entries,
  labels,
}: {
  currentAccountName: string;
  data: WorkloadScopeResponse | undefined;
  entries: WorkloadScopeResponse["entries"];
  labels: TaskGroupPresentationLabels;
}) {
  const topAccounts = useMemo(() => {
    return Object.entries(data?.totalsByAccount ?? {})
      .sort((left, right) => right[1] - left[1])
      .slice(0, 6);
  }, [data?.totalsByAccount]);

  return (
    <div
      aria-label="工作量记录"
      className={styles.historyLayout}
      role="region"
      tabIndex={0}
    >
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
                <span>{getWorkloadRoleLabel(entry.roleKey, labels)}</span>
                <span>{entry.displayName ?? entry.accountId ?? "未记录"}</span>
                <span>{getSettlementStatusLabel(entry.settlementStatus)}</span>
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
    <article className={styles[`metricTile${capitalize(tone)}`]} data-testid="workload-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function WorkflowRail({
  archiveStatus,
  currentNodeKey,
  nodes,
  terminalStatus,
  workflowStatus,
}: {
  archiveStatus: string;
  currentNodeKey: string | null;
  nodes: readonly WorkflowNodeSchema[];
  terminalStatus: string;
  workflowStatus: string;
}) {
  const currentIndex = currentNodeKey
    ? nodes.findIndex((node) => node.nodeKey === currentNodeKey)
    : -1;
  const archiveHasFailed = hasArchiveFailure({ archiveStatus, workflowStatus });
  const approvalIsComplete =
    archiveHasFailed ||
    workflowStatus === terminalStatus ||
    workflowStatus === "archiving" ||
    workflowStatus === "archived" ||
    ["running", "succeeded"].includes(archiveStatus);
  const archiveState =
    archiveHasFailed
      ? "failed"
      : archiveStatus === "succeeded" || workflowStatus === "archived"
        ? "done"
        : archiveStatus === "running" || workflowStatus === "archiving"
          ? "current"
          : "pending";
  const stages = [
    ...nodes.map((node, index) => ({
      key: node.nodeKey,
      label: node.nodeLabel,
      state: approvalIsComplete
        ? "done"
        : index < currentIndex
          ? "done"
          : index === currentIndex
            ? "current"
            : "pending",
    })),
    { key: "archive", label: "归档", state: archiveState },
  ];

  return (
    <ol
      aria-label="任务流程"
      className={styles.flowRail}
      style={{ gridTemplateColumns: `repeat(${Math.max(stages.length, 1)}, minmax(0, 1fr))` }}
    >
      {stages.map((stage) => {
        const state = stage.state;
        const stateLabel = {
          current: "当前",
          done: "已完成",
          failed: "异常",
          pending: "待处理",
        }[state];
        return (
          <li
            aria-current={state === "current" ? "step" : undefined}
            className={styles[`flowNode${capitalize(state)}`]}
            key={stage.key}
          >
            <span aria-hidden="true" className={styles.flowDot} />
            <span>{stage.label}</span>
            <span className={styles.flowStateLabel}>{stateLabel}</span>
          </li>
        );
      })}
    </ol>
  );
}

function AccessibleModal({
  ariaLabel,
  children,
  descriptionId,
  initialFocusRef,
  onClose,
}: {
  ariaLabel: string;
  children: ReactNode;
  descriptionId: string;
  initialFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
}) {
  const modalCardRef = useRef<HTMLDivElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    returnFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    initialFocusRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }

      const modalCard = modalCardRef.current;
      if (!modalCard) {
        return;
      }
      const focusableElements = Array.from(
        modalCard.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => element.getAttribute("aria-hidden") !== "true");
      const firstFocusable = focusableElements[0];
      const lastFocusable = focusableElements[focusableElements.length - 1];
      if (!firstFocusable || !lastFocusable) {
        event.preventDefault();
        modalCard.focus();
        return;
      }
      const activeElement = document.activeElement;
      if (event.shiftKey && (activeElement === firstFocusable || !modalCard.contains(activeElement))) {
        event.preventDefault();
        lastFocusable.focus();
      } else if (
        !event.shiftKey &&
        (activeElement === lastFocusable || !modalCard.contains(activeElement))
      ) {
        event.preventDefault();
        firstFocusable.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      returnFocusRef.current?.focus();
    };
  }, [initialFocusRef]);

  return (
    <div
      aria-describedby={descriptionId}
      aria-label={ariaLabel}
      aria-modal="true"
      className={styles.modalBackdrop}
      role="dialog"
    >
      <div className={styles.modalCard} ref={modalCardRef} tabIndex={-1}>
        {children}
      </div>
    </div>
  );
}

function buildApprovalPreview(item: TaskGroupSummary, inputValue: string) {
  const initialWorkload = item.workload.initialWorkloadA1;
  const appliedFactor = Object.entries(item.workload.nodeFactors).reduce(
    (product, [nodeKey, factor]) => {
      if (nodeKey === item.currentNodeKey) {
        return product;
      }
      const numericFactor = Number(factor);
      return Number.isFinite(numericFactor) ? product * numericFactor : product;
    },
    1,
  );
  const inputFactor = Number.parseFloat(inputValue);
  const hasValidInput = Number.isFinite(inputFactor);
  return {
    initialWorkload,
    appliedFactor,
    inputFactorLabel: hasValidInput ? inputFactor.toFixed(2) : "待输入",
    projectedWorkloadLabel: hasValidInput
      ? `${formatWorkload(initialWorkload * appliedFactor * inputFactor)} A1`
      : "待输入",
  };
}

function resolveErrorMessage(error: unknown, fallback: string) {
  const errorCode =
    typeof error === "object" &&
    error &&
    "detail" in error &&
    typeof (error as { detail?: unknown }).detail === "string"
      ? (error as { detail: string }).detail
      : null;
  return (errorCode && WORKFLOW_ERROR_MESSAGES[errorCode]) || fallback;
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatApprovalFactor(value: number, precision: number) {
  const safePrecision = Math.max(0, Math.trunc(precision));
  return value.toFixed(safePrecision);
}

function formatFactorProduct(value: number) {
  return value.toLocaleString("zh-CN", {
    maximumFractionDigits: 4,
    minimumFractionDigits: 2,
    useGrouping: false,
  });
}
