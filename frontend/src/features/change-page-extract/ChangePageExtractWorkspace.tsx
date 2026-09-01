import { useQueries } from "@tanstack/react-query";
import { startTransition, useState } from "react";

import type { ApiAdapter, CreateBatchPayload, JobSummary } from "../../platform/api/types";
import { TaskConfigModal } from "../../shared/ui/TaskConfigModal";
import styles from "./ChangePageExtractWorkspace.module.css";

type ChangePageExtractWorkspaceProps = {
  adapter: ApiAdapter;
  isOpen: boolean;
  onBatchCreated: (payload: CreateBatchPayload) => void;
  onClose: () => void;
};

const ALLOWED_EXTENSIONS = new Set([".zip", ".rar", ".7z"]);
const MAX_ARCHIVES = 50;
const ACTIVE_STATUSES = new Set(["queued", "running", "cancel_requested"]);

export function ChangePageExtractWorkspace({
  adapter,
  isOpen,
  onBatchCreated,
  onClose,
}: ChangePageExtractWorkspaceProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [submittedJobs, setSubmittedJobs] = useState<JobSummary[]>([]);
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const detailQueries = useQueries({
    queries: submittedJobs.map((job) => ({
      queryKey: ["change-page-extract", job.jobId],
      queryFn: () => adapter.getJobDetail(job.jobId),
      refetchInterval: (query: { state: { data?: { status?: string } } }) =>
        ACTIVE_STATUSES.has(query.state.data?.status ?? job.status) ? 1500 : false,
      retry: 1,
    })),
  });

  if (!isOpen) {
    return null;
  }

  function handleFiles(nextFiles: File[]) {
    setFiles(nextFiles);
    setFormErrors([]);
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors: string[] = [];
    if (files.length === 0) {
      nextErrors.push("请至少选择一个压缩包。");
    }
    if (files.length > MAX_ARCHIVES) {
      nextErrors.push(`一次最多选择 ${MAX_ARCHIVES} 个压缩包。`);
    }
    if (files.some((file) => !ALLOWED_EXTENSIONS.has(getExtension(file.name)))) {
      nextErrors.push("仅支持 ZIP、RAR、7z 压缩包。");
    }
    if (nextErrors.length > 0) {
      setFormErrors(nextErrors);
      return;
    }

    setIsSubmitting(true);
    try {
      const payload = await adapter.createChangePageExtract(files);
      setSubmittedJobs(payload.jobs);
      setFiles([]);
      setFormErrors([]);
      startTransition(() => onBatchCreated(payload));
    } catch (error) {
      setFormErrors(readApiErrors(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <TaskConfigModal title="变更页码提取" onRequestClose={onClose}>
      <div className={styles.workspace}>
        <header className={styles.header}>
          <div>
            <p className={styles.kicker}>Change Page Count</p>
            <h2>变更页码提取</h2>
            <p>上传 ZIP、RAR 或 7z 压缩包，系统会分别统计包内每个 PDF 的页数。</p>
          </div>
          <button className={styles.secondaryButton} type="button" onClick={onClose}>
            关闭
          </button>
        </header>

        <form className={styles.uploadPanel} onSubmit={handleSubmit}>
          <div>
            <h3>选择压缩包</h3>
            <p>一次最多选择 50 个压缩包；每个压缩包独立处理、独立显示结果。</p>
          </div>
          {files.length > 0 ? (
            <ul className={styles.fileList}>
              {files.map((file) => (
                <li key={`${file.name}-${file.size}-${file.lastModified}`}>
                  <span>{file.name}</span>
                  <span>{formatFileSize(file.size)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.emptyState}>尚未选择压缩包。</p>
          )}
          {formErrors.length > 0 ? (
            <div className={styles.errorPanel} role="alert">
              {formErrors.map((error) => (
                <p key={error}>{error}</p>
              ))}
            </div>
          ) : null}
          <div className={styles.actions}>
            <label className={styles.fileButton}>
              选择压缩包
              <input
                accept=".zip,.rar,.7z"
                aria-label="选择变更页码压缩包"
                className={styles.fileInput}
                multiple
                type="file"
                onChange={(event) => {
                  handleFiles(Array.from(event.currentTarget.files ?? []));
                  event.currentTarget.value = "";
                }}
              />
            </label>
            <button
              className={styles.secondaryButton}
              disabled={files.length === 0 || isSubmitting}
              type="button"
              onClick={() => handleFiles([])}
            >
              清空选择
            </button>
            <button className={styles.primaryButton} disabled={isSubmitting} type="submit">
              {isSubmitting ? "正在创建任务" : "开始提取"}
            </button>
          </div>
        </form>

        {submittedJobs.length > 0 ? (
          <section className={styles.results} aria-label="变更页码提取结果">
            <div className={styles.resultsHeader}>
              <h3>提取结果</h3>
              <span>{submittedJobs.length} 个压缩包</span>
            </div>
            <div className={styles.resultList}>
              {submittedJobs.map((job, index) => {
                const detailQuery = detailQueries[index];
                const detail = detailQuery?.data;
                const status = detail?.status ?? job.status;
                const result = detail?.changePageResult;
                const failure = detail?.failureReason || detail?.message;
                return (
                  <article className={styles.resultCard} key={job.jobId}>
                    <div className={styles.resultTitle}>
                      <h4>{job.sourceFilename}</h4>
                      <span data-status={status}>{getStatusLabel(status)}</span>
                    </div>
                    {result ? (
                      <>
                        <div className={styles.resultMeta}>
                          <span>PDF {result.pdfCount} 个</span>
                          <span>合计 {result.totalPages} 页</span>
                        </div>
                        <pre
                          className={styles.resultText}
                          data-testid="change-page-result-text"
                          tabIndex={0}
                        >
                          {result.text}
                        </pre>
                      </>
                    ) : status === "failed" ? (
                      <p className={styles.failureText}>{failure || "压缩包处理失败。"}</p>
                    ) : detailQuery?.isError ? (
                      <p className={styles.failureText}>暂时无法读取任务状态，请稍后重试。</p>
                    ) : (
                      <p className={styles.pendingText}>{detail?.message || "正在等待处理…"}</p>
                    )}
                  </article>
                );
              })}
            </div>
          </section>
        ) : null}
      </div>
    </TaskConfigModal>
  );
}

function getExtension(filename: string) {
  const index = filename.lastIndexOf(".");
  return index >= 0 ? filename.slice(index).toLowerCase() : "";
}

function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function getStatusLabel(status: string) {
  if (status === "succeeded") return "完成";
  if (status === "failed") return "失败";
  if (status === "running") return "处理中";
  if (status === "cancelled") return "已取消";
  return "排队中";
}

function readApiErrors(error: unknown): string[] {
  if (typeof error !== "object" || !error || !("detail" in error)) {
    return ["任务创建失败，请稍后重试。"];
  }
  const detail = (error as {
    detail?: { upload_errors?: Record<string, string[]> } | string | null;
  }).detail;
  if (typeof detail === "string") {
    return [detail];
  }
  const messages = Object.values(detail?.upload_errors ?? {}).flat();
  return messages.length > 0 ? messages : ["任务创建失败，请检查压缩包后重试。"];
}
