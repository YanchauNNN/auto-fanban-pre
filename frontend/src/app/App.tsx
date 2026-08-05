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
  useInfiniteQuery,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Suspense,
  useCallback,
  useEffect,
  useDeferredValue,
  useLayoutEffect,
  isValidElement,
  lazy,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  BrowserRouter,
  Link,
  Navigate,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";

import groupLogoUrl from "../assets/group-logo.jpg";
import loginPlantHeroUrl from "../assets/login-plant-hero.jpg";
import nuclearPlantHeroUrl from "../assets/nuclear-plant-hero.jpg";
import structureLogoWatermarkUrl from "../assets/structure-logo-watermark.jpg";
import { AiChatDrawer } from "../features/ai-chat/AiChatDrawer";
import { CalculationBookTaskWarnings } from "../features/calculation-book/CalculationBookTaskWarnings";
import type {
  ApiAdapter,
  CalculationBookOutput,
  CreateBatchPayload,
  DeliverableOutputs,
  FontReplacementMap,
  FindingGroup,
  JobDetail,
  JobList,
  JobsActivity,
  JobSummary,
  TaskKind,
} from "../platform/api/types";
import { useApiAdapter } from "../platform/api/useApiAdapter";
import "../shared/global.css";
import { SessionProvider, useSession } from "../shared/session/SessionContext";
import styles from "./App.module.css";
import { AccountModulePanel, WorkloadModulePanel, type AccountPanelMode } from "./ModulePanels";
import { RoutePlaceholder } from "./RoutePlaceholder";
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
const JOBS_MODAL_PAGE_SIZE = 50;
const BACKEND_CONNECTION_INTERRUPTED_MESSAGE = "后台服务连接中断，请检查后端服务或代理配置。";
const BACKEND_BUSINESS_HEALTH_WARNING_MESSAGE = "后台业务健康异常";
const BACKEND_HEALTH_PROBE_RETRYING_MESSAGE = "后台健康检查重试中";
const CONNECTION_REFETCH_INTERVAL_MS = 12000;
const CONNECTION_RETRY_COUNT = 2;
const CONNECTION_RECENT_SUCCESS_GRACE_MS = 60000;
const CONNECTION_RETRY_BASE_DELAY_MS = 100;
const HEALTH_REFETCH_INTERVAL_MS = 20000;
const HEALTH_RETRY_COUNT = 1;
const HEALTH_STALE_TIME_MS = 10000;
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
const CalculationBookWorkspace = lazy(async () => ({
  default: (await import("../features/calculation-book/CalculationBookWorkspace"))
    .CalculationBookWorkspace,
}));
const PreviewPdfModal = lazy(async () => ({
  default: (await import("./PreviewPdfModal")).PreviewPdfModal,
}));

const JOB_FILTER_OPTIONS: Array<{ label: string; value?: string }> = [
  { label: "全部" },
  { label: "排队中", value: "queued" },
  { label: "运行中", value: "running" },
  { label: "成功", value: "succeeded" },
  { label: "失败", value: "failed" },
];

const FAILED_JOB_CONTACT_NOTICE =
  "点击“查看任务”查看错误原因进行检查，如有需要请联系开发人员：王任超。";

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
type ArtifactDownloadHandler = (url: string, label: string) => void;

function useArtifactDownload(adapter: ApiAdapter): ArtifactDownloadHandler {
  return useCallback(
    (url, label) => {
      if (adapter.downloadArtifact) {
        void adapter.downloadArtifact(url, label).catch((error: unknown) => {
          console.error("Failed to download job artifact", error);
        });
        return;
      }
      window.location.href = url;
    },
    [adapter],
  );
}

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
  failureReason: TUTORIAL_GROUP_SUMMARY.failureReason ?? null,
  stageContext: TUTORIAL_GROUP_SUMMARY.stageContext ?? null,
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
  ping: async () => ({
    ok: true,
    serverTime: TUTORIAL_CREATED_AT,
  }),
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
  createSplitOnlyBatch: async () => {
    throw new Error("Tutorial preview cannot create real tasks.");
  },
  createAuditCheck: async () => {
    throw new Error("Tutorial preview cannot create real tasks.");
  },
  createAuditReplace: async () => {
    throw new Error("Tutorial preview cannot create real tasks.");
  },
  createCalculationBook: async () => {
    throw new Error("Tutorial preview cannot create real tasks.");
  },
  rememberAuditReplaceFactoryCodes: async () => ({ factoryCodes: [] }),
  listJobs: async () => ({
    total: 1,
    items: [TUTORIAL_GROUP_SUMMARY],
  }),
  getJobsActivity: async () => ({
    total: 1,
    active: 0,
    lastChangedAt: TUTORIAL_FINISHED_AT,
  }),
  getJobDetail: async (jobId: string) => {
    const detail = TUTORIAL_DETAIL_LOOKUP.get(jobId);
    if (!detail) {
      throw new Error(`Missing tutorial preview detail for ${jobId}.`);
    }
    return detail;
  },
  getAiState: async () => ({
    enabled: false,
    profile: "tutorial",
    model: "",
    ownerKey: "tutorial",
    defaultAgent: "platform_assistant",
    attachments: {
      enabled: false,
      allowedExtensions: [],
      maxFilesPerMessage: 0,
      maxImageSizeMb: 0,
      maxFileSizeMb: 0,
      maxTotalSizeMbPerMessage: 0,
    },
    agents: [],
    skills: [],
    mcpServers: [],
  }),
  listAiConversations: async () => [],
  createAiConversation: async () => {
    throw new Error("Tutorial preview cannot create AI conversations.");
  },
  getAiConversation: async () => {
    throw new Error("Tutorial preview cannot load AI conversations.");
  },
  renameAiConversation: async () => {
    throw new Error("Tutorial preview cannot rename AI conversations.");
  },
  sendAiMessage: async () => {
    throw new Error("Tutorial preview cannot send AI messages.");
  },
  clearAiConversation: async () => {},
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
  const adapter = useApiAdapter();
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider adapter={adapter}>
        <BrowserRouter
          future={{
            v7_relativeSplatPath: true,
            v7_startTransition: true,
          }}
        >
          <Routes>
            <Route element={<LoginPage />} path="/login" />
            <Route element={<RequireSession><WorkspacePage /></RequireSession>} path="/" />
            <Route
              element={<RequireSession><JobDetailPage /></RequireSession>}
              path="/jobs/:jobId"
            />
            <Route
              element={<RequireSession><JobDetailPage /></RequireSession>}
              path="/task-groups/:jobId"
            />
          </Routes>
        </BrowserRouter>
      </SessionProvider>
    </QueryClientProvider>
  );
}

