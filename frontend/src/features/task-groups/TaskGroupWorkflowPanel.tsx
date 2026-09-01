import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { TaskGroupConflictDialog } from "../../app/TaskGroupConflictDialog";
import type {
  ApiAdapter,
  ApiError,
  TaskGroupDetail,
  TaskGroupSubmitPayload,
} from "../../platform/api/types";
import { useSession } from "../../shared/session/SessionContext";
import styles from "./TaskGroupWorkflowPanel.module.css";

type ConflictKind = "archive" | "duplicate";

const EMPTY_SUBMIT_FLAGS: TaskGroupSubmitPayload = {
  overwriteArchiveExisting: false,
  cancelExistingInProgress: false,
};

const UNKNOWN_STATUS_LABEL = "未知状态";
const UNKNOWN_BLOCKER_LABEL = "存在未识别的提交条件，请联系管理员处理。";

const BLOCKER_LABELS: Record<string, string> = {
  workflow_not_draft: "审批流程已经启动，不能重复提交",
  task_group_not_succeeded: "任务包尚未生成完成",
  task_group_children_missing: "任务包内没有可提交的子任务",
  task_group_child_not_found: "任务包中的子任务记录缺失",
  task_group_child_not_succeeded: "任务包中仍有子任务未完成",
  shared_prep_invalid: "共享预处理数据无效或不完整",
  shared_prep_source_missing: "共享预处理源文件不存在",
  shared_prep_source_outside: "共享预处理源文件不在任务包目录内",
  deliverable_main_missing: "任务包缺少主交付任务",
  deliverable_main_duplicate: "任务包包含多个主交付任务",
  deliverable_package_not_declared: "主交付任务未登记交付压缩包",
  deliverable_package_not_found: "交付压缩包文件不存在",
  deliverable_ied_not_declared: "任务要求 IED 时未登记 IED 文件",
  deliverable_ied_not_found: "任务要求的 IED 文件不存在",
};

const WORKFLOW_LABELS: Record<string, string> = {
  draft: "待提交",
  submitted: "已提交",
  in_review: "审批中",
  three_review_approved: "三审通过",
  archiving: "归档中",
  archived: "已归档",
  archive_failed: "归档失败",
  cancelled: "已取消",
};

const ARCHIVE_LABELS: Record<string, string> = {
  pending: "待归档",
  running: "归档中",
  succeeded: "已归档",
  failed: "归档失败",
};

const NODE_STATUS_LABELS: Record<string, string> = {
  pending: "待处理",
  current: "当前节点",
  approved: "已通过",
  cancelled: "已取消",
};

