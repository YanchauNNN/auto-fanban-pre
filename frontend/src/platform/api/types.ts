export type TaskKind = "deliverable" | "audit_check" | "audit_replace";
export type TaskIntent = TaskKind;

export type FormFieldType = "text" | "select" | "combobox" | "date" | "nameId";

export type CurrentAccount = {
  accountId: string;
  displayName: string;
  role: string;
  officeCode: string | null;
  officeName: string | null;
  valid: boolean;
  pendingTodoCount: number;
};

export type LoginRequest = {
  accountId: string;
  password: string;
};

export type LoginResponse = {
  token: string;
  account: CurrentAccount;
};

export type AccountRecord = {
  officeCode: string | null;
  officeName: string | null;
  accountId: string;
  displayName: string;
  role: string;
  password: string;
  valid: boolean;
  rowNumber: number | null;
  errors: string[];
};

export type InvalidAccountRow = {
  rowNumber: number;
  raw: Record<string, string>;
  errors: string[];
};

export type AccountListResponse = {
  items: AccountRecord[];
};

export type InvalidAccountRowList = {
  items: InvalidAccountRow[];
};

export type AdminConfig = {
  archiveRootPath: string | null;
};

export type AccountCreatePayload = {
  officeCode: string | null;
  officeName: string | null;
  accountId: string;
  displayName: string;
  role: string;
  password: string;
};

export type AccountUpdatePayload = {
  officeCode?: string | null;
  officeName?: string | null;
  accountId?: string;
  displayName?: string;
  role?: string;
  password?: string;
};

export type PersonnelCandidate = {
  accountId: string;
  displayName: string;
  role: string;
  officeCode: string | null;
  officeName: string | null;
  valid: boolean;
};

export type PersonnelNormalizationResult = {
  normalized: NormalizedPersonnel;
  candidates: PersonnelCandidate[];
};

export type TaskOwnerSnapshot = {
  creatorAccount: string;
  creatorName: string;
  creatorRole: string;
  creatorOffice: string | null;
  createdByScope: string;
  submittedAt: string | null;
};

export type NormalizedPersonnel = {
  fieldName: string;
  rawValue: string | null;
  normalizedValue: string | null;
  matchedAccount: string | null;
  matchedName: string | null;
  matchStrategy: string | null;
  status: string;
  errors: string[];
};

export type PersonnelSnapshot = {
  members: Record<string, NormalizedPersonnel>;
};

export type WorkflowNodeState = {
  nodeKey: string;
  nodeLabel: string;
  assigneeAccount: string | null;
  assigneeName: string | null;
  status: string;
  factor: number;
  approvedAt: string | null;
  actedByAccount: string | null;
  actedByName: string | null;
};

export type WorkflowState = {
  status: string;
  initiatedAt: string | null;
  initiatedByAccount: string | null;
  initiatedByName: string | null;
  duplicatePolicy: string | null;
  overwriteArchiveTarget: string | null;
  currentNodeKey: string | null;
  nodes: WorkflowNodeState[];
  archiveStatus: string | null;
  archiveRetryCount: number;
  archiveLastError: string | null;
  archiveLastAttemptAt: string | null;
};

export type ArchiveState = {
  archiveRootPath: string | null;
  targetDir: string | null;
  status: string;
  overwriteMode: string | null;
  startedAt: string | null;
  completedAt: string | null;
  lastError: string | null;
  retryCount: number;
  lastAttemptAt: string | null;
  archivedFiles: string[];
};

export type ReplacementState = {
  albumInternalCode: string | null;
  revision: string | null;
  replacedGroupId: string | null;
  replacedRecordPendingDelete: boolean;
};

export type LegacyVisibilityState = {
  scope: string;
  reason: string | null;
};

export type WorkloadContributorEntry = {
  roleKey: string;
  accountId: string | null;
  displayName: string | null;
  workloadA1: number;
  settledAt: string | null;
};

export type WorkloadSummary = {
  initialWorkloadA1: number;
  finalWorkloadA1: number;
  oneReviewFactor: number;
  twoReviewFactor: number;
  threeReviewFactor: number;
  settlementStatus: string;
  settledAt: string | null;
  contributorEntries: WorkloadContributorEntry[];
};

export type WorkloadQueryParams = {
  startDate?: string;
  endDate?: string;
  status?: string;
  validOnly?: boolean;
};

export type WorkloadQueryFilters = {
  startDate: string | null;
  endDate: string | null;
  status: string | null;
  validOnly: boolean;
};

export type WorkloadScopeEntry = {
  roleKey: string;
  accountId: string | null;
  displayName: string | null;
  workloadA1: number;
  settledAt: string | null;
  groupId: string;
  settlementStatus: string;
};

export type WorkloadScopeResponse = {
  scope: string;
  filters: WorkloadQueryFilters;
  officeName: string | null;
  totalWorkloadA1: number;
  totalsByAccount: Record<string, number>;
  entries: WorkloadScopeEntry[];
};

export type WorkflowMonitorItem = TaskGroupSummary;

