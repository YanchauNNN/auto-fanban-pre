export type TaskKind = "deliverable" | "audit_check" | "audit_replace";
export type TaskIntent = TaskKind;
export type PreviewMode = "plain" | "annotated";

export type FormFieldType = "text" | "select" | "combobox" | "date" | "nameId" | "checkbox";

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

export type FormSchema = {
  schemaVersion: string;
  uploadLimits: UploadLimits;
  sections: readonly FormSection[];
  auditReplaceProjectOptions?: readonly string[];
  auditReplaceProjectUnits?: Record<string, readonly string[]>;
  auditReplaceSourceUnitOptions?: Record<string, readonly AuditReplaceUnitOption[]>;
  auditReplaceTargetUnitOptions?: Record<string, readonly AuditReplaceUnitOption[]>;
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

export type JobArtifacts = {
  packageAvailable: boolean;
  iedAvailable: boolean;
  previewAvailable?: boolean;
  previewMode?: PreviewMode | null;
  reportAvailable: boolean;
  replacedDwgAvailable: boolean;
  packageDownloadUrl?: string | null;
  iedDownloadUrl?: string | null;
  previewDownloadUrl?: string | null;
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
  category?: string;
  contextKind?: string;
  issueType?: string;
  summary?: string;
  details?: string[];
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
  settlementStatus: string;
  settledAt: string | null;
};

export type SubmissionParams = Record<string, unknown>;

export type CreateAuditReplaceParams = {
  sourceProjectNo: string;
  sourceIslandNo?: string | null;
  targetProjectNo: string;
  targetIslandNo?: string | null;
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
  runSplitOnly?: boolean;
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
  createAuditCheck: (
    projectNo: string,
    unitNo: string,
    files: File[],
    batchId?: string,
  ) => Promise<CreateBatchPayload>;
  createAuditReplace: (params: CreateAuditReplaceParams) => Promise<CreateBatchPayload>;
  listJobs: (status?: string, offset?: number, limit?: number) => Promise<JobList>;
  getJobDetail: (jobId: string) => Promise<JobDetail>;
};
