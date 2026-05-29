import { normalizeFormSchema } from "../../features/schema/schema";
import {
  getSessionAccessToken,
  notifySessionUnauthorized,
} from "../../shared/session/sessionRuntime";
import type {
  AccountCreatePayload,
  AccountListResponse,
  AccountRecord,
  AccountUpdatePayload,
  AdminConfig,
  ApiAdapter,
  ApiError,
  ArchiveState,
  CreateAuditReplaceParams,
  CreateBatchPayload,
  CurrentAccount,
  DeliverableOutputs,
  FontReplacementMap,
  FontReplacementOption,
  FontPreflightSummary,
  FontPreflightResult,
  FindingGroup,
  FormSchema,
  HealthStatus,
  InvalidAccountRow,
  InvalidAccountRowList,
  JobDetail,
  JobList,
  JobSummary,
  LegacyVisibilityState,
  LoginRequest,
  LoginResponse,
  NormalizedPersonnel,
  PersonnelCandidate,
  PersonnelNormalizationResult,
  PersonnelSnapshot,
  PingStatus,
  ReplacementState,
  SubmissionParams,
  TaskGroupDetail,
  TaskGroupList,
  TaskGroupSubmitPayload,
  TaskGroupSummary,
  TaskOwnerSnapshot,
  WorkflowApprovePayload,
  WorkflowMonitorList,
  WorkflowRepairPayload,
  WorkflowState,
  WorkloadQueryParams,
  WorkloadScopeResponse,
  WorkloadSummary,
} from "./types";

type FetchPolicy = {
  retry?: boolean;
  retryCount?: number;
  retryBaseDelayMs?: number;
  timeoutMs?: number;
};

const DEFAULT_GET_RETRY_COUNT = 2;
const DEFAULT_GET_RETRY_BASE_DELAY_MS = 250;
const DEFAULT_GET_TIMEOUT_MS = 8000;

type RawArtifacts = {
  package_available: boolean;
  ied_available: boolean;
  preview_available?: boolean | null;
  preview_mode?: "plain" | "annotated" | null;
  report_available: boolean;
  replaced_dwg_available: boolean;
  package_download_url?: string | null;
  ied_download_url?: string | null;
  preview_download_url?: string | null;
  report_download_url?: string | null;
  replaced_dwg_download_url?: string | null;
};

type RawJobSummary = {
  job_id: string;
  batch_id: string | null;
  group_id?: string | null;
  shared_run_id?: string | null;
  task_role?: string | null;
  is_group?: boolean;
  source_filename?: string | null;
  source_filenames?: string[] | null;
  task_kind?: "deliverable" | "audit_check" | "audit_replace" | null;
  job_mode?: string | null;
  project_no: string | null;
  status: string;
  stage: string | null;
  percent: number | null;
  message: string | null;
  failure_reason?: string | null;
  stage_context?: string | null;
  created_at: string;
  finished_at: string | null;
  run_audit_check?: boolean | null;
  child_job_ids?: string[] | null;
  findings_count?: number | null;
  affected_drawings_count?: number | null;
  plot_style_key?: string | null;
  plot_resource_mode?: string | null;
  slot_id?: string | null;
  cad_version?: string | null;
  accoreconsole_exe?: string | null;
  profile_arg?: string | null;
  pc3_path?: string | null;
  pmp_path?: string | null;
  ctb_path?: string | null;
  font_preflight_summary?: {
    files?: RawFontPreflightResult["files"];
    policy?: string | null;
    font_compatibility_mode?: boolean | null;
    replacement_fonts?: Record<string, string | null> | null;
    font_map_path?: string | null;
    font_alt?: string | null;
  } | null;
  missing_fonts_detected?: boolean | null;
  font_replacement_applied?: boolean | null;
  replacement_font?: string | null;
  replacement_fonts?: Record<string, string | null> | null;
  replaced_style_count?: number | null;
  artifacts: RawArtifacts;
  retry_available: boolean;
  children?: RawJobSummary[] | null;
};

type RawJobDetail = RawJobSummary & {
  started_at?: string | null;
  current_file?: string | null;
  flags?: string[];
  errors?: string[];
  top_wrong_texts?: string[] | null;
  top_internal_codes?: string[] | null;
  shared_dir?: string | null;
  deliverable_outputs?: {
    dwg_count?: number | null;
    pdf_count?: number | null;
    documents?: Array<{
      name?: string | null;
      kind?: string | null;
    }> | null;
    drawings?: Array<{
      name?: string | null;
      internal_code?: string | null;
      dwg_name?: string | null;
      pdf_name?: string | null;
      page_total?: number | null;
    }> | null;
  } | null;
  finding_groups?: Array<{
    matched_text?: string | null;
    count?: number | null;
    internal_codes?: string[] | null;
  }> | null;
  replace_summary?: {
    replacement_count?: number | null;
    skipped_count?: number | null;
    affected_drawings_count?: number | null;
    source_project_no?: string | null;
    source_island_no?: string | null;
    target_project_no?: string | null;
    target_island_no?: string | null;
    top_replaced_texts?: string[] | null;
    top_internal_codes?: string[] | null;
  } | null;
  factory_index_map?: {
    applied?: boolean | null;
    action_count?: number | null;
    report_json?: string | null;
    message?: string | null;
  } | null;
};

type RawFontPreflightResult = {
  files?: Array<{
    filename?: string | null;
    status?: string | null;
    missing_fonts?: Array<{
      style_name?: string | null;
      font_name?: string | null;
      bigfont_name?: string | null;
      kind?: string | null;
      used_in_block?: boolean | null;
    }> | null;
    detected_style_count?: number | null;
    missing_style_count?: number | null;
    font_replacement_applied?: boolean | null;
    replacement_font?: string | null;
    replacement_fonts?: Record<string, string | null> | null;
    font_compatibility_mode?: boolean | null;
    font_compatibility_replacements?: Record<string, string | null> | null;
    replaced_style_count?: number | null;
    verify_after_replace?: {
      status?: string | null;
      missing_style_count?: number | null;
      missing_fonts?: Array<{
        style_name?: string | null;
        font_name?: string | null;
        bigfont_name?: string | null;
        kind?: string | null;
        used_in_block?: boolean | null;
      }> | null;
    } | null;
    font_replacement_incomplete?: boolean | null;
    errors?: string[] | null;
  }> | null;
  replacement_options?: Array<{
    label?: string | null;
    value?: string | null;
    family?: string | null;
    path?: string | null;
    kind?: string | null;
    source?: string | null;
  }> | null;
  replacement_options_by_kind?: Record<
    string,
    Array<{
      label?: string | null;
      value?: string | null;
      family?: string | null;
      path?: string | null;
      kind?: string | null;
      source?: string | null;
    }> | null
  > | null;
  default_replacement_font?: string | null;
  default_replacement_fonts?: Record<string, string | null> | null;
  requires_confirmation?: boolean | null;
};

