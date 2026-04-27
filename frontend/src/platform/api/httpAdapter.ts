import { normalizeFormSchema } from "../../features/schema/schema";
import type {
  ApiAdapter,
  ApiError,
  CreateAuditReplaceParams,
  CreateBatchPayload,
  DeliverableOutputs,
  FontSyncApplyResult,
  FontSyncDependency,
  FontSyncEnvironment,
  FontSyncExportResult,
  FontSyncInstallation,
  FontSyncPreviewResult,
  FontSyncSourceScanResult,
  FontSyncStyle,
  FontSyncTargetScanResult,
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
    target_project_no?: string | null;
    top_replaced_texts?: string[] | null;
    top_internal_codes?: string[] | null;
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

type RawFontSyncInstallation = {
  label?: string | null;
  install_dir?: string | null;
  acad_exe?: string | null;
  accoreconsole_exe?: string | null;
  fonts_dir?: string | null;
};

type RawFontSyncEnvironment = {
  autocad_ready?: boolean | null;
  supported?: boolean | null;
  active_profile?: string | null;
  support_path?: string | null;
  font_file_map?: string | null;
  alt_font_file?: string | null;
  windows_fonts_dir?: string | null;
  font_search_roots?: string[] | null;
  installations?: RawFontSyncInstallation[] | null;
  selected_installation?: RawFontSyncInstallation | null;
  errors?: string[] | null;
};

type RawFontSyncStyle = {
  style_name?: string | null;
  font_name?: string | null;
  bigfont_name?: string | null;
  kind?: string | null;
};

type RawFontSyncDependency = {
  dependency_id?: string | null;
  style_name?: string | null;
  role?: string | null;
  font_name?: string | null;
  kind?: string | null;
  used_in_block?: boolean | null;
  absolute_path_reference?: boolean | null;
  resolved?: boolean | null;
  resolved_path?: string | null;
  copy_status?: string | null;
  bundle_font_name?: string | null;
  bundle_font_path?: string | null;
};

type RawFontSyncSourceScanResult = {
  source_id?: string | null;
  source_path?: string | null;
  bundle_mode?: "guaranteed" | "best_effort" | null;
  drawing?: Record<string, unknown> | null;
  environment?: RawFontSyncEnvironment | null;
  styles?: RawFontSyncStyle[] | null;
  font_dependencies?: RawFontSyncDependency[] | null;
};

type RawFontSyncExportResult = RawFontSyncSourceScanResult & {
  bundle_id?: string | null;
  bundle_path?: string | null;
  profile_backup_path?: string | null;
  checksums_path?: string | null;
  bundle_download_url?: string | null;
};

type RawFontSyncTargetScanResult = {
  environment?: RawFontSyncEnvironment | null;
  supported?: boolean | null;
  autocad_ready?: boolean | null;
};

type RawFontSyncPreviewResult = {
  import_id?: string | null;
  bundle_id?: string | null;
  bundle_filename?: string | null;
  bundle_mode?: "guaranteed" | "best_effort" | null;
  current_environment?: RawFontSyncEnvironment | null;
  planned_changes?: {
    managed_root?: string | null;
    managed_fonts_dir?: string | null;
    support_path?: string | null;
    font_file_map?: string | null;
    alt_font_file?: string | null;
  } | null;
  diff?: {
    support_path_changed?: boolean | null;
    font_file_map_changed?: boolean | null;
    alt_font_file_changed?: boolean | null;
  } | null;
  manifest?: Record<string, unknown> | null;
};

type RawFontSyncApplyResult = {
  import_id?: string | null;
  bundle_id?: string | null;
  bundle_mode?: "guaranteed" | "best_effort" | null;
  status?: "matched" | "partial" | "failed" | null;
  profile_backup_path?: string | null;
  managed_root?: string | null;
  managed_fonts_dir?: string | null;
  font_file_map?: string | null;
  environment?: RawFontSyncEnvironment | null;
};

export class HttpAdapter implements ApiAdapter {
  private readonly normalizedBaseUrl: string;

  constructor(private readonly baseUrl = "") {
    this.normalizedBaseUrl = baseUrl.replace(/\/+$/, "");
    this.scanFontSyncSource = this.scanFontSyncSource.bind(this);
    this.exportFontSyncBundle = this.exportFontSyncBundle.bind(this);
    this.scanFontSyncTarget = this.scanFontSyncTarget.bind(this);
    this.previewFontSyncBundle = this.previewFontSyncBundle.bind(this);
    this.applyFontSyncBundle = this.applyFontSyncBundle.bind(this);
  }

  async getHealth(): Promise<HealthStatus> {
    const payload = await this.fetchJson<{
      status: string;
      ready: boolean;
      storage_writable: boolean;
      worker_alive: boolean;
      queue_depth: number;
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

  async createAuditCheck(
    projectNo: string,
    files: File[],
    batchId?: string,
  ): Promise<CreateBatchPayload> {
    const formData = new FormData();
    formData.append("mode", "check");
    const params: Record<string, string> = { project_no: projectNo };
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
    targetProjectNo,
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
        target_project_no: targetProjectNo,
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

  async listJobs(status?: string): Promise<JobList> {
    const search = new URLSearchParams();
    if (status) {
      search.set("status", status);
    }
    search.set("limit", "100");

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
    };
  }

  async scanFontSyncSource(file: File): Promise<FontSyncSourceScanResult> {
    const formData = new FormData();
    formData.append("file", file);
    const payload = await this.fetchJson<RawFontSyncSourceScanResult>("/api/font-sync/source-scan", {
      method: "POST",
      body: formData,
    });
    return this.normalizeFontSyncSourceScan(payload);
  }

  async exportFontSyncBundle(file: File): Promise<FontSyncExportResult> {
    const formData = new FormData();
    formData.append("file", file);
    const payload = await this.fetchJson<RawFontSyncExportResult>("/api/font-sync/export", {
      method: "POST",
      body: formData,
    });
    return this.normalizeFontSyncExportResult(payload);
  }

  async scanFontSyncTarget(): Promise<FontSyncTargetScanResult> {
    const payload = await this.fetchJson<RawFontSyncTargetScanResult>("/api/font-sync/target-scan", {
      method: "POST",
    });
    return {
      environment: this.normalizeFontSyncEnvironment(payload.environment),
      supported: Boolean(payload.supported),
      autocadReady: Boolean(payload.autocad_ready),
    };
  }

  async previewFontSyncBundle(bundle: File): Promise<FontSyncPreviewResult> {
    const formData = new FormData();
    formData.append("bundle", bundle);
    const payload = await this.fetchJson<RawFontSyncPreviewResult>("/api/font-sync/import-preview", {
      method: "POST",
      body: formData,
    });
    return this.normalizeFontSyncPreviewResult(payload);
  }

  async applyFontSyncBundle(importId: string): Promise<FontSyncApplyResult> {
    const search = new URLSearchParams({ import_id: importId });
    const payload = await this.fetchJson<RawFontSyncApplyResult>(
      `/api/font-sync/apply?${search.toString()}`,
      { method: "POST" },
    );
    return this.normalizeFontSyncApplyResult(payload);
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

  private normalizeFontSyncInstallation(
    payload: RawFontSyncInstallation | null | undefined,
  ): FontSyncInstallation {
    return {
      label: payload?.label ?? "",
      installDir: payload?.install_dir ?? "",
      acadExe: payload?.acad_exe ?? null,
      accoreconsoleExe: payload?.accoreconsole_exe ?? null,
      fontsDir: payload?.fonts_dir ?? null,
    };
  }

  private normalizeFontSyncEnvironment(
    payload: RawFontSyncEnvironment | null | undefined,
  ): FontSyncEnvironment {
    return {
      autocadReady: Boolean(payload?.autocad_ready),
      supported: Boolean(payload?.supported),
      activeProfile: payload?.active_profile ?? "",
      supportPath: payload?.support_path ?? "",
      fontFileMap: payload?.font_file_map ?? null,
      altFontFile: payload?.alt_font_file ?? null,
      windowsFontsDir: payload?.windows_fonts_dir ?? null,
      fontSearchRoots: payload?.font_search_roots ?? [],
      installations: (payload?.installations ?? []).map((item) =>
        this.normalizeFontSyncInstallation(item),
      ),
      selectedInstallation: payload?.selected_installation
        ? this.normalizeFontSyncInstallation(payload.selected_installation)
        : null,
      errors: payload?.errors ?? [],
    };
  }

  private normalizeFontSyncStyle(payload: RawFontSyncStyle): FontSyncStyle {
    return {
      styleName: payload.style_name ?? "",
      fontName: payload.font_name ?? "",
      bigfontName: payload.bigfont_name ?? "",
      kind: payload.kind ?? "unknown",
    };
  }

  private normalizeFontSyncDependency(payload: RawFontSyncDependency): FontSyncDependency {
    return {
      dependencyId: payload.dependency_id ?? "",
      styleName: payload.style_name ?? "",
      role: payload.role ?? "",
      fontName: payload.font_name ?? "",
      kind: payload.kind ?? "unknown",
      usedInBlock: Boolean(payload.used_in_block),
      absolutePathReference: Boolean(payload.absolute_path_reference),
      resolved: Boolean(payload.resolved),
      resolvedPath: payload.resolved_path ?? null,
      copyStatus: payload.copy_status ?? "unknown",
      bundleFontName: payload.bundle_font_name ?? "",
      bundleFontPath: payload.bundle_font_path ?? null,
    };
  }

  private normalizeFontSyncSourceScan(
    payload: RawFontSyncSourceScanResult,
  ): FontSyncSourceScanResult {
    return {
      sourceId: payload.source_id ?? "",
      sourcePath: payload.source_path ?? "",
      bundleMode: payload.bundle_mode ?? "best_effort",
      drawing: payload.drawing ?? {},
      environment: this.normalizeFontSyncEnvironment(payload.environment),
      styles: (payload.styles ?? []).map((item) => this.normalizeFontSyncStyle(item)),
      fontDependencies: (payload.font_dependencies ?? []).map((item) =>
        this.normalizeFontSyncDependency(item),
      ),
    };
  }

  private normalizeFontSyncExportResult(
    payload: RawFontSyncExportResult,
  ): FontSyncExportResult {
    return {
      ...this.normalizeFontSyncSourceScan(payload),
      bundleId: payload.bundle_id ?? "",
      bundlePath: payload.bundle_path ?? "",
      profileBackupPath: payload.profile_backup_path ?? "",
      checksumsPath: payload.checksums_path ?? "",
      bundleDownloadUrl: this.resolveUrl(payload.bundle_download_url) ?? null,
    };
  }

  private normalizeFontSyncPreviewResult(
    payload: RawFontSyncPreviewResult,
  ): FontSyncPreviewResult {
    return {
      importId: payload.import_id ?? "",
      bundleId: payload.bundle_id ?? "",
      bundleFilename: payload.bundle_filename ?? "",
      bundleMode: payload.bundle_mode ?? "best_effort",
      currentEnvironment: this.normalizeFontSyncEnvironment(payload.current_environment),
      plannedChanges: {
        managedRoot: payload.planned_changes?.managed_root ?? "",
        managedFontsDir: payload.planned_changes?.managed_fonts_dir ?? "",
        supportPath: payload.planned_changes?.support_path ?? "",
        fontFileMap: payload.planned_changes?.font_file_map ?? "",
        altFontFile: payload.planned_changes?.alt_font_file ?? null,
      },
      diff: {
        supportPathChanged: Boolean(payload.diff?.support_path_changed),
        fontFileMapChanged: Boolean(payload.diff?.font_file_map_changed),
        altFontFileChanged: Boolean(payload.diff?.alt_font_file_changed),
      },
      manifest: payload.manifest ?? {},
    };
  }

  private normalizeFontSyncApplyResult(payload: RawFontSyncApplyResult): FontSyncApplyResult {
    return {
      importId: payload.import_id ?? "",
      bundleId: payload.bundle_id ?? "",
      bundleMode: payload.bundle_mode ?? "best_effort",
      status: payload.status ?? "failed",
      profileBackupPath: payload.profile_backup_path ?? "",
      managedRoot: payload.managed_root ?? "",
      managedFontsDir: payload.managed_fonts_dir ?? "",
      fontFileMap: payload.font_file_map ?? "",
      environment: this.normalizeFontSyncEnvironment(payload.environment),
    };
  }

  private async fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(this.buildUrl(path), init);
    const text = await response.text();
    const payload = text ? (JSON.parse(text) as unknown) : null;

    if (!response.ok) {
      const error: ApiError = {
        status: response.status,
        detail:
          payload && typeof payload === "object" && "detail" in payload
            ? (payload as { detail: ApiError["detail"] }).detail
            : null,
      };
      throw error;
    }

    return payload as T;
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
      targetProjectNo: payload.target_project_no ?? "",
      topReplacedTexts: payload.top_replaced_texts ?? [],
      topInternalCodes: payload.top_internal_codes ?? [],
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
