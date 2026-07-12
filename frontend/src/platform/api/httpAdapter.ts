import { normalizeFormSchema } from "../../features/schema/schema";
import type {
  AiAgent,
  AiConversationDetail,
  AiConversationSummary,
  AiMcpServer,
  AiMessage,
  AiSendMessageResult,
  AiSkill,
  AiState,
  ApiAdapter,
  ApiError,
  CreateAuditReplaceParams,
  CreateBatchPayload,
  DeliverableOutputs,
  FontReplacementMap,
  FontReplacementOption,
  FontPreflightSummary,
  FontPreflightResult,
  FindingGroup,
  FormSchema,
  HealthStatus,
  JobDetail,
  JobList,
  JobListSort,
  JobSummary,
  JobsActivity,
  PingStatus,
  SubmissionParams,
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
  workload?: {
    initial_workload_a1?: number | null;
    final_workload_a1?: number | null;
    one_review_factor?: number | null;
    two_review_factor?: number | null;
    three_review_factor?: number | null;
    settlement_status?: string | null;
    settled_at?: string | null;
  } | null;
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
    factory_index_maps?: {
      source_variant_options?: Record<string, string[]>;
      target_variant_options?: Record<string, string[]>;
    };
  };
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

  constructor(private readonly baseUrl = "") {
    this.normalizedBaseUrl = baseUrl.replace(/\/+$/, "");
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
      source.close();
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
    };
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
    },
  ): Promise<AiSendMessageResult> {
    const response = await this.fetchJson<RawAiSendMessageResult>(
      `/api/ai/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: payload.content,
          agent_id: payload.agentId ?? null,
          skill_ids: payload.skillIds ?? [],
          mcp_server_ids: payload.mcpServerIds ?? [],
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

  private normalizeWorkloadSummary(payload: RawJobSummary["workload"]): JobSummary["workload"] {
    if (!payload) {
      return null;
    }

    return {
      initialWorkloadA1: payload.initial_workload_a1 ?? 0,
      finalWorkloadA1: payload.final_workload_a1 ?? 0,
      oneReviewFactor: payload.one_review_factor ?? 1,
      twoReviewFactor: payload.two_review_factor ?? 1,
      threeReviewFactor: payload.three_review_factor ?? 1,
      settlementStatus: payload.settlement_status ?? "pending",
      settledAt: payload.settled_at ?? null,
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
    const requestInit = requestSignal ? { ...init, signal: requestSignal } : init;

    try {
      const response = await fetch(this.buildUrl(path), requestInit);
      const text = await response.text();
      const payload = text ? this.parseJsonOrText(text) : null;

      if (!response.ok) {
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
