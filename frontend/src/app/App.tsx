import "@fontsource/noto-sans-sc/400.css";
import "@fontsource/noto-sans-sc/500.css";
import "@fontsource/noto-sans-sc/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/700.css";
import "@fontsource/rajdhani/500.css";
import "@fontsource/rajdhani/700.css";

import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  BrowserRouter,
  Link,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";

import { AuditCheckSummaryModal } from "../features/audit-check/AuditCheckSummaryModal";
import { AuditCheckWorkspace } from "../features/audit-check/AuditCheckWorkspace";
import { DeliverableWorkspace } from "../features/deliverable/DeliverableWorkspace";
import type { CreateBatchPayload, JobDetail, JobList, JobSummary, TaskKind } from "../platform/api/types";
import { useApiAdapter } from "../platform/api/useApiAdapter";
import "../shared/global.css";
import styles from "./App.module.css";

const ACTIVE_JOB_STATUSES = ["queued", "running", "cancel_requested"] as const;

const JOB_STATUS_FILTERS: Array<{ label: string; value?: string }> = [
  { label: "全部" },
  { label: "排队中", value: "queued" },
  { label: "运行中", value: "running" },
  { label: "成功", value: "succeeded" },
  { label: "失败", value: "failed" },
];

const STATUS_META: Record<string, { label: string; tone: string }> = {
  queued: { label: "排队中", tone: "queued" },
  running: { label: "运行中", tone: "running" },
  cancel_requested: { label: "取消中", tone: "queued" },
  cancelled: { label: "已取消", tone: "default" },
  succeeded: { label: "成功", tone: "succeeded" },
  failed: { label: "失败", tone: "failed" },
};

