export type TaskKind =
  | "deliverable"
  | "audit_check"
  | "audit_replace"
  | "calculation_book"
  | "change_page_extract";
export type TaskIntent = TaskKind;
export type PreviewMode = "plain" | "annotated";
export type ReinforcementSource = "provided" | "ai_suggested";

export type FormFieldType =
  | "text"
  | "number"
  | "select"
  | "combobox"
  | "date"
  | "nameId"
  | "checkbox";

export type CalculationBookField = {
  key: string;
  label: string;
  type: "text" | "number" | "select" | "checkbox";
  required: boolean;
  defaultValue?: string;
  unit?: string;
  placeholder?: string;
  pattern?: string;
  maxLength?: number;
  uppercase?: boolean;
  options?: readonly string[];
  optionsFrom?: string;
  derivedFrom?: string;
};

export type CalculationBookSchema = {
  templates: readonly { value: string; label: string }[];
  projectOptions: readonly { value: string; label: string }[];
  fields: readonly CalculationBookField[];
  archive: {
    accept: readonly string[];
    requiredRootDirections: readonly string[];
    requiredFolders: readonly string[];
    rootFigurePattern: string;
    description: string;
  };
};

export type CalculationBookDirectionEvidence = {
  imageFilename: string;
  smn: number | null;
  smx: number | null;
  legendValues: readonly number[];
  isZeroResult: boolean;
  sourceCell: string;
  originalText: string;
  canonicalSpecification: string;
  narrativeSpecification: string;
  actualArea: number | null;
};

export type CalculationBookSlabEvidence = CalculationBookDirectionEvidence & {
  elevation: string;
  key: string;
  position: "TOP" | "MIDDLE" | "BOTTOM" | null;
  direction: "X" | "Y" | "Z";
  sourceRow: number | null;
};

export type CalculationBookConfirmationCandidate = {
  sourceRow: number;
  sourceSheet: string;
  directions: Record<
    "X" | "Y" | "Z",
    Pick<
      CalculationBookDirectionEvidence,
      | "sourceCell"
      | "originalText"
      | "canonicalSpecification"
      | "narrativeSpecification"
      | "actualArea"
    >
  >;
};

export type CalculationBookNormalizationIssue = {
  sourceSheet: string;
  sourceRow: number;
  sourceCells: Record<"wall" | "X" | "Y" | "Z", string>;
  originalValues: Record<"wall" | "X" | "Y" | "Z", string>;
  originalWallText: string;
  wallId: string | null;
  error: string;
};

export type CalculationBookPreflightResult = {
  preflightToken: string;
  reinforcementSource: ReinforcementSource;
  requiresAiRecommendation: boolean;
  figureCount: number;
  wallDirectionFigureCount: number;
  zeroFigureCount: number;
  zZeroOrMissingSmxCount: number;
  wallCount: number;
  reinforcementSourceRowCount: number;
  reinforcementNormalizedRowCount: number;
  reinforcementIssueRowCount: number;
  reinforcementUniqueWallCount: number;
  normalizationTriggered: boolean;
  normalizationSkillId: string | null;
  normalizationIssues: readonly CalculationBookNormalizationIssue[];
  requiresAiNormalization: boolean;
  aiReinforcementExpectedSourceRowCount: number | null;
  aiConfirmationMessage: string | null;
  formatInspection: CalculationBookFormatInspection;
  imageWallGroupCount: number;
  imageUniqueWallCount: number;
  matchedUniqueWallCount: number;
  imageOnlyWallIds: readonly string[];
  workbookOnlyWallIds: readonly string[];
  requiresWallCountConfirmation: boolean;
  slabFigureCount: number;
  slabZeroFigureCount: number;
  slabElevationCount: number;
  slabActualGroupCount: number;
  reinforcementWorkbook: string | null;
  requiresOcrReview: boolean;
  ignoredRootImages: readonly string[];
  reviewItems: readonly CalculationBookReviewItem[];
  requiresManualConfirmation: boolean;
  confirmations: readonly {
    wallId: string;
    baseWallId: string;
    reasons: readonly string[];
    suggestedSourceRow: number;
    candidates: readonly CalculationBookConfirmationCandidate[];
  }[];
  walls: readonly {
    wallId: string;
    baseWallId: string;
    groupIndex: number | null;
    suggestedSourceRow: number | null;
    directions: Record<"X" | "Y" | "Z", CalculationBookDirectionEvidence>;
  }[];
  slabs: readonly CalculationBookSlabEvidence[];
  warnings: readonly {
    code: string;
    filenames: readonly string[];
  }[];
};

