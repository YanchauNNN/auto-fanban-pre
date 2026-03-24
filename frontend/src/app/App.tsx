import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/700.css";
import "@fontsource/noto-sans-sc/400.css";
import "@fontsource/noto-sans-sc/500.css";
import "@fontsource/noto-sans-sc/700.css";
import "@fontsource/rajdhani/500.css";
import "@fontsource/rajdhani/700.css";

import {
  QueryClient,
  QueryClientProvider,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  BrowserRouter,
  Link,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";

import groupLogoUrl from "../assets/group-logo.jpg";
import nuclearPlantHeroUrl from "../assets/nuclear-plant-hero.jpg";
import structureLogoWatermarkUrl from "../assets/structure-logo-watermark.jpg";
import { AuditCheckSummaryModal } from "../features/audit-check/AuditCheckSummaryModal";
import { AuditCheckWorkspace } from "../features/audit-check/AuditCheckWorkspace";
import { DeliverableWorkspace } from "../features/deliverable/DeliverableWorkspace";
import type {
  ApiAdapter,
  CreateBatchPayload,
  DeliverableOutputs,
  FindingGroup,
  JobDetail,
  JobList,
  JobSummary,
  TaskKind,
} from "../platform/api/types";
import { useApiAdapter } from "../platform/api/useApiAdapter";
import "../shared/global.css";
import styles from "./App.module.css";
import {
  buildJobCardModels,
  getMessageLabel,
  getStageLabel,
  getStatusLabel,
  getTaskKindLabel,
  type JobCardModel,
} from "./jobPresentation";

const ACTIVE_JOB_STATUSES = ["queued", "running", "cancel_requested"] as const;
const DEFAULT_VISIBLE_JOB_CARDS = 8;

const JOB_FILTER_OPTIONS: Array<{ label: string; value?: string }> = [
  { label: "全部" },
  { label: "排队中", value: "queued" },
  { label: "运行中", value: "running" },
  { label: "成功", value: "succeeded" },
  { label: "失败", value: "failed" },
];

const MODULE_OPTIONS = [
  { key: "business", label: "业务模块" },
  { key: "account", label: "账号模块" },
  { key: "workload", label: "工作量模块" },
] as const;

type HomeModule = (typeof MODULE_OPTIONS)[number]["key"];

const STATUS_META: Record<string, { label: string; tone: string }> = {
  queued: { label: "排队中", tone: "queued" },
  running: { label: "运行中", tone: "running" },
  cancel_requested: { label: "取消中", tone: "queued" },
  cancelled: { label: "已取消", tone: "default" },
  succeeded: { label: "成功", tone: "succeeded" },
  failed: { label: "失败", tone: "failed" },
};

const HERO_PANEL_STYLE = {
  "--hero-photo": `url("${nuclearPlantHeroUrl}")`,
  "--structure-watermark": `url("${structureLogoWatermarkUrl}")`,
} as CSSProperties;

const TUTORIAL_SAMPLE_FILE = "demo-2026-structural-package.dwg";
const TUTORIAL_SAMPLE_PROJECT = "2026";
const LEGACY_DELIVERABLE_TUTORIAL_STEPS = [
  {
    id: "entry",
    title: "步骤 1 / 6",
    body:
      "先从首页“新建任务”区域开始。这里是出图流程的真正入口：点击“出图”后，系统会调起 DWG 文件选择器，随后依次进入任务配置、任务记录与产物下载页面。先记住这个区域，后续所有操作都会围绕这里展开。",
  },
  {
    id: "picker_select",
    title: "步骤 2 / 6",
    body:
      "这一步模拟系统文件选择器中的“文件列表”区域。正式使用时，需要在这个窗口里找到本次要处理的 DWG 图册文件，并确认当前高亮的是正确的源图册。教程里用内置样例来演示，不会真的读取磁盘文件。",
  },
  {
    id: "picker_confirm",
    title: "步骤 3 / 6",
    body:
      "确认样例 DWG 已经选中后，点击右下角“打开”。这一步对应真实流程里的文件确认动作：点开后就会进入任务配置页面，开始补齐项目、设计文件和 IED 信息。",
  },
  {
    id: "config",
    title: "步骤 4 / 6",
    body:
      "进入任务配置后，需要补齐设计文件、IED 基础信息和打印设置。若此时勾选“纠错”，系统会把纠错与出图一起创建为同一任务包；教程里会明确说明这一点，但不会真的提交任务。",
  },
  {
    id: "record",
    title: "步骤 5 / 6",
    body:
      "提交后，业务首页下方的“任务记录”会出现新的任务包卡片。这里可以快速查看任务状态、子任务关系，并从卡片进入任务包详情页，继续查看出图与纠错的完成情况。",
  },
  {
    id: "detail",
    title: "步骤 6 / 6",
    body:
      "最后进入任务包详情页。这里可以查看任务概览，并从下载区获取任务包、IED 计划和纠错报告等产物。这一步就是完整出图流程的收口位置：确认结果、回看子任务并下载产物。",
  },
] as const;

const DELIVERABLE_TUTORIAL_STEPS = [
  {
    id: "entry",
    title: "步骤 1 / 5",
    body:
      "先从首页“新建任务”区域开始。这里是出图流程的真正入口：点击“出图”后，系统会调起 DWG 文件选择器，随后依次进入任务配置、任务记录与产物下载页面。先记住这个区域，后续所有操作都会围绕这里展开。",
  },
  {
    id: "picker_select",
    title: "步骤 2 / 5",
    body:
      "这一步模拟系统文件选择器。正式使用时，需要在这个窗口里找到本次要处理的 DWG 图册文件，确认高亮的是正确源文件后，再点击右下角“打开”进入任务配置页面。教程里用内置样例来演示，不会真的读取磁盘文件。",
  },
  {
    id: "config",
    title: "步骤 3 / 5",
    body:
      "进入任务配置后，需要补齐设计文件、IED 基础信息和打印设置。若此时勾选“纠错”，系统会把纠错与出图一起创建为同一任务包；教程里会明确说明这一点，但不会真的提交任务。",
  },
  {
    id: "record",
    title: "步骤 4 / 5",
    body:
      "提交后，业务首页下方的“任务记录”会出现新的任务包卡片。这里可以快速查看任务状态、子任务关系，并从卡片进入任务包详情页，继续查看出图与纠错的完成情况。",
  },
  {
    id: "detail",
    title: "步骤 5 / 5",
    body:
      "最后进入任务包详情页。这里可以查看任务概览，并从下载区获取任务包、IED 计划和纠错报告等产物。这一步就是完整出图流程的收口位置：确认结果、回看子任务并下载产物。",
  },
] as const;

type TutorialStep = (typeof DELIVERABLE_TUTORIAL_STEPS)[number];
type TutorialStepId = TutorialStep["id"];

type SpotlightRect = {
  top: number;
  left: number;
  width: number;
  height: number;
};

function getTutorialTargetSelector(stepId: TutorialStepId): string {
  switch (stepId) {
    case "entry":
      return '[data-tutorial-target="entry"]';
    case "picker_select":
      return '[data-tutorial-target="picker-select"]';
    case "config":
      return '[data-tutorial-target="config"]';
    case "record":
      return '[data-tutorial-target="record"]';
    case "detail":
      return '[data-tutorial-target="detail"]';
  }
}

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
  const [recentJobsSearch, setRecentJobsSearch] = useState("");
  const [allJobsModalOpen, setAllJobsModalOpen] = useState(false);
  const [activeModule, setActiveModule] = useState<HomeModule>("business");
  const [jobsRefreshState, setJobsRefreshState] = useState<"idle" | "refreshing" | "done">("idle");
  const [showReplaceTooltip, setShowReplaceTooltip] = useState(false);
  const [tutorialStepIndex, setTutorialStepIndex] = useState<number | null>(null);

  const [deliverableConfigOpen, setDeliverableConfigOpen] = useState(false);
  const [deliverableDraftAvailable, setDeliverableDraftAvailable] = useState(false);
  const [incomingFiles, setIncomingFiles] = useState<File[]>([]);

  const [auditConfigOpen, setAuditConfigOpen] = useState(false);
  const [auditDraftAvailable, setAuditDraftAvailable] = useState(false);
  const [auditSummaryQueue, setAuditSummaryQueue] = useState<JobDetail[]>([]);
  const [auditNotice, setAuditNotice] = useState<string | null>(null);
  const jobsRefreshResetTimerRef = useRef<number | null>(null);
  const tutorialActive = tutorialStepIndex !== null;
  const tutorialStep =
    tutorialStepIndex === null ? null : DELIVERABLE_TUTORIAL_STEPS[tutorialStepIndex];

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
  const actionsReady = Boolean(schemaQuery.data);
  const primaryActionLabel = actionsReady ? "出图" : "正在加载配置";
  const auditActionLabel = actionsReady
    ? auditDraftAvailable
      ? "继续纠错"
      : "纠错"
    : "正在加载配置";

  const jobsQuery = useQuery({
    queryKey: ["jobs", jobsStatusFilter ?? "all"],
    queryFn: () => adapter.listJobs(jobsStatusFilter),
    refetchInterval: (query) => {
      const items = (query.state.data as JobList | undefined)?.items ?? [];
      const hasActive = items.some((item) => ACTIVE_JOB_STATUSES.includes(item.status as never));
      return hasActive ? 3000 : 12000;
    },
  });

  const jobCards = useMemo(
    () => buildJobCardModels(jobsQuery.data?.items ?? []),
    [jobsQuery.data?.items],
  );
  const normalizedRecentJobsSearch = recentJobsSearch.trim().toLowerCase();
  const filteredJobCards = useMemo(() => {
    if (!normalizedRecentJobsSearch) {
      return jobCards;
    }

    return jobCards.filter((card) => card.title.toLowerCase().includes(normalizedRecentJobsSearch));
  }, [jobCards, normalizedRecentJobsSearch]);
  const hiddenJobCardCount = normalizedRecentJobsSearch
    ? 0
    : Math.max(filteredJobCards.length - DEFAULT_VISIBLE_JOB_CARDS, 0);
  const visibleJobCards = normalizedRecentJobsSearch
    ? filteredJobCards
    : filteredJobCards.slice(0, DEFAULT_VISIBLE_JOB_CARDS);

  useEffect(() => {
    if (normalizedRecentJobsSearch) {
      setAllJobsModalOpen(false);
    }
  }, [normalizedRecentJobsSearch]);

  useEffect(() => {
    return () => {
      if (jobsRefreshResetTimerRef.current !== null) {
        window.clearTimeout(jobsRefreshResetTimerRef.current);
      }
    };
  }, []);

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
        !job.isGroup &&
        job.taskKind === "audit_check" &&
        previousStatus !== undefined &&
        ACTIVE_JOB_STATUSES.includes(previousStatus as never) &&
        job.status === "succeeded" &&
        !notifiedAuditJobIdsRef.current.has(job.jobId)
      );
    });

    const completedAuditGroups = items.filter((job) => {
      const previousStatus = previousStatuses.get(job.jobId);
      return (
        job.isGroup &&
        job.runAuditCheck &&
        previousStatus !== undefined &&
        ACTIVE_JOB_STATUSES.includes(previousStatus as never) &&
        job.status === "succeeded" &&
        !notifiedAuditJobIdsRef.current.has(job.jobId)
      );
    });

    if (completedAuditJobs.length === 0 && completedAuditGroups.length === 0) {
      return;
    }

    [...completedAuditJobs, ...completedAuditGroups].forEach((job) => {
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
            // list polling will continue; the user can still open the detail page manually
          }
          continue;
        }

        passedWithoutFindings.push(job.sourceFilename);
      }

      for (const group of completedAuditGroups) {
        if (group.findingsCount > 0) {
          try {
            const groupDetail = await adapter.getJobDetail(group.jobId);
            const auditChild = groupDetail.children?.find((child) => child.taskKind === "audit_check");
            if (auditChild) {
              const auditDetail = await adapter.getJobDetail(auditChild.jobId);
              if (auditDetail.taskKind === "audit_check") {
                summaries.push(auditDetail);
              }
            }
          } catch {
            // list polling will continue; the user can still open the detail page manually
          }
          continue;
        }

        passedWithoutFindings.push(group.sourceFilename);
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

  function handleOpenTutorial() {
    setActiveModule("business");
    setTutorialStepIndex(0);
    setAllJobsModalOpen(false);
  }

  function handleCloseTutorial() {
    setTutorialStepIndex(null);
  }

  function handleNextTutorialStep() {
    setTutorialStepIndex((current) => {
      if (current === null) {
        return 0;
      }

      return Math.min(current + 1, DELIVERABLE_TUTORIAL_STEPS.length - 1);
    });
  }

  function handlePreviousTutorialStep() {
    setTutorialStepIndex((current) => {
      if (current === null) {
        return 0;
      }

      return Math.max(current - 1, 0);
    });
  }

  async function handleJobsRefresh() {
    if (jobsRefreshResetTimerRef.current !== null) {
      window.clearTimeout(jobsRefreshResetTimerRef.current);
      jobsRefreshResetTimerRef.current = null;
    }

    setJobsRefreshState("refreshing");

    try {
      await jobsQuery.refetch();
      setJobsRefreshState("done");
      jobsRefreshResetTimerRef.current = window.setTimeout(() => {
        setJobsRefreshState("idle");
        jobsRefreshResetTimerRef.current = null;
      }, 1200);
    } catch {
      setJobsRefreshState("idle");
    }
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
    <div className={styles.workspacePage}>
      <header className={styles.titleStrip} data-testid="title-strip">
        <div className={styles.titleStripLayout}>
          <div className={styles.titleStripBrand}>
            <img alt="中核集团标识" className={styles.titleStripLogo} src={groupLogoUrl} />
            <div className={styles.titleStripText}>
              <p className={styles.brandTop}>CNPE Structural Drawing Platform</p>
              <h1>中核工程—建筑结构所出图平台</h1>
            </div>
          </div>
          <section className={styles.titleStripStatus} data-testid="title-strip-status">
            <div className={styles.titleStripStatusTop}>
              <p className={styles.titleStripStatusLabel}>System Status</p>
              <button
                className={styles.tutorialEntryButton}
                type="button"
                onClick={handleOpenTutorial}
              >
                教程
              </button>
            </div>
            {healthQuery.data ? (
              <div className={styles.titleStripHealthGrid}>
                <StatRow label="服务" value={healthQuery.data.ready ? "就绪" : "异常"} />
                <StatRow
                  label="存储"
                  value={healthQuery.data.storageWritable ? "正常" : "异常"}
                />
                <StatRow label="队列" value={`${healthQuery.data.queueDepth} 项`} />
                <StatRow
                  label="AutoCAD"
                  value={healthQuery.data.autocadReady ? "可用" : "缺失"}
                />
                <StatRow
                  label="Office"
                  value={healthQuery.data.officeReady ? "可用" : "缺失"}
                />
              </div>
            ) : (
              <p className={styles.titleStripHealthLoading}>正在读取</p>
            )}
          </section>
        </div>
      </header>

      <nav className={styles.moduleToolbar} data-testid="module-toolbar">
        {MODULE_OPTIONS.map((module) => {
          const active = activeModule === module.key;
          return (
            <button
              aria-pressed={active}
              className={`${styles.moduleToolbarButton} ${
                active ? styles.moduleToolbarButtonActive : ""
              }`}
              key={module.key}
              type="button"
              onClick={() => setActiveModule(module.key)}
            >
              {module.label}
            </button>
          );
        })}
      </nav>

      <div className={styles.shell}>
        <main className={styles.mainColumn}>
          {activeModule === "business" ? (
            <section className={styles.modulePanel} data-testid="module-business-panel">
              <section
                className={styles.controlPanel}
                data-tutorial-active={tutorialStep?.id === "entry" ? "true" : "false"}
                data-testid="tutorial-target-entry"
                data-tutorial-target="entry"
                style={HERO_PANEL_STYLE}
              >
                <div className={styles.controlPanelBackdrop} />
                <div
                  className={styles.controlPanelWatermark}
                  data-testid="hero-watermark"
                />
                <div className={styles.controlPanelContent}>
                  <div>
                    <p className={styles.brandTop}>Task Entry</p>
                    <h2>新建任务</h2>
                  </div>

                  <div className={styles.uploadActions}>
                    <button
                      className={styles.primaryActionButton}
                      aria-busy={!actionsReady}
                      disabled={!actionsReady}
                      type="button"
                      onClick={handleDeliverableUploadClick}
                    >
                      {primaryActionLabel}
                    </button>
                    <button
                      className={styles.primaryActionButton}
                      aria-busy={!actionsReady}
                      disabled={!actionsReady}
                      type="button"
                      onClick={() => setAuditConfigOpen(true)}
                    >
                      {auditActionLabel}
                    </button>
                    <span
                      className={styles.disabledPreviewWrap}
                      data-testid="replace-preview-wrap"
                      onBlur={() => setShowReplaceTooltip(false)}
                      onFocus={() => setShowReplaceTooltip(true)}
                      onMouseEnter={() => setShowReplaceTooltip(true)}
                      onMouseLeave={() => setShowReplaceTooltip(false)}
                    >
                      <button
                        aria-disabled="true"
                        className={styles.disabledPreviewButton}
                        tabIndex={-1}
                        type="button"
                      >
                        翻版
                      </button>
                      {showReplaceTooltip ? (
                        <span
                          aria-label="敬请期待"
                          className={styles.disabledPreviewTooltip}
                          data-side="right"
                          role="tooltip"
                        >
                          敬请期待
                        </span>
                      ) : null}
                    </span>
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

                  {auditNotice ? (
                    <div className={styles.noticeBanner}>
                      <span>{auditNotice}</span>
                      <button
                        className={styles.noticeClose}
                        type="button"
                        onClick={() => setAuditNotice(null)}
                      >
                        关闭
                      </button>
                    </div>
                  ) : null}
                </div>
              </section>

              <section className={styles.jobsSection} data-testid="recent-jobs-section">
                <header className={styles.jobsHeader}>
                  <div>
                    <p className={styles.brandTop}>Task Record</p>
                    <h2>任务记录</h2>
                  </div>
                  <button className={styles.subtleButton} type="button" onClick={() => void handleJobsRefresh()}>
                    {jobsRefreshState === "refreshing"
                      ? "刷新中"
                      : jobsRefreshState === "done"
                        ? "已刷新"
                        : "刷新"}
                  </button>
                </header>

                <div className={styles.filterRow}>
                  {JOB_FILTER_OPTIONS.map((filter) => {
                    const active = (jobsStatusFilter ?? "") === (filter.value ?? "");
                    return (
                      <button
                        className={`${styles.filterButton} ${active ? styles.filterButtonActive : ""}`}
                        key={filter.label}
                        type="button"
                        onClick={() => setJobsStatusFilter(filter.value)}
                      >
                        {filter.label}
                      </button>
                    );
                  })}
                </div>

                <div className={styles.searchRow}>
                  <input
                    aria-label="搜索任务名称"
                    className={styles.searchInput}
                    placeholder="搜索任务名称"
                    role="searchbox"
                    type="search"
                    value={recentJobsSearch}
                    onChange={(event) => setRecentJobsSearch(event.target.value)}
                  />
                  {hiddenJobCardCount > 0 ? (
                    <button
                      className={styles.collapseToggle}
                      type="button"
                      onClick={() => setAllJobsModalOpen(true)}
                    >
                      展开其余 {hiddenJobCardCount} 个
                    </button>
                  ) : null}
                </div>

                <div className={styles.jobsGrid}>
                  {visibleJobCards.length > 0 ? (
                    visibleJobCards.map((card) => (
                      <JobCard
                        adapter={adapter}
                        card={card}
                        highlighted={Boolean(
                          card.summary.batchId && card.summary.batchId === highlightedBatchId,
                        )}
                        key={card.key}
                      />
                    ))
                  ) : (
                    <div className={styles.emptyPanel}>
                      <p>{normalizedRecentJobsSearch ? "没有匹配的任务。" : "当前没有任务记录。"}</p>
                    </div>
                  )}
                </div>
              </section>
            </section>
          ) : activeModule === "account" ? (
            <section className={styles.placeholderPanel} data-testid="module-account-panel">
              <p className={styles.brandTop}>Account Module</p>
              <h2>账号模块预留</h2>
            </section>
          ) : (
            <section className={styles.placeholderPanel} data-testid="module-workload-panel">
              <p className={styles.brandTop}>Workload Module</p>
              <h2>工作量模块预留</h2>
            </section>
          )}
        </main>
      </div>

      {allJobsModalOpen ? (
        <JobsBrowserModal
          adapter={adapter}
          cards={filteredJobCards}
          filterValue={jobsStatusFilter}
          refreshState={jobsRefreshState}
          searchValue={recentJobsSearch}
          onClose={() => setAllJobsModalOpen(false)}
          onFilterChange={setJobsStatusFilter}
          onRefresh={handleJobsRefresh}
          onSearchChange={setRecentJobsSearch}
        />
      ) : null}

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
          onClose={() => setAuditSummaryQueue((current) => current.slice(1))}
        />
      ) : null}

      {tutorialActive && tutorialStep ? (
        <DeliverableTutorialOverlay
          step={tutorialStep}
          stepIndex={tutorialStepIndex}
          totalSteps={DELIVERABLE_TUTORIAL_STEPS.length}
          onClose={handleCloseTutorial}
          onNext={handleNextTutorialStep}
          onPrevious={handlePreviousTutorialStep}
        />
      ) : null}
    </div>
  );
}