export function App() {
  const [queryClient] = useState(() => new QueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter
        future={{
          v7_relativeSplatPath: true,
          v7_startTransition: true,
        }}
      >
        <Routes>
          <Route element={<WorkspacePage />} path="/" />
          <Route element={<JobDetailPage />} path="/jobs/:jobId" />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

function WorkspacePage() {
  const adapter = useApiAdapter();
  const reactQueryClient = useQueryClient();
  const deliverableFileInputRef = useRef<HTMLInputElement | null>(null);
  const knownJobStatusesRef = useRef<Map<string, string> | null>(null);
  const notifiedAuditJobIdsRef = useRef<Set<string>>(new Set());

  const [jobsStatusFilter, setJobsStatusFilter] = useState<string | undefined>();
  const [highlightedBatchId, setHighlightedBatchId] = useState<string | null>(null);

  const [deliverableConfigOpen, setDeliverableConfigOpen] = useState(false);
  const [deliverableDraftAvailable, setDeliverableDraftAvailable] = useState(false);
  const [incomingFiles, setIncomingFiles] = useState<File[]>([]);

  const [auditConfigOpen, setAuditConfigOpen] = useState(false);
  const [auditDraftAvailable, setAuditDraftAvailable] = useState(false);
  const [auditSummaryQueue, setAuditSummaryQueue] = useState<JobDetail[]>([]);
  const [auditNotice, setAuditNotice] = useState<string | null>(null);

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: () => adapter.getHealth(),
    refetchInterval: 15000,
  });

  const schemaQuery = useQuery({
    queryKey: ["form-schema"],
    queryFn: () => adapter.getFormSchema(),
    staleTime: 60000,
  });

  const jobsQuery = useQuery({
    queryKey: ["jobs", jobsStatusFilter ?? "all"],
    queryFn: () => adapter.listJobs(jobsStatusFilter),
    refetchInterval: (query) => {
      const items = ((query.state.data as JobList | undefined)?.items ?? []);
      const hasActive = items.some((item) => ACTIVE_JOB_STATUSES.includes(item.status as never));
      return hasActive ? 3000 : 12000;
    },
  });

  const jobPackages = useMemo(
    () => buildJobPackages(jobsQuery.data?.items ?? []),
    [jobsQuery.data?.items],
  );

  useEffect(() => {
    const items = jobsQuery.data?.items;
    if (!items) {
      return;
    }

    const currentStatuses = new Map(items.map((job) => [job.jobId, job.status]));
    const previousStatuses = knownJobStatusesRef.current;
    knownJobStatusesRef.current = currentStatuses;

    if (!previousStatuses) {
      return;
    }

    const completedAuditJobs = items.filter((job) => {
      const previousStatus = previousStatuses.get(job.jobId);
      return (
        job.taskKind === "audit_check" &&
        previousStatus !== undefined &&
        ACTIVE_JOB_STATUSES.includes(previousStatus as never) &&
        job.status === "succeeded" &&
        !notifiedAuditJobIdsRef.current.has(job.jobId)
      );
    });

    if (completedAuditJobs.length === 0) {
      return;
    }

    completedAuditJobs.forEach((job) => {
      notifiedAuditJobIdsRef.current.add(job.jobId);
    });

    let active = true;

    void (async () => {
      const summaries: JobDetail[] = [];
      const passedWithoutFindings: string[] = [];

      for (const job of completedAuditJobs) {
        if (job.findingsCount > 0) {
          try {
            const detail = await adapter.getJobDetail(job.jobId);
            if (detail.taskKind === "audit_check") {
              summaries.push(detail);
            }
          } catch {
            // keep the session moving; list polling will continue and the user can open detail manually
          }
          continue;
        }

        passedWithoutFindings.push(job.sourceFilename);
      }

      if (!active) {
        return;
      }

      if (summaries.length > 0) {
        setAuditSummaryQueue((current) => [...current, ...summaries]);
      }

      if (passedWithoutFindings.length > 0) {
        setAuditNotice(`纠错任务已完成，未发现问题：${passedWithoutFindings.join("、")}`);
      }
    })();

    return () => {
      active = false;
    };
  }, [adapter, jobsQuery.data]);

  function handleBatchCreated(payload: CreateBatchPayload) {
    setHighlightedBatchId(payload.batchId);
    setDeliverableConfigOpen(false);
    setAuditConfigOpen(false);
    void reactQueryClient.invalidateQueries({ queryKey: ["jobs"] });
  }

  function handleDeliverableUploadClick() {
    deliverableFileInputRef.current?.click();
  }

  function handleDeliverableFileSelection(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (files.length === 0 || !schemaQuery.data) {
      event.currentTarget.value = "";
      return;
    }

    setIncomingFiles(files);
    setDeliverableConfigOpen(true);
    event.currentTarget.value = "";
  }

  const activeAuditSummary = auditSummaryQueue[0] ?? null;

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div>
          <p className={styles.brandTop}>CNPE Drawing Desk</p>
          <h1>图纸处理工作台</h1>
          <p className={styles.brandBody}>
            当前主线已经把出图和纠错接到同一个工作台里。出图继续走任务配置弹窗，纠错使用独立配置弹窗。
          </p>
        </div>

        <section className={styles.healthCard}>
          <h2>系统状态</h2>
          {healthQuery.data ? (
            <dl className={styles.healthGrid}>
              <StatRow label="服务" value={healthQuery.data.ready ? "可用" : "异常"} />
              <StatRow label="存储" value={healthQuery.data.storageWritable ? "可写" : "不可写"} />
              <StatRow label="队列" value={`${healthQuery.data.queueDepth} 项`} />
              <StatRow label="AutoCAD" value={healthQuery.data.autocadReady ? "就绪" : "缺失"} />
              <StatRow label="Office" value={healthQuery.data.officeReady ? "就绪" : "缺失"} />
            </dl>
          ) : (
            <p className={styles.muted}>正在读取系统状态…</p>
          )}
        </section>
      </aside>

      <main className={styles.mainColumn}>
        <section className={styles.controlPanel}>
          <div>
            <p className={styles.brandTop}>Task Entry</p>
            <h2>新建任务</h2>
            <p className={styles.brandBody}>
              出图继续从系统文件选择器进入；纠错从独立弹窗进入，表单只保留项目号和 DWG 上传。
            </p>
          </div>

          <div className={styles.uploadActions}>
            <button
              className={styles.primaryActionButton}
              disabled={!schemaQuery.data}
              type="button"
              onClick={handleDeliverableUploadClick}
            >
              出图
            </button>
            <button
              className={styles.primaryActionButton}
              disabled={!schemaQuery.data}
              type="button"
              onClick={() => setAuditConfigOpen(true)}
            >
              {auditDraftAvailable ? "继续纠错" : "纠错"}
            </button>
            {deliverableDraftAvailable ? (
              <button
                className={styles.secondaryActionButton}
                type="button"
                onClick={() => setDeliverableConfigOpen(true)}
              >
                继续草稿
              </button>
            ) : null}
          </div>

          <input
            ref={deliverableFileInputRef}
            accept=".dwg"
            aria-label="选择出图 DWG 文件"
            className={styles.hiddenFileInput}
            multiple
            type="file"
            onChange={handleDeliverableFileSelection}
          />

          <div className={styles.entryHint}>
            <span>真实可提交：交付处理、纠错</span>
            <span>仍未开放：翻版真实提交</span>
            <span>草稿策略：关闭保留，提交成功或清空后重置</span>
          </div>

          {auditNotice ? (
            <div className={styles.noticeBanner}>
              <span>{auditNotice}</span>
              <button className={styles.noticeClose} type="button" onClick={() => setAuditNotice(null)}>
                关闭
              </button>
            </div>
          ) : null}
        </section>
      </main>

      <aside className={styles.jobsColumn}>
        <header className={styles.jobsHeader}>
          <div>
            <p className={styles.brandTop}>Recent Jobs</p>
            <h2>最近任务</h2>
          </div>
          <button className={styles.subtleButton} type="button" onClick={() => jobsQuery.refetch()}>
            刷新
          </button>
        </header>

        <div className={styles.filterRow}>
          {JOB_STATUS_FILTERS.map((filter) => {
            const active = (jobsStatusFilter ?? "") === (filter.value ?? "");
            return (
              <button
                key={filter.label}
                className={`${styles.filterButton} ${active ? styles.filterButtonActive : ""}`}
                type="button"
                onClick={() => setJobsStatusFilter(filter.value)}
              >
                {filter.label}
              </button>
            );
          })}
        </div>

        <div className={styles.jobsPanel}>
          {jobPackages.length ? (
            jobPackages.map((jobPackage) => {
              const job = jobPackage.jobs[0]!;
              return (
                <div
                className={`${styles.jobCard} ${
                  jobPackage.batchId && jobPackage.batchId === highlightedBatchId
                    ? styles.jobCardHighlight
                    : ""
                }`}
                key={jobPackage.packageKey}
              >
                <div className={styles.jobCardHeader}>
                  <strong>{jobPackage.sourceFilename}</strong>
                  <StatusPill status={jobPackage.status} />
                </div>
                <p className={styles.packageMeta}>包含 {jobPackage.jobs.length} 个子任务</p>
                <div className={styles.jobMetaRow}>
                  <TaskKindBadge kind={job.taskKind} />
                  {job.taskKind === "audit_check" ? (
                    <span className={styles.jobMetric}>
                      错误数 {job.findingsCount}
                    </span>
                  ) : null}
                  {job.taskKind === "audit_check" ? (
                    <span className={styles.jobMetric}>
                      受影响图纸 {job.affectedDrawingsCount}
                    </span>
                  ) : null}
                </div>
                <p className={styles.jobStage}>{job.stage ?? "queued"}</p>
                <p className={styles.jobMessage}>{job.message || "等待处理中"}</p>
                <div className={styles.packageTaskList}>
                  {jobPackage.jobs.map((subtask) => (
                    <Link className={styles.subtaskLink} key={subtask.jobId} to={`/jobs/${subtask.jobId}`}>
                      <TaskKindBadge kind={subtask.taskKind} />
                      <span className={styles.subtaskStatus}>{statusLabel(subtask.status)}</span>
                    </Link>
                  ))}
                </div>
                <div className={styles.progressBar}>
                  <div style={{ width: `${job.percent}%` }} />
                </div>
                </div>
              );
            })
          ) : (
            <div className={styles.emptyPanel}>
              <p>当前没有任务记录。</p>
            </div>
          )}
        </div>
      </aside>

      {schemaQuery.data ? (
        <>
        <DeliverableWorkspace
          adapter={adapter}
          incomingFiles={incomingFiles}
          isOpen={deliverableConfigOpen}
          onBatchCreated={handleBatchCreated}
          onNotice={setAuditNotice}
          onClose={() => setDeliverableConfigOpen(false)}
          onDraftAvailabilityChange={setDeliverableDraftAvailable}
          schema={schemaQuery.data}
          />
          <AuditCheckWorkspace
            adapter={adapter}
            isOpen={auditConfigOpen}
            onBatchCreated={handleBatchCreated}
            onClose={() => setAuditConfigOpen(false)}
            onDraftAvailabilityChange={setAuditDraftAvailable}
            schema={schemaQuery.data}
          />
        </>
      ) : null}

      {activeAuditSummary ? (
        <AuditCheckSummaryModal
          job={activeAuditSummary}
          onClose={() =>
            setAuditSummaryQueue((current) => current.slice(1))
          }
        />
      ) : null}
    </div>
  );
}

