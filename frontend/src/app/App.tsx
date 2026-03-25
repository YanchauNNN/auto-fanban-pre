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
  Suspense,
  useEffect,
  useDeferredValue,
  useLayoutEffect,
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
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";

import groupLogoUrl from "../assets/group-logo.jpg";
import loginPlantHeroUrl from "../assets/login-plant-hero.jpg";
import nuclearPlantHeroUrl from "../assets/nuclear-plant-hero.jpg";
import structureLogoWatermarkUrl from "../assets/structure-logo-watermark.jpg";
import type {
  ApiAdapter,
  CreateBatchPayload,
  DeliverableOutputs,
  FindingGroup,
  JobDetail,
  JobSummary,
  TaskGroupDetail,
  TaskGroupList,
  TaskKind,
  TaskGroupSummary,
} from "../platform/api/types";
import { useApiAdapter } from "../platform/api/useApiAdapter";
import "../shared/global.css";
import { SessionProvider, useSession } from "../shared/session/SessionContext";
import styles from "./App.module.css";
import {
  getMessageLabel,
  getStageLabel,
  getStatusLabel,
  getTaskKindLabel,
} from "./jobPresentation";
import {
  buildTaskGroupCardModels,
  getArchiveStatusLabel,
  getCurrentNodeLabel,
  getWorkflowStatusLabel,
  type TaskGroupCardModel,
} from "./taskGroupPresentation";

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
const AccountPage = lazy(async () => ({
  default: (await import("../features/account/AccountPage")).AccountPage,
}));
const AccountAdminPage = lazy(async () => ({
  default: (await import("../features/account/AccountAdminPage")).AccountAdminPage,
}));
const WorkloadPage = lazy(async () => ({
  default: (await import("../features/workload/WorkloadPage")).WorkloadPage,
}));

const JOB_FILTER_OPTIONS: Array<{ label: string; value?: string }> = [
  { label: "全部" },
  { label: "排队中", value: "queued" },
  { label: "运行中", value: "running" },
  { label: "成功", value: "succeeded" },
  { label: "失败", value: "failed" },
];

const MODULE_OPTIONS = [
  { key: "business", label: "业务模块", path: "/business" },
  { key: "account", label: "账号模块", path: "/account" },
  { key: "workload", label: "工作量模块", path: "/workload" },
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
const LOGIN_PAGE_STYLE = {
  "--login-hero": `url("${loginPlantHeroUrl}")`,
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
    reportAvailable: false,
    replacedDwgAvailable: false,
    packageDownloadUrl: "/tutorial/download/package.zip",
    iedDownloadUrl: "/tutorial/download/ied.xlsx",
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
    reportAvailable: true,
    replacedDwgAvailable: false,
    packageDownloadUrl: null,
    iedDownloadUrl: null,
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
    reportAvailable: true,
    replacedDwgAvailable: false,
    packageDownloadUrl: "/tutorial/download/package.zip",
    iedDownloadUrl: "/tutorial/download/ied.xlsx",
    reportDownloadUrl: "/tutorial/download/report.xlsx",
    replacedDwgDownloadUrl: null,
  },
  retryAvailable: false,
  taskRole: null,
  sharedRunId: "tutorial-run",
  children: [TUTORIAL_DELIVERABLE_CHILD_SUMMARY, TUTORIAL_AUDIT_CHILD_SUMMARY],
};

const TUTORIAL_TASK_GROUP_SUMMARY: TaskGroupSummary = {
  groupId: TUTORIAL_GROUP_JOB_ID,
  batchId: "tutorial-batch",
  projectNo: TUTORIAL_SAMPLE_PROJECT,
  status: "succeeded",
  createdAt: TUTORIAL_CREATED_AT,
  sourceFilenames: [TUTORIAL_SAMPLE_FILE],
  ownerSnapshot: {
    creatorAccount: "tutorial",
    creatorName: "教程演示",
    creatorRole: "设计人员",
    creatorOffice: "河北分公司-建筑结构所",
    createdByScope: "current_login_user",
    submittedAt: TUTORIAL_CREATED_AT,
  },
  creatorName: "教程演示",
  creatorAccount: "tutorial",
  creatorOffice: "河北分公司-建筑结构所",
  workflowStatus: "archived",
  currentNodeKey: null,
  archiveStatus: "succeeded",
  workload: {
    initialWorkloadA1: 1.2,
    finalWorkloadA1: 1.2,
    oneReviewFactor: 1,
    twoReviewFactor: 1,
    threeReviewFactor: 1,
    settlementStatus: "settled",
    settledAt: TUTORIAL_FINISHED_AT,
    contributorEntries: [],
  },
  effectiveWorkload: 1.2,
  canViewDetail: true,
  canSubmit: false,
  canApprove: false,
  isRelatedToCurrentUser: true,
};

const TUTORIAL_RECORD_CARD: TaskGroupCardModel =
  buildTaskGroupCardModels([TUTORIAL_TASK_GROUP_SUMMARY])[0] ?? {
    key: TUTORIAL_GROUP_JOB_ID,
    groupId: TUTORIAL_GROUP_JOB_ID,
    title: TUTORIAL_SAMPLE_FILE,
    searchText: TUTORIAL_SAMPLE_FILE.toLowerCase(),
    status: "succeeded",
    createdAt: TUTORIAL_CREATED_AT,
    creatorLabel: "教程演示",
    officeLabel: "河北分公司-建筑结构所",
    workflowLabel: "已归档",
    currentNodeLabel: "未进入审批",
    archiveLabel: "已归档",
    effectiveWorkloadLabel: "1.20",
    canViewDetail: true,
    canSubmit: false,
    canApprove: false,
    summary: TUTORIAL_TASK_GROUP_SUMMARY,
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
    files: [
      {
        filename: TUTORIAL_SAMPLE_FILE,
        status: "missing_fonts",
        missingFonts: [],
        detectedStyleCount: 16,
        missingStyleCount: 2,
        fontReplacementApplied: true,
        replacementFont: "simplex.shx",
        replacedStyleCount: 2,
        errors: [],
      },
    ],
  },
  missingFontsDetected: true,
  fontReplacementApplied: true,
  replacementFont: "simplex.shx",
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