export function TaskGroupWorkflowPanel({
  adapter,
  groupId,
}: {
  adapter: ApiAdapter;
  groupId: string;
}) {
  const queryClient = useQueryClient();
  const { currentAccount, refreshCurrentAccount } = useSession();
  const submitButtonRef = useRef<HTMLButtonElement>(null);
  const activeGroupIdRef = useRef<string | null>(null);
  const submissionGenerationRef = useRef(0);
  const submissionInFlightRef = useRef(false);
  const confirmedFlagsRef = useRef<TaskGroupSubmitPayload>({ ...EMPTY_SUBMIT_FLAGS });
  const [conflict, setConflict] = useState<ConflictKind | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    activeGroupIdRef.current = groupId;
    submissionGenerationRef.current += 1;
    submissionInFlightRef.current = false;
    confirmedFlagsRef.current = { ...EMPTY_SUBMIT_FLAGS };
    setConflict(null);
    setIsSubmitting(false);
    setFeedback(null);
    setSubmitError(null);

    return () => {
      if (activeGroupIdRef.current === groupId) {
        activeGroupIdRef.current = null;
      }
      submissionGenerationRef.current += 1;
      submissionInFlightRef.current = false;
    };
  }, [groupId]);

  const detailQuery = useQuery({
    queryKey: ["task-group-detail", groupId],
    queryFn: async () => {
      if (!adapter.getTaskGroupDetail) {
        throw new Error("task-group management unavailable");
      }
      return adapter.getTaskGroupDetail(groupId);
    },
    enabled: Boolean(groupId),
    retry: false,
  });

  const restoreSubmitFocus = useCallback(() => {
    window.setTimeout(() => submitButtonRef.current?.focus(), 0);
  }, []);

  const closeConflict = useCallback(() => {
    setConflict(null);
    restoreSubmitFocus();
  }, [restoreSubmitFocus]);

  async function refreshDependentViews(updated: TaskGroupDetail, requestGroupId: string) {
    queryClient.setQueryData(["task-group-detail", requestGroupId], updated);
    await Promise.allSettled([
      queryClient.invalidateQueries({ queryKey: ["job-detail", requestGroupId] }),
      queryClient.invalidateQueries({ queryKey: ["jobs"] }),
      queryClient.invalidateQueries({ queryKey: ["jobs-activity"] }),
      queryClient.invalidateQueries({ queryKey: ["task-groups"] }),
      queryClient.invalidateQueries({ queryKey: ["workflow", "monitor"] }),
      queryClient.invalidateQueries({ queryKey: ["workload"] }),
      refreshCurrentAccount(),
    ]);
  }

  async function executeSubmission(
    payload: TaskGroupSubmitPayload,
    useRestart: boolean,
  ) {
    if (submissionInFlightRef.current) {
      return;
    }
    const requestGroupId = groupId;
    const requestGeneration = submissionGenerationRef.current;
    const isCurrentRequest = () =>
      activeGroupIdRef.current === requestGroupId &&
      submissionGenerationRef.current === requestGeneration;

    submissionInFlightRef.current = true;
    setIsSubmitting(true);
    setFeedback(null);
    setSubmitError(null);
    try {
      let updated: TaskGroupDetail;
      if (useRestart) {
        if (!adapter.restartSubmitTaskGroup) {
          throw new Error("restart submission unavailable");
        }
        updated = await adapter.restartSubmitTaskGroup(requestGroupId, payload);
      } else {
        if (!adapter.submitTaskGroup) {
          throw new Error("submission unavailable");
        }
        updated = await adapter.submitTaskGroup(requestGroupId, payload);
      }
      if (!isCurrentRequest()) {
        return;
      }
      setConflict(null);
      await refreshDependentViews(updated, requestGroupId);
      if (!isCurrentRequest()) {
        return;
      }
      setFeedback("审批流程已提交。");
    } catch (error) {
      if (!isCurrentRequest()) {
        return;
      }
      const nextConflict = readConflictKind(error);
      if (nextConflict) {
        setConflict(nextConflict);
      } else {
        setConflict(null);
        setSubmitError(readErrorMessage());
        restoreSubmitFocus();
      }
    } finally {
      if (isCurrentRequest()) {
        submissionInFlightRef.current = false;
        setIsSubmitting(false);
      }
    }
  }

  function handleInitialSubmit() {
    if (submissionInFlightRef.current) {
      return;
    }
    const flags = { ...EMPTY_SUBMIT_FLAGS };
    confirmedFlagsRef.current = flags;
    void executeSubmission(flags, false);
  }

  function handleConflictConfirm() {
    if (!conflict || submissionInFlightRef.current) {
      return;
    }
    const nextFlags = {
      ...confirmedFlagsRef.current,
      ...(conflict === "archive"
        ? { overwriteArchiveExisting: true }
        : { cancelExistingInProgress: true }),
    };
    confirmedFlagsRef.current = nextFlags;
    setConflict(null);
    void executeSubmission(nextFlags, true);
  }

  if (detailQuery.isLoading) {
    return (
      <section aria-label="审批与归档" className={styles.panel}>
        <p className={styles.loading} role="status">正在读取审批状态…</p>
      </section>
    );
  }

  if (detailQuery.isError || !detailQuery.data) {
    return (
      <section
        aria-label="审批与归档"
        className={`${styles.panel} ${styles.errorPanel}`}
        role="alert"
      >
        <strong>审批信息暂时无法加载，任务产物仍可正常查看。</strong>
        <span>可稍后刷新页面重试，不影响下方产物下载。</span>
      </section>
    );
  }

  const detail = detailQuery.data;
  const isCreator =
    !detail.creatorAccount || detail.creatorAccount === currentAccount?.accountId;
  const blockers = detail.submitBlockers ?? [];
  const currentNode = detail.workflow.nodes.find(
    (node) => node.nodeKey === detail.currentNodeKey,
  );

  return (
    <section aria-label="审批与归档" className={styles.panel}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>WORKFLOW CONTROL</p>
          <h2>审批与归档</h2>
        </div>
        <div className={styles.statusLine} aria-label="当前管理状态">
          <StatusItem
            label="审批"
            value={WORKFLOW_LABELS[detail.workflowStatus] ?? UNKNOWN_STATUS_LABEL}
          />
          <StatusItem
            label="当前节点"
            value={
              currentNode?.nodeLabel ??
              (detail.currentNodeKey ? "未知节点" : "未进入审批")
            }
          />
          <StatusItem
            label="归档"
            value={ARCHIVE_LABELS[detail.archiveStatus] ?? UNKNOWN_STATUS_LABEL}
          />
        </div>
      </header>

      {detail.workflow.nodes.length > 0 ? (
        <ol className={styles.nodeList} aria-label="审批节点">
          {detail.workflow.nodes.map((node) => (
            <li
              key={node.nodeKey}
              aria-current={node.nodeKey === detail.currentNodeKey ? "step" : undefined}
              data-current={node.nodeKey === detail.currentNodeKey}
            >
              <span>{node.nodeLabel}</span>
              <strong>{NODE_STATUS_LABELS[node.status] ?? UNKNOWN_STATUS_LABEL}</strong>
              <small>{node.assigneeName ?? "待分配"}</small>
            </li>
          ))}
        </ol>
      ) : null}

      <div className={styles.actionRow}>
        <div className={styles.guidance} aria-live="polite">
          {!isCreator ? (
            <p>
              仅任务创建人 {detail.creatorName ?? "未知"}（{detail.creatorAccount ?? "未记录"}）可以提交审批。
            </p>
          ) : blockers.length > 0 ? (
            <div>
              <strong>提交前仍需处理</strong>
              <ul>
                {blockers.map((code) => (
                  <li key={code}>{BLOCKER_LABELS[code] ?? UNKNOWN_BLOCKER_LABEL}</li>
                ))}
              </ul>
            </div>
          ) : detail.canSubmit ? (
            <p>任务产物与人员信息已就绪，可发起审批。</p>
          ) : (
            <p>当前流程状态不允许再次提交。</p>
          )}
          {feedback ? <p className={styles.success}>{feedback}</p> : null}
          {submitError ? (
            <p className={styles.submitError} role="alert">{submitError}</p>
          ) : null}
        </div>

        {isCreator ? (
          <button
            ref={submitButtonRef}
            className={styles.submitButton}
            disabled={!detail.canSubmit || blockers.length > 0 || isSubmitting}
            type="button"
            onClick={handleInitialSubmit}
          >
            {isSubmitting ? "正在提交…" : "提交审批"}
          </button>
        ) : null}
      </div>

      {conflict ? (
        <TaskGroupConflictDialog
          kind={conflict}
          onClose={closeConflict}
          onConfirm={handleConflictConfirm}
        />
      ) : null}
    </section>
  );
}

function StatusItem({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.statusItem}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function readConflictKind(error: unknown): ConflictKind | null {
  if (!isApiError(error) || error.status !== 422 || typeof error.detail !== "string") {
    return null;
  }
  if (error.detail.includes("archive_target_exists")) {
    return "archive";
  }
  if (error.detail.includes("duplicate_in_progress_exists")) {
    return "duplicate";
  }
  return null;
}

function readErrorMessage() {
  return "提交失败，服务器未能完成审批请求，请稍后重试。";
}

function isApiError(error: unknown): error is ApiError {
  return Boolean(
    error &&
      typeof error === "object" &&
      typeof (error as { status?: unknown }).status === "number" &&
      "detail" in error,
  );
}
