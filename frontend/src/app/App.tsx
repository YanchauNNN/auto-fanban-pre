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
import pdfPreviewWorkerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";
import { Document, Page, pdfjs } from "react-pdf";
import {
  Suspense,
  useEffect,
  useDeferredValue,
  useLayoutEffect,
  lazy,
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
import type {
  ApiAdapter,
  CreateBatchPayload,
  DeliverableOutputs,
  FontReplacementMap,
  FindingGroup,
  JobDetail,
  JobList,
  JobSummary,
  TaskKind,
} from "../platform/api/types";
import { useApiAdapter } from "../platform/api/useApiAdapter";
import {
  ensurePromiseWithResolvers,
} from "../shared/pdfPreviewCompat";
import "../shared/global.css";
import styles from "./App.module.css";
import { TaskConfigModal } from "../features/deliverable/TaskConfigModal";
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
const BACKEND_MAINTENANCE_MESSAGE = "后台维护升级中，为您带来的不便十分抱歉（＞人＜；）";
const DeliverableWorkspace = lazy(async () => ({
  default: (await import("../features/deliverable/DeliverableWorkspace")).DeliverableWorkspace,
}));
const ReplaceWorkspace = lazy(async () => ({
  default: (await import("../features/replace/ReplaceWorkspace")).ReplaceWorkspace,
}));
const AuditCheckWorkspace = lazy(async () => ({
  default: (await import("../features/audit-check/AuditCheckWorkspace")).AuditCheckWorkspace,
}));
const AuditCheckSummaryModal = lazy(async () => ({
  default: (await import("../features/audit-check/AuditCheckSummaryModal")).AuditCheckSummaryModal,
}));

ensurePromiseWithResolvers();

pdfjs.GlobalWorkerOptions.workerSrc = pdfPreviewWorkerUrl;

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
type PreviewRequest = {
  title: string;
  url: string;
};

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

const DELIVERABLE_TUTORIAL_STEPS = [
  {
    id: "entry",
    title: "步骤 1 / 5",
    body:
      "先从首页的“新建任务”区域开始。正式使用时，点击这里的“出图”按钮，系统会拉起 DWG 文件选择窗口，整个出图流程就从这里启动。",
  },
  {
    id: "picker_select",
    title: "步骤 2 / 5",
    body:
      "点击“出图”后，浏览器会拉起系统文件选择窗口。正式使用时，需要在文件列表中选中本次要处理的 DWG 图册文件，再点击“打开”，进入任务配置页面。",
  },
  {
    id: "config",
    title: "步骤 3 / 5",
    body:
      "进入任务配置后，需要补齐项目、设计文件、IED 与打印设置等关键参数。若勾选纠错，系统会与出图一起创建为同一任务包，本教程只做流程演示。",
  },
  {
    id: "record",
    title: "步骤 4 / 5",
    body:
      "提交后，下方的任务记录会出现新的任务包卡片。你可以在这里看到任务状态、子任务关系，并点击进入详情页继续查看结果。",
  },
  {
    id: "detail",
    title: "步骤 5 / 5",
    body:
      "最后进入任务包详情页，在下载区获取任务包、IED 计划和纠错报告等产物，这就是完整的出图结果查看和下载流程。",
  },
] as const;

const TUTORIAL_GROUP_JOB_ID = "tutorial-group-detail";
const TUTORIAL_DELIVERABLE_JOB_ID = "tutorial-deliverable-child";
const TUTORIAL_AUDIT_JOB_ID = "tutorial-audit-child";
const TUTORIAL_CREATED_AT = "2026-03-24T10:20:30+08:00";
const TUTORIAL_FINISHED_AT = "2026-03-24T10:38:30+08:00";

const TUTORIAL_DELIVERABLE_CHILD_SUMMARY: JobSummary = {
  jobId: TUTORIAL_DELIVERABLE_JOB_ID,
  batchId: "tutorial-batch",
  isGroup: false,
  groupId: TUTORIAL_GROUP_JOB_ID,
  sourceFilename: TUTORIAL_SAMPLE_FILE,
  sourceFilenames: [TUTORIAL_SAMPLE_FILE],
  taskKind: "deliverable",
  jobMode: "deliverable",
  projectNo: TUTORIAL_SAMPLE_PROJECT,
  status: "succeeded",
  stage: "PACKAGE_ZIP",
  percent: 100,
  message: "",
  createdAt: TUTORIAL_CREATED_AT,
  finishedAt: TUTORIAL_FINISHED_AT,
  runAuditCheck: true,
  childJobIds: [],
  findingsCount: 0,
  affectedDrawingsCount: 0,
  artifacts: {
    packageAvailable: true,
    iedAvailable: true,
    previewAvailable: true,
    previewMode: "plain",
    reportAvailable: false,
    replacedDwgAvailable: false,
    packageDownloadUrl: "/tutorial/download/package.zip",
    iedDownloadUrl: "/tutorial/download/ied.xlsx",
    previewDownloadUrl: "/tutorial/download/preview.pdf",
    reportDownloadUrl: null,
    replacedDwgDownloadUrl: null,
  },
  retryAvailable: false,
  taskRole: "出图子任务",
  sharedRunId: "tutorial-run",
};

const TUTORIAL_AUDIT_CHILD_SUMMARY: JobSummary = {
  jobId: TUTORIAL_AUDIT_JOB_ID,
  batchId: "tutorial-batch",
  isGroup: false,
  groupId: TUTORIAL_GROUP_JOB_ID,
  sourceFilename: TUTORIAL_SAMPLE_FILE,
  sourceFilenames: [TUTORIAL_SAMPLE_FILE],
  taskKind: "audit_check",
  jobMode: "audit_check",
  projectNo: TUTORIAL_SAMPLE_PROJECT,
  status: "succeeded",
  stage: "EXPORT_REPORT",
  percent: 100,
  message: "",
  createdAt: TUTORIAL_CREATED_AT,
  finishedAt: TUTORIAL_FINISHED_AT,
  runAuditCheck: true,
  childJobIds: [],
  findingsCount: 3,
  affectedDrawingsCount: 2,
  artifacts: {
    packageAvailable: false,
    iedAvailable: false,
    previewAvailable: true,
    previewMode: "annotated",
    reportAvailable: true,
    replacedDwgAvailable: false,
    packageDownloadUrl: null,
    iedDownloadUrl: null,
    previewDownloadUrl: "/tutorial/download/preview-annotated.pdf",
    reportDownloadUrl: "/tutorial/download/audit-report.xlsx",
    replacedDwgDownloadUrl: null,
  },
  retryAvailable: false,
  taskRole: "纠错子任务",
  sharedRunId: "tutorial-run",
};

const TUTORIAL_GROUP_SUMMARY: JobSummary = {
  jobId: TUTORIAL_GROUP_JOB_ID,
  batchId: "tutorial-batch",
  isGroup: true,
  groupId: null,
  sourceFilename: TUTORIAL_SAMPLE_FILE,
  sourceFilenames: [TUTORIAL_SAMPLE_FILE],
  taskKind: null,
  jobMode: "group",
  projectNo: TUTORIAL_SAMPLE_PROJECT,
  status: "succeeded",
  stage: "GROUP_COMPLETE",
  percent: 100,
  message: "",
  createdAt: TUTORIAL_CREATED_AT,
  finishedAt: TUTORIAL_FINISHED_AT,
  runAuditCheck: true,
  childJobIds: [TUTORIAL_DELIVERABLE_JOB_ID, TUTORIAL_AUDIT_JOB_ID],
  findingsCount: 3,
  affectedDrawingsCount: 2,
  artifacts: {
    packageAvailable: true,
    iedAvailable: true,
    previewAvailable: true,
    previewMode: "annotated",
    reportAvailable: true,
    replacedDwgAvailable: false,
    packageDownloadUrl: "/tutorial/download/package.zip",
    iedDownloadUrl: "/tutorial/download/ied.xlsx",
    previewDownloadUrl: "/tutorial/download/preview-annotated.pdf",
    reportDownloadUrl: "/tutorial/download/report.xlsx",
    replacedDwgDownloadUrl: null,
  },
  retryAvailable: false,
  taskRole: null,
  sharedRunId: "tutorial-run",
  children: [TUTORIAL_DELIVERABLE_CHILD_SUMMARY, TUTORIAL_AUDIT_CHILD_SUMMARY],
};

const TUTORIAL_RECORD_CARD: JobCardModel = {
  kind: "real_group",
  key: `group:${TUTORIAL_GROUP_JOB_ID}`,
  jobId: TUTORIAL_GROUP_JOB_ID,
  title: TUTORIAL_SAMPLE_FILE,
  status: TUTORIAL_GROUP_SUMMARY.status,
  percent: TUTORIAL_GROUP_SUMMARY.percent,
  stageLabel: getStageLabel(TUTORIAL_GROUP_SUMMARY.stage, TUTORIAL_GROUP_SUMMARY),
  messageLabel: getMessageLabel(TUTORIAL_GROUP_SUMMARY),
  findingsCount: TUTORIAL_GROUP_SUMMARY.findingsCount,
  affectedDrawingsCount: TUTORIAL_GROUP_SUMMARY.affectedDrawingsCount,
  childCount: 2,
  childJobs: [TUTORIAL_DELIVERABLE_CHILD_SUMMARY, TUTORIAL_AUDIT_CHILD_SUMMARY],
  summary: TUTORIAL_GROUP_SUMMARY,
};

const TUTORIAL_DELIVERABLE_CHILD_DETAIL: JobDetail = {
  ...TUTORIAL_DELIVERABLE_CHILD_SUMMARY,
  startedAt: TUTORIAL_CREATED_AT,
  currentFile: null,
  flags: [],
  errors: [],
  topWrongTexts: [],
  topInternalCodes: [],
  deliverableOutputs: {
    dwgCount: 4,
    pdfCount: 4,
    documents: [
      { name: "IED计划表.xlsx", kind: "xlsx" },
      { name: "目录.docx", kind: "docx" },
    ],
    drawings: [
      {
        name: "核岛结构施工图册",
        internalCode: "JGS-101",
        dwgName: "JGS-101.dwg",
        pdfName: "JGS-101.pdf",
        pageTotal: 12,
      },
      {
        name: "基础布置图",
        internalCode: "JGS-102",
        dwgName: "JGS-102.dwg",
        pdfName: "JGS-102.pdf",
        pageTotal: 8,
      },
    ],
  },
  fontPreflightSummary: {
    policy: "replace_missing",
    replacementFonts: {
      shx: "simplex.shx",
    },
    fontMapPath: null,
    fontAlt: null,
    files: [
      {
        filename: TUTORIAL_SAMPLE_FILE,
        status: "missing_fonts",
        missingFonts: [],
        detectedStyleCount: 16,
        missingStyleCount: 2,
        fontReplacementApplied: true,
        replacementFont: "simplex.shx",
        replacementFonts: {
          shx: "simplex.shx",
        },
        replacedStyleCount: 2,
        verifyAfterReplace: null,
        fontReplacementIncomplete: false,
        errors: [],
      },
    ],
  },
  missingFontsDetected: true,
  fontReplacementApplied: true,
  replacementFont: "simplex.shx",
  replacementFonts: {
    shx: "simplex.shx",
  },
  replacedStyleCount: 2,
};

const TUTORIAL_AUDIT_CHILD_DETAIL: JobDetail = {
  ...TUTORIAL_AUDIT_CHILD_SUMMARY,
  startedAt: TUTORIAL_CREATED_AT,
  currentFile: null,
  flags: [],
  errors: [],
  topWrongTexts: ["梁配筋标注不一致"],
  topInternalCodes: ["JGS-101", "JGS-102"],
  findingGroups: [
    {
      matchedText: "梁配筋标注不一致",
      count: 2,
      internalCodes: ["JGS-101", "JGS-102"],
    },
    {
      matchedText: "图签日期未更新",
      count: 1,
      internalCodes: ["JGS-105"],
    },
  ],
};

const TUTORIAL_GROUP_DETAIL: JobDetail = {
  ...TUTORIAL_GROUP_SUMMARY,
  startedAt: TUTORIAL_CREATED_AT,
  currentFile: null,
  flags: [],
  errors: [],
  topWrongTexts: [],
  topInternalCodes: [],
  children: [TUTORIAL_DELIVERABLE_CHILD_SUMMARY, TUTORIAL_AUDIT_CHILD_SUMMARY],
};

const TUTORIAL_DETAIL_LOOKUP = new Map<string, JobDetail>([
  [TUTORIAL_GROUP_JOB_ID, TUTORIAL_GROUP_DETAIL],
  [TUTORIAL_DELIVERABLE_JOB_ID, TUTORIAL_DELIVERABLE_CHILD_DETAIL],
  [TUTORIAL_AUDIT_JOB_ID, TUTORIAL_AUDIT_CHILD_DETAIL],
]);

const TUTORIAL_DELIVERABLE_VALUES = {
  project_no: TUTORIAL_SAMPLE_PROJECT,
  cover_variant: "通用",
  album_title_cn: "建筑结构施工图册",
  subitem_name: "BOP 子项结构施工图",
  file_category: "1.2.1 设计总说明书",
  plot_style_key: "red_wider",
};

const TUTORIAL_PREVIEW_ADAPTER: ApiAdapter = {
  getHealth: async () => ({
    status: "ok",
    ready: true,
    storageWritable: true,
    workerAlive: true,
    queueDepth: 0,
    autocadReady: true,
    officeReady: true,
    serverTime: TUTORIAL_CREATED_AT,
  }),
  getFormSchema: async () => {
    throw new Error("Tutorial preview does not load schema.");
  },
  preflightFonts: async () => ({
    files: [],
    replacementOptions: [],
    replacementOptionsByKind: {},
    defaultReplacementFont: null,
    defaultReplacementFonts: {},
    requiresConfirmation: false,
  }),
  createBatch: async () => {
    throw new Error("Tutorial preview cannot create real tasks.");
  },
  createAuditCheck: async () => {
    throw new Error("Tutorial preview cannot create real tasks.");
  },
  createAuditReplace: async () => {
    throw new Error("Tutorial preview cannot create real tasks.");
  },
  listJobs: async () => ({
    total: 1,
    items: [TUTORIAL_GROUP_SUMMARY],
  }),
  getJobDetail: async (jobId: string) => {
    const detail = TUTORIAL_DETAIL_LOOKUP.get(jobId);
    if (!detail) {
      throw new Error(`Missing tutorial preview detail for ${jobId}.`);
    }
    return detail;
  },
};

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
      return '[data-tutorial-target="picker-trigger"]';
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
  const [tutorialStepIndex, setTutorialStepIndex] = useState<number | null>(null);

  const [deliverableConfigOpen, setDeliverableConfigOpen] = useState(false);
  const [deliverableDraftAvailable, setDeliverableDraftAvailable] = useState(false);
  const [incomingFiles, setIncomingFiles] = useState<File[]>([]);
  const [replaceConfigOpen, setReplaceConfigOpen] = useState(false);
  const [pendingReplaceConfig, setPendingReplaceConfig] = useState<{
    sourceProjectNo: string;
    targetProjectNo: string;
    runDeliverable: boolean;
  } | null>(null);

  const [auditConfigOpen, setAuditConfigOpen] = useState(false);
  const [auditDraftAvailable, setAuditDraftAvailable] = useState(false);
  const [auditSummaryQueue, setAuditSummaryQueue] = useState<JobDetail[]>([]);
  const [auditNotice, setAuditNotice] = useState<string | null>(null);
  const jobsRefreshResetTimerRef = useRef<number | null>(null);
  const tutorialActive = tutorialStepIndex !== null;
  const tutorialStep =
    tutorialStepIndex === null ? null : DELIVERABLE_TUTORIAL_STEPS[tutorialStepIndex];
  const tutorialIncomingFiles = useMemo(
    () => [new File(["tutorial-dwg"], TUTORIAL_SAMPLE_FILE, { type: "application/acad" })],
    [],
  );

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: () => adapter.getHealth(),
    refetchInterval: 15000,
    retry: false,
  });

  const schemaQuery = useQuery({
    queryKey: ["form-schema"],
    queryFn: () => adapter.getFormSchema(),
    staleTime: 60000,
  });
  const actionsReady = Boolean(schemaQuery.data);
  const backendUnavailable = healthQuery.isError || healthQuery.data?.ready === false;
  const entryActionsDisabled = !actionsReady || backendUnavailable;
  const primaryActionLabel = actionsReady ? "出图" : "正在加载配置";
  const auditActionLabel = actionsReady
    ? auditDraftAvailable
      ? "继续纠错"
      : "纠错"
    : "正在加载配置";

  const jobsQuery = useQuery({
    queryKey: ["jobs"],
    queryFn: () => adapter.listJobs(),
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
  const deferredRecentJobsSearch = useDeferredValue(recentJobsSearch);
  const normalizedRecentJobsSearch = deferredRecentJobsSearch.trim().toLowerCase();
  const statusFilteredJobCards = useMemo(() => {
    if (!jobsStatusFilter) {
      return jobCards;
    }

    return jobCards.filter((card) => card.status === jobsStatusFilter);
  }, [jobCards, jobsStatusFilter]);
  const filteredJobCards = useMemo(() => {
    if (!normalizedRecentJobsSearch) {
      return statusFilteredJobCards;
    }

    return statusFilteredJobCards.filter((card) =>
      card.title.toLowerCase().includes(normalizedRecentJobsSearch),
    );
  }, [normalizedRecentJobsSearch, statusFilteredJobCards]);
  const hiddenJobCardCount = normalizedRecentJobsSearch
    ? 0
    : Math.max(filteredJobCards.length - DEFAULT_VISIBLE_JOB_CARDS, 0);
  const visibleJobCards = normalizedRecentJobsSearch
    ? filteredJobCards
    : filteredJobCards.slice(0, DEFAULT_VISIBLE_JOB_CARDS);
  const tutorialShowsRecordPreview = tutorialStep?.id === "record" || tutorialStep?.id === "detail";
  const displayedJobCards = tutorialShowsRecordPreview
    ? [TUTORIAL_RECORD_CARD, ...visibleJobCards]
    : visibleJobCards;

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
    setReplaceConfigOpen(false);
    setAuditConfigOpen(false);
    void reactQueryClient.invalidateQueries({ queryKey: ["jobs"] });
  }

  function handleDeliverableUploadClick() {
    setPendingReplaceConfig(null);
    deliverableFileInputRef.current?.click();
  }

  function handleReplaceFlowToDeliverable(payload: {
    files: File[];
    replaceConfig: {
      sourceProjectNo: string;
      targetProjectNo: string;
      runDeliverable: boolean;
    };
  }) {
    setIncomingFiles(payload.files);
    setPendingReplaceConfig(payload.replaceConfig);
    setReplaceConfigOpen(false);
    setDeliverableConfigOpen(true);
  }

  function handleOpenTutorial() {
    setActiveModule("business");
    setDeliverableConfigOpen(false);
    setReplaceConfigOpen(false);
    setAuditConfigOpen(false);
    setPendingReplaceConfig(null);
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

    setPendingReplaceConfig(null);
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
              <h1>中核工程-河北分公司-建筑结构所出图平台</h1>
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
            ) : healthQuery.isError ? (
              <p className={styles.titleStripHealthWarning}>暂时无法连接后台服务</p>
            ) : (
              <p className={styles.titleStripHealthLoading}>正在读取</p>
            )}
          </section>
        </div>
        {backendUnavailable ? (
          <div className={styles.titleStripMaintenanceBanner} role="alert">
            {BACKEND_MAINTENANCE_MESSAGE}
          </div>
        ) : null}
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
                      data-tutorial-target="picker-trigger"
                      disabled={entryActionsDisabled}
                      type="button"
                      onClick={handleDeliverableUploadClick}
                    >
                      {primaryActionLabel}
                    </button>
                    <button
                      className={styles.primaryActionButton}
                      aria-busy={!actionsReady}
                      disabled={entryActionsDisabled}
                      type="button"
                      onClick={() => setAuditConfigOpen(true)}
                    >
                      {auditActionLabel}
                    </button>
                    <button
                      className={styles.primaryActionButton}
                      aria-busy={!actionsReady}
                      disabled={entryActionsDisabled}
                      type="button"
                      onClick={() => setReplaceConfigOpen(true)}
                    >
                      翻版
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
                        aria-pressed={active}
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
                  {displayedJobCards.length > 0 ? (
                    displayedJobCards.map((card) => {
                      const isTutorialRecordCard = card.key === TUTORIAL_RECORD_CARD.key;
                      const node = (
                        <JobCard
                          adapter={isTutorialRecordCard ? TUTORIAL_PREVIEW_ADAPTER : adapter}
                          card={card}
                          highlighted={Boolean(
                            !isTutorialRecordCard &&
                              card.summary.batchId &&
                              card.summary.batchId === highlightedBatchId,
                          )}
                          key={card.key}
                        />
                      );

                      if (!isTutorialRecordCard) {
                        return node;
                      }

                      return (
                        <div
                          data-testid="tutorial-record-preview"
                          data-tutorial-target={tutorialStep?.id === "record" ? "record" : undefined}
                          key={card.key}
                        >
                          {node}
                        </div>
                      );
                    })
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
        <Suspense fallback={null}>
          {deliverableConfigOpen ? (
            <DeliverableWorkspace
              adapter={adapter}
              incomingFiles={incomingFiles}
              isOpen
              onBatchCreated={handleBatchCreated}
              onClearPendingReplaceFlow={() => setPendingReplaceConfig(null)}
              onNotice={setAuditNotice}
              onClose={() => setDeliverableConfigOpen(false)}
              onDraftAvailabilityChange={setDeliverableDraftAvailable}
              pendingReplaceConfig={pendingReplaceConfig}
              schema={schemaQuery.data}
            />
          ) : null}
          {tutorialStep?.id === "config" ? (
            <DeliverableWorkspace
              adapter={TUTORIAL_PREVIEW_ADAPTER}
              incomingFiles={tutorialIncomingFiles}
              isOpen
              onBatchCreated={() => {}}
              onClearPendingReplaceFlow={() => {}}
              onNotice={() => {}}
              onClose={() => {}}
              onDraftAvailabilityChange={() => {}}
              schema={schemaQuery.data}
              tutorialPreview={{
                dialogTarget: "config",
                initialValues: TUTORIAL_DELIVERABLE_VALUES,
                initialRunAuditCheck: true,
              }}
            />
          ) : null}
          {replaceConfigOpen ? (
            <ReplaceWorkspace
              adapter={adapter}
              isOpen
              onBatchCreated={handleBatchCreated}
              onClose={() => setReplaceConfigOpen(false)}
              onContinueToDeliverable={handleReplaceFlowToDeliverable}
              onDraftAvailabilityChange={() => {}}
              schema={schemaQuery.data}
            />
          ) : null}
          {auditConfigOpen ? (
            <AuditCheckWorkspace
              adapter={adapter}
              isOpen
              onBatchCreated={handleBatchCreated}
              onClose={() => setAuditConfigOpen(false)}
              onDraftAvailabilityChange={setAuditDraftAvailable}
              schema={schemaQuery.data}
            />
          ) : null}
        </Suspense>
      ) : null}

      {activeAuditSummary ? (
        <Suspense fallback={null}>
          <AuditCheckSummaryModal
            job={activeAuditSummary}
            onClose={() => setAuditSummaryQueue((current) => current.slice(1))}
          />
        </Suspense>
      ) : null}

      {tutorialStep?.id === "detail" ? <TutorialGroupDetailPreview /> : null}

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
                aria-pressed={active}
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