export type WorkflowMonitorList = {
  total: number;
  items: WorkflowMonitorItem[];
};

export type WorkflowApprovePayload = {
  factor: number;
  nodeKey?: string | null;
};

export type WorkflowRepairPayload = {
  replaceWithAccountId?: string;
  createAccountPayload?: AccountCreatePayload;
};

export type TaskGroupSummary = {
  groupId: string;
  batchId: string | null;
  projectNo: string | null;
  status: string;
  createdAt: string;
  sourceFilenames: string[];
  ownerSnapshot: TaskOwnerSnapshot | null;
  creatorName: string | null;
  creatorAccount: string | null;
  creatorOffice: string | null;
  workflowStatus: string;
  currentNodeKey: string | null;
  archiveStatus: string;
  workload: WorkloadSummary;
  effectiveWorkload: number;
  canViewDetail: boolean;
  canSubmit: boolean;
  canApprove: boolean;
  isRelatedToCurrentUser: boolean;
};

export type TaskGroupDetail = TaskGroupSummary & {
  childJobIds: string[];
  personnelSnapshot: PersonnelSnapshot;
  workflow: WorkflowState;
  archive: ArchiveState;
  replacement: ReplacementState;
  legacyVisibility: LegacyVisibilityState;
};

export type TaskGroupList = {
  total: number;
  items: TaskGroupSummary[];
};

export type TaskGroupSubmitPayload = {
  overwriteArchiveExisting: boolean;
  cancelExistingInProgress: boolean;
};

export type UploadLimits = {
  maxFiles: number;
  allowedExts: readonly string[];
  maxTotalMb: number;
};

export type FormField = {
  key: string;
  label: string;
  type: FormFieldType;
  required: boolean;
  requiredWhen: string | null;
  defaultValue: string;
  description: string;
  options: readonly string[];
};

export type FormSection = {
  id: string;
  title: string;
  fields: readonly FormField[];
};

export type FormSchema = {
  schemaVersion: string;
  uploadLimits: UploadLimits;
  sections: readonly FormSection[];
  auditReplaceProjectOptions?: readonly string[];
};

export type HealthStatus = {
  status: string;
  ready: boolean;
  storageWritable: boolean;
  workerAlive: boolean;
  queueDepth: number;
  autocadReady: boolean;
  officeReady: boolean;
  serverTime: string;
};

export type JobArtifacts = {
  packageAvailable: boolean;
  iedAvailable: boolean;
  reportAvailable: boolean;
  replacedDwgAvailable: boolean;
  packageDownloadUrl?: string | null;
  iedDownloadUrl?: string | null;
  reportDownloadUrl?: string | null;
  replacedDwgDownloadUrl?: string | null;
};

export type DeliverableDrawingOutput = {
  name: string;
  internalCode: string | null;
  dwgName: string | null;
  pdfName: string | null;
  pageTotal: number;
};

export type DeliverableDocumentOutput = {
  name: string;
  kind: string;
};

export type DeliverableOutputs = {
  dwgCount: number;
  pdfCount: number;
  documents: DeliverableDocumentOutput[];
  drawings: DeliverableDrawingOutput[];
};

export type FindingGroup = {
  matchedText: string;
  count: number;
  internalCodes: string[];
};

export type ReplaceSummary = {
  replacementCount: number;
  skippedCount: number;
  affectedDrawingsCount: number;
  sourceProjectNo: string;
  targetProjectNo: string;
  topReplacedTexts: string[];
  topInternalCodes: string[];
};

export type MissingFontEntry = {
  styleName: string;
  fontName: string;
  bigfontName: string;
  kind: string;
  usedInBlock: boolean;
};

export type FontReplacementOption = {
  label: string;
  value: string;
  family: string;
  path: string;
  kind: string;
  source: string;
};

export type FontPreflightFileResult = {
  filename: string;
  status: string;
  missingFonts: MissingFontEntry[];
  detectedStyleCount: number;
  missingStyleCount: number;
  fontReplacementApplied: boolean;
  replacementFont: string | null;
  replacedStyleCount: number;
  errors: string[];
};

export type FontPreflightResult = {
  files: FontPreflightFileResult[];
  replacementOptions: FontReplacementOption[];
  requiresConfirmation: boolean;
};

export type FontPreflightSummary = {
  files: FontPreflightFileResult[];
  policy: string;
};

export type CreateAuditReplaceParams = {
  sourceProjectNo: string;
  targetProjectNo: string;
  files: File[];
  runDeliverable: boolean;
  deliverableParams?: Record<string, string>;
};

