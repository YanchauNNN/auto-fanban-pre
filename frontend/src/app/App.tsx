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
import { useRef, useState } from "react";
import {
  BrowserRouter,
  Link,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";

import { DeliverableWorkspace } from "../features/deliverable/DeliverableWorkspace";
import type { CreateBatchPayload, JobDetail, JobList } from "../platform/api/types";
import { useApiAdapter } from "../platform/api/useApiAdapter";
import "../shared/global.css";
import styles from "./App.module.css";

const queryClient = new QueryClient();
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
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [jobsStatusFilter, setJobsStatusFilter] = useState<string | undefined>();
  const [highlightedBatchId, setHighlightedBatchId] = useState<string | null>(null);
  const [taskConfigOpen, setTaskConfigOpen] = useState(false);
  const [hasDraft, setHasDraft] = useState(false);
  const [incomingFiles, setIncomingFiles] = useState<File[]>([]);

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
      const hasActive = items.some((item) =>
        ["queued", "running", "cancel_requested"].includes(item.status),
      );
      return hasActive ? 3000 : 12000;
    },
  });

  function handleBatchCreated(payload: CreateBatchPayload) {
    setHighlightedBatchId(payload.batchId);
    setTaskConfigOpen(false);
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
  }

  function handleUploadClick() {
    fileInputRef.current?.click();
  }

  function handleFileSelection(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (files.length === 0 || !schemaQuery.data) {
      event.currentTarget.value = "";
      return;
    }

    setIncomingFiles(files);
    setTaskConfigOpen(true);
    event.currentTarget.value = "";
  }

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div>
          <p className={styles.brandTop}>CNPE Drawing Desk</p>
          <h1>图纸处理工作台</h1>
          <p className={styles.brandBody}>
            面向内网工程人员的统一入口。录入动作全部收敛到任务配置弹窗，主页面只保留状态与任务视图。
          </p>
        </div>

        <section className={styles.healthCard}>
          <h2>系统状态</h2>
          {healthQuery.data ? (
            <dl className={styles.healthGrid}>
              <StatRow label="服务" value={healthQuery.data.ready ? "可用" : "异常"} />
              <StatRow
                label="存储"
                value={healthQuery.data.storageWritable ? "可写" : "不可写"}
              />
              <StatRow label="队列" value={`${healthQuery.data.queueDepth} 项`} />
              <StatRow
                label="AutoCAD"
                value={healthQuery.data.autocadReady ? "就绪" : "缺失"}
              />
              <StatRow
                label="Office"
                value={healthQuery.data.officeReady ? "就绪" : "缺失"}
              />
            </dl>
          ) : (
            <p className={styles.muted}>正在读取系统状态...</p>
          )}
        </section>
      </aside>

      <main className={styles.mainColumn}>
        <section className={styles.controlPanel}>
          <div>
            <p className={styles.brandTop}>Task Entry</p>
            <h2>新建任务</h2>
            <p className={styles.brandBody}>
              点击上传后使用系统文件选择器选取 DWG。若已有未提交草稿，可直接恢复继续填写。
            </p>
          </div>

          <div className={styles.uploadActions}>
            <button
              className={styles.primaryActionButton}
              disabled={!schemaQuery.data}
              type="button"
              onClick={handleUploadClick}
            >
              上传 DWG
            </button>
            {hasDraft ? (
              <button
                className={styles.secondaryActionButton}
                type="button"
                onClick={() => setTaskConfigOpen(true)}
              >
                继续草稿
              </button>
            ) : null}
          </div>

          <input
            ref={fileInputRef}
            accept=".dwg"
            aria-label="选择 DWG 文件"
            className={styles.hiddenFileInput}
            multiple
            type="file"
            onChange={handleFileSelection}
          />

          <div className={styles.entryHint}>
            <span>真实提交链路：交付处理</span>
            <span>预留结构：纠错 / 翻版</span>
            <span>草稿策略：关闭保留，提交成功或手动清空后重置</span>
          </div>
        </section>
      </main>

      <aside className={styles.jobsColumn}>
        <header className={styles.jobsHeader}>
          <div>
            <p className={styles.brandTop}>Recent Jobs</p>
            <h2>最近任务</h2>
          </div>
          <button
            className={styles.subtleButton}
            type="button"
            onClick={() => jobsQuery.refetch()}
          >
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
          {jobsQuery.data?.items.length ? (
            jobsQuery.data.items.map((job) => (
              <Link
                className={`${styles.jobCard} ${
                  job.batchId && job.batchId === highlightedBatchId
                    ? styles.jobCardHighlight
                    : ""
                }`}
                key={job.jobId}
                to={`/jobs/${job.jobId}`}
              >
                <div className={styles.jobCardHeader}>
                  <strong>{job.sourceFilename}</strong>
                  <StatusPill status={job.status} />
                </div>
                <p className={styles.jobStage}>{job.stage ?? "queued"}</p>
                <p className={styles.jobMessage}>{job.message || "等待处理中"}</p>
                <div className={styles.progressBar}>
                  <div style={{ width: `${job.percent}%` }} />
                </div>
              </Link>
            ))
          ) : (
            <div className={styles.emptyPanel}>
              <p>当前没有任务记录。</p>
            </div>
          )}
        </div>
      </aside>

      {schemaQuery.data ? (
        <DeliverableWorkspace
          adapter={adapter}
          incomingFiles={incomingFiles}
          isOpen={taskConfigOpen}
          onBatchCreated={handleBatchCreated}
          onClose={() => setTaskConfigOpen(false)}
          onDraftAvailabilityChange={setHasDraft}
          schema={schemaQuery.data}
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
      return data && ["queued", "running", "cancel_requested"].includes(data.status)
        ? 3000
        : 12000;
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
                {detail.jobId} / {detail.projectNo ?? "未标记项目"}
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
            <InfoBlock label="当前阶段" value={detail.stage ?? "queued"} />
            <InfoBlock label="进度" value={`${detail.percent}%`} />
            <InfoBlock label="当前文件" value={detail.currentFile ?? "-"} />
            <InfoBlock label="创建时间" value={formatTimestamp(detail.createdAt)} />
          </div>

          <div className={styles.progressBarLarge}>
            <div style={{ width: `${detail.percent}%` }} />
          </div>

          <section className={styles.detailSection}>
            <h2>告警与错误</h2>
            <div className={styles.columns}>
              <div>
                <h3>Flags</h3>
                {detail.flags.length ? (
                  <ul>
                    {detail.flags.map((flag) => (
                      <li key={flag}>{flag}</li>
                    ))}
                  </ul>
                ) : (
                  <p className={styles.muted}>暂无 flags</p>
                )}
              </div>
              <div>
                <h3>Errors</h3>
                {detail.errors.length ? (
                  <ul>
                    {detail.errors.map((error) => (
                      <li key={error}>{error}</li>
                    ))}
                  </ul>
                ) : (
                  <p className={styles.muted}>暂无 errors</p>
                )}
              </div>
            </div>
          </section>

          <section className={styles.detailSection}>
            <h2>下载</h2>
            <div className={styles.downloadGrid}>
              <ArtifactButton href={detail.artifacts.packageDownloadUrl ?? undefined} label="下载 package.zip" />
              <ArtifactButton href={detail.artifacts.iedDownloadUrl ?? undefined} label="下载 IED计划.xlsx" />
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