function TutorialGroupDetailPreview() {
  return (
    <div className={styles.tutorialScene}>
      <div className={styles.tutorialDetailPreview} data-tutorial-target="detail">
        <div className={styles.detailPage}>
          <GroupDetailPanel adapter={TUTORIAL_PREVIEW_ADAPTER} detail={TUTORIAL_GROUP_DETAIL} />
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
    const previousBodyOverflow = document.body.style.overflow;
    const previousHtmlOverflow = document.documentElement.style.overflow;
    const previousScrollbarGutter = document.documentElement.style.scrollbarGutter;

    document.documentElement.style.overflow = "hidden";
    document.documentElement.style.scrollbarGutter = "stable";
    document.body.style.overflow = "hidden";

    return () => {
      document.documentElement.style.overflow = previousHtmlOverflow;
      document.documentElement.style.scrollbarGutter = previousScrollbarGutter;
      document.body.style.overflow = previousBodyOverflow;
    };
  }, []);

  return (
    <>
      <TutorialSpotlight stepId={step.id} />
      <aside className={styles.tutorialPanel} role="dialog" aria-label="教程浮层">
        <p className={styles.brandTop}>Deliverable Tutorial</p>
        <h2>{step.title}</h2>
        <p className={styles.brandBody}>{step.body}</p>
        <div className={styles.tutorialAuditHint}>
          当前为演示模式，不会创建真实任务，也不会改动任务记录。
        </div>
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
  const [previewRequest, setPreviewRequest] = useState<PreviewRequest | null>(null);
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

      {detail.taskKind === "audit_replace" ? (
        <section className={styles.detailSection}>
          <h2>翻版摘要</h2>
          <ReplaceResultCard
            affectedDrawingsCount={detail.affectedDrawingsCount}
            replaceSummary={detail.replaceSummary}
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

      {detail.taskKind === "deliverable" ? (
        <section className={styles.detailSection}>
          <h2>字体处理摘要</h2>
          <FontPreflightCard detail={detail} />
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
          {renderArtifactButtons(detail, "default", setPreviewRequest)}
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

      {previewRequest ? (
        <PreviewPdfModal
          title={previewRequest.title}
          url={previewRequest.url}
          onClose={() => setPreviewRequest(null)}
        />
      ) : null}
    </section>
  );
}

function GroupDetailPanel({ adapter, detail }: { adapter: ApiAdapter; detail: JobDetail }) {
  const [previewRequest, setPreviewRequest] = useState<PreviewRequest | null>(null);
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
          {renderArtifactButtons(detail, "default", setPreviewRequest)}
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
              ) : child.taskKind === "audit_replace" ? (
                <ReplaceResultCard
                  affectedDrawingsCount={
                    childDetailsById.get(child.jobId)?.affectedDrawingsCount ??
                    child.affectedDrawingsCount
                  }
                  replaceSummary={childDetailsById.get(child.jobId)?.replaceSummary}
                />
              ) : (
                <p className={styles.muted}>暂无可展示的子任务结果。</p>
              )}

              <div className={styles.childTaskActions}>
                <Link className={styles.subtaskLink} to={`/jobs/${child.jobId}`}>
                  查看子任务 {child.taskRole ?? child.jobId}
                </Link>
                <div className={styles.childTaskDownloads}>
                  {renderArtifactButtons(
                    childDetailsById.get(child.jobId) ?? child,
                    "child",
                    setPreviewRequest,
                  )}
                </div>
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

      {previewRequest ? (
        <PreviewPdfModal
          title={previewRequest.title}
          url={previewRequest.url}
          onClose={() => setPreviewRequest(null)}
        />
      ) : null}
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

      {hasSameCodeMultiPageOutputs(outputs) ? (
        <div className={styles.noticeBanner}>
          <strong>同编码多页：目录合并为一行，物理文件按页分别输出</strong>
          <span>物理文件命名会保留后端返回的 X@Y 页码后缀。</span>
        </div>
      ) : null}

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

function FontPreflightCard({ detail }: { detail: JobDetail }) {
  const summary = detail.fontPreflightSummary;
  const files = summary?.files ?? [];
  const replacementFonts = collectEffectiveReplacementFonts(detail);
  const replacementFontEntries = Object.entries(replacementFonts);
  const replacementWarning = getFontReplacementWarning(detail);
  const replacedStyleCount =
    detail.replacedStyleCount ??
    files.reduce((count, file) => count + Math.max(file.replacedStyleCount ?? 0, 0), 0);
  const statusText = detail.fontReplacementApplied
    ? "已执行缺失字体替代"
    : detail.missingFontsDetected
      ? "检测到缺失字体，未执行替代"
      : "未检测到缺失字体";

  return (
    <div className={styles.resultStack}>
      <div className={styles.resultSummaryGrid}>
        <InfoBlock label="处理结果" value={statusText} />
        <InfoBlock label="替代策略" value={summary?.policy || "none"} />
        <InfoBlock label="缺失字体" value={detail.missingFontsDetected ? "已检测到" : "未检测到"} />
        <InfoBlock label="替换样式数" value={String(replacedStyleCount)} />
      </div>

      {replacementFontEntries.length > 0 ? (
        <div className={styles.resultSectionBlock}>
          <h3>最终替代字体</h3>
          <div className={styles.outputGrid}>
            {replacementFontEntries.map(([kind, fontName]) => (
              <div className={styles.outputCard} key={`${kind}:${fontName}`}>
                <strong>{getFontReplacementKindDisplayLabel(kind)}</strong>
                <span>{fontName}</span>
              </div>
            ))}
          </div>
        </div>
      ) : detail.replacementFont ? (
        <div className={styles.resultSectionBlock}>
          <h3>最终替代字体</h3>
          <div className={styles.resultSummaryGrid}>
            <InfoBlock label="统一替代字体" value={detail.replacementFont} />
          </div>
        </div>
      ) : null}

      {replacementWarning ? (
        <section className={styles.warningBanner}>
          <strong>字体已尝试替代，但关键字体可能仍未完全恢复，建议优先补齐原始字体文件。</strong>
          <span>{replacementWarning}</span>
        </section>
      ) : null}

      {summary?.fontMapPath || summary?.fontAlt ? (
        <div className={styles.resultSectionBlock}>
          <h3>字体映射信息</h3>
          <div className={styles.resultSummaryGrid}>
            <InfoBlock label="font_map_path" value={summary?.fontMapPath ?? "-"} />
            <InfoBlock label="font_alt" value={summary?.fontAlt ?? "-"} />
          </div>
        </div>
      ) : null}

      {files.length > 0 ? (
        <div className={styles.resultSectionBlock}>
          <h3>文件级结果</h3>
          <div className={styles.outputGrid}>
            {files.map((file) => {
              const fileReplacementFonts = normalizeFontReplacementMap(file.replacementFonts);

              return (
                <div className={styles.outputCard} key={`${file.filename}-${file.status}`}>
                  <strong>{file.filename}</strong>
                  <span>{getFontPreflightStatusLabel(file.status)}</span>
                  <ul className={styles.outputMetaList}>
                    <li>{`检测样式数：${file.detectedStyleCount}`}</li>
                    <li>{`缺失样式数：${file.missingStyleCount}`}</li>
                    <li>{`替换样式数：${file.replacedStyleCount}`}</li>
                    {Object.keys(fileReplacementFonts).length > 0 ? (
                      <li>{`替代字体：${formatReplacementFontEntrySummary(fileReplacementFonts)}`}</li>
                    ) : file.replacementFont ? (
                      <li>{`替代字体：${file.replacementFont}`}</li>
                    ) : null}
                    {file.verifyAfterReplace ? (
                      <li>{`二次校验：${getFontVerifyStatusLabel(file.verifyAfterReplace.status)}`}</li>
                    ) : null}
                  </ul>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
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

function PreviewButton({
  label,
  onOpen,
}: {
  label: string;
  onOpen: () => void;
}) {
  return (
    <button className={styles.downloadButton} onClick={onOpen} type="button">
      {label}
    </button>
  );
}

function PreviewPdfModal({
  title,
  url,
  onClose,
}: {
  title: string;
  url: string;
  onClose: () => void;
}) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [pageCount, setPageCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pageWidth, setPageWidth] = useState(960);
  const previewPagesRef = useRef<HTMLDivElement | null>(null);
  const previewStatusText = loadError
    ? "预览加载失败"
    : isLoading
      ? "正在加载 PDF..."
      : pageCount > 0
        ? `共 ${pageCount} 页`
        : "正在解析 PDF...";

  useEffect(() => {
    const controller = new AbortController();
    let currentObjectUrl: string | null = null;

    setObjectUrl(null);
    setPageCount(0);
    setIsLoading(true);
    setLoadError(null);

    void fetch(url, {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`preview request failed with status ${response.status}`);
        }

        const blob = await response.blob();
        currentObjectUrl = URL.createObjectURL(blob);
        setObjectUrl(currentObjectUrl);
        setIsLoading(false);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        console.error("Failed to load PDF preview", error);
        setLoadError("PDF 预览加载失败，请使用新窗口打开查看。");
        setIsLoading(false);
      });

    return () => {
      controller.abort();
      if (currentObjectUrl) {
        URL.revokeObjectURL(currentObjectUrl);
      }
    };
  }, [url]);

  useLayoutEffect(() => {
    const node = previewPagesRef.current;
    if (!node) {
      return;
    }

    const updatePageWidth = () => {
      setPageWidth(Math.max(320, Math.floor(node.clientWidth - 48)));
    };

    updatePageWidth();
    if (typeof ResizeObserver === "undefined") {
      return;
    }

    const observer = new ResizeObserver(() => {
      updatePageWidth();
    });
    observer.observe(node);

    return () => {
      observer.disconnect();
    };
  }, []);

  return (
    <TaskConfigModal dialogClassName={styles.previewDialog} title={title}>
      <div className={styles.previewModalContent}>
        <div className={styles.previewModalHeader}>
          <div>
            <p className={styles.brandTop}>Preview PDF</p>
            <h2>{title}</h2>
          </div>
          <div className={styles.previewModalActions}>
            <a
              className={styles.downloadButton}
              href={url}
              rel="noreferrer"
              target="_blank"
            >
              新窗口打开
            </a>
            <button className={styles.secondaryActionButton} onClick={onClose} type="button">
              关闭
            </button>
          </div>
        </div>
        <div className={styles.previewViewerShell}>
          <div className={styles.previewViewerStatusRow}>
            <span className={styles.previewStatusText}>{previewStatusText}</span>
          </div>
          <div className={styles.previewPages} ref={previewPagesRef}>
            {loadError ? (
              <div className={styles.previewFallback} role="status">
                <strong>预览暂时不可用</strong>
                <p>{loadError}</p>
              </div>
            ) : objectUrl ? (
              <Document
                file={objectUrl}
                loading={
                  <div className={styles.previewLoading} role="status">
                    正在渲染 PDF 页面...
                  </div>
                }
                onLoadError={(error) => {
                  console.error("Failed to parse PDF preview", error);
                  setLoadError("PDF 预览加载失败，请使用新窗口打开查看。");
                }}
                onLoadSuccess={({ numPages }) => {
                  setPageCount(numPages);
                }}
              >
                {Array.from({ length: Math.max(pageCount, 1) }, (_, index) => (
                  <div className={styles.previewPageCard} key={`${objectUrl}-${index + 1}`}>
                    <Page
                      pageNumber={index + 1}
                      renderAnnotationLayer={false}
                      renderTextLayer={false}
                      width={pageWidth}
                    />
                    <span className={styles.previewPageNumber}>第 {index + 1} 页</span>
                  </div>
                ))}
              </Document>
            ) : (
              <div className={styles.previewLoading} role="status">
                正在加载 PDF...
              </div>
            )}
          </div>
        </div>
      </div>
    </TaskConfigModal>
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

function ReplaceResultCard({
  affectedDrawingsCount,
  replaceSummary,
}: {
  affectedDrawingsCount: number;
  replaceSummary: JobDetail["replaceSummary"];
}) {
  if (!replaceSummary) {
    return <p className={styles.muted}>正在整理翻版结果。</p>;
  }

  return (
    <div className={styles.resultStack}>
      <div className={styles.resultSummaryGrid}>
        <InfoBlock label="替换数量" value={String(replaceSummary.replacementCount)} />
        <InfoBlock
          label="受影响图纸数"
          value={String(replaceSummary.affectedDrawingsCount || affectedDrawingsCount)}
        />
        <InfoBlock label="源项目号" value={replaceSummary.sourceProjectNo} />
        <InfoBlock label="目标项目号" value={replaceSummary.targetProjectNo} />
      </div>

      <div className={styles.resultSectionBlock}>
        <h3>高频替换文本</h3>
        {replaceSummary.topReplacedTexts.length > 0 ? (
          <div className={styles.outputGrid}>
            {replaceSummary.topReplacedTexts.map((text) => (
              <div className={styles.outputCard} key={text}>
                <strong>替换文本</strong>
                <span>{`文本值：${text}`}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className={styles.muted}>当前没有高频替换文本。</p>
        )}
      </div>

      <div className={styles.resultSectionBlock}>
        <h3>重点图纸编码</h3>
        {replaceSummary.topInternalCodes.length > 0 ? (
          <div className={styles.outputGrid}>
            {replaceSummary.topInternalCodes.map((code) => (
              <div className={styles.outputCard} key={code}>
                <strong>图纸编码</strong>
                <span>{code}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className={styles.muted}>当前没有重点图纸编码。</p>
        )}
      </div>
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
    <div className={styles.listBlock}>
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

function renderArtifactButtons(
  job: JobSummary,
  scope: "default" | "child" = "default",
  onOpenPreview?: (request: PreviewRequest) => void,
) {
  const labels =
    scope === "child"
      ? {
          package: "下载子任务 package.zip",
          ied: "下载子任务 IED计划.xlsx",
          preview: "预览子任务 PDF",
          previewAnnotated: "预览子任务 PDF（纠错标注）",
          report: "下载子任务 report.xlsx",
          replacedDwg: "下载子任务替换后 DWG",
        }
      : {
          package: "下载 package.zip",
          ied: "下载 IED计划.xlsx",
          preview: "预览 PDF",
          previewAnnotated: "预览 PDF（纠错标注）",
          report: "下载 report.xlsx",
          replacedDwg: "下载替换后 DWG",
        };

  const previewButton =
    job.artifacts.previewAvailable &&
    job.artifacts.previewDownloadUrl &&
    onOpenPreview
      ? [
          <PreviewButton
            key="preview"
            label={
              job.artifacts.previewMode === "annotated"
                ? labels.previewAnnotated
                : labels.preview
            }
            onOpen={() =>
              onOpenPreview({
                title:
                  job.artifacts.previewMode === "annotated"
                    ? labels.previewAnnotated
                    : labels.preview,
                url: job.artifacts.previewDownloadUrl ?? "",
              })
            }
          />,
        ]
      : [];

  if (job.isGroup) {
    return [
      ...previewButton,
      <ArtifactButton
        href={job.artifacts.packageDownloadUrl ?? undefined}
        key="package"
        label="下载任务包"
      />,
      ...(job.artifacts.iedAvailable
        ? [
            <ArtifactButton
              href={job.artifacts.iedDownloadUrl ?? undefined}
              key="ied"
              label="下载 IED"
            />,
          ]
        : []),
      <ArtifactButton
        href={job.artifacts.reportDownloadUrl ?? undefined}
        key="report"
        label="下载 report.xlsx"
      />,
      <ArtifactButton
        href={job.artifacts.replacedDwgDownloadUrl ?? undefined}
        key="replaced-dwg"
        label="下载替换后 DWG"
      />,
    ];
  }

  if (job.taskKind === "deliverable") {
    return [
      ...previewButton,
      <ArtifactButton
        href={job.artifacts.packageDownloadUrl ?? undefined}
        key="package"
        label={labels.package}
      />,
      ...(job.artifacts.iedAvailable
        ? [
            <ArtifactButton
              href={job.artifacts.iedDownloadUrl ?? undefined}
              key="ied"
              label={labels.ied}
            />,
          ]
        : []),
    ];
  }

  if (job.taskKind === "audit_check") {
    return [
      ...previewButton,
      <ArtifactButton
        href={job.artifacts.reportDownloadUrl ?? undefined}
        key="report"
        label={labels.report}
      />,
    ];
  }

  if (job.taskKind !== "audit_replace") {
    return [];
  }

  return [
    ...previewButton,
    <ArtifactButton
      href={job.artifacts.reportDownloadUrl ?? undefined}
      key="report"
      label={labels.report}
    />,
    <ArtifactButton
      href={job.artifacts.replacedDwgDownloadUrl ?? undefined}
      key="replaced-dwg"
      label={labels.replacedDwg}
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

function hasSameCodeMultiPageOutputs(outputs: DeliverableOutputs) {
  return outputs.drawings.some((drawing) => {
    const names = [drawing.name, drawing.dwgName, drawing.pdfName].filter(Boolean);
    return names.some((name) => /\d+@\d+/.test(name ?? ""));
  });
}

function getFontPreflightStatusLabel(status: string) {
  switch (status.trim().toLowerCase()) {
    case "ok":
      return "未检测到缺失字体";
    case "missing_fonts":
      return "检测到缺失字体";
    case "failed":
      return "字体预检失败";
    default:
      return status || "-";
  }
}

function getFontVerifyStatusLabel(status: string) {
  switch (status.trim().toLowerCase()) {
    case "ok":
      return "已恢复正常";
    case "missing_fonts":
      return "仍有缺失字体";
    case "failed":
      return "二次校验失败";
    default:
      return status || "-";
  }
}

function collectEffectiveReplacementFonts(detail: JobDetail): FontReplacementMap {
  const summaryFonts = normalizeFontReplacementMap(detail.fontPreflightSummary?.replacementFonts);
  if (Object.keys(summaryFonts).length > 0) {
    return summaryFonts;
  }

  const detailFonts = normalizeFontReplacementMap(detail.replacementFonts);
  if (Object.keys(detailFonts).length > 0) {
    return detailFonts;
  }

  const fileFonts = normalizeFontReplacementMap(
    Object.assign({}, ...(detail.fontPreflightSummary?.files ?? []).map((file) => file.replacementFonts)),
  );
  if (Object.keys(fileFonts).length > 0) {
    return fileFonts;
  }

  const fallbackFont =
    detail.replacementFont?.trim() ||
    (detail.fontPreflightSummary?.files ?? [])
      .map((file) => file.replacementFont?.trim() ?? "")
      .find(Boolean) ||
    "";
  return fallbackFont ? { unified: fallbackFont } : {};
}

function normalizeFontReplacementMap(
  input: Record<string, string> | null | undefined,
): FontReplacementMap {
  if (!input) {
    return {};
  }

  return Object.fromEntries(
    Object.entries(input)
      .map(([kind, value]) => [kind.trim().toLowerCase(), value.trim()])
      .filter(([kind, value]) => Boolean(kind && value)),
  );
}

function getFontReplacementKindDisplayLabel(kind: string) {
  switch (kind.trim().toLowerCase()) {
    case "shx":
      return "SHX";
    case "ttf":
      return "TrueType";
    case "bigfont":
      return "大字体";
    case "unified":
      return "统一替代字体";
    default:
      return kind || "未知类型";
  }
}

function formatReplacementFontEntrySummary(replacementFonts: FontReplacementMap) {
  const entries = Object.entries(normalizeFontReplacementMap(replacementFonts));
  if (entries.length === 0) {
    return "-";
  }
  return entries
    .map(([kind, value]) => `${getFontReplacementKindDisplayLabel(kind)}=${value}`)
    .join("；");
}

function getFontReplacementWarning(detail: JobDetail) {
  const files = detail.fontPreflightSummary?.files ?? [];
  const verifyWarnings = files.filter((file) => {
    const status = file.verifyAfterReplace?.status.trim().toLowerCase() ?? "";
    return Boolean(status && status !== "ok");
  }).length;
  const incompleteFiles = files.filter((file) => file.fontReplacementIncomplete).length;
  const hasIncompleteFlag = detail.flags.some((flag) => flag.includes("FONT_REPLACEMENT_INCOMPLETE"));
  const parts: string[] = [];

  if (verifyWarnings > 0) {
    parts.push(`${verifyWarnings} 个文件二次校验未完全通过`);
  }
  if (incompleteFiles > 0) {
    parts.push(`${incompleteFiles} 个文件仍标记为未完全恢复`);
  }
  if (hasIncompleteFlag) {
    parts.push("命中 FONT_REPLACEMENT_INCOMPLETE");
  }

  return parts.length > 0 ? parts.join(" / ") : null;
}