function RequireSession({ children }: { children: ReactNode }) {
  const { sessionStatus } = useSession();
  if (sessionStatus === "loading") {
    return <RoutePlaceholder description="正在确认登录状态..." title="正在进入平台" />;
  }
  if (sessionStatus === "anonymous") {
    return <Navigate replace to="/login" />;
  }
  return <>{children}</>;
}

function LoginPage() {
  const adapter = useApiAdapter();
  const navigate = useNavigate();
  const { currentAccount, login, sessionStatus } = useSession();
  const [accountId, setAccountId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (sessionStatus === "authenticated" && currentAccount) {
      navigate("/", { replace: true });
    }
  }, [currentAccount, navigate, sessionStatus]);

  const schemaQuery = useQuery({
    queryKey: ["form-schema"],
    queryFn: () => adapter.getFormSchema(),
    staleTime: 60000,
  });
  const defaultPassword = schemaQuery.data?.management?.account.adminCreatedDefaultPassword.trim();

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedAccountId = accountId.trim();
    if (!normalizedAccountId || !password) {
      setError("请输入账号和密码。");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await login({ accountId: normalizedAccountId, password });
      navigate("/", { replace: true });
    } catch {
      setError("登录失败，请确认账号和密码。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main
      className={styles.loginPage}
      style={{ "--login-hero": `url("${loginPlantHeroUrl}")` } as CSSProperties}
    >
      <section className={styles.loginHeroPanel}>
        <div className={styles.loginHeroContent}>
          <img alt="" className={styles.loginLogo} src={groupLogoUrl} />
          <p className={styles.loginEyebrow}>Nuclear Design Workflow</p>
          <h1 className={styles.loginHeroTitle}>核电图纸业务协同平台</h1>
          <p className={styles.loginHeroBody}>统一进入出图、任务审批、账号管理和工作量结算。</p>
        </div>
      </section>
      <section className={styles.loginCardPanel}>
        <form className={styles.loginCard} onSubmit={handleSubmit}>
          <p className={styles.loginCardEyebrow}>Account Login</p>
          <h2>登录平台</h2>
          <label className={styles.loginField} htmlFor="login-account-id">
            账号
            <input
              autoComplete="username"
              className={styles.loginInput}
              id="login-account-id"
              onChange={(event) => setAccountId(event.currentTarget.value)}
              value={accountId}
            />
          </label>
          <label className={styles.loginField} htmlFor="login-password">
            密码
            <input
              autoComplete="current-password"
              className={styles.loginInput}
              id="login-password"
              onChange={(event) => setPassword(event.currentTarget.value)}
              type="password"
              value={password}
            />
          </label>
          {error ? <p className={styles.loginError} role="alert">{error}</p> : null}
          {defaultPassword ? <p className={styles.loginHelper}>管理员新建账号默认密码：{defaultPassword}</p> : null}
          <button className={styles.loginPrimaryButton} disabled={submitting} type="submit">
            {submitting ? "正在登录..." : "登录"}
          </button>
        </form>
      </section>
    </main>
  );
}

