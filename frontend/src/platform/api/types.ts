export type TaskKind = "deliverable" | "audit_check" | "audit_replace";
export type TaskIntent = TaskKind;

export type FormFieldType = "text" | "select" | "combobox" | "date" | "nameId";

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
  getHealth: () => Promise<HealthStatus>;
  getFormSchema: () => Promise<FormSchema>;
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
  listJobs: (status?: string) => Promise<JobList>;
  getJobDetail: (jobId: string) => Promise<JobDetail>;
};
