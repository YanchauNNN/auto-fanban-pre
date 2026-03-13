export type TaskKind = "deliverable" | "audit_check" | "audit_replace";
export type TaskIntent = TaskKind;

export type FormFieldType = "text" | "select" | "date" | "nameId";

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
  sourceFilename: string;
  taskKind: TaskKind;
  jobMode: string | null;
  projectNo: string | null;
  status: string;
  stage: string | null;
  percent: number;
  message: string;
  createdAt: string;
  finishedAt: string | null;
  findingsCount: number;
  affectedDrawingsCount: number;
  artifacts: JobArtifacts;
  retryAvailable: boolean;
};

export type JobDetail = JobSummary & {
  startedAt: string | null;
  currentFile: string | null;
  flags: string[];
  errors: string[];
  topWrongTexts: string[];
  topInternalCodes: string[];
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
  values: Record<string, string>;
  replaceConfig: ReplaceTaskConfig;
  updatedAt: string;
};

export type TaskConfigDraft = {
  intent: TaskIntent;
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
  createBatch: (params: Record<string, string>, files: File[]) => Promise<CreateBatchPayload>;
  createAuditCheck: (projectNo: string, files: File[]) => Promise<CreateBatchPayload>;
  listJobs: (status?: string) => Promise<JobList>;
  getJobDetail: (jobId: string) => Promise<JobDetail>;
};