const TUTORIAL_TASK_GROUP_DETAIL: TaskGroupDetail = {
  ...TUTORIAL_TASK_GROUP_SUMMARY,
  childJobIds: [TUTORIAL_DELIVERABLE_JOB_ID, TUTORIAL_AUDIT_JOB_ID],
  personnelSnapshot: {
    members: {
      ied_prepared_by: {
        fieldName: "ied_prepared_by",
        rawValue: "教程演示",
        normalizedValue: "教程演示@tutorial",
        matchedAccount: "tutorial",
        matchedName: "教程演示",
        matchStrategy: "exact",
        status: "matched",
        errors: [],
      },
    },
  },
  workflow: {
    status: "archived",
    initiatedAt: TUTORIAL_CREATED_AT,
    initiatedByAccount: "tutorial",
    initiatedByName: "教程演示",
    duplicatePolicy: null,
    overwriteArchiveTarget: null,
    currentNodeKey: null,
    nodes: [
      {
        nodeKey: "one_review",
        nodeLabel: "一审",
        assigneeAccount: "reviewer-a",
        assigneeName: "一审负责人",
        status: "approved",
        factor: 1,
        approvedAt: TUTORIAL_FINISHED_AT,
        actedByAccount: "reviewer-a",
        actedByName: "一审负责人",
      },
      {
        nodeKey: "two_review",
        nodeLabel: "二审",
        assigneeAccount: "reviewer-b",
        assigneeName: "二审负责人",
        status: "approved",
        factor: 1,
        approvedAt: TUTORIAL_FINISHED_AT,
        actedByAccount: "reviewer-b",
        actedByName: "二审负责人",
      },
      {
        nodeKey: "three_review",
        nodeLabel: "三审",
        assigneeAccount: "reviewer-c",
        assigneeName: "三审负责人",
        status: "approved",
        factor: 1,
        approvedAt: TUTORIAL_FINISHED_AT,
        actedByAccount: "reviewer-c",
        actedByName: "三审负责人",
      },
    ],
    archiveStatus: "succeeded",
    archiveRetryCount: 0,
    archiveLastError: null,
    archiveLastAttemptAt: null,
  },
  archive: {
    archiveRootPath: "D:\\Archive",
    targetDir: "D:\\Archive\\tutorial\\2026",
    status: "succeeded",
    overwriteMode: "skip",
    startedAt: TUTORIAL_CREATED_AT,
    completedAt: TUTORIAL_FINISHED_AT,
    lastError: null,
    retryCount: 0,
    lastAttemptAt: TUTORIAL_FINISHED_AT,
    archivedFiles: ["package.zip", "IED.xlsx", "report.xlsx"],
  },
  replacement: {
    albumInternalCode: null,
    revision: null,
    replacedGroupId: null,
    replacedRecordPendingDelete: false,
  },
  legacyVisibility: {
    scope: "owner_only",
    reason: null,
  },
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
  login: async () => {
    throw new Error("Tutorial preview does not support login.");
  },
  logout: async () => ({ ok: true }),
  getMe: async () => ({
    accountId: "tutorial",
    displayName: "教程演示",
    role: "设计人员",
    officeCode: "HB-JG",
    officeName: "河北分公司-建筑结构所",
    valid: true,
    pendingTodoCount: 0,
  }),
  changePassword: async () => {
    throw new Error("Tutorial preview does not support password changes.");
  },
  normalizePersonnel: async () => ({
    normalized: {
      fieldName: "ied_checked_by",
      rawValue: "教程演示",
      normalizedValue: "教程演示@tutorial",
      matchedAccount: "tutorial",
      matchedName: "教程演示",
      matchStrategy: "tutorial",
      status: "matched",
      errors: [],
    },
    candidates: [],
  }),
  getWorkloadMe: async () => ({
    scope: "me",
    filters: {
      startDate: null,
      endDate: null,
      status: null,
      validOnly: false,
    },
    officeName: null,
    totalWorkloadA1: 2.6,
    totalsByAccount: {},
    entries: [
      {
        roleKey: "ied_prepared_by",
        accountId: "tutorial",
        displayName: "教程演示",
        workloadA1: 1.4,
        settledAt: TUTORIAL_FINISHED_AT,
        groupId: TUTORIAL_GROUP_JOB_ID,
        settlementStatus: "settled",
      },
      {
        roleKey: "ied_checked_by",
        accountId: "reviewer-a",
        displayName: "一审负责人",
        workloadA1: 1.2,
        settledAt: TUTORIAL_FINISHED_AT,
        groupId: TUTORIAL_GROUP_JOB_ID,
        settlementStatus: "settled",
      },
    ],
  }),
  getWorkloadOffice: async () => ({
    scope: "office",
    filters: {
      startDate: null,
      endDate: null,
      status: null,
      validOnly: false,
    },
    officeName: "河北分公司-建筑结构所",
    totalWorkloadA1: 3.8,
    totalsByAccount: {},
    entries: [
      {
        roleKey: "ied_prepared_by",
        accountId: "tutorial",
        displayName: "教程演示",
        workloadA1: 2.1,
        settledAt: TUTORIAL_FINISHED_AT,
        groupId: TUTORIAL_GROUP_JOB_ID,
        settlementStatus: "settled",
      },
    ],
  }),
  getWorkloadInstitute: async () => ({
    scope: "institute",
    filters: {
      startDate: null,
      endDate: null,
      status: null,
      validOnly: false,
    },
    officeName: null,
    totalWorkloadA1: 6.4,
    totalsByAccount: {},
    entries: [
      {
        roleKey: "ied_checked_by",
        accountId: "reviewer-a",
        displayName: "一审负责人",
        workloadA1: 1.8,
        settledAt: TUTORIAL_FINISHED_AT,
        groupId: TUTORIAL_GROUP_JOB_ID,
        settlementStatus: "settled",
      },
    ],
  }),
  getWorkloadAdmin: async () => ({
    scope: "admin",
    filters: {
      startDate: null,
      endDate: null,
      status: null,
      validOnly: false,
    },
    officeName: null,
    totalWorkloadA1: 6.4,
    totalsByAccount: {
      tutorial: 2.6,
      "reviewer-a": 1.8,
    },
    entries: [
      {
        roleKey: "ied_checked_by",
        accountId: "reviewer-a",
        displayName: "一审负责人",
        workloadA1: 1.8,
        settledAt: TUTORIAL_FINISHED_AT,
        groupId: TUTORIAL_GROUP_JOB_ID,
        settlementStatus: "settled",
      },
    ],
  }),
  getWorkflowMonitor: async () => ({
    total: 1,
    items: [TUTORIAL_TASK_GROUP_SUMMARY],
  }),
  approveWorkflow: async () => undefined,
  repairCurrentNode: async () => undefined,
  listAccounts: async () => ({
    items: [
      {
        officeCode: "HB-JG",
        officeName: "河北分公司-建筑结构所",
        accountId: "tutorial",
        displayName: "教程演示",
        role: "设计人员",
        password: "password",
        valid: true,
        rowNumber: 1,
        errors: [],
      },
    ],
  }),
  listInvalidAccountRows: async () => ({
    items: [],
  }),
  createAccount: async () => ({
    officeCode: "HB-JG",
    officeName: "河北分公司-建筑结构所",
    accountId: "tutorial-new",
    displayName: "教程新账号",
    role: "设计人员",
    password: "password",
    valid: true,
    rowNumber: 2,
    errors: [],
  }),
  updateAccount: async () => ({
    officeCode: "HB-JG",
    officeName: "河北分公司-建筑结构所",
    accountId: "tutorial",
    displayName: "教程演示",
    role: "设计人员",
    password: "password",
    valid: true,
    rowNumber: 1,
    errors: [],
  }),
  getAdminConfig: async () => ({
    archiveRootPath: "D:\\Archive",
  }),
  patchAdminConfig: async (payload) => payload,
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
  listTaskGroups: async () => ({
    total: 1,
    items: [TUTORIAL_TASK_GROUP_SUMMARY],
  }),
  getTaskGroupDetail: async (groupId: string) => {
    if (groupId !== TUTORIAL_GROUP_JOB_ID) {
      throw new Error(`Missing tutorial task-group detail for ${groupId}.`);
    }
    return TUTORIAL_TASK_GROUP_DETAIL;
  },
  submitTaskGroup: async () => TUTORIAL_TASK_GROUP_DETAIL,
  restartSubmitTaskGroup: async () => TUTORIAL_TASK_GROUP_DETAIL,
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
  const adapter = useApiAdapter();
  const [queryClient] = useState(() => new QueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider adapter={adapter}>
        <BrowserRouter
          future={{
            v7_relativeSplatPath: true,
            v7_startTransition: true,
          }}
        >
          <AppRoutes />
        </BrowserRouter>
      </SessionProvider>
    </QueryClientProvider>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route element={<LoginPage />} path="/login" />
      <Route element={<ProtectedAppShell />}>
        <Route element={<Navigate replace to="/business" />} path="/" />
        <Route element={<WorkspacePage />} path="/business" />
        <Route element={<TaskGroupDetailPage />} path="/task-groups/:groupId" />
        <Route element={<JobDetailPage />} path="/jobs/:jobId" />
        <Route
          element={
            <Suspense fallback={<RoutePlaceholder description="正在加载账号信息..." title="账号模块" />}>
              <AccountPage />
            </Suspense>
          }
          path="/account"
        />
        <Route
          element={
            <AdminOnlyRoute>
              <Suspense
                fallback={<RoutePlaceholder description="正在加载管理员配置..." title="管理员模块" />}
              >
                <AccountAdminPage />
              </Suspense>
            </AdminOnlyRoute>
          }
          path="/account/admin"
        />
        <Route
          element={
            <Suspense fallback={<RoutePlaceholder description="正在加载工作量模块..." title="工作量模块" />}>
              <WorkloadPage />
            </Suspense>
          }
          path="/workload"
        />
      </Route>
    </Routes>
  );
}