function JobDetailPage() {
  const adapter = useApiAdapter();
  const navigate = useNavigate();
  const params = useParams();

  const detailQuery = useQuery({
    queryKey: ["job-detail", params.jobId],
    queryFn: () => adapter.getJobDetail(params.jobId ?? ""),
    enabled: Boolean(params.jobId),
    refetchInterval: (query) => {
      const data = query.state.data as JobDetail | undefined;
      return data && ACTIVE_JOB_STATUSES.includes(data.status as never) ? 3000 : 12000;
    },
  });

  const detail = detailQuery.data;
  const hasWarnings = Boolean(detail && (detail.flags.length > 0 || detail.errors.length > 0));

  return (
    <div className={styles.detailPage}>
      <button className={styles.backButton} type="button" onClick={() => navigate("/")}>
        返回工作台
      </button>

      {detail ? (
        <section className={styles.detailPanel}>
          <header className={styles.detailHeader}>
            <div>
              <p className={styles.brandTop}>Job Detail</p>
              <h1>{detail.sourceFilename}</h1>
              <p className={styles.brandBody}>
                {detail.jobId} / {detail.projectNo ?? "未标记项目"} / {taskKindLabel(detail.taskKind)}
              </p>
            </div>
            <StatusPill status={detail.status} />
          </header>

          {hasWarnings ? (
            <section className={styles.warningBanner}>
              <strong>
                {detail.status === "succeeded"
                  ? "任务已完成，但仍有告警或缺失项需要处理。"
                  : "任务存在告警或错误，请先检查后再继续处理。"}
              </strong>
              <span>
                flags {detail.flags.length} 项 / errors {detail.errors.length} 项
              </span>
            </section>
          ) : null}

          <div className={styles.detailGrid}>
            <InfoBlock label="任务类型" value={taskKindLabel(detail.taskKind)} />
            <InfoBlock label="当前阶段" value={detail.stage ?? "queued"} />
            <InfoBlock label="进度" value={`${detail.percent}%`} />
            <InfoBlock label="当前文件" value={detail.currentFile ?? "-"} />
            <InfoBlock label="创建时间" value={formatTimestamp(detail.createdAt)} />
            <InfoBlock label="完成时间" value={detail.finishedAt ? formatTimestamp(detail.finishedAt) : "-"} />
          </div>

          <div className={styles.progressBarLarge}>
            <div style={{ width: `${detail.percent}%` }} />
          </div>

          {detail.taskKind === "audit_check" ? (
            <section className={styles.detailSection}>
              <h2>纠错摘要</h2>
              <div className={styles.detailGrid}>
                <InfoBlock label="总错误数" value={String(detail.findingsCount)} />
                <InfoBlock label="受影响图纸数" value={String(detail.affectedDrawingsCount)} />
              </div>
              <div className={styles.columns}>
                <ListBlock title="前 10 个错误文本" items={detail.topWrongTexts} emptyText="暂无错误文本摘要" />
                <ListBlock title="前 10 个受影响内部编码" items={detail.topInternalCodes} emptyText="暂无内部编码摘要" />
              </div>
            </section>
          ) : null}

          <section className={styles.detailSection}>
            <h2>告警与错误</h2>
            <div className={styles.columns}>
              <ListBlock title="Flags" items={detail.flags} emptyText="暂无 flags" />
              <ListBlock title="Errors" items={detail.errors} emptyText="暂无 errors" />
            </div>
          </section>

          <section className={styles.detailSection}>
            <h2>下载</h2>
            <div className={styles.downloadGrid}>
              {detail.taskKind === "deliverable" ? (
                <>
                  <ArtifactButton
                    href={detail.artifacts.packageDownloadUrl ?? undefined}
                    label="下载 package.zip"
                  />
                  <ArtifactButton
                    href={detail.artifacts.iedDownloadUrl ?? undefined}
                    label="下载 IED计划.xlsx"
                  />
                </>
              ) : detail.taskKind === "audit_check" ? (
                <ArtifactButton
                  href={detail.artifacts.reportDownloadUrl ?? undefined}
                  label="下载 report.xlsx"
                />
              ) : (
                <ArtifactButton
                  href={detail.artifacts.replacedDwgDownloadUrl ?? undefined}
                  label="下载替换后 DWG"
                />
              )}
            </div>
          </section>

          <section className={styles.detailSection}>
            <h2>后续动作</h2>
            <div className={styles.downloadGrid}>
              <button className={styles.disabledAction} disabled type="button">
                取消任务（接口未开放）
              </button>
              <button className={styles.disabledAction} disabled type="button">
                重试任务（接口未开放）
              </button>
            </div>
          </section>
        </section>
      ) : (
        <section className={styles.detailPanel}>
          <p className={styles.muted}>正在加载任务详情...</p>
        </section>
      )}
    </div>
  );
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

function ArtifactButton({ href, label }: { href?: string; label: string }) {
  if (!href) {
    return (
      <button className={styles.disabledAction} disabled type="button">
        {label}
      </button>
    );
  }

  return (
    <a className={styles.downloadButton} href={href}>
      {label}
    </a>
  );
}

function InfoBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.infoBlock}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ListBlock({
  title,
  items,
  emptyText,
}: {
  title: string;
  items: readonly string[];
  emptyText: string;
}) {
  return (
    <div>
      <h3>{title}</h3>
      {items.length > 0 ? (
        <ul>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className={styles.muted}>{emptyText}</p>
      )}
    </div>
  );
}