type RawFormSchema = {
  schema_version: string;
  upload_limits: {
    max_files: number;
    allowed_exts: string[];
    max_total_mb: number;
  };
  deliverable: {
    sections: Array<{
      id: string;
      title: string;
      fields: Array<{
        key: string;
        label: string;
        type: string;
        required: boolean;
        required_when: string | null;
        source: "frontend";
        default: string | null;
        format: string | null;
        desc: string;
        options: string[];
      }>;
    }>;
  };
  audit_check?: {
    unit_consistency?: {
      enabled?: boolean;
      project_units?: Record<string, string[]>;
      allow_unlisted_unit_no?: boolean;
      unit_no_pattern?: string;
    };
  };
  audit_replace?: {
    project_options?: string[];
    project_units?: Record<string, string[]>;
    source_unit_options?: Record<string, { value: string; label: string }[]>;
    target_unit_options?: Record<string, { value: string; label: string }[]>;
    factory_index_maps?: {
      source_variant_options?: Record<string, string[]>;
      target_variant_options?: Record<string, string[]>;
    };
  };
};

type RawAccount = {
  account_id: string;
  display_name: string;
  role: string;
  office_code?: string | null;
  office_name?: string | null;
  valid?: boolean | null;
  pending_todo_count?: number | null;
};

type RawTaskOwnerSnapshot = {
  creator_account?: string | null;
  creator_name?: string | null;
  creator_role?: string | null;
  creator_office?: string | null;
  created_by_scope?: string | null;
  submitted_at?: string | null;
};

type RawWorkloadScopeEntry = {
  role_key?: string | null;
  account_id?: string | null;
  display_name?: string | null;
  workload_a1?: number | null;
  settled_at?: string | null;
  group_id?: string | null;
  settlement_status?: string | null;
};

type RawWorkloadScopeResponse = {
  scope?: string | null;
  filters?: {
    start_date?: string | null;
    end_date?: string | null;
    status?: string | null;
    valid_only?: boolean | null;
  } | null;
  office_name?: string | null;
  total_workload_a1?: number | null;
  totals_by_account?: Record<string, number | null> | null;
  entries?: RawWorkloadScopeEntry[] | null;
};

type RawWorkloadSummary = {
  initial_workload_a1?: number | null;
  final_workload_a1?: number | null;
  one_review_factor?: number | null;
  two_review_factor?: number | null;
  three_review_factor?: number | null;
  node_factors?: Record<string, number | null> | null;
  settlement_status?: string | null;
  settled_at?: string | null;
  contributor_entries?:
    | Array<{
        role_key?: string | null;
        account_id?: string | null;
        display_name?: string | null;
        workload_a1?: number | null;
        settled_at?: string | null;
      }>
    | null;
};

type RawNormalizedPersonnel = {
  field_name?: string | null;
  raw_value?: string | null;
  normalized_value?: string | null;
  matched_account?: string | null;
  matched_name?: string | null;
  match_strategy?: string | null;
  status?: string | null;
  errors?: string[] | null;
};

type RawPersonnelCandidate = {
  account_id?: string | null;
  display_name?: string | null;
  role?: string | null;
  office_code?: string | null;
  office_name?: string | null;
  valid?: boolean | null;
};

type RawPersonnelNormalizationResult = {
  normalized?: RawNormalizedPersonnel | null;
  candidates?: RawPersonnelCandidate[] | null;
};

type RawAccountRecord = {
  office_code?: string | null;
  office_name?: string | null;
  account_id: string;
  display_name: string;
  role: string;
  password?: string | null;
  valid?: boolean | null;
  row_number?: number | null;
  errors?: string[] | null;
};

type RawInvalidAccountRow = {
  row_number: number;
  raw?: Record<string, string> | null;
  errors?: string[] | null;
};

type RawAdminConfig = {
  archive_root_path?: string | null;
};

type RawPersonnelSnapshot = {
  members?: Record<string, RawNormalizedPersonnel> | null;
};

type RawWorkflowNodeState = {
  node_key?: string | null;
  node_label?: string | null;
  assignee_account?: string | null;
  assignee_name?: string | null;
  status?: string | null;
  factor?: number | null;
  approved_at?: string | null;
  acted_by_account?: string | null;
  acted_by_name?: string | null;
};

type RawWorkflowState = {
  status?: string | null;
  initiated_at?: string | null;
  initiated_by_account?: string | null;
  initiated_by_name?: string | null;
  duplicate_policy?: string | null;
  overwrite_archive_target?: string | null;
  current_node_key?: string | null;
  nodes?: RawWorkflowNodeState[] | null;
  archive_status?: string | null;
  archive_retry_count?: number | null;
  archive_last_error?: string | null;
  archive_last_attempt_at?: string | null;
};

type RawArchiveState = {
  archive_root_path?: string | null;
  target_dir?: string | null;
  status?: string | null;
  overwrite_mode?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  last_error?: string | null;
  retry_count?: number | null;
  last_attempt_at?: string | null;
  archived_files?: string[] | null;
};

type RawReplacementState = {
  album_internal_code?: string | null;
  revision?: string | null;
  replaced_group_id?: string | null;
  replaced_record_pending_delete?: boolean | null;
};

type RawLegacyVisibilityState = {
  scope?: string | null;
  reason?: string | null;
};

type RawTaskGroupSummary = {
  group_id: string;
  batch_id?: string | null;
  project_no?: string | null;
  status?: string | null;
  created_at?: string | null;
  source_filenames?: string[] | null;
  owner_snapshot?: RawTaskOwnerSnapshot | null;
  creator_name?: string | null;
  creator_account?: string | null;
  creator_office?: string | null;
  workflow_status?: string | null;
  current_node_key?: string | null;
  archive_status?: string | null;
  workload?: RawWorkloadSummary | null;
  effective_workload?: number | null;
  can_view_detail?: boolean | null;
  can_submit?: boolean | null;
  can_approve?: boolean | null;
  is_related_to_current_user?: boolean | null;
};

type RawTaskGroupDetail = RawTaskGroupSummary & {
  child_job_ids?: string[] | null;
  personnel_snapshot?: RawPersonnelSnapshot | null;
  workflow?: RawWorkflowState | null;
  archive?: RawArchiveState | null;
  replacement?: RawReplacementState | null;
  legacy_visibility?: RawLegacyVisibilityState | null;
};