export type JobSummary = {
  jobId: string;
  batchId: string | null;
  isGroup: boolean;
  groupId: string | null;
  sourceFilename: string;
  sourceFilenames: string[];
  taskKind: TaskKind | null;
  jobMode: string | null;
  projectNo: string | null;
  status: string;
  stage: string | null;
  percent: number;
  message: string;
  createdAt: string;
  finishedAt: string | null;
  runAuditCheck: boolean;
  childJobIds: string[];
  findingsCount: number;
  affectedDrawingsCount: number;
  artifacts: JobArtifacts;
  retryAvailable: boolean;
  taskRole: string | null;
  sharedRunId: string | null;
  plotStyleKey?: string | null;
  plotResourceMode?: string | null;
  slotId?: string | null;
  cadVersion?: string | null;
  accoreconsoleExe?: string | null;
  profileArg?: string | null;
  pc3Path?: string | null;
  pmpPath?: string | null;
  ctbPath?: string | null;
  fontPreflightSummary?: FontPreflightSummary | null;
  missingFontsDetected?: boolean;
  fontReplacementApplied?: boolean;
  replacementFont?: string | null;
  replacedStyleCount?: number;
  children?: JobSummary[];
};

export type JobDetail = JobSummary & {
  startedAt: string | null;
  currentFile: string | null;
  flags: string[];
  errors: string[];
  topWrongTexts: string[];
  topInternalCodes: string[];
  sharedDir?: string | null;
  deliverableOutputs?: DeliverableOutputs;
  findingGroups?: FindingGroup[];
  replaceSummary?: ReplaceSummary;
};

export type JobList = {
  total: number;
  items: JobSummary[];
};

export type CreateBatchPayload = {
  batchId: string;
  jobs: JobSummary[];
};

export type UploadProjectInference = {
  inferredProjectNos: string[];
  primaryProjectNo: string;
  hasConflict: boolean;
};

export type ReplaceTaskConfig = {
  sourceProjectNo: string;
  targetProjectNo: string;
};

export type TaskConfigPreset = {
  id: string;
  name: string;
  intent: TaskIntent;
  runAuditCheck: boolean;
  values: Record<string, string>;
  replaceConfig: ReplaceTaskConfig;
  updatedAt: string;
};

export type TaskConfigDraft = {
  intent: TaskIntent;
  runAuditCheck: boolean;
  files: File[];
  values: Record<string, string>;
  fieldErrors: Record<string, string[]>;
  formErrors: string[];
  inference: UploadProjectInference;
  replaceConfig: ReplaceTaskConfig;
};

export type ApiValidationError = {
  upload_errors?: Record<string, string[]>;
  param_errors?: Record<string, string[]>;
};

export type ApiError = {
  status: number;
  detail: ApiValidationError | string | null;
};

export type ApiAdapter = {
  login: (payload: LoginRequest) => Promise<LoginResponse>;
  logout: () => Promise<{ ok: boolean }>;
  getMe: () => Promise<CurrentAccount>;
  changePassword: (newPassword: string) => Promise<CurrentAccount>;
  normalizePersonnel: (
    fieldName: string,
    rawValue: string | null,
  ) => Promise<PersonnelNormalizationResult>;
  getWorkloadMe: (filters?: WorkloadQueryParams) => Promise<WorkloadScopeResponse>;
  getWorkloadOffice: (filters?: WorkloadQueryParams) => Promise<WorkloadScopeResponse>;
  getWorkloadInstitute: (filters?: WorkloadQueryParams) => Promise<WorkloadScopeResponse>;
  getWorkloadAdmin: (filters?: WorkloadQueryParams) => Promise<WorkloadScopeResponse>;
  getWorkflowMonitor: () => Promise<WorkflowMonitorList>;
  approveWorkflow: (groupId: string, payload: WorkflowApprovePayload) => Promise<void>;
  repairCurrentNode: (groupId: string, payload: WorkflowRepairPayload) => Promise<void>;
  listAccounts: () => Promise<AccountListResponse>;
  listInvalidAccountRows: () => Promise<InvalidAccountRowList>;
  createAccount: (payload: AccountCreatePayload) => Promise<AccountRecord>;
  updateAccount: (accountId: string, payload: AccountUpdatePayload) => Promise<AccountRecord>;
  getAdminConfig: () => Promise<AdminConfig>;
  patchAdminConfig: (payload: AdminConfig) => Promise<AdminConfig>;
  getHealth: () => Promise<HealthStatus>;
  getFormSchema: () => Promise<FormSchema>;
  preflightFonts: (files: File[]) => Promise<FontPreflightResult>;
  createBatch: (
    params: Record<string, string>,
    files: File[],
    runAuditCheck?: boolean,
  ) => Promise<CreateBatchPayload>;
  createAuditCheck: (
    projectNo: string,
    files: File[],
    batchId?: string,
  ) => Promise<CreateBatchPayload>;
  createAuditReplace: (params: CreateAuditReplaceParams) => Promise<CreateBatchPayload>;
  listTaskGroups: () => Promise<TaskGroupList>;
  getTaskGroupDetail: (groupId: string) => Promise<TaskGroupDetail>;
  submitTaskGroup: (
    groupId: string,
    payload: TaskGroupSubmitPayload,
  ) => Promise<TaskGroupDetail>;
  restartSubmitTaskGroup: (
    groupId: string,
    payload: TaskGroupSubmitPayload,
  ) => Promise<TaskGroupDetail>;
  listJobs: (status?: string) => Promise<JobList>;
  getJobDetail: (jobId: string) => Promise<JobDetail>;
};
