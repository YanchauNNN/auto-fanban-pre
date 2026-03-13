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
});
