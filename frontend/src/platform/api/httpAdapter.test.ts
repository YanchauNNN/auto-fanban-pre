import { afterEach, describe, expect, it, vi } from "vitest";

import { HttpAdapter } from "./httpAdapter";

describe("HttpAdapter", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("uses a normalized API base URL and resolves relative artifact links", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          job_id: "job-1",
          batch_id: "batch-1",
          source_filename: "A01.dwg",
          task_kind: "deliverable",
          job_mode: "deliverable",
          project_no: "2016",
          status: "succeeded",
          stage: "package",
          percent: 100,
          message: "done",
          created_at: "2026-03-09T00:00:00+08:00",
          finished_at: "2026-03-09T00:01:00+08:00",
          started_at: "2026-03-09T00:00:10+08:00",
          current_file: "A01.dwg",
          flags: [],
          errors: [],
          findings_count: 0,
          affected_drawings_count: 0,
          top_wrong_texts: [],
          top_internal_codes: [],
          retry_available: false,
          artifacts: {
            package_available: true,
            ied_available: true,
            report_available: false,
            replaced_dwg_available: false,
            package_download_url: "/api/jobs/job-1/download/package",
            ied_download_url: "/api/jobs/job-1/download/ied",
            report_download_url: null,
            replaced_dwg_download_url: null,
          },
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const detail = await adapter.getJobDetail("job-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/jobs/job-1",
      undefined,
    );
    expect(detail.artifacts.packageDownloadUrl).toBe(
      "http://127.0.0.1:8000/api/jobs/job-1/download/package",
    );
    expect(detail.artifacts.iedDownloadUrl).toBe(
      "http://127.0.0.1:8000/api/jobs/job-1/download/ied",
    );
  });

  it("creates audit check jobs with mode=check and normalizes audit summary fields", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            batch_id: "batch-audit-1",
            jobs: [
              {
                job_id: "audit-job-1",
                batch_id: "batch-audit-1",
                source_filename: "20261NH-JGS51-B合并版.dwg",
                task_kind: "audit_check",
                job_mode: "check",
                project_no: "2026",
                status: "queued",
                stage: "INIT",
                percent: 0,
                message: "",
                created_at: "2026-03-13T09:00:00+08:00",
                finished_at: null,
                findings_count: 0,
                affected_drawings_count: 0,
                retry_available: false,
                artifacts: {
                  package_available: false,
                  ied_available: false,
                  report_available: false,
                  replaced_dwg_available: false,
                },
              },
            ],
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            total: 1,
            items: [
              {
                job_id: "audit-job-1",
                batch_id: "batch-audit-1",
                source_filename: "20261NH-JGS51-B合并版.dwg",
                task_kind: "audit_check",
                job_mode: "check",
                project_no: "2026",
                status: "succeeded",
                stage: "EXPORT_REPORT",
                percent: 100,
                message: "done",
                created_at: "2026-03-13T09:00:00+08:00",
                finished_at: "2026-03-13T09:01:00+08:00",
                findings_count: 12,
                affected_drawings_count: 4,
                retry_available: false,
                artifacts: {
                  package_available: false,
                  ied_available: false,
                  report_available: true,
                  replaced_dwg_available: false,
                },
              },
            ],
          }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const file = new File(["dwg"], "20261NH-JGS51-B合并版.dwg", {
      type: "application/acad",
    });

    const created = await adapter.createAuditCheck("2026", [file]);
    const jobs = await adapter.listJobs();

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/api/jobs/audit-replace",
      expect.objectContaining({
        method: "POST",
        body: expect.any(FormData),
      }),
    );

    const formData = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(formData.get("mode")).toBe("check");
    expect(formData.get("params_json")).toBe(JSON.stringify({ project_no: "2026" }));
    expect(formData.getAll("files[]")).toHaveLength(1);

    expect(created.jobs[0]?.taskKind).toBe("audit_check");
    expect(jobs.items[0]?.findingsCount).toBe(12);
    expect(jobs.items[0]?.affectedDrawingsCount).toBe(4);
  });
});
