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
  AiAgent,
  AiAttachment,
  AiConversationDetail,
  AiConversationSummary,
  AiMcpServer,
  AiMessage,
  AiSendMessageResult,
  AiSkill,
  AiState,
  ApiAdapter,
  ApiError,
  ArchiveState,
  CalculationBookDirectionEvidence,
  CalculationBookPreflightResult,
  ChangePageResult,
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
  JobExecutionActions,
  JobRetryResult,
  JobWorkloadSubmission,
  JobWorkloadSubmitPayload,
  JobList,
  JobListSort,
  JobSummary,
  JobsActivity,
  LegacyVisibilityState,
  LoginRequest,
  LoginResponse,
  NormalizedPersonnel,
  PersonnelCandidate,
  PersonnelNormalizationResult,
  PersonnelSnapshot,
  PingStatus,
  ReplacementState,
  ReinforcementSource,
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
const AI_CONTROL_TIMEOUT_MS = 15000;

type RawArtifacts = {
  package_available: boolean;
  ied_available: boolean;
  preview_available?: boolean | null;
  preview_mode?: "plain" | "annotated" | null;
  report_available: boolean;
  replaced_dwg_available: boolean;
  calculation_docx_available?: boolean | null;
  calculation_log_available?: boolean | null;
  package_download_url?: string | null;
  ied_download_url?: string | null;
  preview_download_url?: string | null;
  report_download_url?: string | null;
  replaced_dwg_download_url?: string | null;
  calculation_docx_download_url?: string | null;
  calculation_log_download_url?: string | null;
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
  owner_snapshot?: RawTaskOwnerSnapshot | null;
  creator_name?: string | null;
  creator_account?: string | null;
  creator_office?: string | null;
  task_kind?:
    | "deliverable"
    | "audit_check"
    | "audit_replace"
    | "calculation_book"
    | "change_page_extract"
    | null;
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
  workload?: RawWorkloadSummary | null;
  effective_workload?: number | null;
  artifacts: RawArtifacts;
  retry_available: boolean;
  children?: RawJobSummary[] | null;
};