function WorkspacePage() {
  const adapter = useApiAdapter();
  const { currentAccount, logout } = useSession();
  const subscribeJobsActivity = adapter.subscribeJobsActivity;
  const reactQueryClient = useQueryClient();
  const deliverableFileInputRef = useRef<HTMLInputElement | null>(null);
  const knownJobStatusesRef = useRef<Map<string, string> | null>(null);
  const notifiedAuditJobIdsRef = useRef<Set<string>>(new Set());
  const lastJobsActivityMarkerRef = useRef<string | null>(null);

  const [jobsStatusFilter, setJobsStatusFilter] = useState<string | undefined>();
  const [highlightedBatchId, setHighlightedBatchId] = useState<string | null>(null);
  const [recentJobsSearch, setRecentJobsSearch] = useState("");
  const [allJobsModalOpen, setAllJobsModalOpen] = useState(false);
  const [activeModule, setActiveModule] = useState<HomeModule>("business");
  const [accountPanelMode, setAccountPanelMode] = useState<AccountPanelMode>("self");
  const [jobsRefreshState, setJobsRefreshState] = useState<"idle" | "refreshing" | "done">("idle");
  const [tutorialStepIndex, setTutorialStepIndex] = useState<number | null>(null);

  const [deliverableConfigOpen, setDeliverableConfigOpen] = useState(false);
  const [deliverableDraftAvailable, setDeliverableDraftAvailable] = useState(false);
  const [incomingFiles, setIncomingFiles] = useState<File[]>([]);
  const [replaceConfigOpen, setReplaceConfigOpen] = useState(false);
  const [pendingReplaceConfig, setPendingReplaceConfig] = useState<{
    sourceProjectNo: string;
    sourceIslandNo: string;
    targetProjectNo: string;
    targetIslandNo: string;
    runDeliverable: boolean;
  } | null>(null);

  const [auditConfigOpen, setAuditConfigOpen] = useState(false);
  const [calculationConfigOpen, setCalculationConfigOpen] = useState(false);
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

  const connectionQuery = useQuery({
    queryKey: ["connection"],
    queryFn: () => adapter.ping(),
    refetchInterval: CONNECTION_REFETCH_INTERVAL_MS,
    retry: CONNECTION_RETRY_COUNT,
    retryDelay: (failureCount) =>
      Math.min(CONNECTION_RETRY_BASE_DELAY_MS * 2 ** failureCount, 1000),
  });

  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: () => adapter.getHealth(),
    refetchInterval: HEALTH_REFETCH_INTERVAL_MS,
    staleTime: HEALTH_STALE_TIME_MS,
    retry: HEALTH_RETRY_COUNT,
    retryDelay: 250,
  });

  const schemaQuery = useQuery({
    queryKey: ["form-schema"],
    queryFn: () => adapter.getFormSchema(),
    staleTime: 60000,
  });
  const actionsReady = Boolean(schemaQuery.data);
  const accountAdminRoles = schemaQuery.data?.management?.account.adminRoles ?? [];
  const isAdmin = Boolean(currentAccount && accountAdminRoles.includes(currentAccount.role));
  const [lastConnectionSuccessAt, setLastConnectionSuccessAt] = useState<number | null>(null);

  useEffect(() => {
    if (connectionQuery.data?.ok) {
      setLastConnectionSuccessAt(Date.now());
    }
  }, [connectionQuery.data?.ok, connectionQuery.data?.serverTime]);

  const hasRecentConnectionSuccess =
    lastConnectionSuccessAt !== null &&
    Date.now() - lastConnectionSuccessAt <= CONNECTION_RECENT_SUCCESS_GRACE_MS;
  const backendConnectionInterrupted =
    connectionQuery.isError &&
    connectionQuery.failureCount > CONNECTION_RETRY_COUNT &&
    !hasRecentConnectionSuccess;
  const backendHealthProbeRetrying =
    !backendConnectionInterrupted && healthQuery.isError && hasRecentConnectionSuccess;
  const backendBusinessHealthWarning =
    !backendConnectionInterrupted && healthQuery.data?.ready === false;
  const entryActionsDisabled = !actionsReady || backendConnectionInterrupted;
  const primaryActionLabel = actionsReady ? "出图" : "正在加载配置";
  const auditActionLabel = actionsReady
    ? auditDraftAvailable
      ? "继续纠错"
      : "纠错"
    : "正在加载配置";

  const jobsQuery = useQuery({
    queryKey: ["jobs", jobsStatusFilter ?? "__all__"],
    queryFn: () => adapter.listJobs(jobsStatusFilter ?? undefined, 0, 100, "created_at"),
    placeholderData: (previous) => previous,
  });
  const jobsActivityQuery = useQuery({
    queryKey: ["jobs-activity"],
    queryFn: () => adapter.getJobsActivity(),
    placeholderData: (previous) => previous,
    refetchInterval: (query) => {
      const activity = query.state.data as JobsActivity | undefined;
      return activity && activity.active > 0 ? 3000 : 12000;
    },
  });
  const jobCards = useMemo(
    () => buildJobCardModels(jobsQuery.data?.items ?? []),
    [jobsQuery.data?.items],
  );
  const deferredRecentJobsSearch = useDeferredValue(recentJobsSearch);
  const normalizedRecentJobsSearch = deferredRecentJobsSearch.trim().toLowerCase();
  const filteredJobCards = useMemo(() => {
    if (!normalizedRecentJobsSearch) {
      return jobCards;
    }

    return jobCards.filter((card) =>
      card.title.toLowerCase().includes(normalizedRecentJobsSearch),
    );
  }, [jobCards, normalizedRecentJobsSearch]);
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
    const activity = jobsActivityQuery.data;
    if (!activity) {
      return;
    }

    const marker = `${activity.total}:${activity.active}:${activity.lastChangedAt ?? ""}`;
    const previousMarker = lastJobsActivityMarkerRef.current;
    lastJobsActivityMarkerRef.current = marker;
    if (previousMarker !== null && previousMarker !== marker) {
      void reactQueryClient.invalidateQueries({ queryKey: ["jobs"] });
    }
  }, [jobsActivityQuery.data, reactQueryClient]);

  useEffect(() => {
    const activity = jobsActivityQuery.data;
    if (!subscribeJobsActivity || !activity || activity.active <= 0) {
      return;
    }

    return subscribeJobsActivity(
      (nextActivity) => {
        reactQueryClient.setQueryData(["jobs-activity"], nextActivity);
      },
      () => {
        void reactQueryClient.invalidateQueries({ queryKey: ["jobs-activity"] });
      },
    );
  }, [jobsActivityQuery.data?.active, reactQueryClient, subscribeJobsActivity]);

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
  }, [adapter, jobsQuery.data?.items]);

  function handleBatchCreated(payload: CreateBatchPayload) {
    setHighlightedBatchId(payload.batchId);
    setDeliverableConfigOpen(false);
    setReplaceConfigOpen(false);
    setAuditConfigOpen(false);
    setCalculationConfigOpen(false);
    void reactQueryClient.invalidateQueries({ queryKey: ["jobs"] });
    void reactQueryClient.invalidateQueries({ queryKey: ["jobs-activity"] });
  }

  function handleDeliverableUploadClick() {
    setPendingReplaceConfig(null);
    deliverableFileInputRef.current?.click();
  }

  function handleReplaceFlowToDeliverable(payload: {
    files: File[];
    replaceConfig: {
      sourceProjectNo: string;
      sourceIslandNo: string;
      targetProjectNo: string;
      targetIslandNo: string;
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
    setCalculationConfigOpen(false);
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
      await Promise.all([jobsQuery.refetch(), jobsActivityQuery.refetch()]);
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
              <div className={styles.titleStripAccountActions}>
                <span className={styles.titleStripAccountName}>
                  {currentAccount?.displayName ?? "未登录"}
                </span>
                <button
                  className={styles.tutorialEntryButton}
                  type="button"
                  onClick={handleOpenTutorial}
                >
                  教程
                </button>
                <button className={styles.tutorialEntryButton} type="button" onClick={() => void logout()}>
                  退出
                </button>
              </div>
            </div>
            {backendConnectionInterrupted ? (
              <p className={styles.titleStripHealthWarning}>后台连接不可达</p>
            ) : backendHealthProbeRetrying ? (
              <p className={styles.titleStripHealthLoading}>
                {BACKEND_HEALTH_PROBE_RETRYING_MESSAGE}
              </p>
            ) : backendBusinessHealthWarning ? (
              <>
                <p className={styles.titleStripHealthWarning}>
                  {BACKEND_BUSINESS_HEALTH_WARNING_MESSAGE}
                </p>
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
                ) : null}
              </>
            ) : healthQuery.data ? (
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
            ) : connectionQuery.isLoading || healthQuery.isLoading ? (
              <p className={styles.titleStripHealthLoading}>正在读取</p>
            ) : (
              <p className={styles.titleStripHealthWarning}>暂时无法连接后台服务</p>
            )}
          </section>
        </div>
        {backendConnectionInterrupted ? (
          <div className={styles.titleStripMaintenanceBanner} role="alert">
            {BACKEND_CONNECTION_INTERRUPTED_MESSAGE}
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
              onClick={() => {
                setActiveModule(module.key);
                if (module.key === "account") {
                  setAccountPanelMode("self");
                }
              }}
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
                      标准化出图
                    </button>
                    <button
                      className={styles.primaryActionButton}
                      aria-busy={!actionsReady}
                      disabled={entryActionsDisabled}
                      type="button"
                      onClick={() => setCalculationConfigOpen(true)}
                    >
                      计算书
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
            <AccountModulePanel
              isAdmin={isAdmin}
              mode={accountPanelMode}
              onModeChange={setAccountPanelMode}
            />
          ) : (
            <WorkloadModulePanel />
          )}
        </main>
      </div>

      {allJobsModalOpen ? (
        <JobsBrowserModal
          adapter={adapter}
          filterValue={jobsStatusFilter}
          searchValue={recentJobsSearch}
          onClose={() => setAllJobsModalOpen(false)}
          onFilterChange={setJobsStatusFilter}
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
          {calculationConfigOpen && schemaQuery.data.calculationBook ? (
            <CalculationBookWorkspace
              adapter={adapter}
              isOpen
              onBatchCreated={handleBatchCreated}
              onClose={() => setCalculationConfigOpen(false)}
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

      {!calculationConfigOpen ? <AiChatDrawer adapter={adapter} /> : null}
    </div>
  );
}

function JobsBrowserModal({
  adapter,
  filterValue,
  searchValue,
  onFilterChange,
  onSearchChange,
  onClose,
}: {
  adapter: ApiAdapter;
  filterValue?: string;
  searchValue: string;
  onFilterChange: (value?: string) => void;
  onSearchChange: (value: string) => void;
  onClose: () => void;
}) {
  const modalJobsQuery = useInfiniteQuery({
    queryKey: ["jobs-browser", filterValue ?? "__all__"],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      adapter.listJobs(filterValue ?? undefined, Number(pageParam), JOBS_MODAL_PAGE_SIZE),
    getNextPageParam: (lastPage, allPages) => {
      const loadedCount = allPages.reduce((sum, page) => sum + page.items.length, 0);
      return loadedCount < lastPage.total ? loadedCount : undefined;
    },
  });
  const loadedJobs = useMemo(
    () => modalJobsQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [modalJobsQuery.data?.pages],
  );
  const loadedCards = useMemo(() => buildJobCardModels(loadedJobs), [loadedJobs]);
  const normalizedSearchValue = searchValue.trim().toLowerCase();
  const visibleCards = useMemo(() => {
    if (!normalizedSearchValue) {
      return loadedCards;
    }

    return loadedCards.filter((card) =>
      card.title.toLowerCase().includes(normalizedSearchValue),
    );
  }, [loadedCards, normalizedSearchValue]);
  const totalJobs = modalJobsQuery.data?.pages[0]?.total ?? 0;
  const remainingJobs = Math.max(totalJobs - loadedJobs.length, 0);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape" || event.defaultPrevented) {
        return;
      }

      event.preventDefault();
      onClose();
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

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
            <button
              className={styles.subtleButton}
              type="button"
              onClick={() => void modalJobsQuery.refetch()}
            >
              {modalJobsQuery.isRefetching ? "刷新中" : "刷新"}
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
          {visibleCards.length > 0 ? (
            visibleCards.map((card) => (
              <JobCard adapter={adapter} card={card} highlighted={false} key={card.key} />
            ))
          ) : modalJobsQuery.isLoading ? (
            <div className={styles.emptyPanel}>
              <p>正在加载任务记录。</p>
            </div>
          ) : (
            <div className={styles.emptyPanel}>
              <p>没有匹配的任务。</p>
            </div>
          )}
        </div>
        {modalJobsQuery.hasNextPage ? (
          <footer className={styles.jobsModalFooter}>
            <button
              className={styles.secondaryActionButton}
              disabled={modalJobsQuery.isFetchingNextPage}
              type="button"
              onClick={() => void modalJobsQuery.fetchNextPage()}
            >
              {modalJobsQuery.isFetchingNextPage
                ? "加载中"
                : remainingJobs > 0
                  ? `加载更多（剩余 ${remainingJobs} 条）`
                  : "加载更多"}
            </button>
          </footer>
        ) : null}
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
  const hasFailureReason = card.status === "failed" && Boolean(card.failureReason);

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
            {card.summary.taskKind ? (
              <TaskKindBadge kind={card.summary.taskKind} jobMode={card.summary.jobMode} />
            ) : null}
            <Link className={styles.subtaskLink} to={`/jobs/${card.jobId}`}>
              查看任务
            </Link>
          </>
        ) : (
          <>
            <span className={`${styles.kindBadge} ${styles.kindGroup}`}>任务包</span>
            {childJobs.map((child) => (
              <Link className={styles.subtaskLink} key={child.jobId} to={`/jobs/${child.jobId}`}>
                {child.taskKind ? <TaskKindBadge kind={child.taskKind} jobMode={child.jobMode} /> : null}
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

      {hasFailureReason ? (
        <>
          <p className={styles.jobFailureReason}>{card.failureReason}</p>
          <p className={styles.jobStageContext}>{card.stageContext ?? card.stageLabel}</p>
        </>
      ) : (
        <>
          <p className={styles.jobStage}>{card.stageLabel}</p>
          <p className={styles.jobMessage}>{card.messageLabel}</p>
        </>
      )}

      {card.status === "failed" ? (
        <p className={styles.failedJobContactNotice} role="note">
          {FAILED_JOB_CONTACT_NOTICE}
        </p>
      ) : null}

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

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape" || event.defaultPrevented) {
        return;
      }

      event.preventDefault();
      onClose();
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

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

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape" || event.defaultPrevented) {
        return;
      }

      if (document.querySelector('[role="dialog"]')) {
        return;
      }

      event.preventDefault();
      navigate("/");
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [navigate]);

  return (
    <div className={styles.detailPage}>
      <button className={styles.backButton} type="button" onClick={() => navigate("/")}>
        返回工作台
      </button>

      {detail ? (
        detail.isGroup ? (
          <GroupDetailPanel adapter={adapter} detail={detail} />
        ) : (
          <SingleJobDetailPanel adapter={adapter} detail={detail} hasWarnings={hasWarnings} />
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
  adapter,
  detail,
  hasWarnings,
}: {
  adapter: ApiAdapter;
  detail: JobDetail;
  hasWarnings: boolean;
}) {
  const [previewRequest, setPreviewRequest] = useState<PreviewRequest | null>(null);
  const downloadArtifact = useArtifactDownload(adapter);
  const readArtifact = adapter.readArtifact;
  const stageLabel = getStageLabel(detail.stage, detail);
  const messageLabel = getMessageLabel(detail);
  const artifactButtons = renderArtifactButtons(
    detail,
    setPreviewRequest,
    adapter.downloadArtifact ? downloadArtifact : undefined,
  );
  const quickDownloadItems = buildQuickDownloadItems(detail, artifactButtons);

  return (
    <section className={styles.detailPanel}>
      <header className={styles.detailHeader}>
        <div>
          <p className={styles.brandTop}>Job Detail</p>
          <h1>{detail.sourceFilename}</h1>
        </div>
        <StatusPill status={detail.status} />
      </header>

      {detail.status === "failed" ? <JobDiagnosticsSection detail={detail} /> : null}

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

      {quickDownloadItems.length > 0 ? (
        <section className={styles.quickDownloadSection}>
          <h2>快捷下载</h2>
          <div className={styles.downloadGrid}>{quickDownloadItems}</div>
        </section>
      ) : null}

      <div className={styles.detailGrid}>
        <InfoBlock
          label="任务类型"
          value={getTaskKindDisplayLabel(detail.taskKind ?? "deliverable", detail.jobMode)}
        />
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
          <h2>标准化出图摘要</h2>
          <ReplaceResultCard
            affectedDrawingsCount={detail.affectedDrawingsCount}
            replaceSummary={detail.replaceSummary}
          />
        </section>
      ) : null}

      {detail.taskKind === "audit_replace" && detail.factoryIndexMap ? (
        <section className={styles.detailSection}>
          <h2>厂房索引图替换</h2>
          <FactoryIndexMapCard factoryIndexMap={detail.factoryIndexMap} />
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

      {detail.taskKind === "calculation_book" ? (
        <section className={styles.detailSection}>
          <h2>计算书结果</h2>
          <CalculationBookResultCard
            output={detail.calculationBookOutput}
            status={detail.status}
          />
        </section>
      ) : null}

      {detail.taskKind === "deliverable" ? (
        <section className={styles.detailSection}>
          <h2>字体处理摘要</h2>
          <FontPreflightCard detail={detail} />
        </section>
      ) : null}

      {detail.status !== "failed" ? <JobDiagnosticsSection detail={detail} /> : null}

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
        <Suspense fallback={null}>
          <PreviewPdfModal
            readArtifact={readArtifact}
            onDownload={adapter.downloadArtifact ? downloadArtifact : undefined}
            title={previewRequest.title}
            url={previewRequest.url}
            onClose={() => setPreviewRequest(null)}
          />
        </Suspense>
      ) : null}
    </section>
  );
}

function GroupDetailPanel({ adapter, detail }: { adapter: ApiAdapter; detail: JobDetail }) {
  const [previewRequest, setPreviewRequest] = useState<PreviewRequest | null>(null);
  const downloadArtifact = useArtifactDownload(adapter);
  const readArtifact = adapter.readArtifact;
  const childJobs = detail.children ?? [];
  const stageLabel = getStageLabel(detail.stage, detail);
  const messageLabel = getMessageLabel(detail);
  const artifactButtons = renderArtifactButtons(
    detail,
    setPreviewRequest,
    adapter.downloadArtifact ? downloadArtifact : undefined,
  );
  const quickDownloadItems = buildQuickDownloadItems(detail, artifactButtons);
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

      {detail.status === "failed" ? <JobDiagnosticsSection detail={detail} /> : null}

      {quickDownloadItems.length > 0 ? (
        <section className={styles.quickDownloadSection}>
          <h2>快捷下载</h2>
          <div className={styles.downloadGrid}>{quickDownloadItems}</div>
        </section>
      ) : null}

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
        <h2>子任务</h2>
        <div className={styles.childTaskList}>
          {childJobs.map((child) => (
            <div className={styles.childTaskCard} key={child.jobId}>
              <div className={styles.jobCardHeader}>
                <div className={styles.childTaskTitle}>
                  <strong>{child.taskRole ?? child.jobId}</strong>
                  {child.taskKind ? (
                    <TaskKindBadge kind={child.taskKind} jobMode={child.jobMode} />
                  ) : null}
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
              </div>
            </div>
          ))}
        </div>
      </section>

      {detail.status !== "failed" ? <JobDiagnosticsSection detail={detail} /> : null}

      {previewRequest ? (
        <Suspense fallback={null}>
          <PreviewPdfModal
            readArtifact={readArtifact}
            onDownload={adapter.downloadArtifact ? downloadArtifact : undefined}
            title={previewRequest.title}
            url={previewRequest.url}
            onClose={() => setPreviewRequest(null)}
          />
        </Suspense>
      ) : null}
    </section>
  );
}

function DrawingQuantityCopy({ value }: { value: string }) {
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">("idle");

  const handleCopy = async () => {
    try {
      await copyPlainText(value);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("failed");
    }
  };

  return (
    <div className={styles.drawingQuantityCopy}>
      <div>
        <span>图纸量（A1等效）</span>
        <strong>{value}</strong>
      </div>
      <button type="button" onClick={handleCopy}>
        {copyStatus === "copied" ? "已复制" : copyStatus === "failed" ? "复制失败" : "复制张数"}
      </button>
    </div>
  );
}

function buildQuickDownloadItems(job: JobSummary, artifactButtons: ReactNode[]) {
  const drawingQuantityText = formatWorkloadQuantity(resolveDrawingQuantity(job));
  if (!drawingQuantityText) {
    return artifactButtons;
  }
  return insertAfterArtifactKey(
    artifactButtons,
    "ied",
    <DrawingQuantityCopy key="drawing-quantity" value={drawingQuantityText} />,
  );
}

function resolveDrawingQuantity(job: JobSummary) {
  const ownQuantity = readJobDrawingQuantity(job);
  if (ownQuantity !== null) {
    return ownQuantity;
  }

  if (!job.isGroup || !job.children?.length) {
    return null;
  }

  const childrenByPriority = [
    ...job.children.filter((child) => child.taskKind === "deliverable"),
    ...job.children.filter((child) => child.taskKind === "audit_check"),
    ...job.children.filter((child) => child.taskKind === "audit_replace"),
    ...job.children,
  ];
  for (const child of childrenByPriority) {
    const childQuantity = readJobDrawingQuantity(child);
    if (childQuantity !== null) {
      return childQuantity;
    }
  }

  return null;
}

function readJobDrawingQuantity(job: JobSummary) {
  const candidates = [
    job.workload?.initialWorkloadA1,
    job.workload?.finalWorkloadA1,
    job.effectiveWorkload,
  ];
  for (const candidate of candidates) {
    if (isUsableDrawingQuantity(candidate)) {
      return candidate;
    }
  }
  return null;
}

function isUsableDrawingQuantity(value: number | null | undefined) {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function insertAfterArtifactKey(
  items: ReactNode[],
  key: string,
  insertedItem: ReactNode,
) {
  const insertIndex = items.findIndex((item) => isValidElement(item) && item.key === key);
  if (insertIndex < 0) {
    return [...items, insertedItem];
  }
  return [...items.slice(0, insertIndex + 1), insertedItem, ...items.slice(insertIndex + 1)];
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

function CalculationBookResultCard({
  output,
  status,
}: {
  output: CalculationBookOutput | undefined;
  status: JobDetail["status"];
}) {
  if (!output) {
    return <p className={styles.muted}>正在整理计算书结果。</p>;
  }

  const templateLabel =
    output.templateType === "internal_structure"
      ? "内部结构计算书"
      : output.templateType === "nuclear_island_plant"
        ? "核岛厂房计算书"
        : output.templateType;

  return (
    <div className={styles.resultStack}>
      <div className={styles.resultSummaryGrid}>
        <InfoBlock label="计算书模板" value={templateLabel} />
        <InfoBlock
          label="配筋来源"
          value={output.reinforcementSource === "ai_suggested" ? "AI 云图建议" : "用户配筋表"}
        />
        <InfoBlock label="配筋图数量" value={`${output.figureCount} 张`} />
        <InfoBlock label="生成文件" value={output.outputFilename} />
      </div>
      {status === "succeeded" ? <CalculationBookTaskWarnings output={output} /> : null}
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
                  <div>
                    {group.category ? (
                      <span className={styles.findingCodePill}>{group.category}</span>
                    ) : null}
                    <strong>{group.matchedText}</strong>
                  </div>
                  <span className={styles.jobMetric}>命中 {group.count}</span>
                </div>
                {group.summary ? <p className={styles.muted}>{group.summary}</p> : null}
                {group.details?.length ? (
                  <ul className={styles.outputMetaList}>
                    {group.details.map((item) => (
                      <li key={`${group.matchedText}-${item}`}>{item}</li>
                    ))}
                  </ul>
                ) : null}
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

function ArtifactButton({
  href,
  label,
  onDownload,
}: {
  href?: string;
  label: string;
  onDownload?: ArtifactDownloadHandler;
}) {
  if (!href) {
    return (
      <button className={styles.disabledAction} disabled type="button">
        {label}
      </button>
    );
  }

  if (!onDownload) {
    return <a className={styles.downloadButton} href={href}>{label}</a>;
  }
  return (
    <button className={styles.downloadButton} type="button" onClick={() => onDownload(href, label)}>
      {label}
    </button>
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
    return <p className={styles.muted}>正在整理标准化出图结果。</p>;
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
        {replaceSummary.sourceIslandNo ? (
          <InfoBlock
            label="来源机组/岛号"
            value={formatUnitOrIslandLabel(replaceSummary.sourceIslandNo)}
          />
        ) : null}
        <InfoBlock label="目标项目号" value={replaceSummary.targetProjectNo} />
        {replaceSummary.targetIslandNo ? (
          <InfoBlock
            label="目标机组/岛号"
            value={formatUnitOrIslandLabel(replaceSummary.targetIslandNo)}
          />
        ) : null}
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

function FactoryIndexMapCard({
  factoryIndexMap,
}: {
  factoryIndexMap: NonNullable<JobDetail["factoryIndexMap"]>;
}) {
  return (
    <div className={styles.resultStack}>
      <div className={styles.resultSummaryGrid}>
        <InfoBlock label="已执行替换" value={factoryIndexMap.applied ? "是" : "否"} />
        <InfoBlock label="动作数量" value={String(factoryIndexMap.actionCount)} />
        <InfoBlock label="调试信息" value={factoryIndexMap.message || "无"} />
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

function DiagnosticPanel({ detail }: { detail: JobDetail }) {
  const diagnostics = detail.diagnostics ?? [];

  if (diagnostics.length === 0) {
    return (
      <div className={styles.columns}>
        <ListBlock title="Flags" items={detail.flags} emptyText="暂无 flags" />
        <ListBlock title="Errors" items={detail.errors} emptyText="暂无 errors" />
      </div>
    );
  }

  return (
    <div className={styles.diagnosticPanel}>
      <div className={styles.diagnosticList}>
        {diagnostics.map((diagnostic, index) => (
          <article
            className={`${styles.diagnosticCard} ${diagnosticSeverityClass(diagnostic.severity)}`}
            key={`${diagnostic.kind}-${diagnostic.title}-${index}`}
          >
            <div className={styles.diagnosticHeader}>
              <span className={styles.diagnosticSeverity}>
                {diagnosticSeverityLabel(diagnostic.severity)}
              </span>
              <h3>{diagnostic.title}</h3>
            </div>
            {diagnostic.summary ? <p className={styles.diagnosticSummary}>{diagnostic.summary}</p> : null}
            {diagnostic.suggestion ? (
              <p className={styles.diagnosticSuggestion}>{diagnostic.suggestion}</p>
            ) : null}
            {diagnostic.details.length > 0 ? (
              <div className={styles.diagnosticDetails}>
                {diagnostic.details.map((detailItem) => (
                  <div className={styles.diagnosticDetailGroup} key={detailItem.label}>
                    <strong>{detailItem.label}</strong>
                    <div className={styles.diagnosticChips}>
                      {detailItem.items.map((item) => (
                        <span className={styles.diagnosticChip} key={item}>
                          {item}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </article>
        ))}
      </div>
      <details className={styles.rawDiagnosticDetails}>
        <summary>展开原始诊断信息</summary>
        <div className={styles.columns}>
          <ListBlock title="Flags" items={detail.flags} emptyText="暂无 flags" />
          <ListBlock title="Errors" items={detail.errors} emptyText="暂无 errors" />
        </div>
      </details>
    </div>
  );
}

function JobDiagnosticsSection({ detail }: { detail: JobDetail }) {
  return (
    <section className={styles.detailSection}>
      <h2>{hasStructuredDiagnostics(detail) ? "问题原因" : "告警与错误"}</h2>
      <DiagnosticPanel detail={detail} />
    </section>
  );
}

function hasStructuredDiagnostics(detail: JobDetail) {
  return Boolean(detail.diagnostics && detail.diagnostics.length > 0);
}

function diagnosticSeverityLabel(severity: string) {
  if (severity === "error") {
    return "错误";
  }
  if (severity === "info") {
    return "提示";
  }
  return "警告";
}

function diagnosticSeverityClass(severity: string) {
  if (severity === "error") {
    return styles.diagnosticError;
  }
  if (severity === "info") {
    return styles.diagnosticInfo;
  }
  return styles.diagnosticWarning;
}

function TaskKindBadge({ kind, jobMode }: { kind: TaskKind; jobMode?: string | null }) {
  return (
    <span className={`${styles.kindBadge} ${kindToneClass(kind)}`}>
      {getTaskKindDisplayLabel(kind, jobMode)}
    </span>
  );
}

function getTaskKindDisplayLabel(kind: TaskKind, jobMode?: string | null) {
  if (jobMode === "split_only") {
    return "仅拆图";
  }
  return getTaskKindLabel(kind);
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
  if (kind === "calculation_book") {
    return styles.kindCalculation;
  }
  return styles.kindDeliverable;
}

function formatUnitOrIslandLabel(unitOrIslandNo: string) {
  const normalizedIslandNo = unitOrIslandNo.trim();
  if (!normalizedIslandNo) {
    return "";
  }
  return `${normalizedIslandNo}号机组/岛`;
}

function renderArtifactButtons(
  job: JobSummary,
  onOpenPreview?: (request: PreviewRequest) => void,
  onDownload?: ArtifactDownloadHandler,
) {
  const labels = {
    package: "下载 package.zip",
    ied: "下载 IED计划.xlsx",
    preview: "预览 PDF",
    previewAnnotated: "预览 PDF（纠错标注）",
    report: "下载 report.xlsx",
    replacedDwg: "下载替换后 DWG",
    calculationDocx: "下载计算书 DOCX",
    calculationLog: "下载诊断日志 JSONL",
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
      ...(job.artifacts.previewAvailable && job.artifacts.previewDownloadUrl
        ? [
            <ArtifactButton
              href={job.artifacts.previewDownloadUrl}
              key="merged-preview-pdf"
              label="下载合并版PDF"
              onDownload={onDownload}
            />,
          ]
        : []),
      <ArtifactButton
        href={job.artifacts.packageDownloadUrl ?? undefined}
        key="package"
        label="下载任务包"
        onDownload={onDownload}
      />,
      ...(job.artifacts.iedAvailable
        ? [
            <ArtifactButton
              href={job.artifacts.iedDownloadUrl ?? undefined}
              key="ied"
              label="下载 IED"
              onDownload={onDownload}
            />,
          ]
        : []),
      <ArtifactButton
        href={job.artifacts.reportDownloadUrl ?? undefined}
        key="report"
        label="下载 report.xlsx"
        onDownload={onDownload}
      />,
      <ArtifactButton
        href={job.artifacts.replacedDwgDownloadUrl ?? undefined}
        key="replaced-dwg"
        label="下载替换后 DWG"
        onDownload={onDownload}
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
        onDownload={onDownload}
      />,
      ...(job.artifacts.iedAvailable
        ? [
            <ArtifactButton
              href={job.artifacts.iedDownloadUrl ?? undefined}
              key="ied"
              label={labels.ied}
              onDownload={onDownload}
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
        onDownload={onDownload}
      />,
    ];
  }

  if (job.taskKind === "calculation_book") {
    return [
      ...(job.artifacts.calculationDocxAvailable &&
      job.artifacts.calculationDocxDownloadUrl
        ? [
            <ArtifactButton
              href={job.artifacts.calculationDocxDownloadUrl}
              key="calculation-docx"
              label={labels.calculationDocx}
              onDownload={onDownload}
            />,
          ]
        : []),
      ...(job.artifacts.calculationLogAvailable &&
      job.artifacts.calculationLogDownloadUrl
        ? [
            <ArtifactButton
              href={job.artifacts.calculationLogDownloadUrl}
              key="calculation-log"
              label={labels.calculationLog}
              onDownload={onDownload}
            />,
          ]
        : []),
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
      onDownload={onDownload}
    />,
    <ArtifactButton
      href={job.artifacts.replacedDwgDownloadUrl ?? undefined}
      key="replaced-dwg"
      label={labels.replacedDwg}
      onDownload={onDownload}
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

function formatWorkloadQuantity(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  return String(Number(value.toFixed(4)));
}

async function copyPlainText(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const textArea = document.createElement("textarea");
  textArea.value = value;
  textArea.setAttribute("readonly", "true");
  textArea.style.position = "fixed";
  textArea.style.left = "-9999px";
  document.body.appendChild(textArea);
  textArea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textArea);
  if (!copied) {
    throw new Error("copy failed");
  }
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

