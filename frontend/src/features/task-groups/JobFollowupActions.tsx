import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { TaskGroupConflictDialog } from "../../app/TaskGroupConflictDialog";
import type {
  ApiAdapter,
  ApiError,
  JobRetryResult,
  JobWorkloadSubmission,
  JobWorkloadSubmitPayload,
} from "../../platform/api/types";
import { useSession } from "../../shared/session/SessionContext";
import { TaskConfigModal } from "../../shared/ui/TaskConfigModal";
import { TaskGroupWorkflowPanel } from "./TaskGroupWorkflowPanel";
import styles from "./JobFollowupActions.module.css";

type DialogAction = "submit" | "cancel" | "retry";
const EMPTY_FLAGS = { overwriteArchiveExisting: false, cancelExistingInProgress: false };

export function JobFollowupActions({
  adapter,
  jobId,
  onOpenWorkload,
  onOpenJob,
}: {
  adapter: ApiAdapter;
  jobId: string;
  onOpenWorkload: () => void;
  onOpenJob: (jobId: string) => void;
}) {
  const client = useQueryClient();
  const { refreshCurrentAccount } = useSession();
  const [dialog, setDialog] = useState<DialogAction | null>(null);
  const [conflict, setConflict] = useState<"archive" | "duplicate" | null>(null);
  const [personnel, setPersonnel] = useState<Record<string, string>>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [retryResult, setRetryResult] = useState<JobRetryResult | null>(null);
  const flags = useRef({ ...EMPTY_FLAGS });
  const inFlight = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const preview = useQuery({
    queryKey: ["job-workload-submission", jobId],
    queryFn: () => adapter.getJobWorkloadSubmission!(jobId),
    enabled: Boolean(adapter.getJobWorkloadSubmission),
    retry: false,
    refetchInterval: 12000,
  });
  const execution = useQuery({
    queryKey: ["job-execution-actions", jobId],
    queryFn: () => adapter.getJobExecutionActions!(jobId),
    enabled: Boolean(adapter.getJobExecutionActions),
    retry: false,
    refetchInterval: 12000,
  });
  const availability = preview.data;
  const actions = execution.data;
  const hasWorkflow = Boolean(availability && availability.workflowStatus !== "draft");

  function openDialog(action: DialogAction) {
    if (inFlight.current) return;
    setError(null);
    setFieldErrors({});
    if (action === "submit") {
      setPersonnel(Object.fromEntries((availability?.personnelFields ?? []).map((field) => [field.key, field.value])));
      flags.current = { ...EMPTY_FLAGS };
    }
    setDialog(action);
  }

  async function refreshViews() {
    await Promise.allSettled([
      ...["job-detail", "job-workload-submission", "job-execution-actions", "jobs", "jobs-activity", "task-groups", "task-group-detail", "workflow", "workload"]
        .map((key) => client.invalidateQueries({ queryKey: [key] })),
      refreshCurrentAccount(),
    ]);
  }

  async function execute(action: DialogAction) {
    if (inFlight.current) return;
    if (action === "submit") {
      const missing = Object.fromEntries((availability?.personnelFields ?? [])
        .filter((field) => field.required && !personnel[field.key]?.trim())
        .map((field) => [field.key, `请填写${field.label}`]));
      setFieldErrors(missing);
      if (Object.keys(missing).length > 0) return;
    }
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      if (action === "submit") {
        if (!adapter.submitJobWorkload) throw new Error("工作量提交服务不可用，请刷新后重试。");
        const payload: JobWorkloadSubmitPayload = { personnel, ...flags.current };
        const group = await adapter.submitJobWorkload(jobId, payload);
        client.setQueryData(["task-group-detail", group.groupId], group);
        client.setQueryData<JobWorkloadSubmission>(["job-workload-submission", jobId], (previous) => previous ? {
          ...previous, group, groupId: group.groupId, workflowStatus: group.workflowStatus, canSubmit: false, blockers: [],
        } : previous);
        if (mounted.current) setFeedback("工作量填报已提交，审批待办已同步至工作量模块。");
      } else if (action === "cancel") {
        if (!adapter.cancelJob) throw new Error("任务取消服务不可用，请刷新后重试。");
        const updated = await adapter.cancelJob(jobId);
        client.setQueryData(["job-execution-actions", jobId], updated);
        if (mounted.current) setFeedback("取消请求已提交，正在等待任务安全停止；原有产物和诊断记录会保留。");
      } else {
        if (!adapter.retryJob) throw new Error("任务重试服务不可用，请刷新后重试。");
        const result = await adapter.retryJob(jobId);
        if (mounted.current) {
          setRetryResult(result);
          setFeedback("已创建新的重试任务，原任务和错误记录保持不变。");
        }
      }
      if (mounted.current) { setDialog(null); setConflict(null); }
      await refreshViews();
    } catch (caught) {
      if (!mounted.current) return;
      const apiError = caught as ApiError;
      const detail = apiError?.detail;
      if (action === "submit" && apiError?.status === 422 && typeof detail === "string" &&
        (detail.includes("archive_target_exists") || detail.includes("duplicate_in_progress_exists"))) {
        setDialog(null);
        setConflict(detail.includes("archive_target_exists") ? "archive" : "duplicate");
      } else {
        if (detail && typeof detail === "object" && "field_errors" in detail) setFieldErrors(detail.field_errors ?? {});
        setError(actionErrorMessage(caught, action));
        if (action === "submit") { setConflict(null); setDialog("submit"); }
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <section aria-label="后续动作" className={styles.panel}>
      <header className={styles.header}>
        <h2>后续动作</h2>
        <p>生成与审批独立；确认提交后，才启动工作量填报流程。</p>
      </header>
      {preview.isLoading ? <p role="status">正在读取工作量提交条件…</p> : null}
      {preview.isError || !adapter.getJobWorkloadSubmission ? (
        <p role="alert" className={styles.error}>工作量信息暂时无法加载，任务产物仍可正常查看和下载。</p>
      ) : null}
      {availability?.group && hasWorkflow ? (
        <TaskGroupWorkflowPanel
          adapter={adapter}
          groupId={availability.group.groupId}
          detail={availability.group}
          allowSubmission={false}
        />
      ) : null}
      {availability && !hasWorkflow ? (
        <div className={styles.workloadAction}>
          <div>
            <strong>工作量填报</strong>
            {availability.initialWorkloadA1 !== null ? <p>识别工作量基数：{availability.initialWorkloadA1} A1</p> : null}
            {availability.blockers.length > 0 ? (
              <ul>{availability.blockers.map((blocker) => <li key={blocker.code}>{blocker.message}</li>)}</ul>
            ) : <p>确认审批人员后，将依次进入一审、二审、三审与归档结算。</p>}
          </div>
          {availability.supported ? (
            <button
              className={styles.primary}
              type="button"
              disabled={!availability.canSubmit || busy || preview.isError}
              onClick={() => openDialog("submit")}
            >提交工作量填报</button>
          ) : null}
        </div>
      ) : null}
      <div className={styles.actions}>
        {hasWorkflow ? (
          <button className={styles.primary} type="button" onClick={onOpenWorkload}>查看工作量流程</button>
        ) : null}
        {actions ? (
          <>
            <div className={styles.actionItem}>
              <button type="button" disabled={!actions.canCancel || busy || execution.isError} onClick={() => openDialog("cancel")}>
                {actions.cancelRequested ? "正在安全取消…" : "取消任务"}
              </button>
              <small>{!actions.canCancel ? actions.cancelReason : "在安全检查点停止，不删除原有产物"}</small>
            </div>
            <div className={styles.actionItem}>
              <button type="button" disabled={!actions.canRetry || busy || execution.isError || Boolean(retryResult)} onClick={() => openDialog("retry")}>
                重试任务
              </button>
              <small>{!actions.canRetry ? actions.retryReason : "创建新任务，保留本次错误记录"}</small>
            </div>
          </>
        ) : null}
        {retryResult ? (
          <button type="button" onClick={() => onOpenJob(retryResult.groupId ?? retryResult.jobId)}>查看重试任务</button>
        ) : null}
      </div>
      {execution.isError ? <p role="alert" className={styles.error}>任务执行状态暂时无法加载，取消与重试已暂停。请稍后刷新。</p> : null}
      {feedback ? <p role="status" className={styles.success}>{feedback}</p> : null}
      {error && !dialog && !conflict ? <p role="alert" className={styles.error}>{error}</p> : null}
      {dialog ? (
        <TaskConfigModal
          title={dialog === "submit" ? "提交工作量填报" : dialog === "cancel" ? "取消任务确认" : "重试任务确认"}
          dialogClassName={styles.dialog}
          onRequestClose={busy ? undefined : () => setDialog(null)}
        >
          <form onSubmit={(event) => { event.preventDefault(); void execute(dialog); }} noValidate>
            <header><h2>{dialog === "submit" ? "提交工作量填报" : dialog === "cancel" ? "取消任务确认" : "重试任务确认"}</h2></header>
            {dialog === "submit" ? (
              <>
                <div className={styles.amount}>
                  <span>识别工作量基数</span>
                  <strong>{availability?.initialWorkloadA1 ?? "待确认"} A1</strong>
                </div>
                <p>请核对审批人员，填写“姓名@账号”。仅用于审批流程，不修改原始 IED 文件。</p>
                <div className={styles.fields}>
                  {availability?.personnelFields.map((field) => (
                    <label key={field.key} htmlFor={`workload-${field.key}`}>
                      <span>{field.label}{field.required ? <em>必填</em> : null}</span>
                      <input
                        id={`workload-${field.key}`}
                        value={personnel[field.key] ?? ""}
                        disabled={busy}
                        required={field.required}
                        placeholder="例如：张三@zhangsan"
                        autoComplete="off"
                        aria-invalid={Boolean(fieldErrors[field.key])}
                        aria-describedby={fieldErrors[field.key] ? `workload-error-${field.key}` : undefined}
                        onChange={(event) => {
                          setPersonnel((previous) => ({ ...previous, [field.key]: event.target.value }));
                          setFieldErrors((previous) => ({ ...previous, [field.key]: "" }));
                        }}
                      />
                      {fieldErrors[field.key] ? (
                        <small id={`workload-error-${field.key}`} className={styles.error}>{fieldErrors[field.key]}</small>
                      ) : null}
                    </label>
                  ))}
                </div>
              </>
            ) : (
              <p>{dialog === "cancel"
                ? "确认停止本次任务？系统会在安全检查点取消，保留已有产物和错误记录。此操作不会取消已启动的审批。"
                : "确认使用原始输入重新执行？系统将创建新任务，不覆盖当前任务及诊断记录。"}</p>
            )}
            {error ? <p role="alert" className={styles.error}>{error}</p> : null}
            <footer className={styles.dialogFooter}>
              <button type="button" disabled={busy} onClick={() => setDialog(null)}>返回</button>
              <button className={styles.primary} type="submit" disabled={busy}>
                {busy ? "正在处理…" : dialog === "submit" ? "确认并提交" : dialog === "cancel" ? "确认取消任务" : "确认重试"}
              </button>
            </footer>
          </form>
        </TaskConfigModal>
      ) : null}
      {conflict ? (
        <TaskGroupConflictDialog
          kind={conflict}
          onClose={() => {
            if (!busy) { setConflict(null); setDialog("submit"); }
          }}
          onConfirm={() => {
            if (busy) return;
            flags.current = {
              ...flags.current,
              ...(conflict === "archive" ? { overwriteArchiveExisting: true } : { cancelExistingInProgress: true }),
            };
            setConflict(null);
            void execute("submit");
          }}
        />
      ) : null}
    </section>
  );
}

function actionErrorMessage(error: unknown, action: DialogAction): string {
  const api = error as ApiError;
  if (api?.status === 403) return action === "submit" ? "当前账号无权提交此任务，请使用任务创建人账号。" : "当前账号无权操作此任务，请联系任务创建人或管理员。";
  if (api?.status === 409) return "任务状态已变化，请刷新详情后再操作。";
  if (api?.detail && typeof api.detail === "object") return api.detail.message ?? "请修正标红的审批人员信息后重新提交。";
  if (typeof api?.detail === "string" && /[\u4e00-\u9fff]/.test(api.detail)) return api.detail;
  if (error instanceof Error && /[\u4e00-\u9fff]/.test(error.message)) return error.message;
  return "操作未完成，请刷新查看最新任务状态后重试；如仍失败，请联系管理员查看日志。";
}