type RawJobDetail = RawJobSummary & {
  started_at?: string | null;
  current_file?: string | null;
  flags?: string[];
  errors?: string[];
  diagnostics?: Array<{
    kind?: string | null;
    severity?: string | null;
    title?: string | null;
    summary?: string | null;
    suggestion?: string | null;
    details?: Array<{
      label?: string | null;
      items?: string[] | null;
    }> | null;
    raw_items?: string[] | null;
  }> | null;
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
    category?: string | null;
    context_kind?: string | null;
    issue_type?: string | null;
    summary?: string | null;
    details?: string[] | null;
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
  calculation_book_output?: {
    reinforcement_source?: ReinforcementSource | null;
    figure_count?: number | null;
    template_type?: string | null;
    output_filename?: string | null;
    ai_normalized?: boolean | null;
    warning_count?: number | null;
    warnings?: Array<{
      code?: string | null;
      scope?: "wall" | "slab" | "reinforcement" | null;
      identity?: string | null;
      direction?: string | null;
      source_sheet?: string | null;
      source_row?: number | null;
      source_cells?: Record<string, string> | null;
      reason?: string | null;
      blank_fields?: string[] | null;
    }> | null;
    ai_normalization?: {
      skill_id?: string | null;
      model?: string | null;
      profile?: string | null;
      call_count?: number | null;
      source_row_count?: number | null;
      normalized_wall_count?: number | null;
      normalized_slab_count?: number | null;
      review_warning_count?: number | null;
      duration_ms?: number | null;
      validation?: string | null;
    } | null;
    ai_rebar_suggestion?: {
      skill_id?: string | null;
      skill_version?: string | null;
      skill_sha256?: string | null;
      model?: string | null;
      call_count?: number | null;
      suggested_direction_count?: number | null;
      blank_direction_count?: number | null;
      repair_round_count?: number | null;
      validation?: string | null;
    } | null;
  } | null;
  change_page_result?: {
    archive_name?: string | null;
    items?: Array<{
      name?: string | null;
      pages?: number | null;
      relative_path?: string | null;
    }> | null;
    text?: string | null;
    pdf_count?: number | null;
    total_pages?: number | null;
    ignored_file_count?: number | null;
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
    font_compatibility_required?: boolean | null;
    empty_style_entity_replaced_count?: number | null;
    empty_style_style_patched_count?: number | null;
    empty_style_shared_skipped_count?: number | null;
    empty_style_shared_styles?: string[] | null;
    empty_style_target_regions_count?: number | null;
    empty_style_global_replaced_count?: number | null;
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
    unit_factory_codes?: string[];
    batch_filename_identity_regex?: string;
    factory_index_maps?: {
      source_variant_options?: Record<string, string[]>;
      target_variant_options?: Record<string, string[]>;
    };
  };
  calculation_book?: {
    templates?: Array<{ value?: string | null; label?: string | null }>;
    project_options?: Array<{ value?: string | null; label?: string | null }>;
    fields?: Array<{
      key?: string | null;
      label?: string | null;
      type?: string | null;
      required?: boolean | null;
      default?: string | number | boolean | null;
      unit?: string | null;
      placeholder?: string | null;
      options?: string[] | null;
      options_from?: string | null;
      derived_from?: string | null;
    }>;
    archive?: {
      accept?: string[] | null;
      required_root_directions?: string[] | null;
      required_folders?: string[] | null;
      root_figure_pattern?: string | null;
      description?: string | null;
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
  group_display_name?: string | null;
  album_internal_code?: string | null;
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
  contributor_entries?: Array<{
    role_key?: string | null;
    account_id?: string | null;
    display_name?: string | null;
    workload_a1?: number | null;
    settled_at?: string | null;
  }> | null;
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
  valid?: boolean | null;
  row_number?: number | null;
  errors?: string[] | null;
};

type RawInvalidAccountRow = {
  row_number: number;
  raw?: Record<string, string> | null;
  errors?: string[] | null;
};

const SENSITIVE_ACCOUNT_RAW_KEY_MARKERS = [
  "password",
  "passwd",
  "pwd",
  "secret",
  "token",
  "apikey",
  "accesskey",
  "密码",
  "密碼",
  "口令",
] as const;

function sanitizeInvalidAccountRaw(
  payload: Record<string, string> | null | undefined,
): Record<string, string> {
  return Object.fromEntries(
    Object.entries(payload ?? {}).filter(([key]) => {
      const normalizedKey = key.toLocaleLowerCase("en-US").replace(/[^\p{L}\p{N}]/gu, "");
      return !SENSITIVE_ACCOUNT_RAW_KEY_MARKERS.some((marker) => normalizedKey.includes(marker));
    }),
  );
}

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
  display_name?: string | null;
  album_internal_code?: string | null;
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
  submit_blockers?: string[] | null;
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

type RawJobExecutionActions = {
  can_cancel: boolean;
  can_retry: boolean;
  cancel_requested: boolean;
  cancel_reason: string | null;
  retry_reason: string | null;
};

type HttpAdapterOptions = {
  getAccessToken?: () => string | null;
  onUnauthorized?: () => void;
};

type RawAiAgent = {
  agent_id?: string | null;
  name?: string | null;
  description?: string | null;
};

type RawAiSkill = {
  skill_id?: string | null;
  name?: string | null;
  description?: string | null;
  enabled?: boolean | null;
  read_only?: boolean | null;
};

type RawAiMcpServer = {
  server_id?: string | null;
  name?: string | null;
  description?: string | null;
  enabled?: boolean | null;
  read_only?: boolean | null;
  transport?: string | null;
};

type RawAiState = {
  enabled?: boolean | null;
  profile?: string | null;
  model?: string | null;
  owner_key?: string | null;
  default_agent?: string | null;
  attachments?: {
    enabled?: boolean | null;
    allowed_extensions?: string[] | null;
    max_files_per_message?: number | null;
    max_image_size_mb?: number | null;
    max_file_size_mb?: number | null;
    max_total_size_mb_per_message?: number | null;
  } | null;
  agents?: RawAiAgent[] | null;
  skills?: RawAiSkill[] | null;
  mcp_servers?: RawAiMcpServer[] | null;
};

type RawAiConversationSummary = {
  conversation_id?: string | null;
  title?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  message_count?: number | null;
};

type RawAiMessage = {
  message_id?: string | null;
  role?: string | null;
  content?: string | null;
  created_at?: string | null;
  model_profile?: string | null;
  metadata?: Record<string, unknown> | null;
};

type RawAiConversationDetail = RawAiConversationSummary & {
  messages?: RawAiMessage[] | null;
};

type RawAiAttachment = {
  attachment_id?: string | null;
  conversation_id?: string | null;
  message_id?: string | null;
  original_name?: string | null;
  media_type?: string | null;
  kind?: string | null;
  size_bytes?: number | null;
  sha256?: string | null;
  status?: string | null;
  metadata?: Record<string, unknown> | null;
  error_code?: string | null;
  created_at?: string | null;
};

type RawAiSendMessageResult = {
  conversation_id?: string | null;
  user_message?: RawAiMessage | null;
  assistant_message?: RawAiMessage | null;
  memory?: {
    used_history_messages?: number | null;
  } | null;
};

const CHAT_POST_TIMEOUT_MS = 90000;

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
    const response = await this.fetchJson<{ token: string; account: RawAccount }>(
      "/api/auth/login",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: payload.accountId, password: payload.password }),
      },
    );
    return { token: response.token, account: this.normalizeAccount(response.account) };
  }

  async logout(): Promise<{ ok: boolean }> {
    return this.fetchJson<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
  }

  async getMe(): Promise<CurrentAccount> {
    return this.normalizeAccount(await this.fetchJson<RawAccount>("/api/auth/me"));
  }

  async changePassword(newPassword: string): Promise<CurrentAccount> {
    const payload = await this.fetchJson<RawAccount>("/api/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_password: newPassword }),
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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field_name: fieldName, raw_value: rawValue }),
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
    const payload = await this.fetchJson<{ total: number; items: RawTaskGroupSummary[] }>(
      "/api/workflow/monitor",
    );
    return {
      total: payload.total,
      items: (payload.items ?? []).map((item) => this.normalizeTaskGroupSummary(item)),
    };
  }

  async approveWorkflow(groupId: string, payload: WorkflowApprovePayload): Promise<void> {
    await this.fetchJson(`/api/workflow/${groupId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ factor: payload.factor, ...(payload.nodeKey ? { node_key: payload.nodeKey } : {}) }),
    });
  }

  async repairCurrentNode(groupId: string, payload: WorkflowRepairPayload): Promise<void> {
    await this.fetchJson(`/api/workflow/${groupId}/repair-current-node`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(this.serializeWorkflowRepairPayload(payload)),
    });
  }

  async listAccounts(): Promise<AccountListResponse> {
    const payload = await this.fetchJson<{ items?: RawAccountRecord[] | null }>("/api/accounts");
    return { items: (payload.items ?? []).map((item) => this.normalizeAccountRecord(item)) };
  }

  async listInvalidAccountRows(): Promise<InvalidAccountRowList> {
    const payload = await this.fetchJson<{ items?: RawInvalidAccountRow[] | null }>(
      "/api/accounts/invalid-rows",
    );
    return { items: (payload.items ?? []).map((item) => this.normalizeInvalidAccountRow(item)) };
  }

  async createAccount(payload: AccountCreatePayload): Promise<AccountRecord> {
    const response = await this.fetchJson<RawAccountRecord>("/api/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(this.serializeAccountCreatePayload(payload)),
    });
    return this.normalizeAccountRecord(response);
  }

  async updateAccount(accountId: string, payload: AccountUpdatePayload): Promise<AccountRecord> {
    const response = await this.fetchJson<RawAccountRecord>(`/api/accounts/${accountId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(this.serializeAccountUpdatePayload(payload)),
    });
    return this.normalizeAccountRecord(response);
  }

  async updateAccountRow(rowNumber: number, payload: AccountUpdatePayload): Promise<AccountRecord> {
    const response = await this.fetchJson<RawAccountRecord>(`/api/accounts/rows/${rowNumber}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(this.serializeAccountUpdatePayload(payload)),
    });
    return this.normalizeAccountRecord(response);
  }

  async getAdminConfig(): Promise<AdminConfig> {
    return this.normalizeAdminConfig(await this.fetchJson<RawAdminConfig>("/api/admin/config"));
  }

  async patchAdminConfig(payload: AdminConfig): Promise<AdminConfig> {
    const response = await this.fetchJson<RawAdminConfig>("/api/admin/config", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ archive_root_path: payload.archiveRootPath ?? "" }),
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

  async rememberAuditReplaceFactoryCodes(
    codes: readonly string[],
  ): Promise<{ factoryCodes: readonly string[] }> {
    const payload = await this.fetchJson<{ factory_codes: string[] }>(
      "/api/meta/audit-replace/factory-codes",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ codes }),
      },
    );
    return { factoryCodes: payload.factory_codes ?? [] };
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
    unitFactoryCodes,
    files,
    runDeliverable,
    deliverableParams,
  }: CreateAuditReplaceParams): Promise<CreateBatchPayload> {
    const formData = new FormData();
    const normalizedUnitFactoryCodes = [...new Set(
      (unitFactoryCodes ?? [])
        .map((code) => code.trim().toUpperCase())
        .filter((code) => /^[A-Z][A-Z0-9]{1,3}$/.test(code)),
    )];
    formData.append("mode", "replace");
    formData.append(
      "params_json",
      JSON.stringify({
        source_project_no: sourceProjectNo,
        ...(sourceIslandNo ? { source_island_no: sourceIslandNo } : {}),
        target_project_no: targetProjectNo,
        ...(targetIslandNo ? { target_island_no: targetIslandNo } : {}),
        unit_factory_codes: normalizedUnitFactoryCodes,
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

  async createCalculationBook(
    params: SubmissionParams,
  ): Promise<CreateBatchPayload> {
    const formData = new FormData();
    formData.append("params_json", JSON.stringify(params));
    const payload = await this.fetchJson<{
      batch_id: string;
      jobs: RawJobSummary[];
    }>("/api/jobs/calculation-books", {
      method: "POST",
      body: formData,
    });
    return {
      batchId: payload.batch_id,
      jobs: payload.jobs.map((job) => this.normalizeSummary(job)),
    };
  }

  async preflightCalculationBook(
    archive: File,
    options: {
      includeSlabStress: boolean;
      reinforcementSource: ReinforcementSource;
      params?: SubmissionParams;
    },
  ): Promise<CalculationBookPreflightResult> {
    const formData = new FormData();
    formData.append("archive", archive);
    formData.append(
      "include_slab_stress",
      String(options.includeSlabStress),
    );
    formData.append("reinforcement_source", options.reinforcementSource);
    if (options.params) {
      formData.append("params_json", JSON.stringify(options.params));
    }
    const payload = await this.fetchJson<{
      preflight_token: string;
      reinforcement_source?: ReinforcementSource | null;
      requires_ai_recommendation?: boolean | null;
      figure_count: number;
      wall_direction_figure_count?: number | null;
      zero_figure_count: number;
      z_zero_or_missing_smx_count?: number | null;
      wall_count: number;
      reinforcement_source_row_count?: number;
      reinforcement_normalized_row_count?: number;
      reinforcement_issue_row_count?: number;
      reinforcement_unique_wall_count?: number;
      normalization_triggered?: boolean;
      normalization_skill_id?: string | null;
      requires_ai_normalization?: boolean;
      ai_reinforcement_expected_source_row_count?: number | null;
      ai_confirmation_message?: string | null;
      format_inspection?: {
        wall_sheet?: string | null;
        slab_sheet?: string | null;
        reasons?: Array<{
          scope?: string | null;
          code?: string | null;
          sheet?: string | null;
          message?: string | null;
        }> | null;
      } | null;
      normalization_issues?: Array<{
        source_sheet: string;
        source_row: number;
        source_cells: Record<"wall" | "X" | "Y" | "Z", string>;
        original_values?: Record<"wall" | "X" | "Y" | "Z", string>;
        original_wall_text: string;
        wall_id: string | null;
        error: string;
      }>;
      image_wall_group_count?: number;
      image_unique_wall_count?: number;
      matched_unique_wall_count?: number;
      image_only_wall_ids?: string[];
      workbook_only_wall_ids?: string[];
      requires_wall_count_confirmation?: boolean;
      slab_figure_count: number;
      slab_zero_figure_count?: number | null;
      slab_elevation_count: number;
      slab_actual_group_count?: number | null;
      reinforcement_workbook: string | null;
      requires_ocr_review?: boolean | null;
      ignored_root_images?: string[] | null;
      review_items?: Array<{
        code?: string | null;
        scope?: string | null;
        identity?: string | null;
        direction?: string | null;
        image_filename?: string | null;
        reason?: string | null;
      }> | null;
      requires_manual_confirmation: boolean;
      confirmations: Array<{
        wall_id: string;
        base_wall_id: string;
        reasons: string[];
        suggested_source_row: number;
        candidates: Array<{
          source_row: number;
          source_sheet: string;
          directions: Record<string, {
            source_cell: string;
            original_text: string;
            canonical_specification: string;
            narrative_specification: string;
            actual_area: number;
          }>;
        }>;
      }>;
      walls: Array<{
        wall_id: string;
        base_wall_id: string;
        group_index: number | null;
        suggested_source_row: number | null;
        directions: Record<string, {
          image_filename: string;
          smn: number | null;
          smx: number | null;
          legend_values: number[];
          is_zero_result: boolean;
          source_cell?: string | null;
          original_text: string;
          canonical_specification: string;
          narrative_specification: string;
          actual_area: number | string | null;
        }>;
      }>;
      slabs: Array<{
        elevation: string;
        key: string;
        position: "TOP" | "MIDDLE" | "BOTTOM" | null;
        direction: "X" | "Y" | "Z";
        image_filename: string;
        smn: number | null;
        smx: number | null;
        legend_values: number[];
        is_zero_result: boolean;
        source_row: number | null;
        source_cell?: string | null;
        original_text: string;
        canonical_specification: string;
        narrative_specification: string;
        actual_area: number | string | null;
      }>;
      warnings: Array<{ code: string; filenames?: string[] | null }>;
    }>("/api/jobs/calculation-books/preflight", {
      method: "POST",
      body: formData,
    }, {
      timeoutMs: 10 * 60 * 1000,
    });
    const mapDirections = (
      directions: Record<string, {
        image_filename?: string;
        smn?: number | null;
        smx?: number | null;
        legend_values?: number[];
        is_zero_result?: boolean;
        source_cell?: string | null;
        original_text: string;
        canonical_specification: string;
        narrative_specification?: string;
        actual_area: number | string | null;
      }>,
    ) => {
      const finiteNumberOrNull = (value: unknown): number | null =>
        typeof value === "number" && Number.isFinite(value) ? value : null;
      const mapDirection = (
        direction: "X" | "Y" | "Z",
      ): CalculationBookDirectionEvidence => {
        const item = directions[direction];
        return {
          imageFilename: item?.image_filename ?? "",
          smn: finiteNumberOrNull(item?.smn),
          smx: finiteNumberOrNull(item?.smx),
          legendValues: item?.legend_values ?? [],
          isZeroResult: item?.is_zero_result ?? false,
          sourceCell: item?.source_cell ?? "",
          originalText: item?.original_text ?? "",
          canonicalSpecification: item?.canonical_specification ?? "",
          narrativeSpecification: item?.narrative_specification ?? "",
          actualArea: finiteNumberOrNull(item?.actual_area),
        };
      };
      return {
        X: mapDirection("X"),
        Y: mapDirection("Y"),
        Z: mapDirection("Z"),
      };
    };
    return {
      preflightToken: payload.preflight_token,
      reinforcementSource:
        payload.reinforcement_source ?? options.reinforcementSource,
      requiresAiRecommendation:
        payload.requires_ai_recommendation ?? false,
      figureCount: payload.figure_count,
      wallDirectionFigureCount:
        payload.wall_direction_figure_count ?? payload.figure_count,
      zeroFigureCount: payload.zero_figure_count,
      zZeroOrMissingSmxCount:
        payload.z_zero_or_missing_smx_count ?? 0,
      wallCount: payload.wall_count,
      reinforcementSourceRowCount:
        payload.reinforcement_source_row_count ?? payload.wall_count,
      reinforcementNormalizedRowCount:
        payload.reinforcement_normalized_row_count ?? payload.wall_count,
      reinforcementIssueRowCount:
        payload.reinforcement_issue_row_count ?? 0,
      reinforcementUniqueWallCount:
        payload.reinforcement_unique_wall_count ?? payload.wall_count,
      normalizationTriggered: payload.normalization_triggered ?? false,
      normalizationSkillId: payload.normalization_skill_id ?? null,
      requiresAiNormalization: payload.requires_ai_normalization ?? false,
      aiReinforcementExpectedSourceRowCount:
        payload.ai_reinforcement_expected_source_row_count ?? null,
      aiConfirmationMessage: payload.ai_confirmation_message ?? null,
      formatInspection: {
        wallSheet: payload.format_inspection?.wall_sheet ?? null,
        slabSheet: payload.format_inspection?.slab_sheet ?? null,
        reasons: (payload.format_inspection?.reasons ?? []).map((reason) => ({
          scope: reason.scope ?? "",
          code: reason.code ?? "",
          sheet: reason.sheet ?? null,
          message: reason.message ?? "",
        })),
      },
      normalizationIssues: (payload.normalization_issues ?? []).map((issue) => ({
        sourceSheet: issue.source_sheet,
        sourceRow: issue.source_row,
        sourceCells: issue.source_cells,
        originalValues: issue.original_values ?? {
          wall: issue.original_wall_text,
          X: "",
          Y: "",
          Z: "",
        },
        originalWallText: issue.original_wall_text,
        wallId: issue.wall_id,
        error: issue.error,
      })),
      imageWallGroupCount:
        payload.image_wall_group_count ?? payload.wall_count,
      imageUniqueWallCount:
        payload.image_unique_wall_count ?? payload.wall_count,
      matchedUniqueWallCount:
        payload.matched_unique_wall_count ?? payload.wall_count,
      imageOnlyWallIds: payload.image_only_wall_ids ?? [],
      workbookOnlyWallIds: payload.workbook_only_wall_ids ?? [],
      requiresWallCountConfirmation:
        payload.requires_wall_count_confirmation ?? false,
      slabFigureCount: payload.slab_figure_count ?? 0,
      slabZeroFigureCount: payload.slab_zero_figure_count ?? 0,
      slabElevationCount: payload.slab_elevation_count ?? 0,
      slabActualGroupCount:
        payload.slab_actual_group_count ?? payload.slab_elevation_count ?? 0,
      reinforcementWorkbook: payload.reinforcement_workbook,
      requiresOcrReview: payload.requires_ocr_review ?? false,
      ignoredRootImages: payload.ignored_root_images ?? [],
      reviewItems: (payload.review_items ?? []).map((item) => ({
        code: item.code ?? "ocr_review_required",
        scope: item.scope ?? "wall",
        identity: item.identity ?? "",
        direction: item.direction ?? null,
        imageFilename: item.image_filename ?? "",
        reason: item.reason ?? "需要人工复核",
      })),
      requiresManualConfirmation: payload.requires_manual_confirmation,
      confirmations: payload.confirmations.map((confirmation) => ({
        wallId: confirmation.wall_id,
        baseWallId: confirmation.base_wall_id,
        reasons: confirmation.reasons,
        suggestedSourceRow: confirmation.suggested_source_row,
        candidates: confirmation.candidates.map((candidate) => ({
          sourceRow: candidate.source_row,
          sourceSheet: candidate.source_sheet,
          directions: mapDirections(candidate.directions),
        })),
      })),
      walls: payload.walls.map((wall) => ({
        wallId: wall.wall_id,
        baseWallId: wall.base_wall_id,
        groupIndex: wall.group_index,
        suggestedSourceRow:
          typeof wall.suggested_source_row === "number"
          && Number.isFinite(wall.suggested_source_row)
            ? wall.suggested_source_row
            : null,
        directions: mapDirections(wall.directions),
      })),
      slabs: (payload.slabs ?? []).map((item) => ({
        elevation: item.elevation,
        key: item.key,
        position: item.position,
        direction: item.direction,
        imageFilename: item.image_filename,
        smn:
          typeof item.smn === "number" && Number.isFinite(item.smn)
            ? item.smn
            : null,
        smx:
          typeof item.smx === "number" && Number.isFinite(item.smx)
            ? item.smx
            : null,
        legendValues: item.legend_values,
        isZeroResult: item.is_zero_result,
        sourceRow:
          typeof item.source_row === "number" && Number.isFinite(item.source_row)
            ? item.source_row
            : null,
        sourceCell: item.source_cell ?? "",
        originalText: item.original_text,
        canonicalSpecification: item.canonical_specification,
        narrativeSpecification: item.narrative_specification,
        actualArea:
          typeof item.actual_area === "number" && Number.isFinite(item.actual_area)
            ? item.actual_area
            : null,
      })),
      warnings: payload.warnings.map((warning) => ({
        code: warning.code,
        filenames: warning.filenames ?? [],
      })),
    };
  }

  async listTaskGroups(): Promise<TaskGroupList> {
    const payload = await this.fetchJson<{ total: number; items: RawTaskGroupSummary[] }>(
      "/api/task-groups",
    );
    return {
      total: payload.total,
      items: (payload.items ?? []).map((item) => this.normalizeTaskGroupSummary(item)),
    };
  }

  async getTaskGroupDetail(groupId: string): Promise<TaskGroupDetail> {
    return this.normalizeTaskGroupDetail(
      await this.fetchJson<RawTaskGroupDetail>(`/api/task-groups/${groupId}`),
    );
  }

  async getJobWorkloadSubmission(jobId: string): Promise<JobWorkloadSubmission> {
    const response = await this.fetchJson<{
      supported: boolean;
      can_submit: boolean;
      blockers: JobWorkloadSubmission["blockers"];
      group_id: string | null;
      workflow_status: string;
      initial_workload_a1: number | null;
      personnel_fields: JobWorkloadSubmission["personnelFields"];
      group: RawTaskGroupDetail | null;
    }>(`/api/jobs/${encodeURIComponent(jobId)}/workload-submission`);
    return {
      supported: response.supported,
      canSubmit: response.can_submit,
      blockers: response.blockers ?? [],
      groupId: response.group_id,
      workflowStatus: response.workflow_status,
      initialWorkloadA1: response.initial_workload_a1,
      personnelFields: response.personnel_fields ?? [],
      group: response.group ? this.normalizeTaskGroupDetail(response.group) : null,
    };
  }

  async submitJobWorkload(jobId: string, payload: JobWorkloadSubmitPayload): Promise<TaskGroupDetail> {
    return this.normalizeTaskGroupDetail(await this.fetchJson<RawTaskGroupDetail>(
      `/api/jobs/${encodeURIComponent(jobId)}/workload-submission`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          personnel: payload.personnel,
          overwrite_archive_existing: payload.overwriteArchiveExisting,
          cancel_existing_in_progress: payload.cancelExistingInProgress,
        }),
      },
    ));
  }

  async getJobExecutionActions(jobId: string): Promise<JobExecutionActions> {
    return this.normalizeJobExecutionActions(await this.fetchJson<RawJobExecutionActions>(
      `/api/jobs/${encodeURIComponent(jobId)}/execution-actions`,
    ));
  }

  async cancelJob(jobId: string): Promise<JobExecutionActions> {
    return this.normalizeJobExecutionActions(await this.fetchJson<RawJobExecutionActions>(
      `/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" },
    ));
  }

  async retryJob(jobId: string): Promise<JobRetryResult> {
    const response = await this.fetchJson<{ job_id: string; group_id: string | null }>(
      `/api/jobs/${encodeURIComponent(jobId)}/retry`, { method: "POST" },
    );
    return { jobId: response.job_id, groupId: response.group_id };
  }

  private normalizeJobExecutionActions(response: RawJobExecutionActions): JobExecutionActions {
    return {
      canCancel: response.can_cancel,
      canRetry: response.can_retry,
      cancelRequested: response.cancel_requested,
      cancelReason: response.cancel_reason,
      retryReason: response.retry_reason,
    };
  }

  async submitTaskGroup(
    groupId: string,
    payload: TaskGroupSubmitPayload,
  ): Promise<TaskGroupDetail> {
    const response = await this.fetchJson<RawTaskGroupDetail>(`/api/task-groups/${groupId}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          overwrite_archive_existing: payload.overwriteArchiveExisting,
          cancel_existing_in_progress: payload.cancelExistingInProgress,
        }),
      },
    );
    return this.normalizeTaskGroupDetail(response);
  }

  async listJobs(status?: string, offset = 0, limit = 100, sort?: JobListSort): Promise<JobList> {
    const search = new URLSearchParams();
    if (status) {
      search.set("status", status);
    }
    search.set("offset", String(offset));
    search.set("limit", String(limit));
    if (sort) {
      search.set("sort", sort);
    }

    const payload = await this.fetchJson<{
      total: number;
      items: RawJobSummary[];
    }>(`/api/jobs?${search.toString()}`, undefined, { retry: true });

    return {
      total: payload.total,
      items: payload.items.map((job) => this.normalizeSummary(job)),
    };
  }

  async createChangePageExtract(files: File[]): Promise<CreateBatchPayload> {
    const formData = new FormData();
    for (const file of files) {
      formData.append("files[]", file);
    }

    const payload = await this.fetchJson<{
      batch_id: string;
      jobs: RawJobSummary[];
    }>("/api/jobs/change-page-extract", {
      method: "POST",
      body: formData,
    });

    return {
      batchId: payload.batch_id,
      jobs: payload.jobs.map((job) => this.normalizeSummary(job)),
    };
  }

  async getJobsActivity(): Promise<JobsActivity> {
    const payload = await this.fetchJson<{
      total: number;
      active: number;
      last_changed_at: string | null;
    }>("/api/jobs/activity", undefined, { retry: true });

    return {
      total: payload.total,
      active: payload.active,
      lastChangedAt: payload.last_changed_at,
    };
  }

  subscribeJobsActivity = (
    onActivity: (activity: JobsActivity) => void,
    onError?: (event: Event) => void,
  ): (() => void) => {
    if (typeof window === "undefined" || typeof window.EventSource === "undefined") {
      return () => {};
    }

    const source = new window.EventSource(this.buildUrl("/api/jobs/activity/stream"));
    const handleActivity = (event: MessageEvent<string>) => {
      const payload = this.parseJsonOrText(event.data);
      if (!payload || typeof payload !== "object") {
        return;
      }
      const raw = payload as {
        total?: number;
        active?: number;
        last_changed_at?: string | null;
      };

      onActivity({
        total: Number(raw.total ?? 0),
        active: Number(raw.active ?? 0),
        lastChangedAt: typeof raw.last_changed_at === "string" ? raw.last_changed_at : null,
      });
    };
    const handleError = (event: Event) => {
      onError?.(event);
    };

    source.addEventListener("jobs_activity", handleActivity as EventListener);
    source.onerror = handleError;

    return () => {
      source.removeEventListener("jobs_activity", handleActivity as EventListener);
      source.onerror = null;
      source.close();
    };
  };

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
      diagnostics: this.normalizeDiagnostics(payload.diagnostics),
      topWrongTexts: payload.top_wrong_texts ?? [],
      topInternalCodes: payload.top_internal_codes ?? [],
      sharedDir: payload.shared_dir ?? null,
      deliverableOutputs: this.normalizeDeliverableOutputs(payload.deliverable_outputs),
      findingGroups: this.normalizeFindingGroups(payload.finding_groups),
      replaceSummary: this.normalizeReplaceSummary(payload.replace_summary),
      factoryIndexMap: this.normalizeFactoryIndexMap(payload.factory_index_map),
      calculationBookOutput: payload.calculation_book_output
        ? {
            reinforcementSource:
              payload.calculation_book_output.reinforcement_source ?? "provided",
            figureCount: Number(payload.calculation_book_output.figure_count ?? 0),
            templateType: payload.calculation_book_output.template_type ?? "",
            outputFilename: payload.calculation_book_output.output_filename ?? "",
            aiNormalized: Boolean(payload.calculation_book_output.ai_normalized),
            warningCount: Number(payload.calculation_book_output.warning_count ?? 0),
            warnings: (payload.calculation_book_output.warnings ?? []).map((warning) => ({
              code: warning.code ?? "needs_review",
              scope:
                warning.scope === "wall" || warning.scope === "slab"
                  ? warning.scope
                  : "reinforcement",
              identity: warning.identity ?? null,
              direction: warning.direction ?? null,
              sourceSheet: warning.source_sheet ?? null,
              sourceRow: warning.source_row ?? null,
              sourceCells: warning.source_cells ?? {},
              reason: warning.reason ?? "相关配筋字段需要人工补充",
              blankFields: warning.blank_fields ?? [],
            })),
            aiNormalization: payload.calculation_book_output.ai_normalization
              ? {
                  skillId:
                    payload.calculation_book_output.ai_normalization.skill_id ?? "",
                  model: payload.calculation_book_output.ai_normalization.model ?? "",
                  profile: payload.calculation_book_output.ai_normalization.profile ?? "",
                  callCount: Number(
                    payload.calculation_book_output.ai_normalization.call_count ?? 0,
                  ),
                  sourceRowCount: Number(
                    payload.calculation_book_output.ai_normalization.source_row_count ?? 0,
                  ),
                  normalizedWallCount: Number(
                    payload.calculation_book_output.ai_normalization.normalized_wall_count ?? 0,
                  ),
                  normalizedSlabCount: Number(
                    payload.calculation_book_output.ai_normalization.normalized_slab_count ?? 0,
                  ),
                  reviewWarningCount: Number(
                    payload.calculation_book_output.ai_normalization.review_warning_count ?? 0,
                  ),
                  durationMs: Number(
                    payload.calculation_book_output.ai_normalization.duration_ms ?? 0,
                  ),
                  validation:
                    payload.calculation_book_output.ai_normalization.validation ?? "",
                }
              : null,
            aiRebarSuggestion: payload.calculation_book_output.ai_rebar_suggestion
              ? {
                  skillId:
                    payload.calculation_book_output.ai_rebar_suggestion.skill_id ?? "",
                  skillVersion:
                    payload.calculation_book_output.ai_rebar_suggestion.skill_version ?? "",
                  skillSha256:
                    payload.calculation_book_output.ai_rebar_suggestion.skill_sha256 ?? "",
                  model:
                    payload.calculation_book_output.ai_rebar_suggestion.model ?? "",
                  callCount: Number(
                    payload.calculation_book_output.ai_rebar_suggestion.call_count ?? 0,
                  ),
                  suggestedDirectionCount: Number(
                    payload.calculation_book_output.ai_rebar_suggestion
                      .suggested_direction_count ?? 0,
                  ),
                  blankDirectionCount: Number(
                    payload.calculation_book_output.ai_rebar_suggestion
                      .blank_direction_count ?? 0,
                  ),
                  repairRoundCount: Number(
                    payload.calculation_book_output.ai_rebar_suggestion
                      .repair_round_count ?? 0,
                  ),
                  validation:
                    payload.calculation_book_output.ai_rebar_suggestion.validation ?? "",
                }
              : null,
          }
        : undefined,
      changePageResult: this.normalizeChangePageResult(payload.change_page_result),
    };
  }

  private normalizeChangePageResult(
    payload: RawJobDetail["change_page_result"],
  ): ChangePageResult | null {
    if (!payload) {
      return null;
    }

    return {
      archiveName: payload.archive_name ?? "",
      items: (payload.items ?? []).map((item) => ({
        name: item.name ?? "",
        pages: Number(item.pages ?? 0),
        relativePath: item.relative_path ?? "",
      })),
      text: payload.text ?? "",
      pdfCount: Number(payload.pdf_count ?? 0),
      totalPages: Number(payload.total_pages ?? 0),
      ignoredFileCount: Number(payload.ignored_file_count ?? 0),
    };
  }

  async readArtifact(url: string): Promise<Blob> {
    return (await this.fetchArtifact(url)).blob;
  }

  async downloadArtifact(url: string, fallbackFilename = "download"): Promise<void> {
    const { blob, filename } = await this.fetchArtifact(url);
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename ?? this.inferFilenameFromUrl(url) ?? fallbackFilename;
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(objectUrl);
  }

  async getAiState(signal?: AbortSignal): Promise<AiState> {
    const payload = await this.fetchJson<RawAiState>("/api/ai/state", { signal }, {
      retry: true,
    });
    return this.normalizeAiState(payload);
  }

  async listAiConversations(signal?: AbortSignal): Promise<AiConversationSummary[]> {
    const payload = await this.fetchJson<RawAiConversationSummary[]>(
      "/api/ai/conversations",
      { signal },
      { retry: true },
    );
    return (payload ?? []).map((conversation) => this.normalizeAiConversationSummary(conversation));
  }

  async createAiConversation(title = "新会话"): Promise<AiConversationSummary> {
    const payload = await this.fetchJson<RawAiConversationSummary>(
      "/api/ai/conversations",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      },
      { timeoutMs: AI_CONTROL_TIMEOUT_MS },
    );
    return this.normalizeAiConversationSummary(payload);
  }

  async renameAiConversation(
    conversationId: string,
    title: string,
  ): Promise<AiConversationSummary> {
    const payload = await this.fetchJson<RawAiConversationSummary>(
      `/api/ai/conversations/${encodeURIComponent(conversationId)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      },
      { timeoutMs: AI_CONTROL_TIMEOUT_MS },
    );
    return this.normalizeAiConversationSummary(payload);
  }

  async getAiConversation(
    conversationId: string,
    signal?: AbortSignal,
  ): Promise<AiConversationDetail> {
    const payload = await this.fetchJson<RawAiConversationDetail>(
      `/api/ai/conversations/${encodeURIComponent(conversationId)}`,
      { signal },
      { retry: true },
    );
    return {
      ...this.normalizeAiConversationSummary(payload),
      messages: (payload.messages ?? []).map((message) => this.normalizeAiMessage(message)),
    };
  }

  async sendAiMessage(
    conversationId: string,
    payload: {
      content: string;
      agentId?: string | null;
      skillIds?: string[];
      mcpServerIds?: string[];
      attachmentIds?: string[];
    },
    signal?: AbortSignal,
  ): Promise<AiSendMessageResult> {
    const response = await this.fetchJson<RawAiSendMessageResult>(
      `/api/ai/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal,
        body: JSON.stringify({
          content: payload.content,
          agent_id: payload.agentId ?? null,
          skill_ids: payload.skillIds ?? [],
          mcp_server_ids: payload.mcpServerIds ?? [],
          attachment_ids: payload.attachmentIds ?? [],
        }),
      },
      { timeoutMs: CHAT_POST_TIMEOUT_MS },
    );
    return {
      conversationId: response.conversation_id ?? conversationId,
      userMessage: this.normalizeAiMessage(response.user_message ?? {}),
      assistantMessage: this.normalizeAiMessage(response.assistant_message ?? {}),
      memory: {
        usedHistoryMessages: response.memory?.used_history_messages ?? 0,
      },
    };
  }

  async clearAiConversation(conversationId: string): Promise<void> {
    await this.fetchJson<{ ok: boolean }>(
      `/api/ai/conversations/${encodeURIComponent(conversationId)}/clear`,
      {
        method: "POST",
      },
      { timeoutMs: AI_CONTROL_TIMEOUT_MS },
    );
  }

  async deleteAiConversation(conversationId: string): Promise<void> {
    await this.fetchJson<{ ok: boolean }>(
      `/api/ai/conversations/${encodeURIComponent(conversationId)}`,
      {
        method: "DELETE",
      },
      { timeoutMs: AI_CONTROL_TIMEOUT_MS },
    );
  }

  async uploadAiAttachment(conversationId: string, file: File): Promise<AiAttachment> {
    const formData = new FormData();
    formData.append("file", file);
    const payload = await this.fetchJson<RawAiAttachment>(
      `/api/ai/conversations/${encodeURIComponent(conversationId)}/attachments`,
      {
        method: "POST",
        body: formData,
      },
      { timeoutMs: CHAT_POST_TIMEOUT_MS },
    );
    return this.normalizeAiAttachment(payload);
  }

  async listAiAttachments(
    conversationId: string,
    signal?: AbortSignal,
  ): Promise<AiAttachment[]> {
    const payload = await this.fetchJson<RawAiAttachment[]>(
      `/api/ai/conversations/${encodeURIComponent(conversationId)}/attachments`,
      { signal },
      { retry: true },
    );
    return (payload ?? []).map((attachment) => this.normalizeAiAttachment(attachment));
  }

  async deleteAiAttachment(conversationId: string, attachmentId: string): Promise<void> {
    await this.fetchJson<{ ok: boolean }>(
      `/api/ai/conversations/${encodeURIComponent(conversationId)}/attachments/${encodeURIComponent(attachmentId)}`,
      { method: "DELETE" },
      { timeoutMs: AI_CONTROL_TIMEOUT_MS },
    );
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
      ownerSnapshot: this.normalizeTaskOwnerSnapshot(payload.owner_snapshot),
      creatorName: payload.creator_name ?? null,
      creatorAccount: payload.creator_account ?? null,
      creatorOffice: payload.creator_office ?? null,
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
        calculationDocxAvailable: payload.artifacts.calculation_docx_available ?? false,
        calculationLogAvailable: payload.artifacts.calculation_log_available ?? false,
        packageDownloadUrl: this.resolveUrl(payload.artifacts.package_download_url),
        iedDownloadUrl: this.resolveUrl(payload.artifacts.ied_download_url),
        previewDownloadUrl: this.resolveUrl(payload.artifacts.preview_download_url),
        reportDownloadUrl: this.resolveUrl(payload.artifacts.report_download_url),
        replacedDwgDownloadUrl: this.resolveUrl(payload.artifacts.replaced_dwg_download_url),
        calculationDocxDownloadUrl: this.resolveUrl(
          payload.artifacts.calculation_docx_download_url,
        ),
        calculationLogDownloadUrl: this.resolveUrl(
          payload.artifacts.calculation_log_download_url,
        ),
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
      workload: this.normalizeWorkloadSummary(payload.workload),
      effectiveWorkload: payload.effective_workload ?? 0,
      children: payload.children?.map((child) => this.normalizeSummary(child)),
    };
  }

  private normalizeAiState(payload: RawAiState): AiState {
    return {
      enabled: Boolean(payload.enabled),
      profile: payload.profile ?? "",
      model: payload.model ?? "",
      ownerKey: payload.owner_key ?? "",
      defaultAgent: payload.default_agent ?? "",
      attachments: {
        enabled: Boolean(payload.attachments?.enabled),
        allowedExtensions: payload.attachments?.allowed_extensions ?? [],
        maxFilesPerMessage: payload.attachments?.max_files_per_message ?? 0,
        maxImageSizeMb: payload.attachments?.max_image_size_mb ?? 0,
        maxFileSizeMb: payload.attachments?.max_file_size_mb ?? 0,
        maxTotalSizeMbPerMessage:
          payload.attachments?.max_total_size_mb_per_message ?? 0,
      },
      agents: (payload.agents ?? []).map((agent) => this.normalizeAiAgent(agent)),
      skills: (payload.skills ?? []).map((skill) => this.normalizeAiSkill(skill)),
      mcpServers: (payload.mcp_servers ?? []).map((server) => this.normalizeAiMcpServer(server)),
    };
  }

  private normalizeAiAgent(payload: RawAiAgent): AiAgent {
    return {
      agentId: payload.agent_id ?? "",
      name: payload.name ?? "",
      description: payload.description ?? "",
    };
  }

  private normalizeAiSkill(payload: RawAiSkill): AiSkill {
    return {
      skillId: payload.skill_id ?? "",
      name: payload.name ?? "",
      description: payload.description ?? "",
      enabled: Boolean(payload.enabled),
      readOnly: payload.read_only ?? true,
    };
  }

  private normalizeAiMcpServer(payload: RawAiMcpServer): AiMcpServer {
    return {
      serverId: payload.server_id ?? "",
      name: payload.name ?? "",
      description: payload.description ?? "",
      enabled: Boolean(payload.enabled),
      readOnly: payload.read_only ?? true,
      transport: payload.transport ?? undefined,
    };
  }

  private normalizeAiConversationSummary(
    payload: RawAiConversationSummary,
  ): AiConversationSummary {
    return {
      conversationId: payload.conversation_id ?? "",
      title: payload.title ?? "新会话",
      createdAt: payload.created_at ?? "",
      updatedAt: payload.updated_at ?? "",
      messageCount: payload.message_count ?? 0,
    };
  }

  private normalizeAiMessage(payload: RawAiMessage): AiMessage {
    return {
      messageId: payload.message_id ?? "",
      role: payload.role ?? "assistant",
      content: payload.content ?? "",
      createdAt: payload.created_at ?? "",
      modelProfile: payload.model_profile ?? null,
      metadata: payload.metadata ?? {},
    };
  }

  private normalizeAiAttachment(payload: RawAiAttachment): AiAttachment {
    return {
      attachmentId: payload.attachment_id ?? "",
      conversationId: payload.conversation_id ?? "",
      messageId: payload.message_id ?? null,
      originalName: payload.original_name ?? "附件",
      mediaType: payload.media_type ?? "application/octet-stream",
      kind: payload.kind ?? "unknown",
      sizeBytes: payload.size_bytes ?? 0,
      sha256: payload.sha256 ?? "",
      status: payload.status ?? "failed",
      metadata: payload.metadata ?? {},
      errorCode: payload.error_code ?? null,
      createdAt: payload.created_at ?? "",
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
        if (
          init?.signal?.aborted ||
          !shouldRetry ||
          attempt >= maxAttempts - 1 ||
          !this.isRetryableError(error)
        ) {
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
    const externalSignal = init?.signal;
    const handleExternalAbort = () => abortController?.abort();
    if (abortController && externalSignal) {
      if (externalSignal.aborted) {
        abortController.abort();
      } else {
        externalSignal.addEventListener("abort", handleExternalAbort, { once: true });
      }
    }
    const timeoutId =
      abortController && timeoutMs
        ? window.setTimeout(() => abortController.abort(), timeoutMs)
        : null;
    const requestSignal = abortController?.signal ?? externalSignal;
    const initWithSignal = requestSignal ? { ...init, signal: requestSignal } : init;
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
      externalSignal?.removeEventListener("abort", handleExternalAbort);
    }
  }

  private async fetchArtifact(path: string): Promise<{ blob: Blob; filename: string | null }> {
    const response = await fetch(this.buildUrl(path), this.withAuthorization());
    if (!response.ok) {
      if (response.status === 401) {
        this.onUnauthorized?.();
      }
      const text = await response.text();
      const payload = text ? this.parseJsonOrText(text) : null;
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
    return {
      blob: await response.blob(),
      filename: this.parseContentDispositionFilename(
        response.headers.get("Content-Disposition"),
      ),
    };
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
    return { ...init, headers };
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

  private parseContentDispositionFilename(value: string | null) {
    if (!value) {
      return null;
    }
    const encodedMatch = value.match(/filename\*=UTF-8''([^;]+)/i);
    if (encodedMatch?.[1]) {
      try {
        return decodeURIComponent(encodedMatch[1]);
      } catch {
        return encodedMatch[1];
      }
    }
    const quotedMatch = value.match(/filename="([^"]+)"/i);
    if (quotedMatch?.[1]) {
      return quotedMatch[1];
    }
    return value.match(/filename=([^;]+)/i)?.[1]?.trim() || null;
  }

  private inferFilenameFromUrl(url: string) {
    const normalized = url.split("?")[0]?.split("#")[0] ?? "";
    return normalized.split("/").filter(Boolean).pop() || null;
  }

  private isRetryableError(error: unknown) {
    if (error && typeof error === "object" && "name" in error && error.name === "AbortError") {
      return false;
    }
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

  private normalizeDiagnostics(payload: RawJobDetail["diagnostics"]) {
    if (!Array.isArray(payload)) {
      return [];
    }
    return payload.map((item) => ({
      kind: item.kind ?? "other",
      severity: item.severity ?? "warning",
      title: item.title ?? "未命名问题",
      summary: item.summary ?? "",
      suggestion: item.suggestion ?? "",
      details: Array.isArray(item.details)
        ? item.details.map((detail) => ({
            label: detail.label ?? "具体信息",
            items: detail.items ?? [],
          }))
        : [],
      rawItems: item.raw_items ?? [],
    }));
  }

  private normalizeFindingGroups(payload: RawJobDetail["finding_groups"]): FindingGroup[] | undefined {
    if (!payload) {
      return undefined;
    }

    return payload.map((group) => ({
      matchedText: group.matched_text ?? "",
      count: group.count ?? 0,
      internalCodes: group.internal_codes ?? [],
      category: group.category ?? undefined,
      contextKind: group.context_kind ?? undefined,
      issueType: group.issue_type ?? undefined,
      summary: group.summary ?? undefined,
      details: group.details ?? undefined,
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

  private normalizeTaskGroupSummary(payload: RawTaskGroupSummary): TaskGroupSummary {
    return {
      groupId: payload.group_id,
      displayName: payload.display_name ?? null,
      albumInternalCode: payload.album_internal_code ?? null,
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
      submitBlockers: payload.submit_blockers ?? [],
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

  private normalizePersonnelSnapshot(payload: RawPersonnelSnapshot | null | undefined): PersonnelSnapshot {
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
      raw: sanitizeInvalidAccountRaw(payload?.raw),
      errors: payload?.errors ?? [],
    };
  }

  private normalizeAdminConfig(payload: RawAdminConfig | null | undefined): AdminConfig {
    return { archiveRootPath: payload?.archive_root_path ?? "" };
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
    return { scope: payload?.scope ?? "admin_only", reason: payload?.reason ?? null };
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

  private serializeAccountCreatePayload(payload: AccountCreatePayload) {
    return {
      office_code: payload.officeCode,
      office_name: payload.officeName,
      account_id: payload.accountId,
      display_name: payload.displayName,
      role: payload.role,
      ...(payload.password ? { password: payload.password } : {}),
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
      ...(payload.replaceWithAccountId ? { replace_with_account_id: payload.replaceWithAccountId } : {}),
      ...(payload.createAccountPayload
        ? { create_account_payload: this.serializeAccountCreatePayload(payload.createAccountPayload) }
        : {}),
    };
  }

  private buildWorkloadQuery(filters: WorkloadQueryParams): URLSearchParams {
    const search = new URLSearchParams();
    if (filters.startDate) search.set("start_date", filters.startDate);
    if (filters.endDate) search.set("end_date", filters.endDate);
    if (filters.status) search.set("status", filters.status);
    if (typeof filters.validOnly === "boolean") {
      search.set("valid_only", filters.validOnly ? "true" : "false");
    }
    return search;
  }

  private async loadWorkloadScope(
    path: string,
    filters: WorkloadQueryParams,
  ): Promise<WorkloadScopeResponse> {
    const search = this.buildWorkloadQuery(filters).toString();
    const payload = await this.fetchJson<RawWorkloadScopeResponse>(
      `${path}${search ? `?${search}` : ""}`,
    );
    return {
      scope: payload.scope ?? "me",
      filters: {
        startDate: payload.filters?.start_date ?? null,
        endDate: payload.filters?.end_date ?? null,
        status: payload.filters?.status ?? null,
        validOnly: Boolean(payload.filters?.valid_only),
      },
      officeName: payload.office_name ?? null,
      totalWorkloadA1: payload.total_workload_a1 ?? 0,
      totalsByAccount: Object.fromEntries(
        Object.entries(payload.totals_by_account ?? {}).map(([accountId, value]) => [accountId, value ?? 0]),
      ),
      entries: (payload.entries ?? []).map((entry) => ({
        roleKey: entry.role_key ?? "",
        accountId: entry.account_id ?? null,
        displayName: entry.display_name ?? null,
        workloadA1: entry.workload_a1 ?? 0,
        settledAt: entry.settled_at ?? null,
        groupId: entry.group_id ?? "",
        groupDisplayName: entry.group_display_name ?? null,
        albumInternalCode: entry.album_internal_code ?? null,
        settlementStatus: entry.settlement_status ?? "pending",
      })),
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
      fontCompatibilityRequired: Boolean(file.font_compatibility_required),
      emptyStyleEntityReplacedCount: file.empty_style_entity_replaced_count ?? 0,
      emptyStyleStylePatchedCount: file.empty_style_style_patched_count ?? 0,
      emptyStyleSharedSkippedCount: file.empty_style_shared_skipped_count ?? 0,
      emptyStyleSharedStyles: file.empty_style_shared_styles ?? [],
      emptyStyleTargetRegionsCount: file.empty_style_target_regions_count ?? 0,
      emptyStyleGlobalReplacedCount: file.empty_style_global_replaced_count ?? 0,
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
