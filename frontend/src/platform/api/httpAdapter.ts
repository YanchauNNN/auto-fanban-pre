import { normalizeFormSchema } from "../../features/schema/schema";
import type {
  ApiAdapter,
  ApiError,
  CreateBatchPayload,
  FormSchema,
  HealthStatus,
  JobDetail,
  JobList,
  JobSummary,
} from "./types";

type RawArtifacts = {
  package_available: boolean;
  ied_available: boolean;
  report_available: boolean;
  replaced_dwg_available: boolean;
  package_download_url?: string | null;
  ied_download_url?: string | null;
  report_download_url?: string | null;
  replaced_dwg_download_url?: string | null;
};

type RawJobSummary = {
  job_id: string;
  batch_id: string | null;
  source_filename: string;
  task_kind: "deliverable" | "audit_check" | "audit_replace";
  job_mode: string | null;
  project_no: string | null;
  status: string;
  stage: string | null;
  percent: number | null;
  message: string | null;
  created_at: string;
  finished_at: string | null;
  findings_count?: number | null;
  affected_drawings_count?: number | null;
  artifacts: RawArtifacts;
  retry_available: boolean;
};

type RawJobDetail = RawJobSummary & {
  started_at: string | null;
  current_file: string | null;
  flags: string[];
  errors: string[];
  top_wrong_texts?: string[] | null;
  top_internal_codes?: string[] | null;
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

  async createBatch(
    params: Record<string, string>,
    files: File[],
  ): Promise<CreateBatchPayload> {
    const formData = new FormData();
    formData.append("params_json", JSON.stringify(params));
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
      startedAt: payload.started_at,
      currentFile: payload.current_file,
      flags: payload.flags,
      errors: payload.errors,
      topWrongTexts: payload.top_wrong_texts ?? [],
      topInternalCodes: payload.top_internal_codes ?? [],
    };
  }

  private normalizeSummary(payload: RawJobSummary): JobSummary {
    return {
      jobId: payload.job_id,
      batchId: payload.batch_id,
      sourceFilename: payload.source_filename,
      taskKind: payload.task_kind,
      jobMode: payload.job_mode,
      projectNo: payload.project_no,
      status: payload.status,
      stage: payload.stage,
      percent: payload.percent ?? 0,
      message: payload.message ?? "",
      createdAt: payload.created_at,
      finishedAt: payload.finished_at,
      findingsCount: payload.findings_count ?? 0,
      affectedDrawingsCount: payload.affected_drawings_count ?? 0,
      artifacts: {
        packageAvailable: payload.artifacts.package_available,
        iedAvailable: payload.artifacts.ied_available,
        reportAvailable: payload.artifacts.report_available,
        replacedDwgAvailable: payload.artifacts.replaced_dwg_available,
        packageDownloadUrl: this.resolveUrl(payload.artifacts.package_download_url),
        iedDownloadUrl: this.resolveUrl(payload.artifacts.ied_download_url),
        reportDownloadUrl: this.resolveUrl(payload.artifacts.report_download_url),
        replacedDwgDownloadUrl: this.resolveUrl(payload.artifacts.replaced_dwg_download_url),
      },
      retryAvailable: payload.retry_available,
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
}