type HttpAdapterOptions = {
  getAccessToken?: () => string | null;
  onUnauthorized?: () => void;
};

export class HttpAdapter implements ApiAdapter {
  private readonly normalizedBaseUrl: string;
  private readonly getAccessToken?: () => string | null;
  private readonly onUnauthorized?: () => void;

  constructor(private readonly baseUrl = "", options: HttpAdapterOptions = {}) {
    this.normalizedBaseUrl = baseUrl.replace(/\/+$/, "");
    this.getAccessToken = options.getAccessToken ?? getSessionAccessToken;
    this.onUnauthorized = options.onUnauthorized ?? notifySessionUnauthorized;
  }

  async login(payload: LoginRequest): Promise<LoginResponse> {
    const response = await this.fetchJson<{
      token: string;
      account: RawAccount;
    }>("/api/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        account_id: payload.accountId,
        password: payload.password,
      }),
    });

    return {
      token: response.token,
      account: this.normalizeAccount(response.account),
    };
  }

  async logout(): Promise<{ ok: boolean }> {
    return this.fetchJson<{ ok: boolean }>("/api/auth/logout", {
      method: "POST",
    });
  }

  async getMe(): Promise<CurrentAccount> {
    const payload = await this.fetchJson<RawAccount>("/api/auth/me");
    return this.normalizeAccount(payload);
  }

  async changePassword(newPassword: string): Promise<CurrentAccount> {
    const payload = await this.fetchJson<RawAccount>("/api/auth/change-password", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        new_password: newPassword,
      }),
    });
    return this.normalizeAccount(payload);
  }

  async normalizePersonnel(
    fieldName: string,
    rawValue: string | null,
  ): Promise<PersonnelNormalizationResult> {
    const payload = await this.fetchJson<RawPersonnelNormalizationResult>(
      "/api/accounts/normalize-personnel",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          field_name: fieldName,
          raw_value: rawValue,
        }),
      },
    );

    return {
      normalized: this.normalizeNormalizedPersonnel(payload.normalized, fieldName),
      candidates: (payload.candidates ?? []).map((candidate) =>
        this.normalizePersonnelCandidate(candidate),
      ),
    };
  }

  async getWorkloadMe(filters: WorkloadQueryParams = {}): Promise<WorkloadScopeResponse> {
    return this.loadWorkloadScope("/api/workload/me", filters);
  }

  async getWorkloadOffice(filters: WorkloadQueryParams = {}): Promise<WorkloadScopeResponse> {
    return this.loadWorkloadScope("/api/workload/office", filters);
  }

  async getWorkloadInstitute(filters: WorkloadQueryParams = {}): Promise<WorkloadScopeResponse> {
    return this.loadWorkloadScope("/api/workload/institute", filters);
  }

  async getWorkloadAdmin(filters: WorkloadQueryParams = {}): Promise<WorkloadScopeResponse> {
    return this.loadWorkloadScope("/api/workload/admin", filters);
  }

  async getWorkflowMonitor(): Promise<WorkflowMonitorList> {
    const payload = await this.fetchJson<{
      total: number;
      items: RawTaskGroupSummary[];
    }>("/api/workflow/monitor");

    return {
      total: payload.total,
      items: (payload.items ?? []).map((item) => this.normalizeTaskGroupSummary(item)),
    };
  }

  async approveWorkflow(groupId: string, payload: WorkflowApprovePayload): Promise<void> {
    await this.fetchJson(`/api/workflow/${groupId}/approve`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        factor: payload.factor,
        ...(payload.nodeKey ? { node_key: payload.nodeKey } : {}),
      }),
    });
  }

  async repairCurrentNode(groupId: string, payload: WorkflowRepairPayload): Promise<void> {
    await this.fetchJson(`/api/workflow/${groupId}/repair-current-node`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(this.serializeWorkflowRepairPayload(payload)),
    });
  }

  async listAccounts(): Promise<AccountListResponse> {
    const payload = await this.fetchJson<{
      items?: RawAccountRecord[] | null;
    }>("/api/accounts");
    return {
      items: (payload.items ?? []).map((item) => this.normalizeAccountRecord(item)),
    };
  }

  async listInvalidAccountRows(): Promise<InvalidAccountRowList> {
    const payload = await this.fetchJson<{
      items?: RawInvalidAccountRow[] | null;
    }>("/api/accounts/invalid-rows");
    return {
      items: (payload.items ?? []).map((item) => this.normalizeInvalidAccountRow(item)),
    };
  }

  async createAccount(payload: AccountCreatePayload): Promise<AccountRecord> {
    const response = await this.fetchJson<RawAccountRecord>("/api/accounts", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(this.serializeAccountCreatePayload(payload)),
    });
    return this.normalizeAccountRecord(response);
  }

  async updateAccount(accountId: string, payload: AccountUpdatePayload): Promise<AccountRecord> {
    const response = await this.fetchJson<RawAccountRecord>(`/api/accounts/${accountId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(this.serializeAccountUpdatePayload(payload)),
    });
    return this.normalizeAccountRecord(response);
  }

  async getAdminConfig(): Promise<AdminConfig> {
    const payload = await this.fetchJson<RawAdminConfig>("/api/admin/config");
    return this.normalizeAdminConfig(payload);
  }

  async patchAdminConfig(payload: AdminConfig): Promise<AdminConfig> {
    const response = await this.fetchJson<RawAdminConfig>("/api/admin/config", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        archive_root_path: payload.archiveRootPath ?? "",
      }),
    });
    return this.normalizeAdminConfig(response);
  }

  async ping(): Promise<PingStatus> {
    const payload = await this.fetchJson<{
      ok: boolean;
      server_time: string;
      version?: string | null;
    }>("/api/system/ping", undefined, {
      retry: true,
      retryCount: 2,
      retryBaseDelayMs: 150,
      timeoutMs: 3000,
    });

    return {
      ok: Boolean(payload.ok),
      serverTime: payload.server_time,
      version: payload.version ?? null,
    };
  }

  async getHealth(): Promise<HealthStatus> {
    const payload = await this.fetchJson<{
      status: string;
      ready: boolean;
      storage_writable: boolean;
      worker_alive: boolean;
      queue_depth: number;
      active_doc_jobs?: number;
      pending_doc_jobs?: number;
      active_total_jobs?: number;
      autocad_ready: boolean;
      office_ready: boolean;
      server_time: string;
    }>("/api/system/health", undefined, { retry: true });

    return {
      status: payload.status,
      ready: payload.ready,
      storageWritable: payload.storage_writable,
      workerAlive: payload.worker_alive,
      queueDepth: payload.queue_depth,
      activeDocJobs: payload.active_doc_jobs,
      pendingDocJobs: payload.pending_doc_jobs,
      activeTotalJobs: payload.active_total_jobs,
      autocadReady: payload.autocad_ready,
      officeReady: payload.office_ready,
      serverTime: payload.server_time,
    };
  }

  async getFormSchema(): Promise<FormSchema> {
    const payload = await this.fetchJson<RawFormSchema>("/api/meta/form-schema", undefined, {
      retry: true,
    });
    return normalizeFormSchema(payload);
  }

  async preflightFonts(files: File[]): Promise<FontPreflightResult> {
    const formData = new FormData();
    for (const file of files) {
      formData.append("files[]", file);
    }

    const payload = await this.fetchJson<RawFontPreflightResult>("/api/jobs/preflight-fonts", {
      method: "POST",
      body: formData,
    });

    const replacementOptions = this.normalizeFontReplacementOptions(payload.replacement_options);
    const replacementOptionsByKind = this.normalizeFontReplacementOptionsByKind(
      payload.replacement_options_by_kind,
      replacementOptions,
    );
    const defaultReplacementFonts = this.normalizeFontReplacementMap(payload.default_replacement_fonts);

    return {
      files: (payload.files ?? []).map((file) => this.normalizeFontPreflightFile(file)),
      replacementOptions,
      replacementOptionsByKind,
      defaultReplacementFont: payload.default_replacement_font ?? null,
      defaultReplacementFonts,
      requiresConfirmation: Boolean(payload.requires_confirmation),
    };
  }

  async createBatch(
    params: SubmissionParams,
    files: File[],
    runAuditCheck = false,
  ): Promise<CreateBatchPayload> {
    const formData = new FormData();
    formData.append("params_json", JSON.stringify(params));
    if (runAuditCheck) {
      formData.append("run_audit_check", "true");
    }
    for (const file of files) {
      formData.append("files[]", file);
    }

    const payload = await this.fetchJson<{
      batch_id: string;
      jobs: RawJobSummary[];
    }>("/api/jobs/batch", {
      method: "POST",
      body: formData,
    });

    return {
      batchId: payload.batch_id,
      jobs: payload.jobs.map((job) => this.normalizeSummary(job)),
    };
  }

  async createSplitOnlyBatch(
    params: SubmissionParams,
    files: File[],
  ): Promise<CreateBatchPayload> {
    const formData = new FormData();
    formData.append("params_json", JSON.stringify(params));
    formData.append("split_only", "true");
    for (const file of files) {
      formData.append("files[]", file);
    }

    const payload = await this.fetchJson<{
      batch_id: string;
      jobs: RawJobSummary[];
    }>("/api/jobs/batch", {
      method: "POST",
      body: formData,
    });

    return {
      batchId: payload.batch_id,
      jobs: payload.jobs.map((job) => this.normalizeSummary(job)),
    };
  }

  async createAuditCheck(
    projectNo: string,
    unitNo: string,
    files: File[],
    batchId?: string,
  ): Promise<CreateBatchPayload> {
    const formData = new FormData();
    formData.append("mode", "check");
    const params: Record<string, string> = { project_no: projectNo };
    if (unitNo.trim()) {
      params.unit_no = unitNo.trim();
    }
    if (batchId) {
      params.batch_id = batchId;
    }
    formData.append("params_json", JSON.stringify(params));
    for (const file of files) {
      formData.append("files[]", file);
    }

    const payload = await this.fetchJson<{
      batch_id: string;
      jobs: RawJobSummary[];
    }>("/api/jobs/audit-replace", {
      method: "POST",
      body: formData,
    });

    return {
      batchId: payload.batch_id,
      jobs: payload.jobs.map((job) => this.normalizeSummary(job)),
    };
  }

  async createAuditReplace({
    sourceProjectNo,
    sourceIslandNo,
    targetProjectNo,
    targetIslandNo,
    files,
    runDeliverable,
    deliverableParams,
  }: CreateAuditReplaceParams): Promise<CreateBatchPayload> {
    const formData = new FormData();
    formData.append("mode", "replace");
    formData.append(
      "params_json",
      JSON.stringify({
        source_project_no: sourceProjectNo,
        ...(sourceIslandNo ? { source_island_no: sourceIslandNo } : {}),
        target_project_no: targetProjectNo,
        ...(targetIslandNo ? { target_island_no: targetIslandNo } : {}),
        run_deliverable: runDeliverable,
        ...(runDeliverable && deliverableParams
          ? { deliverable_params: deliverableParams }
          : {}),
      }),
    );
    for (const file of files) {
      formData.append("files[]", file);
    }

    const payload = await this.fetchJson<{
      batch_id: string;
      jobs: RawJobSummary[];
    }>("/api/jobs/audit-replace", {
      method: "POST",
      body: formData,
    });

    return {
      batchId: payload.batch_id,
      jobs: payload.jobs.map((job) => this.normalizeSummary(job)),
    };
  }

  async listTaskGroups(): Promise<TaskGroupList> {
    const payload = await this.fetchJson<{
      total: number;
      items: RawTaskGroupSummary[];
    }>("/api/task-groups");

    return {
      total: payload.total,
      items: payload.items.map((item) => this.normalizeTaskGroupSummary(item)),
    };
  }

  async getTaskGroupDetail(groupId: string): Promise<TaskGroupDetail> {
    const payload = await this.fetchJson<RawTaskGroupDetail>(`/api/task-groups/${groupId}`);
    return this.normalizeTaskGroupDetail(payload);
  }

  async submitTaskGroup(
    groupId: string,
    payload: TaskGroupSubmitPayload,
  ): Promise<TaskGroupDetail> {
    const response = await this.fetchJson<RawTaskGroupDetail>(`/api/task-groups/${groupId}/submit`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        overwrite_archive_existing: payload.overwriteArchiveExisting,
        cancel_existing_in_progress: payload.cancelExistingInProgress,
      }),
    });
    return this.normalizeTaskGroupDetail(response);
  }

  async restartSubmitTaskGroup(
    groupId: string,
    payload: TaskGroupSubmitPayload,
  ): Promise<TaskGroupDetail> {
    const response = await this.fetchJson<RawTaskGroupDetail>(
      `/api/task-groups/${groupId}/restart-submit`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          overwrite_archive_existing: payload.overwriteArchiveExisting,
          cancel_existing_in_progress: payload.cancelExistingInProgress,
        }),
      },
    );
    return this.normalizeTaskGroupDetail(response);
  }

  async listJobs(status?: string, offset = 0, limit = 100): Promise<JobList> {
    const search = new URLSearchParams();
    if (status) {
      search.set("status", status);
    }
    search.set("offset", String(offset));
    search.set("limit", String(limit));

    const payload = await this.fetchJson<{
      total: number;
      items: RawJobSummary[];
    }>(`/api/jobs?${search.toString()}`, undefined, { retry: true });

    return {
      total: payload.total,
      items: payload.items.map((job) => this.normalizeSummary(job)),
    };
  }

  async getJobDetail(jobId: string): Promise<JobDetail> {
    const payload = await this.fetchJson<RawJobDetail>(`/api/jobs/${jobId}`, undefined, {
      retry: true,
    });
    return {
      ...this.normalizeSummary(payload),
      startedAt: payload.started_at ?? null,
      currentFile: payload.current_file ?? null,
      flags: payload.flags ?? [],
      errors: payload.errors ?? [],
      topWrongTexts: payload.top_wrong_texts ?? [],
      topInternalCodes: payload.top_internal_codes ?? [],
      sharedDir: payload.shared_dir ?? null,
      deliverableOutputs: this.normalizeDeliverableOutputs(payload.deliverable_outputs),
      findingGroups: this.normalizeFindingGroups(payload.finding_groups),
      replaceSummary: this.normalizeReplaceSummary(payload.replace_summary),
      factoryIndexMap: this.normalizeFactoryIndexMap(payload.factory_index_map),
    };
  }

  private normalizeSummary(payload: RawJobSummary): JobSummary {
    const sourceFilename = payload.source_filename ?? payload.source_filenames?.[0] ?? payload.job_id;
    return {
      jobId: payload.job_id,
      batchId: payload.batch_id,
      isGroup: payload.is_group ?? false,
      groupId: payload.group_id ?? null,
      sourceFilename,
      sourceFilenames: payload.source_filenames ?? [sourceFilename],
      taskKind: payload.task_kind ?? null,
      jobMode: payload.job_mode ?? null,
      projectNo: payload.project_no,
      status: payload.status,
      stage: payload.stage,
      percent: payload.percent ?? 0,
      message: payload.message ?? "",
      failureReason: payload.failure_reason ?? null,
      stageContext: payload.stage_context ?? null,
      createdAt: payload.created_at,
      finishedAt: payload.finished_at,
      runAuditCheck: payload.run_audit_check ?? false,
      childJobIds: payload.child_job_ids ?? [],
      findingsCount: payload.findings_count ?? 0,
      affectedDrawingsCount: payload.affected_drawings_count ?? 0,
      artifacts: {
        packageAvailable: payload.artifacts.package_available,
        iedAvailable: payload.artifacts.ied_available,
        previewAvailable: payload.artifacts.preview_available ?? false,
        previewMode: payload.artifacts.preview_mode ?? null,
        reportAvailable: payload.artifacts.report_available,
        replacedDwgAvailable: payload.artifacts.replaced_dwg_available,
        packageDownloadUrl: this.resolveUrl(payload.artifacts.package_download_url),
        iedDownloadUrl: this.resolveUrl(payload.artifacts.ied_download_url),
        previewDownloadUrl: this.resolveUrl(payload.artifacts.preview_download_url),
        reportDownloadUrl: this.resolveUrl(payload.artifacts.report_download_url),
        replacedDwgDownloadUrl: this.resolveUrl(payload.artifacts.replaced_dwg_download_url),
      },
      retryAvailable: payload.retry_available,
      taskRole: payload.task_role ?? null,
      sharedRunId: payload.shared_run_id ?? null,
      plotStyleKey: payload.plot_style_key ?? null,
      plotResourceMode: payload.plot_resource_mode ?? null,
      slotId: payload.slot_id ?? null,
      cadVersion: payload.cad_version ?? null,
      accoreconsoleExe: payload.accoreconsole_exe ?? null,
      profileArg: payload.profile_arg ?? null,
      pc3Path: payload.pc3_path ?? null,
      pmpPath: payload.pmp_path ?? null,
      ctbPath: payload.ctb_path ?? null,
      fontPreflightSummary: this.normalizeFontPreflightSummary(payload.font_preflight_summary),
      missingFontsDetected: payload.missing_fonts_detected ?? false,
      fontReplacementApplied: payload.font_replacement_applied ?? false,
      replacementFont: payload.replacement_font ?? null,
      replacementFonts: this.normalizeFontReplacementMap(payload.replacement_fonts),
      replacedStyleCount: payload.replaced_style_count ?? 0,
      children: payload.children?.map((child) => this.normalizeSummary(child)),
    };
  }

  private async fetchJson<T>(
    path: string,
    init?: RequestInit,
    policy: FetchPolicy = {},
  ): Promise<T> {
    const method = (init?.method ?? "GET").toUpperCase();
    const shouldRetry = method === "GET" && Boolean(policy.retry);
    const maxAttempts = shouldRetry ? (policy.retryCount ?? DEFAULT_GET_RETRY_COUNT) + 1 : 1;
    let lastError: unknown = null;

    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      try {
        return await this.fetchJsonOnce<T>(path, init, policy);
      } catch (error) {
        lastError = error;
        if (!shouldRetry || attempt >= maxAttempts - 1 || !this.isRetryableError(error)) {
          throw error;
        }
        await this.delay(this.retryDelayMs(attempt, policy.retryBaseDelayMs));
      }
    }

    throw lastError;
  }

  private async fetchJsonOnce<T>(
    path: string,
    init?: RequestInit,
    policy: FetchPolicy = {},
  ): Promise<T> {
    const timeoutMs = policy.timeoutMs ?? (policy.retry ? DEFAULT_GET_TIMEOUT_MS : undefined);
    const abortController = timeoutMs ? new AbortController() : null;
    const timeoutId =
      abortController && timeoutMs
        ? window.setTimeout(() => abortController.abort(), timeoutMs)
        : null;
    const initWithSignal = abortController ? { ...init, signal: abortController.signal } : init;
    const requestInit = this.withAuthorization(initWithSignal);

    try {
      const response = await fetch(this.buildUrl(path), requestInit);
      const text = await response.text();
      const payload = text ? this.parseJsonOrText(text) : null;

      if (!response.ok) {
        if (response.status === 401) {
          this.onUnauthorized?.();
        }
        const error: ApiError = {
          status: response.status,
          detail:
            payload && typeof payload === "object" && "detail" in payload
              ? (payload as { detail: ApiError["detail"] }).detail
              : typeof payload === "string"
                ? payload
                : null,
        };
        throw error;
      }

      return payload as T;
    } finally {
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
    }
  }

  private withAuthorization(init?: RequestInit): RequestInit | undefined {
    const accessToken = this.getAccessToken?.();
    if (!accessToken) {
      return init;
    }

    const headers = new Headers(init?.headers);
    if (!headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${accessToken}`);
    }

    return {
      ...init,
      headers,
    };
  }

  private parseJsonOrText(text: string): unknown {
    try {
      return JSON.parse(text) as unknown;
    } catch {
      return text;
    }
  }

  private buildUrl(path: string) {
    if (/^https?:\/\//i.test(path)) {
      return path;
    }
    return `${this.normalizedBaseUrl}${path}`;
  }

  private resolveUrl(path: string | null | undefined) {
    if (!path) {
      return path;
    }
    return this.buildUrl(path);
  }

  private isRetryableError(error: unknown) {
    if (this.isApiError(error)) {
      return [408, 429, 500, 502, 503, 504].includes(error.status);
    }
    return true;
  }

  private isApiError(error: unknown): error is ApiError {
    return Boolean(error && typeof error === "object" && "status" in error);
  }

  private retryDelayMs(attempt: number, baseDelayMs = DEFAULT_GET_RETRY_BASE_DELAY_MS) {
    const exponentialDelayMs = baseDelayMs * 2 ** attempt;
    const jitterMs = Math.floor(exponentialDelayMs * 0.2 * Math.random());
    return exponentialDelayMs + jitterMs;
  }

  private async delay(ms: number) {
    await new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  private normalizeDeliverableOutputs(
    payload: RawJobDetail["deliverable_outputs"],
  ): DeliverableOutputs | undefined {
    if (!payload) {
      return undefined;
    }

    return {
      dwgCount: payload.dwg_count ?? 0,
      pdfCount: payload.pdf_count ?? 0,
      documents: (payload.documents ?? []).map((document) => ({
        name: document.name ?? "",
        kind: document.kind ?? "",
      })),
      drawings: (payload.drawings ?? []).map((drawing) => ({
        name: drawing.name ?? "",
        internalCode: drawing.internal_code ?? null,
        dwgName: drawing.dwg_name ?? null,
        pdfName: drawing.pdf_name ?? null,
        pageTotal: drawing.page_total ?? 0,
      })),
    };
  }

  private normalizeFindingGroups(payload: RawJobDetail["finding_groups"]): FindingGroup[] | undefined {
    if (!payload) {
      return undefined;
    }

    return payload.map((group) => ({
      matchedText: group.matched_text ?? "",
      count: group.count ?? 0,
      internalCodes: group.internal_codes ?? [],
    }));
  }

  private normalizeReplaceSummary(payload: RawJobDetail["replace_summary"]) {
    if (!payload) {
      return undefined;
    }

    return {
      replacementCount: payload.replacement_count ?? 0,
      skippedCount: payload.skipped_count ?? 0,
      affectedDrawingsCount: payload.affected_drawings_count ?? 0,
      sourceProjectNo: payload.source_project_no ?? "",
      sourceIslandNo: payload.source_island_no ?? null,
      targetProjectNo: payload.target_project_no ?? "",
      targetIslandNo: payload.target_island_no ?? null,
      topReplacedTexts: payload.top_replaced_texts ?? [],
      topInternalCodes: payload.top_internal_codes ?? [],
    };
  }

  private normalizeFactoryIndexMap(payload: RawJobDetail["factory_index_map"]) {
    if (!payload) {
      return null;
    }

    return {
      applied: Boolean(payload.applied),
      actionCount: payload.action_count ?? 0,
      reportJson: payload.report_json ?? null,
      message: payload.message ?? "",
    };
  }

  private normalizeFontPreflightSummary(
    payload: RawJobSummary["font_preflight_summary"],
  ): FontPreflightSummary | null {
    if (!payload) {
      return null;
    }

    return {
      files: (payload.files ?? []).map((file) => this.normalizeFontPreflightFile(file)),
      policy: payload.policy ?? "none",
      fontCompatibilityMode: Boolean(payload.font_compatibility_mode),
      replacementFonts: this.normalizeFontReplacementMap(payload.replacement_fonts),
      fontMapPath: payload.font_map_path ?? null,
      fontAlt: payload.font_alt ?? null,
    };
  }

  private normalizeFontPreflightFile(
    file: NonNullable<RawFontPreflightResult["files"]>[number],
  ): FontPreflightResult["files"][number] {
    return {
      filename: file.filename ?? "",
      status: file.status ?? "",
      missingFonts: (file.missing_fonts ?? []).map((font) => ({
        styleName: font.style_name ?? "",
        fontName: font.font_name ?? "",
        bigfontName: font.bigfont_name ?? "",
        kind: font.kind ?? "unknown",
        usedInBlock: Boolean(font.used_in_block),
      })),
      detectedStyleCount: file.detected_style_count ?? 0,
      missingStyleCount: file.missing_style_count ?? 0,
      fontReplacementApplied: Boolean(file.font_replacement_applied),
      replacementFont: file.replacement_font ?? null,
      replacementFonts: this.normalizeFontReplacementMap(file.replacement_fonts),
      fontCompatibilityMode: Boolean(file.font_compatibility_mode),
      fontCompatibilityReplacements: this.normalizeFontReplacementMap(
        file.font_compatibility_replacements,
      ),
      replacedStyleCount: file.replaced_style_count ?? 0,
      verifyAfterReplace: file.verify_after_replace
        ? {
            status: file.verify_after_replace.status ?? "",
            missingStyleCount: file.verify_after_replace.missing_style_count ?? 0,
            missingFonts: (file.verify_after_replace.missing_fonts ?? []).map((font) => ({
              styleName: font.style_name ?? "",
              fontName: font.font_name ?? "",
              bigfontName: font.bigfont_name ?? "",
              kind: font.kind ?? "unknown",
              usedInBlock: Boolean(font.used_in_block),
            })),
          }
        : null,
      fontReplacementIncomplete: Boolean(file.font_replacement_incomplete),
      errors: file.errors ?? [],
    };
  }

  private normalizeFontReplacementOptions(
    options: RawFontPreflightResult["replacement_options"],
  ): FontReplacementOption[] {
    return (options ?? []).map((option) => ({
      label: option.label ?? "",
      value: option.value ?? "",
      family: option.family ?? "",
      path: option.path ?? "",
      kind: option.kind ?? "unknown",
      source: option.source ?? "unknown",
    }));
  }

  private normalizeFontReplacementOptionsByKind(
    optionsByKind: RawFontPreflightResult["replacement_options_by_kind"],
    fallbackOptions: FontReplacementOption[],
  ): Record<string, FontReplacementOption[]> {
    if (optionsByKind && Object.keys(optionsByKind).length > 0) {
      return Object.fromEntries(
        Object.entries(optionsByKind).map(([kind, options]) => [
          kind,
          this.normalizeFontReplacementOptions(options ?? []),
        ]),
      );
    }

    const grouped = new Map<string, FontReplacementOption[]>();
    for (const option of fallbackOptions) {
      const kind = option.kind.trim().toLowerCase() || "unknown";
      grouped.set(kind, [...(grouped.get(kind) ?? []), option]);
    }
    return Object.fromEntries(grouped.entries());
  }

  private normalizeTaskGroupSummary(payload: RawTaskGroupSummary): TaskGroupSummary {
    return {
      groupId: payload.group_id,
      batchId: payload.batch_id ?? null,
      projectNo: payload.project_no ?? null,
      status: payload.status ?? "queued",
      createdAt: payload.created_at ?? "",
      sourceFilenames: payload.source_filenames ?? [],
      ownerSnapshot: this.normalizeTaskOwnerSnapshot(payload.owner_snapshot),
      creatorName: payload.creator_name ?? null,
      creatorAccount: payload.creator_account ?? null,
      creatorOffice: payload.creator_office ?? null,
      workflowStatus: payload.workflow_status ?? "draft",
      currentNodeKey: payload.current_node_key ?? null,
      archiveStatus: payload.archive_status ?? "pending",
      workload: this.normalizeWorkloadSummary(payload.workload),
      effectiveWorkload: payload.effective_workload ?? 0,
      canViewDetail: Boolean(payload.can_view_detail),
      canSubmit: Boolean(payload.can_submit),
      canApprove: Boolean(payload.can_approve),
      isRelatedToCurrentUser: Boolean(payload.is_related_to_current_user),
    };
  }

  private normalizeTaskGroupDetail(payload: RawTaskGroupDetail): TaskGroupDetail {
    return {
      ...this.normalizeTaskGroupSummary(payload),
      childJobIds: payload.child_job_ids ?? [],
      personnelSnapshot: this.normalizePersonnelSnapshot(payload.personnel_snapshot),
      workflow: this.normalizeWorkflowState(payload.workflow),
      archive: this.normalizeArchiveState(payload.archive),
      replacement: this.normalizeReplacementState(payload.replacement),
      legacyVisibility: this.normalizeLegacyVisibilityState(payload.legacy_visibility),
    };
  }

  private normalizeTaskOwnerSnapshot(
    payload: RawTaskOwnerSnapshot | null | undefined,
  ): TaskOwnerSnapshot | null {
    if (!payload?.creator_account || !payload.creator_name || !payload.creator_role) {
      return null;
    }

    return {
      creatorAccount: payload.creator_account,
      creatorName: payload.creator_name,
      creatorRole: payload.creator_role,
      creatorOffice: payload.creator_office ?? null,
      createdByScope: payload.created_by_scope ?? "",
      submittedAt: payload.submitted_at ?? null,
    };
  }

  private normalizeWorkloadSummary(payload: RawWorkloadSummary | null | undefined): WorkloadSummary {
    return {
      initialWorkloadA1: payload?.initial_workload_a1 ?? 0,
      finalWorkloadA1: payload?.final_workload_a1 ?? 0,
      oneReviewFactor: payload?.one_review_factor ?? 1,
      twoReviewFactor: payload?.two_review_factor ?? 1,
      threeReviewFactor: payload?.three_review_factor ?? 1,
      nodeFactors: Object.fromEntries(
        Object.entries(payload?.node_factors ?? {}).map(([key, value]) => [key, value ?? 1]),
      ),
      settlementStatus: payload?.settlement_status ?? "pending",
      settledAt: payload?.settled_at ?? null,
      contributorEntries: (payload?.contributor_entries ?? []).map((entry) => ({
        roleKey: entry.role_key ?? "",
        accountId: entry.account_id ?? null,
        displayName: entry.display_name ?? null,
        workloadA1: entry.workload_a1 ?? 0,
        settledAt: entry.settled_at ?? null,
      })),
    };
  }

  private normalizePersonnelSnapshot(
    payload: RawPersonnelSnapshot | null | undefined,
  ): PersonnelSnapshot {
    return {
      members: Object.fromEntries(
        Object.entries(payload?.members ?? {}).map(([fieldName, member]) => [
          fieldName,
          this.normalizeNormalizedPersonnel(member, fieldName),
        ]),
      ),
    };
  }

  private normalizeNormalizedPersonnel(
    payload: RawNormalizedPersonnel | null | undefined,
    fallbackFieldName = "",
  ): NormalizedPersonnel {
    return {
      fieldName: payload?.field_name ?? fallbackFieldName,
      rawValue: payload?.raw_value ?? null,
      normalizedValue: payload?.normalized_value ?? null,
      matchedAccount: payload?.matched_account ?? null,
      matchedName: payload?.matched_name ?? null,
      matchStrategy: payload?.match_strategy ?? null,
      status: payload?.status ?? "empty",
      errors: payload?.errors ?? [],
    };
  }

  private normalizePersonnelCandidate(
    payload: RawPersonnelCandidate | null | undefined,
  ): PersonnelCandidate {
    return {
      accountId: payload?.account_id ?? "",
      displayName: payload?.display_name ?? "",
      role: payload?.role ?? "",
      officeCode: payload?.office_code ?? null,
      officeName: payload?.office_name ?? null,
      valid: payload?.valid ?? true,
    };
  }

  private normalizeAccountRecord(payload: RawAccountRecord | null | undefined): AccountRecord {
    return {
      officeCode: payload?.office_code ?? null,
      officeName: payload?.office_name ?? null,
      accountId: payload?.account_id ?? "",
      displayName: payload?.display_name ?? "",
      role: payload?.role ?? "",
      password: payload?.password ?? "",
      valid: payload?.valid ?? true,
      rowNumber: payload?.row_number ?? null,
      errors: payload?.errors ?? [],
    };
  }

  private normalizeInvalidAccountRow(
    payload: RawInvalidAccountRow | null | undefined,
  ): InvalidAccountRow {
    return {
      rowNumber: payload?.row_number ?? 0,
      raw: payload?.raw ?? {},
      errors: payload?.errors ?? [],
    };
  }

  private normalizeAdminConfig(payload: RawAdminConfig | null | undefined): AdminConfig {
    return {
      archiveRootPath: payload?.archive_root_path ?? "",
    };
  }

  private serializeAccountCreatePayload(payload: AccountCreatePayload) {
    return {
      office_code: payload.officeCode,
      office_name: payload.officeName,
      account_id: payload.accountId,
      display_name: payload.displayName,
      role: payload.role,
      password: payload.password,
    };
  }

  private serializeAccountUpdatePayload(payload: AccountUpdatePayload) {
    return Object.fromEntries(
      Object.entries({
        office_code: payload.officeCode,
        office_name: payload.officeName,
        account_id: payload.accountId,
        display_name: payload.displayName,
        role: payload.role,
        password: payload.password,
      }).filter(([, value]) => value !== undefined),
    );
  }

  private serializeWorkflowRepairPayload(payload: WorkflowRepairPayload) {
    return {
      ...(payload.replaceWithAccountId
        ? { replace_with_account_id: payload.replaceWithAccountId }
        : {}),
      ...(payload.createAccountPayload
        ? {
            create_account_payload: this.serializeAccountCreatePayload(
              payload.createAccountPayload,
            ),
          }
        : {}),
    };
  }

  private buildWorkloadQuery(filters: WorkloadQueryParams): URLSearchParams {
    const search = new URLSearchParams();
    if (filters.startDate) {
      search.set("start_date", filters.startDate);
    }
    if (filters.endDate) {
      search.set("end_date", filters.endDate);
    }
    if (filters.status) {
      search.set("status", filters.status);
    }
    if (typeof filters.validOnly === "boolean") {
      search.set("valid_only", filters.validOnly ? "true" : "false");
    }
    return search;
  }

  private async loadWorkloadScope(
    path: string,
    filters: WorkloadQueryParams,
  ): Promise<WorkloadScopeResponse> {
    const search = this.buildWorkloadQuery(filters);
    const suffix = search.toString();
    const payload = await this.fetchJson<RawWorkloadScopeResponse>(
      `${path}${suffix ? `?${suffix}` : ""}`,
    );
    return this.normalizeWorkloadScopeResponse(payload);
  }

  private normalizeWorkloadScopeResponse(
    payload: RawWorkloadScopeResponse | null | undefined,
  ): WorkloadScopeResponse {
    return {
      scope: payload?.scope ?? "me",
      filters: {
        startDate: payload?.filters?.start_date ?? null,
        endDate: payload?.filters?.end_date ?? null,
        status: payload?.filters?.status ?? null,
        validOnly: Boolean(payload?.filters?.valid_only),
      },
      officeName: payload?.office_name ?? null,
      totalWorkloadA1: payload?.total_workload_a1 ?? 0,
      totalsByAccount: Object.fromEntries(
        Object.entries(payload?.totals_by_account ?? {}).map(([accountId, value]) => [
          accountId,
          value ?? 0,
        ]),
      ),
      entries: (payload?.entries ?? []).map((entry) => ({
        roleKey: entry.role_key ?? "",
        accountId: entry.account_id ?? null,
        displayName: entry.display_name ?? null,
        workloadA1: entry.workload_a1 ?? 0,
        settledAt: entry.settled_at ?? null,
        groupId: entry.group_id ?? "",
        settlementStatus: entry.settlement_status ?? "pending",
      })),
    };
  }

  private normalizeWorkflowState(payload: RawWorkflowState | null | undefined): WorkflowState {
    return {
      status: payload?.status ?? "draft",
      initiatedAt: payload?.initiated_at ?? null,
      initiatedByAccount: payload?.initiated_by_account ?? null,
      initiatedByName: payload?.initiated_by_name ?? null,
      duplicatePolicy: payload?.duplicate_policy ?? null,
      overwriteArchiveTarget: payload?.overwrite_archive_target ?? null,
      currentNodeKey: payload?.current_node_key ?? null,
      nodes: (payload?.nodes ?? []).map((node) => ({
        nodeKey: node.node_key ?? "",
        nodeLabel: node.node_label ?? "",
        assigneeAccount: node.assignee_account ?? null,
        assigneeName: node.assignee_name ?? null,
        status: node.status ?? "pending",
        factor: node.factor ?? 1,
        approvedAt: node.approved_at ?? null,
        actedByAccount: node.acted_by_account ?? null,
        actedByName: node.acted_by_name ?? null,
      })),
      archiveStatus: payload?.archive_status ?? null,
      archiveRetryCount: payload?.archive_retry_count ?? 0,
      archiveLastError: payload?.archive_last_error ?? null,
      archiveLastAttemptAt: payload?.archive_last_attempt_at ?? null,
    };
  }

  private normalizeArchiveState(payload: RawArchiveState | null | undefined): ArchiveState {
    return {
      archiveRootPath: payload?.archive_root_path ?? null,
      targetDir: payload?.target_dir ?? null,
      status: payload?.status ?? "pending",
      overwriteMode: payload?.overwrite_mode ?? null,
      startedAt: payload?.started_at ?? null,
      completedAt: payload?.completed_at ?? null,
      lastError: payload?.last_error ?? null,
      retryCount: payload?.retry_count ?? 0,
      lastAttemptAt: payload?.last_attempt_at ?? null,
      archivedFiles: payload?.archived_files ?? [],
    };
  }

  private normalizeReplacementState(
    payload: RawReplacementState | null | undefined,
  ): ReplacementState {
    return {
      albumInternalCode: payload?.album_internal_code ?? null,
      revision: payload?.revision ?? null,
      replacedGroupId: payload?.replaced_group_id ?? null,
      replacedRecordPendingDelete: Boolean(payload?.replaced_record_pending_delete),
    };
  }

  private normalizeLegacyVisibilityState(
    payload: RawLegacyVisibilityState | null | undefined,
  ): LegacyVisibilityState {
    return {
      scope: payload?.scope ?? "admin_only",
      reason: payload?.reason ?? null,
    };
  }

  private normalizeAccount(payload: RawAccount): CurrentAccount {
    return {
      accountId: payload.account_id,
      displayName: payload.display_name,
      role: payload.role,
      officeCode: payload.office_code ?? null,
      officeName: payload.office_name ?? null,
      valid: payload.valid ?? true,
      pendingTodoCount: payload.pending_todo_count ?? 0,
    };
  }

  private normalizeFontReplacementMap(
    value: Record<string, string | null> | null | undefined,
  ): FontReplacementMap {
    return Object.fromEntries(
      Object.entries(value ?? {})
        .map(([kind, fontName]) => [kind.trim().toLowerCase(), fontName?.trim() ?? ""])
        .filter(([kind, fontName]) => kind && fontName),
    );
  }
}
