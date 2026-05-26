import { normalizeFormSchema } from "../../features/schema/schema";
import type {
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
  JobSummary,
  SubmissionParams,
} from "./types";

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
  audit_replace?: {
    project_options?: string[];
  };
};

export class HttpAdapter implements ApiAdapter {
  private readonly normalizedBaseUrl: string;

  constructor(private readonly baseUrl = "") {
    this.normalizedBaseUrl = baseUrl.replace(/\/+$/, "");
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
    }>("/api/system/health");

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
    const payload = await this.fetchJson<RawFormSchema>("/api/meta/form-schema");
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
    }>(`/api/jobs?${search.toString()}`);

    return {
      total: payload.total,
      items: payload.items.map((job) => this.normalizeSummary(job)),
    };
  }

  async getJobDetail(jobId: string): Promise<JobDetail> {
    const payload = await this.fetchJson<RawJobDetail>(`/api/jobs/${jobId}`);
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

  private async fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(this.buildUrl(path), init);
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