function JobsBrowserModal({
  adapter,
  cards,
  filterValue,
  refreshState,
  searchValue,
  onFilterChange,
  onSearchChange,
  onRefresh,
  onClose,
}: {
  adapter: ApiAdapter;
  cards: JobCardModel[];
  filterValue?: string;
  refreshState: "idle" | "refreshing" | "done";
  searchValue: string;
  onFilterChange: (value?: string) => void;
  onSearchChange: (value: string) => void;
  onRefresh: () => Promise<void>;
  onClose: () => void;
}) {
  return (
    <div className={styles.jobsModalBackdrop}>
      <div
        aria-label="全部任务浏览器"
        aria-modal="true"
        className={styles.jobsModal}
        role="dialog"
      >
        <header className={styles.jobsModalHeader}>
          <div>
            <p className={styles.brandTop}>Task Record</p>
            <h2>全部任务记录</h2>
          </div>
          <div className={styles.jobsModalActions}>
            <button className={styles.subtleButton} type="button" onClick={() => void onRefresh()}>
              {refreshState === "refreshing"
                ? "刷新中"
                : refreshState === "done"
                  ? "已刷新"
                  : "刷新"}
            </button>
            <button className={styles.secondaryActionButton} type="button" onClick={onClose}>
              关闭
            </button>
          </div>
        </header>

        <div className={styles.filterRow}>
          {JOB_FILTER_OPTIONS.map((filter) => {
            const active = (filterValue ?? "") === (filter.value ?? "");
            return (
              <button
                className={`${styles.filterButton} ${active ? styles.filterButtonActive : ""}`}
                key={filter.label}
                type="button"
                onClick={() => onFilterChange(filter.value)}
              >
                {filter.label}
              </button>
            );
          })}
        </div>

        <div className={styles.searchRow}>
          <input
            aria-label="搜索任务名称"
            className={styles.searchInput}
            placeholder="搜索任务名称"
            role="searchbox"
            type="search"
            value={searchValue}
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </div>

        <div className={styles.jobsModalBody}>
          {cards.length > 0 ? (
            cards.map((card) => (
              <JobCard adapter={adapter} card={card} highlighted={false} key={card.key} />
            ))
          ) : (
            <div className={styles.emptyPanel}>
              <p>没有匹配的任务。</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function JobCard({
  adapter,
  card,
  highlighted,
}: {
  adapter: ApiAdapter;
  card: JobCardModel;
  highlighted: boolean;
}) {
  const groupDetailQuery = useQuery({
    queryKey: ["job-card-group-detail", card.jobId],
    queryFn: () => adapter.getJobDetail(card.jobId),
    enabled: card.kind === "real_group",
    refetchInterval:
      card.kind === "real_group" && ACTIVE_JOB_STATUSES.includes(card.status as never)
        ? 3000
        : false,
  });

  const childJobs =
    card.kind === "real_group" ? (groupDetailQuery.data?.children ?? card.childJobs) : card.childJobs;

  return (
    <div
      className={`${styles.jobCard} ${highlighted ? styles.jobCardHighlight : ""}`}
      data-testid="recent-job-card"
    >
      <div className={styles.jobCardHeader}>
        <strong>{card.title}</strong>
        <div className={styles.jobCardHeaderMeta}>
          {card.kind !== "single_job" ? (
            <p className={styles.packageMeta}>包含 {Math.max(childJobs.length, card.childCount)} 个子任务</p>
          ) : null}
          <StatusPill status={card.status} />
        </div>
      </div>

      <div className={styles.jobMetaRow}>
        {card.kind === "single_job" ? (
          <>
            {card.summary.taskKind ? <TaskKindBadge kind={card.summary.taskKind} /> : null}
            <Link className={styles.subtaskLink} to={`/jobs/${card.jobId}`}>
              查看任务
            </Link>
          </>
        ) : (
          <>
            <span className={`${styles.kindBadge} ${styles.kindGroup}`}>任务包</span>
            {childJobs.map((child) => (
              <Link className={styles.subtaskLink} key={child.jobId} to={`/jobs/${child.jobId}`}>
                {child.taskKind ? <TaskKindBadge kind={child.taskKind} /> : null}
                <span className={styles.subtaskStatus}>{getStatusLabel(child.status)}</span>
              </Link>
            ))}
            {card.kind === "real_group" ? (
              <Link className={styles.subtaskLink} to={`/jobs/${card.jobId}`}>
                查看任务包
              </Link>
            ) : null}
          </>
        )}

        {(card.kind !== "single_job" || card.summary.taskKind === "audit_check") && card.findingsCount > 0 ? (
          <span className={styles.jobMetric}>错误数 {card.findingsCount}</span>
        ) : null}
        {(card.kind !== "single_job" || card.summary.taskKind === "audit_check") &&
        card.affectedDrawingsCount > 0 ? (
          <span className={styles.jobMetric}>受影响图纸 {card.affectedDrawingsCount}</span>
        ) : null}
      </div>

      <p className={styles.jobStage}>{card.stageLabel}</p>
      <p className={styles.jobMessage}>{card.messageLabel}</p>

      <div className={styles.progressBar}>
        <div style={{ width: `${card.percent}%` }} />
      </div>
    </div>
  );
}

function TutorialSpotlight({ stepId }: { stepId: TutorialStepId }) {
  const [targetRect, setTargetRect] = useState<SpotlightRect | null>(null);

  useLayoutEffect(() => {
    const insetByStep: Record<TutorialStepId, number> = {
      entry: 18,
      picker_select: 12,
      config: 16,
      record: 14,
      detail: 16,
    };

    function updateSpotlight() {
      const target = document.querySelector<HTMLElement>(getTutorialTargetSelector(stepId));
      if (!target) {
        setTargetRect(null);
        return;
      }

      const rect = target.getBoundingClientRect();
      const inset = insetByStep[stepId];
      setTargetRect({
        top: Math.max(8, rect.top - inset),
        left: Math.max(8, rect.left - inset),
        width: rect.width + inset * 2,
        height: rect.height + inset * 2,
      });
    }

    const target = document.querySelector<HTMLElement>(getTutorialTargetSelector(stepId));
    if (target && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ block: "center", inline: "nearest" });
    }

    updateSpotlight();

    const rafId = window.requestAnimationFrame(() => {
      const nextTarget = document.querySelector<HTMLElement>(getTutorialTargetSelector(stepId));
      if (!nextTarget) {
          setTargetRect(null);
        return;
      }
      updateSpotlight();
    });
    window.addEventListener("resize", updateSpotlight);
    window.addEventListener("scroll", updateSpotlight, true);

    return () => {
      window.cancelAnimationFrame(rafId);
      window.removeEventListener("resize", updateSpotlight);
      window.removeEventListener("scroll", updateSpotlight, true);
    };
  }, [stepId]);

  if (!targetRect) {
    return <div className={styles.tutorialDimmer} data-testid="tutorial-dimmer" />;
  }

  return (
    <div
      aria-hidden="true"
      className={styles.tutorialSpotlight}
      data-target={stepId}
      data-testid="tutorial-spotlight"
      style={{
        top: `${targetRect.top}px`,
        left: `${targetRect.left}px`,
        width: `${targetRect.width}px`,
        height: `${targetRect.height}px`,
      }}
    />
  );
}

function TutorialFilePicker({ stepId }: { stepId: TutorialStepId }) {
  return (
    <div className={styles.tutorialScene}>
      <div
        aria-label="教程文件选择"
        aria-modal="true"
        className={styles.tutorialPicker}
        role="dialog"
      >
        <div className={styles.tutorialPickerHeader}>
          <span>打开</span>
          <button className={styles.tutorialWindowClose} tabIndex={-1} type="button">
            ×
          </button>
        </div>
        <div className={styles.tutorialPickerBody}>
          <div className={styles.tutorialPickerSidebar}>
            <span>下载</span>
            <span>文档</span>
            <span>图片</span>
            <span>Terminal</span>
          </div>
          <div className={styles.tutorialPickerMain}>
            <div className={styles.tutorialPickerPath}>
              E:\project\auto-fanban-pre\test\zhangxiaomin-feedback
            </div>
            <div
              className={styles.tutorialPickerFileList}
              data-tutorial-active={stepId === "picker_select" ? "true" : "false"}
              data-tutorial-target="picker-select"
            >
              <div className={styles.tutorialPickerFileRow}>
                <span>1</span>
                <span>文件夹</span>
              </div>
              <div className={`${styles.tutorialPickerFileRow} ${styles.tutorialPickerFileRowActive}`}>
                <span>18185NE-JGS11.dwg</span>
                <span>DWG 文件</span>
              </div>
              <div className={styles.tutorialPickerFileRow}>
                <span>1818-JGS11.dwg</span>
                <span>DWG 文件</span>
              </div>
            </div>
          </div>
        </div>
        <div className={styles.tutorialPickerFooter}>
          <div className={styles.tutorialPickerFilename}>文件名：18185NE-JGS11.dwg</div>
          <div className={styles.tutorialPickerActions}>
            <button className={styles.secondaryActionButton} type="button">
              打开
            </button>
            <button className={styles.subtleButton} type="button">
              取消
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function TutorialConfigDialog() {
  return (
    <div className={styles.tutorialScene}>
      <div
        aria-label="教程任务配置"
        aria-modal="true"
        className={`${styles.tutorialDialog} ${styles.tutorialConfigDialog}`}
        data-testid="tutorial-config-dialog"
        data-tutorial-target="config"
        role="dialog"
      >
        <header className={styles.tutorialDialogHeader}>
          <div>
            <p className={styles.brandTop}>Deliverable Config</p>
            <h3>任务配置</h3>
          </div>
        </header>
        <div className={styles.tutorialDialogBody}>
          <div className={styles.tutorialConfigSection}>
            <div className={styles.tutorialSectionTitleRow}>
              <strong>任务与项目</strong>
              <span>教程示例</span>
            </div>
            <div className={styles.tutorialConfigGrid}>
              <div className={styles.tutorialField}>
                <span>示例文件</span>
                <strong>{TUTORIAL_SAMPLE_FILE}</strong>
              </div>
              <div className={styles.tutorialField}>
                <span>项目号</span>
                <strong>{TUTORIAL_SAMPLE_PROJECT}</strong>
              </div>
              <div className={styles.tutorialField}>
                <span>封面模板</span>
                <strong>通用</strong>
              </div>
              <div className={styles.tutorialField}>
                <span>密级</span>
                <strong>非密</strong>
              </div>
            </div>
          </div>
          <div className={styles.tutorialConfigSection}>
            <div className={styles.tutorialSectionTitleRow}>
              <strong>设计文件与 IED</strong>
              <span>关键必填项</span>
            </div>
            <div className={styles.tutorialConfigGrid}>
              <div className={styles.tutorialField}>
                <span>WBS 编码</span>
                <strong>5NE-11</strong>
              </div>
              <div className={styles.tutorialField}>
                <span>文件类别</span>
                <strong>1.2.1 设计总说明书</strong>
              </div>
              <div className={styles.tutorialField}>
                <span>工时数</span>
                <strong>100</strong>
              </div>
              <div className={styles.tutorialField}>
                <span>IED 状态</span>
                <strong>发布</strong>
              </div>
              <div className={styles.tutorialField}>
                <span>责任设总</span>
                <strong>王任超@wangrca</strong>
              </div>
              <div className={styles.tutorialField}>
                <span>校核者与工种负责人</span>
                <strong>孟志勇@mengzy</strong>
              </div>
            </div>
          </div>
          <div className={styles.tutorialConfigSection}>
            <div className={styles.tutorialSectionTitleRow}>
              <strong>打印设置</strong>
              <span>提交时随任务一起生效</span>
            </div>
            <div className={styles.tutorialPrintChips}>
              <span className={styles.tutorialPrintChipActive}>红色更宽</span>
              <span className={styles.tutorialPrintChip}>同线宽</span>
              <span className={styles.tutorialPrintChip}>交审图</span>
            </div>
          </div>
          <div className={styles.tutorialAuditHint}>
            若勾选纠错，系统会与出图一起创建为同一任务包；本教程仅演示流程，不会真的提交任务。
          </div>
          <div className={styles.tutorialDialogActions}>
            <button className={styles.downloadButton} type="button">
              创建出图任务
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function TutorialRecordCard() {
  return (
    <div
      className={`${styles.jobCard} ${styles.tutorialJobCard}`}
      data-testid="tutorial-record-card"
      data-tutorial-target="record"
    >
      <div className={styles.jobCardHeader}>
        <strong>18185NE-JGS11.dwg</strong>
        <div className={styles.jobCardHeaderMeta}>
          <p className={styles.packageMeta}>包含 2 个子任务</p>
          <span className={`${styles.statusPill} ${styles.statusSucceeded}`}>成功</span>
        </div>
      </div>

      <div className={styles.jobMetaRow}>
        <span className={`${styles.kindBadge} ${styles.kindGroup}`}>任务包</span>
        <span className={styles.subtaskLink}>
          <span className={`${styles.kindBadge} ${styles.kindDeliverable}`}>交付</span>
          <span className={styles.subtaskStatus}>成功</span>
        </span>
        <span className={styles.subtaskLink}>
          <span className={`${styles.kindBadge} ${styles.kindAudit}`}>纠错</span>
          <span className={styles.subtaskStatus}>成功</span>
        </span>
        <span className={styles.subtaskLink}>查看任务包</span>
      </div>

      <p className={styles.jobStage}>任务包完成</p>
      <p className={styles.jobMessage}>任务包已完成</p>

      <div className={styles.progressBar}>
        <div style={{ width: "100%" }} />
      </div>
    </div>
  );
}

function TutorialRecordScene() {
  return (
    <div className={styles.tutorialScene}>
      <div aria-label="教程任务记录" aria-modal="true" className={styles.tutorialRecordScene} role="dialog">
        <header className={styles.jobsHeader}>
          <div>
            <p className={styles.brandTop}>Task Record</p>
            <h2>任务记录</h2>
          </div>
        </header>
        <div className={styles.searchRow}>
          <input
            aria-label="搜索任务名称"
            className={styles.searchInput}
            placeholder="搜索任务名称"
            readOnly
            role="searchbox"
            type="search"
            value=""
          />
        </div>
        <TutorialRecordCard />
      </div>
    </div>
  );
}

function TutorialDetailDialog() {
  return (
    <div className={styles.tutorialScene}>
      <div
        aria-label="教程任务详情"
        aria-modal="true"
        className={`${styles.tutorialDialog} ${styles.tutorialDetailDialog}`}
        data-testid="tutorial-detail-dialog"
        data-tutorial-target="detail"
        role="dialog"
      >
        <header className={styles.tutorialDialogHeader}>
          <div>
            <p className={styles.brandTop}>Group Detail</p>
            <h3>18185NE-JGS11.dwg</h3>
          </div>
        </header>
        <div className={styles.tutorialDialogBody}>
          <div className={styles.detailGrid}>
            <div className={styles.infoBlock}>
              <span>当前阶段</span>
              <strong>任务包完成</strong>
            </div>
            <div className={styles.infoBlock}>
              <span>进度</span>
              <strong>100%</strong>
            </div>
          </div>
          <div className={styles.downloadGrid}>
            <button className={styles.downloadButton} type="button">
              下载任务包
            </button>
            <button className={styles.downloadButton} type="button">
              下载 IED
            </button>
            <button className={styles.downloadButton} type="button">
              下载纠错报告
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function DeliverableTutorialOverlay({
  step,
  stepIndex,
  totalSteps,
  onClose,
  onNext,
  onPrevious,
}: {
  step: (typeof DELIVERABLE_TUTORIAL_STEPS)[number];
  stepIndex: number | null;
  totalSteps: number;
  onClose: () => void;
  onNext: () => void;
  onPrevious: () => void;
}) {
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const previousBodyPaddingRight = document.body.style.paddingRight;
    const previousBodyWidth = document.body.style.width;
    const previousHtmlOverflow = document.documentElement.style.overflow;
    const scrollbarWidth = Math.max(0, window.innerWidth - document.documentElement.clientWidth);

    document.documentElement.style.overflow = "hidden";
    document.body.style.overflow = "hidden";
    document.body.style.width = "100%";
    if (scrollbarWidth > 0) {
      document.body.style.paddingRight = `${scrollbarWidth}px`;
    }

    return () => {
      document.documentElement.style.overflow = previousHtmlOverflow;
      document.body.style.overflow = previousOverflow;
      document.body.style.paddingRight = previousBodyPaddingRight;
      document.body.style.width = previousBodyWidth;
    };
  }, []);

  return (
    <>
      <TutorialSpotlight stepId={step.id} />
      <aside className={styles.tutorialPanel} role="dialog" aria-label="教程浮层">
        <p className={styles.brandTop}>Deliverable Tutorial</p>
        <h2>{step.title}</h2>
        <p className={styles.brandBody}>{step.body}</p>
        <div className={styles.tutorialAuditHint}>当前为演示模式，不会创建真实任务，也不会改动任务记录。</div>
        <div className={styles.tutorialActions}>
          <button
            className={styles.secondaryActionButton}
            disabled={stepIndex === 0}
            type="button"
            onClick={onPrevious}
          >
            上一步
          </button>
          <button
            className={styles.primaryActionButton}
            disabled={stepIndex !== null && stepIndex >= totalSteps - 1}
            type="button"
            onClick={onNext}
          >
            下一步
          </button>
          <button className={styles.subtleButton} type="button" onClick={onClose}>
            退出
          </button>
        </div>
      </aside>

      {step.id === "picker_select" && <TutorialFilePicker stepId={step.id} />}
      {step.id === "config" && <TutorialConfigDialog />}
      {step.id === "record" && <TutorialRecordScene />}
      {step.id === "detail" && <TutorialDetailDialog />}
    </>
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
        detail.isGroup ? (
          <GroupDetailPanel adapter={adapter} detail={detail} />
        ) : (
          <SingleJobDetailPanel detail={detail} hasWarnings={hasWarnings} />
        )
      ) : (
        <section className={styles.detailPanel}>
          <p className={styles.muted}>正在加载任务详情…</p>
        </section>
      )}
    </div>
  );
}

function SingleJobDetailPanel({
  detail,
  hasWarnings,
}: {
  detail: JobDetail;
  hasWarnings: boolean;
}) {
  const stageLabel = getStageLabel(detail.stage, detail);
  const messageLabel = getMessageLabel(detail);

  return (
    <section className={styles.detailPanel}>
      <header className={styles.detailHeader}>
        <div>
          <p className={styles.brandTop}>Job Detail</p>
          <h1>{detail.sourceFilename}</h1>
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
        <InfoBlock label="任务类型" value={getTaskKindLabel(detail.taskKind ?? "deliverable")} />
        <InfoBlock label="当前阶段" value={stageLabel} />
        <InfoBlock label="进度" value={`${detail.percent}%`} />
        <InfoBlock label="当前文件" value={detail.currentFile ?? "-"} />
        <InfoBlock label="状态说明" value={messageLabel} />
        <InfoBlock
          label="完成时间"
          value={detail.finishedAt ? formatTimestamp(detail.finishedAt) : "-"}
        />
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
          <AuditResultCard
            affectedDrawingsCount={detail.affectedDrawingsCount}
            findingGroups={detail.findingGroups}
            findingsCount={detail.findingsCount}
          />
        </section>
      ) : null}

      {detail.taskKind === "deliverable" ? (
        <section className={styles.detailSection}>
          <h2>出图结果</h2>
          <DeliverableResultCard
            outputs={detail.deliverableOutputs}
            sourceFilename={detail.sourceFilename}
          />
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
        <div className={styles.downloadGrid}>{renderArtifactButtons(detail)}</div>
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
  );
}

function GroupDetailPanel({ adapter, detail }: { adapter: ApiAdapter; detail: JobDetail }) {
  const childJobs = detail.children ?? [];
  const stageLabel = getStageLabel(detail.stage, detail);
  const messageLabel = getMessageLabel(detail);
  const childDetailQueries = useQueries({
    queries: childJobs.map((child) => ({
      queryKey: ["group-child-detail", child.jobId],
      queryFn: () => adapter.getJobDetail(child.jobId),
      refetchInterval: ACTIVE_JOB_STATUSES.includes(child.status as never) ? 3000 : false,
    })),
  });
  const childDetailsById = useMemo(
    () =>
      new Map(
        childJobs.map((child, index) => [child.jobId, childDetailQueries[index]?.data] as const),
      ),
    [childDetailQueries, childJobs],
  );

  return (
    <section className={styles.detailPanel}>
      <header className={styles.detailHeader}>
        <div>
          <p className={styles.brandTop}>Group Detail</p>
          <h1>{detail.sourceFilename}</h1>
        </div>
        <StatusPill status={detail.status} />
      </header>

      <section className={styles.detailSection}>
        <h2>任务包概览</h2>
        <div className={styles.detailGrid}>
          <InfoBlock label="当前阶段" value={stageLabel} />
          <InfoBlock label="进度" value={`${detail.percent}%`} />
          <InfoBlock label="状态说明" value={messageLabel} />
          <InfoBlock
            label="子任务数"
            value={String(Math.max(childJobs.length, detail.childJobIds.length))}
          />
          <InfoBlock label="已启用纠错" value={detail.runAuditCheck ? "是" : "否"} />
          <InfoBlock
            label="完成时间"
            value={detail.finishedAt ? formatTimestamp(detail.finishedAt) : "-"}
          />
        </div>
        <div className={styles.progressBarLarge}>
          <div style={{ width: `${detail.percent}%` }} />
        </div>
      </section>

      <section className={styles.detailSection}>
        <h2>聚合下载</h2>
        <div className={styles.downloadGrid}>
          <ArtifactButton href={detail.artifacts.packageDownloadUrl ?? undefined} label="下载任务包" />
          <ArtifactButton href={detail.artifacts.iedDownloadUrl ?? undefined} label="下载 IED" />
          <ArtifactButton
            href={detail.artifacts.reportDownloadUrl ?? undefined}
            label="下载纠错报告"
          />
        </div>
      </section>

      <section className={styles.detailSection}>
        <h2>子任务</h2>
        <div className={styles.childTaskList}>
          {childJobs.map((child) => (
            <div className={styles.childTaskCard} key={child.jobId}>
              <div className={styles.jobCardHeader}>
                <div className={styles.childTaskTitle}>
                  <strong>{child.taskRole ?? child.jobId}</strong>
                  {child.taskKind ? <TaskKindBadge kind={child.taskKind} /> : null}
                </div>
                <StatusPill status={child.status} />
              </div>

              {child.taskKind === "deliverable" ? (
                <DeliverableResultCard
                  outputs={childDetailsById.get(child.jobId)?.deliverableOutputs}
                  sourceFilename={child.sourceFilename}
                />
              ) : child.taskKind === "audit_check" ? (
                <AuditResultCard
                  affectedDrawingsCount={
                    childDetailsById.get(child.jobId)?.affectedDrawingsCount ??
                    child.affectedDrawingsCount
                  }
                  findingGroups={childDetailsById.get(child.jobId)?.findingGroups}
                  findingsCount={
                    childDetailsById.get(child.jobId)?.findingsCount ?? child.findingsCount
                  }
                />
              ) : (
                <p className={styles.muted}>暂无可展示的子任务结果。</p>
              )}

              <div className={styles.childTaskActions}>
                <Link className={styles.subtaskLink} to={`/jobs/${child.jobId}`}>
                  查看子任务 {child.taskRole ?? child.jobId}
                </Link>
                <div className={styles.childTaskDownloads}>{renderArtifactButtons(child)}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className={styles.detailSection}>
        <h2>告警与错误</h2>
        <div className={styles.columns}>
          <ListBlock title="Flags" items={detail.flags} emptyText="暂无 flags" />
          <ListBlock title="Errors" items={detail.errors} emptyText="暂无 errors" />
        </div>
      </section>
    </section>
  );
}

function DeliverableResultCard({
  outputs,
  sourceFilename,
}: {
  outputs: DeliverableOutputs | undefined;
  sourceFilename: string;
}) {
  if (!outputs) {
    return <p className={styles.muted}>正在整理出图结果。</p>;
  }

  return (
    <div className={styles.resultStack}>
      <div className={styles.resultSummaryGrid}>
        <InfoBlock label="DWG 数量" value={String(outputs.dwgCount)} />
        <InfoBlock label="PDF 数量" value={String(outputs.pdfCount)} />
        <InfoBlock label="文档数量" value={String(outputs.documents.length)} />
      </div>

      <div className={styles.resultSectionBlock}>
        <h3>拆图结果</h3>
        {outputs.drawings.length > 0 ? (
          <div className={styles.outputGrid}>
            {outputs.drawings.map((drawing) => (
              <div className={styles.outputCard} key={drawing.name || drawing.internalCode || sourceFilename}>
                <strong>{drawing.internalCode ?? drawing.name ?? sourceFilename}</strong>
                <span>{drawing.name || sourceFilename}</span>
                <ul className={styles.outputMetaList}>
                  <li>DWG：{drawing.dwgName ?? "-"}</li>
                  <li>PDF：{drawing.pdfName ?? "-"}</li>
                  <li>页数：{formatPageTotal(drawing.pageTotal)}</li>
                </ul>
              </div>
            ))}
          </div>
        ) : (
          <p className={styles.muted}>当前没有拆图结果。</p>
        )}
      </div>

      <div className={styles.resultSectionBlock}>
        <h3>文档结果</h3>
        {outputs.documents.length > 0 ? (
          <div className={styles.outputGrid}>
            {outputs.documents.map((document) => (
              <div className={styles.documentCard} key={document.name}>
                <strong>{document.name}</strong>
                <span>{document.kind.toUpperCase() || "文档"}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className={styles.muted}>当前没有文档产物。</p>
        )}
      </div>
    </div>
  );
}

function AuditResultCard({
  findingsCount,
  affectedDrawingsCount,
  findingGroups,
}: {
  findingsCount: number;
  affectedDrawingsCount: number;
  findingGroups: FindingGroup[] | undefined;
}) {
  const groups = findingGroups ?? [];

  return (
    <div className={styles.resultStack}>
      <div className={styles.resultSummaryGrid}>
        <InfoBlock label="总错误数" value={String(findingsCount)} />
        <InfoBlock label="受影响图纸数" value={String(affectedDrawingsCount)} />
      </div>

      <div className={styles.resultSectionBlock}>
        <h3>错误与图纸编号</h3>
        {groups.length > 0 ? (
          <div className={styles.findingGroupList}>
            {groups.map((group) => (
              <div className={styles.findingGroupCard} key={group.matchedText}>
                <div className={styles.findingGroupHeader}>
                  <strong>{group.matchedText}</strong>
                  <span className={styles.jobMetric}>命中 {group.count}</span>
                </div>
                <div className={styles.findingCodeList}>
                  {group.internalCodes.map((internalCode) => (
                    <span className={styles.findingCodePill} key={`${group.matchedText}-${internalCode}`}>
                      {internalCode}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : findingsCount > 0 ? (
          <p className={styles.muted}>正在整理纠错结果。</p>
        ) : (
          <p className={styles.muted}>未发现错误。</p>
        )}
      </div>
    </div>
  );
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.titleStripHealthItem} data-testid="title-strip-status-item">
      <span className={styles.titleStripHealthItemLabel}>{label}</span>
      <strong className={styles.titleStripHealthItemValue}>{value}</strong>
    </div>
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
  return <span className={`${styles.kindBadge} ${kindToneClass(kind)}`}>{getTaskKindLabel(kind)}</span>;
}

function StatusPill({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? { label: status, tone: "default" };
  return <span className={`${styles.statusPill} ${statusToneClass(meta.tone)}`}>{meta.label}</span>;
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

function renderArtifactButtons(job: JobSummary) {
  if (job.taskKind === "deliverable") {
    return [
      <ArtifactButton
        href={job.artifacts.packageDownloadUrl ?? undefined}
        key="package"
        label="下载 package.zip"
      />,
      <ArtifactButton
        href={job.artifacts.iedDownloadUrl ?? undefined}
        key="ied"
        label="下载 IED计划.xlsx"
      />,
    ];
  }

  if (job.taskKind === "audit_check") {
    return [
      <ArtifactButton
        href={job.artifacts.reportDownloadUrl ?? undefined}
        key="report"
        label="下载 report.xlsx"
      />,
    ];
  }

  return [
    <ArtifactButton
      href={job.artifacts.replacedDwgDownloadUrl ?? undefined}
      key="replaced-dwg"
      label="下载替换后 DWG"
    />,
  ];
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

function formatPageTotal(pageTotal: number) {
  if (!pageTotal || pageTotal < 1) {
    return "-";
  }
  return `${pageTotal} 页`;
}