export type CalculationBookReviewItem = {
  code: string;
  scope: "wall" | "slab" | string;
  identity: string;
  direction: string | null;
  imageFilename: string;
  reason: string;
};

export type CalculationBookFormatInspection = {
  wallSheet: string | null;
  slabSheet: string | null;
  reasons: readonly {
    scope: string;
    code: string;
    sheet: string | null;
    message: string;
  }[];
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

export type AuditReplaceUnitOption = {
  value: string;
  label: string;
};

export type WorkflowFactorSchema = {
  default: number;
  min: number;
  max: number;
  precision: number;
};

export type WorkflowNodeSchema = {
  nodeKey: string;
  nodeLabel: string;
  roleField: string;
  factorKey: string;
};

export type WorkloadStatusOption = {
  label: string;
  value: string;
};

export type ManagementSchema = {
  account: {
    fieldMap: {
      officeCode: string;
      officeName: string;
      accountId: string;
      displayName: string;
      role: string;
      password: string;
    };
    validRoles: readonly string[];
    adminRoles: readonly string[];
    adminCreatedDefaultPasswordConfigured: boolean;
    adminCreatedDefaultPassword: string;
  };
  workflow: {
    terminalStatus: string;
    archiveTriggerStatus?: string;
    nodes: readonly WorkflowNodeSchema[];
    factor: WorkflowFactorSchema;
    statusLabels: Record<string, string>;
    nodeLabels: Record<string, string>;
    emptyCurrentNodeLabel: string;
  };
  workload: {
    settlementTrigger: string;
    scopeRoles: Record<string, readonly string[]>;
    scopeLabels: Record<string, string>;
    statusOptions: readonly WorkloadStatusOption[];
  };
  archive?: {
    statusLabels: Record<string, string>;
  };
};

export type FormSchema = {
  schemaVersion: string;
  uploadLimits: UploadLimits;
  sections: readonly FormSection[];
  management?: ManagementSchema;
  auditReplaceProjectOptions?: readonly string[];
  auditReplaceProjectUnits?: Record<string, readonly string[]>;
  auditReplaceSourceUnitOptions?: Record<string, readonly AuditReplaceUnitOption[]>;
  auditReplaceTargetUnitOptions?: Record<string, readonly AuditReplaceUnitOption[]>;
  auditReplaceUnitFactoryCodes?: readonly string[];
  auditReplaceBatchFilenameIdentityRegex?: string;
  auditReplaceFactoryIndexMaps?: {
    sourceVariantOptions: Record<string, readonly string[]>;
    targetVariantOptions: Record<string, readonly string[]>;
  };
  auditCheckUnitConsistency?: {
    enabled: boolean;
    projectUnits: Record<string, readonly string[]>;
    allowUnlistedUnitNo?: boolean;
    unitNoPattern?: string;
  };
  calculationBook?: CalculationBookSchema;
};

export type HealthStatus = {
  status: string;
  ready: boolean;
  storageWritable: boolean;
  workerAlive: boolean;
  queueDepth: number;
  activeDocJobs?: number;
  pendingDocJobs?: number;
  activeTotalJobs?: number;
  autocadReady: boolean;
  officeReady: boolean;
  serverTime: string;
};

export type PingStatus = {
  ok: boolean;
  serverTime: string;
  version?: string | null;
};

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
  valid: boolean;
  rowNumber: number | null;
  errors: string[];
};

export type AccountListResponse = {
  items: AccountRecord[];
};