function TaskKindBadge({ kind }: { kind: TaskKind }) {
  return <span className={`${styles.kindBadge} ${kindToneClass(kind)}`}>{taskKindLabel(kind)}</span>;
}

function StatusPill({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? { label: status, tone: "default" };

  return (
    <span className={`${styles.statusPill} ${statusToneClass(meta.tone)}`}>
      {meta.label}
    </span>
  );
}

function statusToneClass(tone: string) {
  if (tone === "queued") {
    return styles.statusQueued;
  }
  if (tone === "running") {
    return styles.statusRunning;
  }
  if (tone === "succeeded") {
    return styles.statusSucceeded;
  }
  if (tone === "failed") {
    return styles.statusFailed;
  }
  return styles.statusDefault;
}

function kindToneClass(kind: TaskKind) {
  if (kind === "audit_check") {
    return styles.kindAudit;
  }
  if (kind === "audit_replace") {
    return styles.kindReplace;
  }
  return styles.kindDeliverable;
}

function taskKindLabel(kind: TaskKind) {
  if (kind === "audit_check") {
    return "纠错";
  }
  if (kind === "audit_replace") {
    return "翻版";
  }
  return "交付";
}

type JobPackage = {
  packageKey: string;
  batchId: string | null;
  sourceFilename: string;
  status: string;
  jobs: JobSummary[];
};

function buildJobPackages(items: readonly JobSummary[]): JobPackage[] {
  const grouped = new Map<string, JobSummary[]>();

  for (const job of items) {
    const packageKey = job.batchId ?? `job:${job.jobId}`;
    const bucket = grouped.get(packageKey);
    if (bucket) {
      bucket.push(job);
    } else {
      grouped.set(packageKey, [job]);
    }
  }

  return Array.from(grouped.entries()).map(([packageKey, jobs]) => {
    const orderedJobs = [...jobs].sort((left, right) => jobSortRank(left) - jobSortRank(right));
    const leadJob = orderedJobs.find((job) => job.taskKind === "deliverable") ?? orderedJobs[0]!;

    return {
      packageKey,
      batchId: leadJob.batchId,
      sourceFilename: leadJob.sourceFilename,
      status: derivePackageStatus(orderedJobs),
      jobs: orderedJobs,
    };
  });
}

function jobSortRank(job: JobSummary) {
  if (job.taskKind === "deliverable") {
    return 0;
  }
  if (job.taskKind === "audit_check") {
    return 1;
  }
  return 2;
}

function derivePackageStatus(jobs: readonly JobSummary[]) {
  if (jobs.some((job) => job.status === "failed")) {
    return "failed";
  }
  if (jobs.some((job) => job.status === "running")) {
    return "running";
  }
  if (jobs.some((job) => job.status === "cancel_requested")) {
    return "cancel_requested";
  }
  if (jobs.some((job) => job.status === "queued")) {
    return "queued";
  }
  if (jobs.every((job) => job.status === "succeeded")) {
    return "succeeded";
  }
  return jobs[0]?.status ?? "queued";
}

function statusLabel(status: string) {
  return STATUS_META[status]?.label ?? status;
}

function formatTimestamp(value: string) {
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
    second: "2-digit",
    hour12: false,
  }).format(date);
}