function ProtectedAppShell() {
  const { currentAccount, sessionStatus, logout } = useSession();
  const location = useLocation();
  const navigate = useNavigate();

  if (sessionStatus === "loading") {
    return (
      <main className={styles.emptyPanel}>
        <p>正在恢复登录状态...</p>
      </main>
    );
  }

  if (!currentAccount) {
    return <Navigate replace to="/login" />;
  }

  const activeModule = getActiveModule(location.pathname);

  return (
    <div className={styles.appShell}>
      <ShellTitleStrip activeModule={activeModule} />
      <div className={styles.appShellBody}>
        <div className={styles.shellToolbarRow} data-testid="shell-toolbar-row">
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
                  onClick={() => navigate(module.path)}
                >
                  {module.label}
                </button>
              );
            })}
          </nav>
          <header className={styles.sessionToolbar} data-testid="protected-app-nav">
            {currentAccount.role === "管理员" ? (
              <Link className={styles.moduleToolbarButton} to="/account/admin">
                管理员配置
              </Link>
            ) : null}
            <button
              className={styles.moduleToolbarButton}
              onClick={() => void logout()}
              type="button"
            >
              退出登录
            </button>
          </header>
        </div>
        <Outlet />
      </div>
    </div>
  );
}

function ShellTitleStrip({ activeModule }: { activeModule: HomeModule }) {
  const navigate = useNavigate();
  const healthQuery = useBackendHealthQuery();
  const moduleLabel = MODULE_OPTIONS.find((module) => module.key === activeModule)?.label ?? "业务模块";
  const backendUnavailable = isBackendUnavailable({
    hasError: healthQuery.isError,
    health: healthQuery.data,
  });

  return (
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
            {activeModule === "business" ? (
              <button
                className={styles.tutorialEntryButton}
                type="button"
                onClick={() => navigate("/business?tutorial=1")}
              >
                教程
              </button>
            ) : (
              <span className={styles.titleStripModuleTag}>{moduleLabel}</span>
            )}
          </div>
          {healthQuery.data ? (
            <div className={styles.titleStripHealthGrid}>
              <StatRow label="服务" value={healthQuery.data.ready ? "就绪" : "异常"} />
              <StatRow label="存储" value={healthQuery.data.storageWritable ? "正常" : "异常"} />
              <StatRow label="队列" value={`${healthQuery.data.queueDepth} 项`} />
              <StatRow label="AutoCAD" value={healthQuery.data.autocadReady ? "可用" : "缺失"} />
              <StatRow label="Office" value={healthQuery.data.officeReady ? "可用" : "缺失"} />
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
  );
}

function getActiveModule(pathname: string): HomeModule {
  if (pathname.startsWith("/workload")) {
    return "workload";
  }
  if (pathname.startsWith("/account")) {
    return "account";
  }
  return "business";
}

function useBackendHealthQuery({ passive = false }: { passive?: boolean } = {}) {
  const adapter = useApiAdapter();
  return useQuery({
    queryKey: ["health"],
    queryFn: () => adapter.getHealth(),
    refetchInterval: passive ? false : 15000,
    staleTime: passive ? Number.POSITIVE_INFINITY : 0,
    refetchOnMount: passive ? false : true,
    refetchOnWindowFocus: passive ? false : true,
    refetchOnReconnect: passive ? false : true,
    retry: false,
  });
}

export function isBackendUnavailable({
  hasError,
  health,
}: {
  hasError: boolean;
  health?: { ready: boolean } | undefined;
}) {
  if (health) {
    return health.ready === false;
  }

  return hasError;
}

function LoginPage() {
  const navigate = useNavigate();
  const { currentAccount, login, sessionStatus } = useSession();
  const [accountId, setAccountId] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (currentAccount) {
      navigate("/business", { replace: true });
    }
  }, [currentAccount, navigate]);

  if (sessionStatus === "loading") {
    return (
      <main className={styles.emptyPanel}>
        <p>正在恢复登录状态...</p>
      </main>
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setErrorMessage(null);
    try {
      await login({
        accountId: accountId.trim(),
        password,
      });
      navigate("/business", { replace: true });
    } catch (error) {
      setErrorMessage("账号或密码错误，请重试。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className={styles.loginPage} style={LOGIN_PAGE_STYLE}>
      <section className={styles.loginHeroPanel}>
        <div className={styles.loginHeroContent}>
          <div className={styles.loginLogoBadge}>
            <img alt="中核集团标识" className={styles.loginLogo} src={groupLogoUrl} />
          </div>
          <p className={styles.loginEyebrow}>CNPE Structural Drawing Platform</p>
          <h1 className={styles.loginHeroTitle}>中核工程-河北分公司-建筑结构所出图平台</h1>
          <p className={styles.loginHeroBody}>
            面向结构出图、翻版、纠错与流程追踪的一体化工程工作台。
            以稳定的任务链路承接设计交付，把复杂流程收束到更清晰的操作界面里。
          </p>
          <div className={styles.loginFeatureList}>
            <span>统一任务入口</span>
            <span>任务包与审批联动</span>
            <span>交付结果集中追踪</span>
          </div>
        </div>
      </section>
      <section className={styles.loginCardPanel}>
        <form aria-label="登录表单" className={styles.loginCard} onSubmit={handleSubmit}>
          <p className={styles.loginCardEyebrow}>Account Access</p>
          <h2>账号登录</h2>
          <p className={styles.loginCardBody}>
            使用单位账号进入平台，继续处理当前的结构出图与流程任务。
          </p>
          <label className={styles.loginField}>
            <span>账号</span>
            <input
              autoComplete="username"
              className={styles.loginInput}
              name="account_id"
              onChange={(event) => setAccountId(event.currentTarget.value)}
              required
              value={accountId}
            />
          </label>
          <label className={styles.loginField}>
            <span>密码</span>
            <input
              autoComplete="current-password"
              className={styles.loginInput}
              name="password"
              onChange={(event) => setPassword(event.currentTarget.value)}
              required
              type="password"
              value={password}
            />
          </label>
          <p className={styles.loginHelper}>默认密码password</p>
          {errorMessage ? (
            <p className={styles.loginError} role="alert">
              {errorMessage}
            </p>
          ) : null}
          <button
            aria-busy={submitting}
            className={styles.loginPrimaryButton}
            disabled={submitting}
            type="submit"
          >
            {submitting ? "登录中..." : "登录"}
          </button>
        </form>
      </section>
      <div className={styles.loginBackdropGlow} />
    </main>
  );
}

function AdminOnlyRoute({ children }: { children: ReactNode }) {
  const { currentAccount, sessionStatus } = useSession();
  if (sessionStatus === "loading") {
    return (
      <main className={styles.emptyPanel}>
        <p>正在恢复登录状态...</p>
      </main>
    );
  }
  if (currentAccount?.role !== "管理员") {
    return <Navigate replace to="/business" />;
  }
  return <>{children}</>;
}

function RoutePlaceholder({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <main className={styles.emptyPanel}>
      <h1>{title}</h1>
      <p>{description}</p>
    </main>
  );
}

function WorkspacePage() {
  const adapter = useApiAdapter();
  const reactQueryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const deliverableFileInputRef = useRef<HTMLInputElement | null>(null);
  const knownJobStatusesRef = useRef<Map<string, string> | null>(null);
  const notifiedAuditJobIdsRef = useRef<Set<string>>(new Set());

  const [jobsStatusFilter, setJobsStatusFilter] = useState<string | undefined>();
  const [highlightedBatchId, setHighlightedBatchId] = useState<string | null>(null);
  const [recentJobsSearch, setRecentJobsSearch] = useState("");
  const [allJobsModalOpen, setAllJobsModalOpen] = useState(false);
  const [jobsRefreshState, setJobsRefreshState] = useState<"idle" | "refreshing" | "done">("idle");
  const [taskGroupActionError, setTaskGroupActionError] = useState<string | null>(null);
  const [taskGroupSubmittingId, setTaskGroupSubmittingId] = useState<string | null>(null);
  const [taskGroupConflict, setTaskGroupConflict] = useState<{
    groupId: string;
    kind: "archive" | "duplicate";
  } | null>(null);
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

  const healthQuery = useBackendHealthQuery({ passive: true });

  const schemaQuery = useQuery({
    queryKey: ["form-schema"],
    queryFn: () => adapter.getFormSchema(),
    staleTime: 60000,
  });
  const actionsReady = Boolean(schemaQuery.data);
  const backendUnavailable = isBackendUnavailable({
    hasError: healthQuery.isError,
    health: healthQuery.data,
  });
  const entryActionsDisabled = !actionsReady || backendUnavailable;
  const primaryActionLabel = actionsReady ? "出图" : "正在加载配置";
  const auditActionLabel = actionsReady
    ? auditDraftAvailable
      ? "继续纠错"
      : "纠错"
    : "正在加载配置";

  const taskGroupsQuery = useQuery({
    queryKey: ["task-groups"],
    queryFn: () => adapter.listTaskGroups(),
    refetchInterval: (query) => {
      const items = (query.state.data as TaskGroupList | undefined)?.items ?? [];
      const hasActive = items.some((item) => ACTIVE_JOB_STATUSES.includes(item.status as never));
      return hasActive ? 3000 : 12000;
    },
  });

  const taskGroupCards = useMemo(
    () => buildTaskGroupCardModels(taskGroupsQuery.data?.items ?? []),
    [taskGroupsQuery.data?.items],
  );
  const deferredRecentJobsSearch = useDeferredValue(recentJobsSearch);
  const normalizedRecentJobsSearch = deferredRecentJobsSearch.trim().toLowerCase();
  const statusFilteredTaskGroupCards = useMemo(() => {
    if (!jobsStatusFilter) {
      return taskGroupCards;
    }

    return taskGroupCards.filter((card) => card.status === jobsStatusFilter);
  }, [taskGroupCards, jobsStatusFilter]);
  const filteredTaskGroupCards = useMemo(() => {
    if (!normalizedRecentJobsSearch) {
      return statusFilteredTaskGroupCards;
    }

    return statusFilteredTaskGroupCards.filter((card) =>
      card.searchText.includes(normalizedRecentJobsSearch),
    );
  }, [normalizedRecentJobsSearch, statusFilteredTaskGroupCards]);
  const hiddenJobCardCount = normalizedRecentJobsSearch
    ? 0
    : Math.max(filteredTaskGroupCards.length - DEFAULT_VISIBLE_JOB_CARDS, 0);
  const visibleTaskGroupCards = normalizedRecentJobsSearch
    ? filteredTaskGroupCards
    : filteredTaskGroupCards.slice(0, DEFAULT_VISIBLE_JOB_CARDS);
  const tutorialShowsRecordPreview = tutorialStep?.id === "record" || tutorialStep?.id === "detail";
  const displayedTaskGroupCards = tutorialShowsRecordPreview
    ? [TUTORIAL_RECORD_CARD, ...visibleTaskGroupCards]
    : visibleTaskGroupCards;

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
    const items = taskGroupsQuery.data?.items;
    if (!items) {
      return;
    }

    const currentStatuses = new Map(items.map((group) => [group.groupId, group.status]));
    const previousStatuses = knownJobStatusesRef.current;
    knownJobStatusesRef.current = currentStatuses;

    if (!previousStatuses) {
      return;
    }

    const completedGroups = items.filter((group) => {
      const previousStatus = previousStatuses.get(group.groupId);
      return (
        previousStatus !== undefined &&
        ACTIVE_JOB_STATUSES.includes(previousStatus as never) &&
        group.status === "succeeded" &&
        !notifiedAuditJobIdsRef.current.has(group.groupId)
      );
    });

    if (completedGroups.length === 0) {
      return;
    }

    completedGroups.forEach((group) => {
      notifiedAuditJobIdsRef.current.add(group.groupId);
    });

    let active = true;

    void (async () => {
      const summaries: JobDetail[] = [];
      const passedWithoutFindings: string[] = [];

      for (const group of completedGroups) {
        try {
          const detail = await adapter.getTaskGroupDetail(group.groupId);
          const childDetails = await Promise.all(
            detail.childJobIds.map(async (childJobId) => adapter.getJobDetail(childJobId)),
          );
          const auditDetail = childDetails.find((child) => child.taskKind === "audit_check");
          if (!auditDetail) {
            continue;
          }
          if (auditDetail.findingsCount > 0) {
            summaries.push(auditDetail);
          } else {
            passedWithoutFindings.push(detail.sourceFilenames[0] ?? detail.groupId);
          }
        } catch {
          // list polling will continue; the user can still open the detail page manually
        }
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
  }, [adapter, taskGroupsQuery.data]);

  function handleBatchCreated(payload: CreateBatchPayload) {
    setHighlightedBatchId(payload.batchId);
    setDeliverableConfigOpen(false);
    setReplaceConfigOpen(false);
    setAuditConfigOpen(false);
    void reactQueryClient.invalidateQueries({ queryKey: ["task-groups"] });
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
      await taskGroupsQuery.refetch();
      setJobsRefreshState("done");
      jobsRefreshResetTimerRef.current = window.setTimeout(() => {
        setJobsRefreshState("idle");
        jobsRefreshResetTimerRef.current = null;
      }, 1200);
    } catch {
      setJobsRefreshState("idle");
    }
  }

  async function submitTaskGroup(
    groupId: string,
    payload: { overwriteArchiveExisting: boolean; cancelExistingInProgress: boolean },
  ) {
    setTaskGroupSubmittingId(groupId);
    setTaskGroupActionError(null);
    try {
      const detail = await adapter.submitTaskGroup(groupId, payload);
      setTaskGroupConflict(null);
      setHighlightedBatchId(detail.batchId);
      await reactQueryClient.invalidateQueries({ queryKey: ["task-groups"] });
    } catch (error) {
      const apiError = error as { status?: number; detail?: unknown };
      if (apiError.status === 422 && apiError.detail === "archive_target_exists") {
        setTaskGroupConflict({ groupId, kind: "archive" });
      } else if (apiError.status === 422 && apiError.detail === "duplicate_in_progress_exists") {
        setTaskGroupConflict({ groupId, kind: "duplicate" });
      } else if (apiError.status === 422 && apiError.detail === "submitter_must_match_creator") {
        setTaskGroupActionError("仅创建者本人可提交");
      } else {
        setTaskGroupActionError("提交失败，请稍后重试。");
      }
    } finally {
      setTaskGroupSubmittingId(null);
    }
  }

  function handleTaskGroupSubmit(groupId: string) {
    void submitTaskGroup(groupId, {
      overwriteArchiveExisting: false,
      cancelExistingInProgress: false,
    });
  }

  function handleConfirmTaskGroupConflict() {
    if (!taskGroupConflict) {
      return;
    }

    void submitTaskGroup(taskGroupConflict.groupId, {
      overwriteArchiveExisting: taskGroupConflict.kind === "archive",
      cancelExistingInProgress: taskGroupConflict.kind === "duplicate",
    });
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

  useEffect(() => {
    if (new URLSearchParams(location.search).get("tutorial") !== "1") {
      return;
    }

    setDeliverableConfigOpen(false);
    setReplaceConfigOpen(false);
    setAuditConfigOpen(false);
    setPendingReplaceConfig(null);
    setTutorialStepIndex(0);
    setAllJobsModalOpen(false);
    navigate("/business", { replace: true });
  }, [location.search, navigate]);

  const activeAuditSummary = auditSummaryQueue[0] ?? null;

  return (
    <div className={styles.workspacePage}>
      <div className={styles.shell}>
        <main className={styles.mainColumn}>
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

                {taskGroupActionError ? (
                  <p className={styles.jobMessage} role="alert">
                    {taskGroupActionError}
                  </p>
                ) : null}

                <div className={styles.jobsGrid}>
                  {displayedTaskGroupCards.length > 0 ? (
                    displayedTaskGroupCards.map((card) => {
                      const isTutorialRecordCard = card.key === TUTORIAL_RECORD_CARD.key;
                      const node = (
                        <TaskGroupCard
                          card={card}
                          highlighted={Boolean(
                            !isTutorialRecordCard &&
                              card.summary.batchId &&
                              card.summary.batchId === highlightedBatchId,
                          )}
                          isSubmitting={!isTutorialRecordCard && taskGroupSubmittingId === card.groupId}
                          onSubmit={isTutorialRecordCard ? undefined : handleTaskGroupSubmit}
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
        </main>
      </div>

      {allJobsModalOpen ? (
        <JobsBrowserModal
          cards={filteredTaskGroupCards}
          filterValue={jobsStatusFilter}
          refreshState={jobsRefreshState}
          searchValue={recentJobsSearch}
          onClose={() => setAllJobsModalOpen(false)}
          onFilterChange={setJobsStatusFilter}
          onRefresh={handleJobsRefresh}
          onSearchChange={setRecentJobsSearch}
        />
      ) : null}

      {taskGroupConflict ? (
        <TaskGroupConflictDialog
          kind={taskGroupConflict.kind}
          onClose={() => setTaskGroupConflict(null)}
          onConfirm={handleConfirmTaskGroupConflict}
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
  cards,
  filterValue,
  refreshState,
  searchValue,
  onFilterChange,
  onSearchChange,
  onRefresh,
  onClose,
}: {
  cards: TaskGroupCardModel[];
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
              <TaskGroupCard card={card} highlighted={false} isSubmitting={false} key={card.key} />
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

function TaskGroupCard({
  card,
  highlighted,
  isSubmitting,
  onSubmit,
}: {
  card: TaskGroupCardModel;
  highlighted: boolean;
  isSubmitting: boolean;
  onSubmit?: (groupId: string) => void;
}) {
  return (
    <div
      className={`${styles.jobCard} ${highlighted ? styles.jobCardHighlight : ""}`}
      data-testid="recent-job-card"
    >
      <div className={styles.jobCardHeader}>
        <strong>{card.title}</strong>
        <div className={styles.jobCardHeaderMeta}>
          <p className={styles.packageMeta}>{card.creatorLabel}</p>
          <StatusPill status={card.status} />
        </div>
      </div>

      <div className={styles.jobMetaRow}>
        <span className={`${styles.kindBadge} ${styles.kindGroup}`}>任务包</span>
        <span className={styles.jobMetric}>{card.officeLabel}</span>
        <span className={styles.jobMetric}>{`工作量 ${card.effectiveWorkloadLabel}`}</span>
      </div>

      <p className={styles.jobStage}>{`流程：${card.workflowLabel}`}</p>
      <p className={styles.jobMessage}>{`${card.currentNodeLabel} · 归档：${card.archiveLabel}`}</p>

      <div className={styles.jobMetaRow}>
        {card.canViewDetail ? (
          <Link className={styles.subtaskLink} to={`/task-groups/${card.groupId}`}>
            查看任务包
          </Link>
        ) : null}
        {card.canSubmit ? (
          <button
            className={styles.subtaskLink}
            disabled={isSubmitting}
            type="button"
            onClick={() => onSubmit?.(card.groupId)}
          >
            {isSubmitting ? "提交中..." : "提交"}
          </button>
        ) : null}
        {card.canApprove ? (
          <Link className={styles.subtaskLink} to="/workload">
            前往审批
          </Link>
        ) : null}
      </div>
    </div>
  );
}

function TaskGroupConflictDialog({
  kind,
  onClose,
  onConfirm,
}: {
  kind: "archive" | "duplicate";
  onClose: () => void;
  onConfirm: () => void;
}) {
  const title = kind === "archive" ? "归档冲突确认" : "重复流程确认";
  const description =
    kind === "archive"
      ? "归档目标已存在，是否覆盖归档后继续提交？"
      : "已有同图册流程在执行中，是否取消旧流程并重新提交？";
  const confirmLabel = kind === "archive" ? "继续提交" : "取消旧流程并重提";

  return (
    <div className={styles.jobsModalBackdrop}>
      <div aria-label={title} aria-modal="true" className={styles.jobsModal} role="dialog">
        <header className={styles.jobsModalHeader}>
          <div>
            <p className={styles.brandTop}>Submit Conflict</p>
            <h2>{title}</h2>
          </div>
        </header>
        <p className={styles.jobMessage}>{description}</p>
        <div className={styles.jobsModalActions}>
          <button className={styles.secondaryActionButton} type="button" onClick={onClose}>
            取消
          </button>
          <button className={styles.primaryActionButton} type="button" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
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
  const childDetailsById = new Map<string, JobDetail>([
    [TUTORIAL_DELIVERABLE_JOB_ID, TUTORIAL_DELIVERABLE_CHILD_DETAIL],
    [TUTORIAL_AUDIT_JOB_ID, TUTORIAL_AUDIT_CHILD_DETAIL],
  ]);

  return (
    <div className={styles.tutorialScene}>
      <div className={styles.tutorialDetailPreview} data-tutorial-target="detail">
        <div className={styles.detailPage}>
          <TaskGroupDetailPanel
            childDetailsById={childDetailsById}
            detail={TUTORIAL_TASK_GROUP_DETAIL}
          />
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

function TaskGroupDetailPage() {
  const adapter = useApiAdapter();
  const navigate = useNavigate();
  const params = useParams();

  const detailQuery = useQuery({
    queryKey: ["task-group-detail", params.groupId],
    queryFn: () => adapter.getTaskGroupDetail(params.groupId ?? ""),
    enabled: Boolean(params.groupId),
    refetchInterval: (query) => {
      const data = query.state.data as TaskGroupDetail | undefined;
      return data && ACTIVE_JOB_STATUSES.includes(data.status as never) ? 3000 : 12000;
    },
  });

  const childJobIds = detailQuery.data?.childJobIds ?? [];
  const childDetailQueries = useQueries({
    queries: childJobIds.map((childJobId) => ({
      queryKey: ["task-group-child-detail", childJobId],
      queryFn: () => adapter.getJobDetail(childJobId),
      enabled: Boolean(detailQuery.data),
    })),
  });
  const childDetailsById = useMemo(
    () =>
      new Map(
        childJobIds.flatMap((childJobId, index) => {
          const detail = childDetailQueries[index]?.data;
          return detail ? ([[childJobId, detail]] as const) : [];
        }),
      ),
    [childDetailQueries, childJobIds],
  );

  return (
    <div className={styles.detailPage}>
      <button className={styles.backButton} type="button" onClick={() => navigate("/business")}>
        返回工作台
      </button>

      {detailQuery.data ? (
        <TaskGroupDetailPanel childDetailsById={childDetailsById} detail={detailQuery.data} />
      ) : (
        <section className={styles.detailPanel}>
          <p className={styles.muted}>正在加载任务包详情…</p>
        </section>
      )}
    </div>
  );
}

function TaskGroupDetailPanel({
  detail,
  childDetailsById,
}: {
  detail: TaskGroupDetail;
  childDetailsById: Map<string, JobDetail>;
}) {
  const childDetails = detail.childJobIds
    .map((childJobId) => childDetailsById.get(childJobId))
    .filter((child): child is JobDetail => Boolean(child));
  const aggregateArtifacts = deriveTaskGroupArtifacts(childDetails);
  const personnelEntries = Object.values(detail.personnelSnapshot.members);
  const title = detail.sourceFilenames[0] ?? detail.groupId;

  return (
    <section className={styles.detailPanel}>
      <header className={styles.detailHeader}>
        <div>
          <p className={styles.brandTop}>Task Group Detail</p>
          <h1>{title}</h1>
        </div>
        <StatusPill status={detail.status} />
      </header>

      <section className={styles.detailSection}>
        <h2>任务包概览</h2>
        <div className={styles.detailGrid}>
          <InfoBlock label="创建者" value={detail.creatorName ?? "-"} />
          <InfoBlock label="科室" value={detail.creatorOffice ?? "-"} />
          <InfoBlock label="流程状态" value={getWorkflowStatusLabel(detail.workflowStatus)} />
          <InfoBlock label="当前节点" value={getCurrentNodeLabel(detail.currentNodeKey)} />
          <InfoBlock label="归档状态" value={getArchiveStatusLabel(detail.archiveStatus)} />
          <InfoBlock label="有效工作量" value={detail.effectiveWorkload.toFixed(2)} />
        </div>
      </section>

      <section className={styles.detailSection}>
        <h2>流程状态</h2>
        {detail.workflow.nodes.length > 0 ? (
          <div className={styles.outputGrid}>
            {detail.workflow.nodes.map((node) => (
              <div className={styles.outputCard} key={node.nodeKey}>
                <strong>{node.nodeLabel}</strong>
                <span>{`状态：${node.status}`}</span>
                <ul className={styles.outputMetaList}>
                  <li>{`处理人：${node.assigneeName ?? "-"}`}</li>
                  <li>{`系数：${node.factor.toFixed(2)}`}</li>
                </ul>
              </div>
            ))}
          </div>
        ) : (
          <p className={styles.muted}>当前尚未进入审批流程。</p>
        )}
      </section>

      <section className={styles.detailSection}>
        <h2>归档状态</h2>
        <div className={styles.detailGrid}>
          <InfoBlock label="归档目录" value={detail.archive.targetDir ?? "-"} />
          <InfoBlock label="归档根路径" value={detail.archive.archiveRootPath ?? "-"} />
          <InfoBlock label="覆盖模式" value={detail.archive.overwriteMode ?? "-"} />
          <InfoBlock label="最近错误" value={detail.archive.lastError ?? "-"} />
        </div>
      </section>

      <section className={styles.detailSection}>
        <h2>人员快照</h2>
        {personnelEntries.length > 0 ? (
          <div className={styles.outputGrid}>
            {personnelEntries.map((personnel) => (
              <div className={styles.outputCard} key={personnel.fieldName}>
                <strong>{personnel.fieldName}</strong>
                <span>{personnel.normalizedValue ?? personnel.rawValue ?? "-"}</span>
                <ul className={styles.outputMetaList}>
                  <li>{`匹配账号：${personnel.matchedAccount ?? "-"}`}</li>
                  <li>{`状态：${personnel.status}`}</li>
                </ul>
              </div>
            ))}
          </div>
        ) : (
          <p className={styles.muted}>暂无人员快照。</p>
        )}
      </section>

      <section className={styles.detailSection}>
        <h2>聚合下载</h2>
        <div className={styles.downloadGrid}>
          <ArtifactButton href={aggregateArtifacts.packageDownloadUrl ?? undefined} label="下载任务包" />
          <ArtifactButton href={aggregateArtifacts.iedDownloadUrl ?? undefined} label="下载 IED" />
          <ArtifactButton href={aggregateArtifacts.reportDownloadUrl ?? undefined} label="下载 report.xlsx" />
          <ArtifactButton
            href={aggregateArtifacts.replacedDwgDownloadUrl ?? undefined}
            label="下载替换后 DWG"
          />
        </div>
      </section>

      <section className={styles.detailSection}>
        <h2>子任务</h2>
        <div className={styles.childTaskList}>
          {detail.childJobIds.length > 0 ? (
            detail.childJobIds.map((childJobId) => {
              const child = childDetailsById.get(childJobId);
              return (
                <div className={styles.childTaskCard} key={childJobId}>
                  <div className={styles.jobCardHeader}>
                    <div className={styles.childTaskTitle}>
                      <strong>{child?.sourceFilename ?? childJobId}</strong>
                      {child?.taskKind ? <TaskKindBadge kind={child.taskKind} /> : null}
                    </div>
                    {child ? <StatusPill status={child.status} /> : null}
                  </div>

                  {child?.taskKind === "deliverable" ? (
                    <DeliverableResultCard
                      outputs={child.deliverableOutputs}
                      sourceFilename={child.sourceFilename}
                    />
                  ) : child?.taskKind === "audit_check" ? (
                    <AuditResultCard
                      affectedDrawingsCount={child.affectedDrawingsCount}
                      findingGroups={child.findingGroups}
                      findingsCount={child.findingsCount}
                    />
                  ) : child?.taskKind === "audit_replace" ? (
                    <ReplaceResultCard
                      affectedDrawingsCount={child.affectedDrawingsCount}
                      replaceSummary={child.replaceSummary}
                    />
                  ) : (
                    <p className={styles.muted}>正在整理子任务详情。</p>
                  )}

                  <div className={styles.childTaskActions}>
                    <Link className={styles.subtaskLink} to={`/jobs/${childJobId}`}>
                      查看子任务
                    </Link>
                  </div>
                </div>
              );
            })
          ) : (
            <p className={styles.muted}>当前没有子任务。</p>
          )}
        </div>
      </section>
    </section>
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
            label="下载 report.xlsx"
          />
          <ArtifactButton
            href={detail.artifacts.replacedDwgDownloadUrl ?? undefined}
            label="下载替换后 DWG"
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
                  {renderArtifactButtons(child, "child")}
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
    </section>
  );
}

function deriveTaskGroupArtifacts(childDetails: readonly JobDetail[]) {
  const deliverableChild = childDetails.find((child) => child.taskKind === "deliverable");
  const replaceChild = childDetails.find((child) => child.taskKind === "audit_replace");
  const auditChild = childDetails.find((child) => child.taskKind === "audit_check");

  return {
    packageDownloadUrl: deliverableChild?.artifacts.packageDownloadUrl ?? null,
    iedDownloadUrl: deliverableChild?.artifacts.iedDownloadUrl ?? null,
    reportDownloadUrl:
      replaceChild?.artifacts.reportDownloadUrl ?? auditChild?.artifacts.reportDownloadUrl ?? null,
    replacedDwgDownloadUrl: replaceChild?.artifacts.replacedDwgDownloadUrl ?? null,
  };
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

function FontPreflightCard({ detail }: { detail: JobDetail }) {
  const summary = detail.fontPreflightSummary;
  const files = summary?.files ?? [];
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
        <InfoBlock label="替代字体" value={detail.replacementFont ?? "-"} />
        <InfoBlock label="替换样式数" value={String(detail.replacedStyleCount ?? 0)} />
      </div>

      {files.length > 0 ? (
        <div className={styles.resultSectionBlock}>
          <h3>文件级结果</h3>
          <div className={styles.outputGrid}>
            {files.map((file) => (
              <div className={styles.outputCard} key={`${file.filename}-${file.status}`}>
                <strong>{file.filename}</strong>
                <span>{getFontPreflightStatusLabel(file.status)}</span>
                <ul className={styles.outputMetaList}>
                  <li>{`检测样式数：${file.detectedStyleCount}`}</li>
                  <li>{`缺失样式数：${file.missingStyleCount}`}</li>
                  <li>{`替换样式数：${file.replacedStyleCount}`}</li>
                </ul>
              </div>
            ))}
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

function renderArtifactButtons(job: JobSummary, scope: "default" | "child" = "default") {
  const labels =
    scope === "child"
      ? {
          package: "下载子任务 package.zip",
          ied: "下载子任务 IED计划.xlsx",
          report: "下载子任务 report.xlsx",
          replacedDwg: "下载子任务替换后 DWG",
        }
      : {
          package: "下载 package.zip",
          ied: "下载 IED计划.xlsx",
          report: "下载 report.xlsx",
          replacedDwg: "下载替换后 DWG",
        };

  if (job.taskKind === "deliverable") {
    return [
      <ArtifactButton
        href={job.artifacts.packageDownloadUrl ?? undefined}
        key="package"
        label={labels.package}
      />,
      <ArtifactButton
        href={job.artifacts.iedDownloadUrl ?? undefined}
        key="ied"
        label={labels.ied}
      />,
    ];
  }

  if (job.taskKind === "audit_check") {
    return [
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