export type InvalidAccountRow = {
  rowNumber: number;
  raw: Record<string, string>;
  errors: string[];
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
  password?: string;
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

export type PersonnelNormalizationResult = {
  normalized: NormalizedPersonnel;
  candidates: PersonnelCandidate[];
};

export type PersonnelSnapshot = {
  members: Record<string, NormalizedPersonnel>;
};

export type TaskOwnerSnapshot = {
  creatorAccount: string;
  creatorName: string;
  creatorRole: string;
  creatorOffice: string | null;
  createdByScope: string;
  submittedAt: string | null;
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
  groupDisplayName: string | null;
  albumInternalCode: string | null;
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

export type TaskGroupSummary = {
  groupId: string;
  displayName: string | null;
  albumInternalCode: string | null;
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
  submitBlockers: string[];
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

export type JobArtifacts = {
  packageAvailable: boolean;
  iedAvailable: boolean;
  previewAvailable?: boolean;
  previewMode?: PreviewMode | null;
  reportAvailable: boolean;
  replacedDwgAvailable: boolean;
  calculationDocxAvailable?: boolean;
  calculationLogAvailable?: boolean;
  packageDownloadUrl?: string | null;
  iedDownloadUrl?: string | null;
  previewDownloadUrl?: string | null;
  reportDownloadUrl?: string | null;
  replacedDwgDownloadUrl?: string | null;
  calculationDocxDownloadUrl?: string | null;
  calculationLogDownloadUrl?: string | null;
};

export type CalculationBookOutput = {
  reinforcementSource: ReinforcementSource;
  figureCount: number;
  templateType: string;
  outputFilename: string;
  aiNormalized: boolean;
  warningCount: number;
  warnings: readonly CalculationBookWarning[];
  aiNormalization: CalculationBookAiNormalization | null;
  aiRebarSuggestion: CalculationBookAiRebarSuggestion | null;
};

export type CalculationBookAiRebarSuggestion = {
  skillId: string;
  skillVersion: string;
  skillSha256: string;
  model: string;
  callCount: number;
  suggestedDirectionCount: number;
  blankDirectionCount: number;
  repairRoundCount: number;
  validation: string;
};

export type CalculationBookWarning = {
  code: string;
  scope: "wall" | "slab" | "reinforcement";
  identity: string | null;
  direction: string | null;
  sourceSheet: string | null;
  sourceRow: number | null;
  sourceCells: Readonly<Record<string, string>>;
  reason: string;
  blankFields: readonly string[];
};

export type CalculationBookAiNormalization = {
  skillId: string;
  model: string;
  profile: string;
  callCount: number;
  sourceRowCount: number;
  normalizedWallCount: number;
  normalizedSlabCount: number;
  reviewWarningCount: number;
  durationMs: number;
  validation: string;
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
  category?: string;
  contextKind?: string;
  issueType?: string;
  summary?: string;
  details?: string[];
};

export type ChangePageResultItem = {
  name: string;
  pages: number;
  relativePath: string;
};

export type ChangePageResult = {
  archiveName: string;
  items: ChangePageResultItem[];
  text: string;
  pdfCount: number;
  totalPages: number;
  ignoredFileCount: number;
};

export type ReplaceSummary = {
  replacementCount: number;
  skippedCount: number;
  affectedDrawingsCount: number;
  sourceProjectNo: string;
  sourceIslandNo?: string | null;
  targetProjectNo: string;
  targetIslandNo?: string | null;
  topReplacedTexts: string[];
  topInternalCodes: string[];
};

export type FactoryIndexMapSummary = {
  applied: boolean;
  actionCount: number;
  reportJson: string | null;
  message: string;
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

export type FontReplacementMap = Record<string, string>;

export type FontVerifyAfterReplaceResult = {
  status: string;
  missingStyleCount: number;
  missingFonts: MissingFontEntry[];
};

export type FontPreflightFileResult = {
  filename: string;
  status: string;
  missingFonts: MissingFontEntry[];
  detectedStyleCount: number;
  missingStyleCount: number;
  fontReplacementApplied: boolean;
  replacementFont: string | null;
  replacementFonts: FontReplacementMap;
  fontCompatibilityMode?: boolean;
  fontCompatibilityReplacements?: FontReplacementMap;
  fontCompatibilityRequired?: boolean;
  emptyStyleEntityReplacedCount?: number;
  emptyStyleStylePatchedCount?: number;
  emptyStyleSharedSkippedCount?: number;
  emptyStyleSharedStyles?: string[];
  emptyStyleTargetRegionsCount?: number;
  emptyStyleGlobalReplacedCount?: number;
  replacedStyleCount: number;
  verifyAfterReplace: FontVerifyAfterReplaceResult | null;
  fontReplacementIncomplete: boolean;
  errors: string[];
};

export type FontPreflightResult = {
  files: FontPreflightFileResult[];
  replacementOptions: FontReplacementOption[];
  replacementOptionsByKind: Record<string, FontReplacementOption[]>;
  defaultReplacementFont: string | null;
  defaultReplacementFonts: FontReplacementMap;
  requiresConfirmation: boolean;
};

export type FontPreflightSummary = {
  files: FontPreflightFileResult[];
  policy: string;
  fontCompatibilityMode?: boolean;
  replacementFonts: FontReplacementMap;
  fontMapPath: string | null;
  fontAlt: string | null;
};

export type WorkloadSummary = {
  initialWorkloadA1: number;
  finalWorkloadA1: number;
  oneReviewFactor: number;
  twoReviewFactor: number;
  threeReviewFactor: number;
  nodeFactors: Record<string, number>;
  settlementStatus: string;
  settledAt: string | null;
  contributorEntries: WorkloadContributorEntry[];
};

export type SubmissionParams = Record<string, unknown>;

export type CreateAuditReplaceParams = {
  sourceProjectNo: string;
  sourceIslandNo?: string | null;
  targetProjectNo: string;
  targetIslandNo?: string | null;
  unitFactoryCodes?: readonly string[];
  files: File[];
  runDeliverable: boolean;
  deliverableParams?: SubmissionParams;
};

export type JobSummary = {
  jobId: string;
  batchId: string | null;
  isGroup: boolean;
  groupId: string | null;
  sourceFilename: string;
  sourceFilenames: string[];
  ownerSnapshot?: TaskOwnerSnapshot | null;
  creatorName?: string | null;
  creatorAccount?: string | null;
  creatorOffice?: string | null;
  taskKind: TaskKind | null;
  jobMode: string | null;
  projectNo: string | null;
  status: string;
  stage: string | null;
  percent: number;
  message: string;
  failureReason?: string | null;
  stageContext?: string | null;
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
  replacementFonts?: FontReplacementMap;
  replacedStyleCount?: number;
  workload?: WorkloadSummary | null;
  effectiveWorkload?: number;
  children?: JobSummary[];
};

export type JobDiagnosticDetail = {
  label: string;
  items: string[];
};

export type JobDiagnostic = {
  kind: string;
  severity: "error" | "warning" | "info" | string;
  title: string;
  summary: string;
  suggestion: string;
  details: JobDiagnosticDetail[];
  rawItems: string[];
};

export type JobDetail = JobSummary & {
  startedAt: string | null;
  currentFile: string | null;
  flags: string[];
  errors: string[];
  diagnostics?: JobDiagnostic[];
  topWrongTexts: string[];
  topInternalCodes: string[];
  sharedDir?: string | null;
  deliverableOutputs?: DeliverableOutputs;
  findingGroups?: FindingGroup[];
  replaceSummary?: ReplaceSummary;
  factoryIndexMap?: FactoryIndexMapSummary | null;
  calculationBookOutput?: CalculationBookOutput;
  changePageResult?: ChangePageResult | null;
};

export type JobList = {
  total: number;
  items: JobSummary[];
};

export type JobListSort = "updated_at" | "created_at";

export type JobsActivity = {
  total: number;
  active: number;
  lastChangedAt: string | null;
};

export type AiAgent = {
  agentId: string;
  name: string;
  description: string;
};

export type AiSkill = {
  skillId: string;
  name: string;
  description: string;
  enabled: boolean;
  readOnly: boolean;
};

export type AiMcpServer = {
  serverId: string;
  name: string;
  description: string;
  enabled: boolean;
  readOnly: boolean;
  transport?: string;
};

export type AiAttachmentCapabilities = {
  enabled: boolean;
  allowedExtensions: string[];
  maxFilesPerMessage: number;
  maxImageSizeMb: number;
  maxFileSizeMb: number;
  maxTotalSizeMbPerMessage: number;
};

export type AiAttachment = {
  attachmentId: string;
  conversationId: string;
  messageId?: string | null;
  originalName: string;
  mediaType: string;
  kind: "image" | "document" | "drawing" | "unknown" | string;
  sizeBytes: number;
  sha256: string;
  status: "uploaded" | "ready" | "failed" | string;
  metadata: Record<string, unknown>;
  errorCode?: string | null;
  createdAt: string;
};

export type AiState = {
  enabled: boolean;
  profile: string;
  model: string;
  ownerKey: string;
  defaultAgent: string;
  attachments: AiAttachmentCapabilities;
  agents: AiAgent[];
  skills: AiSkill[];
  mcpServers: AiMcpServer[];
};

export type AiConversationSummary = {
  conversationId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
};

export type AiMessage = {
  messageId: string;
  role: "system" | "user" | "assistant" | string;
  content: string;
  createdAt: string;
  modelProfile?: string | null;
  metadata?: Record<string, unknown>;
};

export type AiConversationDetail = AiConversationSummary & {
  messages: AiMessage[];
};

export type SendAiMessagePayload = {
  content: string;
  agentId?: string | null;
  skillIds?: string[];
  mcpServerIds?: string[];
  attachmentIds?: string[];
};

export type AiSendMessageResult = {
  conversationId: string;
  userMessage: AiMessage;
  assistantMessage: AiMessage;
  memory: {
    usedHistoryMessages: number;
  };
};

export type CreateBatchPayload = {
  batchId: string;
  jobs: JobSummary[];
};

export type UploadProjectInference = {
  inferredProjectNos: string[];
  inferredUnitNos: string[];
  primaryProjectNo: string;
  primaryUnitNo: string;
  hasConflict: boolean;
  hasUnitConflict: boolean;
};

export type ReplaceTaskConfig = {
  sourceProjectNo: string;
  sourceIslandNo: string;
  targetProjectNo: string;
  targetIslandNo: string;
  unitFactoryCodes?: readonly string[];
};

export type TaskConfigPreset = {
  id: string;
  name: string;
  intent: TaskIntent;
  runAuditCheck: boolean;
  fontCompatibilityMode: boolean;
  values: Record<string, string>;
  replaceConfig: ReplaceTaskConfig;
  updatedAt: string;
};

export type TaskConfigDraft = {
  intent: TaskIntent;
  runAuditCheck: boolean;
  runSplitOnly?: boolean;
  fontCompatibilityMode?: boolean;
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
  ping: () => Promise<PingStatus>;
  login?: (payload: LoginRequest) => Promise<LoginResponse>;
  logout?: () => Promise<{ ok: boolean }>;
  getMe?: () => Promise<CurrentAccount>;
  changePassword?: (newPassword: string) => Promise<CurrentAccount>;
  normalizePersonnel?: (
    fieldName: string,
    rawValue: string | null,
  ) => Promise<PersonnelNormalizationResult>;
  getWorkloadMe?: (filters?: WorkloadQueryParams) => Promise<WorkloadScopeResponse>;
  getWorkloadOffice?: (filters?: WorkloadQueryParams) => Promise<WorkloadScopeResponse>;
  getWorkloadInstitute?: (filters?: WorkloadQueryParams) => Promise<WorkloadScopeResponse>;
  getWorkloadAdmin?: (filters?: WorkloadQueryParams) => Promise<WorkloadScopeResponse>;
  getWorkflowMonitor?: () => Promise<WorkflowMonitorList>;
  approveWorkflow?: (groupId: string, payload: WorkflowApprovePayload) => Promise<void>;
  repairCurrentNode?: (groupId: string, payload: WorkflowRepairPayload) => Promise<void>;
  listAccounts?: () => Promise<AccountListResponse>;
  listInvalidAccountRows?: () => Promise<InvalidAccountRowList>;
  createAccount?: (payload: AccountCreatePayload) => Promise<AccountRecord>;
  updateAccount?: (accountId: string, payload: AccountUpdatePayload) => Promise<AccountRecord>;
  updateAccountRow?: (rowNumber: number, payload: AccountUpdatePayload) => Promise<AccountRecord>;
  getAdminConfig?: () => Promise<AdminConfig>;
  patchAdminConfig?: (payload: AdminConfig) => Promise<AdminConfig>;
  getHealth: () => Promise<HealthStatus>;
  getFormSchema: () => Promise<FormSchema>;
  preflightFonts: (files: File[]) => Promise<FontPreflightResult>;
  createBatch: (
    params: SubmissionParams,
    files: File[],
    runAuditCheck?: boolean,
  ) => Promise<CreateBatchPayload>;
  createSplitOnlyBatch: (
    params: SubmissionParams,
    files: File[],
  ) => Promise<CreateBatchPayload>;
  createChangePageExtract: (files: File[]) => Promise<CreateBatchPayload>;
  createAuditCheck: (
    projectNo: string,
    unitNo: string,
    files: File[],
    batchId?: string,
  ) => Promise<CreateBatchPayload>;
  createAuditReplace: (params: CreateAuditReplaceParams) => Promise<CreateBatchPayload>;
  createCalculationBook?: (
    params: SubmissionParams,
  ) => Promise<CreateBatchPayload>;
  preflightCalculationBook?: (
    archive: File,
    options: {
      includeSlabStress: boolean;
      reinforcementSource: ReinforcementSource;
      params?: SubmissionParams;
    },
  ) => Promise<CalculationBookPreflightResult>;
  listTaskGroups?: () => Promise<TaskGroupList>;
  getTaskGroupDetail?: (groupId: string) => Promise<TaskGroupDetail>;
  submitTaskGroup?: (
    groupId: string,
    payload: TaskGroupSubmitPayload,
  ) => Promise<TaskGroupDetail>;
  restartSubmitTaskGroup?: (
    groupId: string,
    payload: TaskGroupSubmitPayload,
  ) => Promise<TaskGroupDetail>;
  rememberAuditReplaceFactoryCodes: (
    codes: readonly string[],
  ) => Promise<{ factoryCodes: readonly string[] }>;
  listJobs: (status?: string, offset?: number, limit?: number, sort?: JobListSort) => Promise<JobList>;
  getJobsActivity: () => Promise<JobsActivity>;
  subscribeJobsActivity?: (
    onActivity: (activity: JobsActivity) => void,
    onError?: (event: Event) => void,
  ) => () => void;
  getJobDetail: (jobId: string) => Promise<JobDetail>;
  readArtifact?: (url: string) => Promise<Blob>;
  downloadArtifact?: (url: string, fallbackFilename?: string) => Promise<void>;
  getAiState: (signal?: AbortSignal) => Promise<AiState>;
  listAiConversations: (signal?: AbortSignal) => Promise<AiConversationSummary[]>;
  createAiConversation: (title?: string) => Promise<AiConversationSummary>;
  getAiConversation: (
    conversationId: string,
    signal?: AbortSignal,
  ) => Promise<AiConversationDetail>;
  renameAiConversation: (
    conversationId: string,
    title: string,
  ) => Promise<AiConversationSummary>;
  sendAiMessage: (
    conversationId: string,
    payload: SendAiMessagePayload,
    signal?: AbortSignal,
  ) => Promise<AiSendMessageResult>;
  clearAiConversation: (conversationId: string) => Promise<void>;
  deleteAiConversation?: (conversationId: string) => Promise<void>;
  uploadAiAttachment?: (conversationId: string, file: File) => Promise<AiAttachment>;
  listAiAttachments?: (
    conversationId: string,
    signal?: AbortSignal,
  ) => Promise<AiAttachment[]>;
  deleteAiAttachment?: (conversationId: string, attachmentId: string) => Promise<void>;
};
