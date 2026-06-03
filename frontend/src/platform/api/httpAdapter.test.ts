import { afterEach, describe, expect, it, vi } from "vitest";

import { HttpAdapter } from "./httpAdapter";

describe("HttpAdapter", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("checks backend process reachability through the lightweight ping endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          ok: true,
          server_time: "2026-05-29T10:20:30+08:00",
          version: "dev",
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const ping = await adapter.ping();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/system/ping",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(ping).toEqual({
      ok: true,
      serverTime: "2026-05-29T10:20:30+08:00",
      version: "dev",
    });
  });

  it("retries idempotent GET requests after transient network failures", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("network reset"))
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            total: 0,
            items: [],
          }),
      });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(Math, "random").mockReturnValue(0);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const jobsPromise = adapter.listJobs();
    await vi.runAllTimersAsync();
    const jobs = await jobsPromise;

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(jobs.items).toEqual([]);
  });

  it("does not retry mutating POST requests after a network failure", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("network reset"));
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const file = new File(["dwg"], "upload.dwg", {
      type: "application/acad",
    });

    await expect(adapter.createBatch({ project_no: "2026" }, [file])).rejects.toThrow(
      "network reset",
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("reads artifact blobs with the current bearer token", async () => {
    const artifactBlob = new Blob(["report"], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => artifactBlob,
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/", {
      getAccessToken: () => "session-token",
    });
    const blob = await adapter.readArtifact("/api/jobs/job-1/download/report");

    expect(blob).toBe(artifactBlob);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/jobs/job-1/download/report",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer session-token");
  });

  it("downloads artifacts through an authenticated blob request", async () => {
    const artifactBlob = new Blob(["report"], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({
        "Content-Disposition": 'attachment; filename="report.xlsx"',
      }),
      blob: async () => artifactBlob,
    });
    const anchor = {
      href: "",
      download: "",
      style: { display: "" },
      click: vi.fn(),
      remove: vi.fn(),
    } as unknown as HTMLAnchorElement;
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(document, "createElement").mockReturnValue(anchor);
    vi.spyOn(document.body, "appendChild").mockImplementation((node) => node);
    const createObjectURLMock = vi.fn().mockReturnValue("blob:report");
    const revokeObjectURLMock = vi.fn();
    URL.createObjectURL = createObjectURLMock;
    URL.revokeObjectURL = revokeObjectURLMock;

    const adapter = new HttpAdapter("http://127.0.0.1:8000/", {
      getAccessToken: () => "session-token",
    });
    await adapter.downloadArtifact("/api/jobs/job-1/download/report", "fallback.xlsx");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/jobs/job-1/download/report",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer session-token");
    expect(createObjectURLMock).toHaveBeenCalledWith(artifactBlob);
    expect(anchor.href).toBe("blob:report");
    expect(anchor.download).toBe("report.xlsx");
    expect(anchor.click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLMock).toHaveBeenCalledWith("blob:report");
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
          deliverable_outputs: {
            dwg_count: 1,
            pdf_count: 1,
            documents: [{ name: "目录.xlsx", kind: "xlsx" }],
            drawings: [
              {
                name: "A01",
                internal_code: "20261RS-JGS65-001",
                dwg_name: "A01.dwg",
                pdf_name: "A01.pdf",
                page_total: 2,
              },
            ],
          },
          retry_available: false,
          artifacts: {
            package_available: true,
            ied_available: true,
            preview_available: true,
            preview_mode: "annotated",
            report_available: false,
            replaced_dwg_available: false,
            package_download_url: "/api/jobs/job-1/download/package",
            ied_download_url: "/api/jobs/job-1/download/ied",
            preview_download_url: "/api/jobs/job-1/download/preview",
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
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(detail.artifacts.packageDownloadUrl).toBe(
      "http://127.0.0.1:8000/api/jobs/job-1/download/package",
    );
    expect(detail.artifacts.iedDownloadUrl).toBe(
      "http://127.0.0.1:8000/api/jobs/job-1/download/ied",
    );
    expect(detail.artifacts.previewDownloadUrl).toBe(
      "http://127.0.0.1:8000/api/jobs/job-1/download/preview",
    );
    expect(detail.artifacts.previewMode).toBe("annotated");
    expect(detail.deliverableOutputs?.drawings[0]).toMatchObject({
      internalCode: "20261RS-JGS65-001",
      dwgName: "A01.dwg",
      pageTotal: 2,
    });
  });

  it("creates audit check jobs with mode=check and can attach them to an existing batch", async () => {
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

    const created = await adapter.createAuditCheck("2026", "1", [file], "batch-shared-1");
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
    expect(formData.get("params_json")).toBe(
      JSON.stringify({ project_no: "2026", unit_no: "1", batch_id: "batch-shared-1" }),
    );
    expect(formData.getAll("files[]")).toHaveLength(1);

    expect(created.jobs[0]?.taskKind).toBe("audit_check");
    expect(jobs.items[0]?.findingsCount).toBe(12);
    expect(jobs.items[0]?.affectedDrawingsCount).toBe(4);
  });

  it("passes status, offset, and limit to listJobs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          total: 12,
          items: [],
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const jobs = await adapter.listJobs("running", 100, 50);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/jobs?status=running&offset=100&limit=50",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(jobs.total).toBe(12);
    expect(jobs.items).toHaveLength(0);
  });

  it("maps owner snapshot fields in job summaries", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          total: 1,
          items: [
            {
              job_id: "job-owned-1",
              batch_id: "batch-owned-1",
              source_filename: "owned.dwg",
              task_kind: "deliverable",
              job_mode: "deliverable",
              project_no: "2016",
              status: "succeeded",
              stage: "DONE",
              percent: 100,
              message: "done",
              created_at: "2026-06-01T10:00:00+08:00",
              finished_at: "2026-06-01T10:01:00+08:00",
              findings_count: 0,
              affected_drawings_count: 0,
              retry_available: false,
              owner_snapshot: {
                creator_account: "zhangsan",
                creator_name: "张三",
                creator_role: "设计人员",
                creator_office: "结构一室",
                created_by_scope: "current_login_user",
                submitted_at: null,
              },
              creator_account: "zhangsan",
              creator_name: "张三",
              creator_office: "结构一室",
              artifacts: {
                package_available: true,
                ied_available: false,
                report_available: false,
                replaced_dwg_available: false,
              },
            },
          ],
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const jobs = await adapter.listJobs();

    expect(jobs.items[0]).toMatchObject({
      creatorAccount: "zhangsan",
      creatorName: "张三",
      creatorOffice: "结构一室",
      ownerSnapshot: {
        creatorAccount: "zhangsan",
        creatorName: "张三",
        creatorRole: "设计人员",
        creatorOffice: "结构一室",
        createdByScope: "current_login_user",
        submittedAt: null,
      },
    });
  });

  it("maps failure display fields in job summaries", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          total: 1,
          items: [
            {
              job_id: "failed-job-1",
              batch_id: "batch-failed-1",
              source_filename: "20162SD-JGS03-出图.dwg",
              task_kind: "deliverable",
              job_mode: "deliverable",
              project_no: "2016",
              status: "failed",
              stage: "A4_MULTIPAGE_GROUPING",
              percent: 60,
              message: "完成阶段: A4_MULTIPAGE_GROUPING",
              failure_reason: "服务重启/中断，任务未完成",
              stage_context: "中断前最后完成阶段：A4 多页合并",
              created_at: "2026-05-14T10:19:22+08:00",
              finished_at: "2026-05-14T10:20:00+08:00",
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
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const jobs = await adapter.listJobs();

    expect(jobs.items[0]?.failureReason).toBe("服务重启/中断，任务未完成");
    expect(jobs.items[0]?.stageContext).toBe("中断前最后完成阶段：A4 多页合并");
  });

  it("creates replace-only jobs with mode=replace and run_deliverable=false", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          batch_id: "batch-replace-1",
          jobs: [
            {
              job_id: "replace-job-1",
              batch_id: "batch-replace-1",
              source_filename: "20261NH-JGS51-B合并版.dwg",
              task_kind: "audit_replace",
              job_mode: "replace",
              project_no: "2026",
              status: "queued",
              stage: "INIT",
              percent: 0,
              message: "",
              created_at: "2026-03-24T09:00:00+08:00",
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
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const file = new File(["dwg"], "20261NH-JGS51-B合并版.dwg", {
      type: "application/acad",
    });

    const created = await adapter.createAuditReplace({
      sourceProjectNo: "2026",
      sourceIslandNo: "2",
      targetProjectNo: "2016",
      targetIslandNo: "1",
      files: [file],
      runDeliverable: false,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/jobs/audit-replace",
      expect.objectContaining({
        method: "POST",
        body: expect.any(FormData),
      }),
    );

    const formData = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(formData.get("mode")).toBe("replace");
    expect(formData.get("params_json")).toBe(
      JSON.stringify({
        source_project_no: "2026",
        source_island_no: "2",
        target_project_no: "2016",
        target_island_no: "1",
        run_deliverable: false,
      }),
    );
    expect(created.jobs[0]?.taskKind).toBe("audit_replace");
  });

  it("creates replace-plus-deliverable groups with deliverable_params", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          batch_id: "batch-replace-group-1",
          jobs: [
            {
              job_id: "group-replace-1",
              group_id: "group-replace-1",
              batch_id: "batch-replace-group-1",
              is_group: true,
              source_filename: "20261NH-JGS51-B合并版.dwg",
              source_filenames: ["20261NH-JGS51-B合并版.dwg"],
              project_no: "2016",
              status: "queued",
              stage: "PREP_SOURCE",
              percent: 0,
              message: "",
              created_at: "2026-03-24T09:01:00+08:00",
              finished_at: null,
              child_job_ids: ["job-replace-1", "job-deliverable-1"],
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
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const file = new File(["dwg"], "20261NH-JGS51-B合并版.dwg", {
      type: "application/acad",
    });

    const created = await adapter.createAuditReplace({
      sourceProjectNo: "2026",
      sourceIslandNo: "2",
      targetProjectNo: "2016",
      targetIslandNo: "1",
      files: [file],
      runDeliverable: true,
      deliverableParams: {
        project_no: "2016",
        cover_variant: "通用",
      },
    });

    const formData = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(formData.get("mode")).toBe("replace");
    expect(formData.get("params_json")).toBe(
      JSON.stringify({
        source_project_no: "2026",
        source_island_no: "2",
        target_project_no: "2016",
        target_island_no: "1",
        run_deliverable: true,
        deliverable_params: {
          project_no: "2016",
          cover_variant: "通用",
        },
      }),
    );
    expect(created.jobs[0]).toMatchObject({
      isGroup: true,
      groupId: "group-replace-1",
      childJobIds: ["job-replace-1", "job-deliverable-1"],
    });
  });

  it("preflights fonts before submit and returns backend replacement options", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          files: [
            {
              filename: "19163RC-JGS04-WD.dwg",
              status: "missing_fonts",
              missing_fonts: [
                {
                  style_name: "HZTXT",
                  font_name: "missing.shx",
                  bigfont_name: "",
                  kind: "shx",
                  used_in_block: true,
                },
              ],
              detected_style_count: 30,
              missing_style_count: 1,
              font_replacement_applied: false,
              replacement_font: null,
              replaced_style_count: 0,
            },
          ],
          replacement_options: [
            {
              label: "simplex.shx (AutoCAD SHX)",
              value: "simplex.shx",
              family: "simplex",
              path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\simplex.shx",
              kind: "shx",
              source: "autocad_fonts",
            },
          ],
          replacement_options_by_kind: {
            shx: [
              {
                label: "simplex.shx (AutoCAD SHX)",
                value: "simplex.shx",
                family: "simplex",
                path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\simplex.shx",
                kind: "shx",
                source: "autocad_fonts",
              },
            ],
          },
          default_replacement_font: "simplex.shx",
          default_replacement_fonts: {
            shx: "simplex.shx",
          },
          requires_confirmation: true,
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const file = new File(["dwg"], "19163RC-JGS04-WD.dwg", {
      type: "application/acad",
    });

    const result = await adapter.preflightFonts([file]);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/jobs/preflight-fonts",
      expect.objectContaining({
        method: "POST",
        body: expect.any(FormData),
      }),
    );

    const formData = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(formData.getAll("files[]")).toHaveLength(1);
    expect(result.requiresConfirmation).toBe(true);
    expect(result.replacementOptions).toEqual([
      {
        label: "simplex.shx (AutoCAD SHX)",
        value: "simplex.shx",
        family: "simplex",
        path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\simplex.shx",
        kind: "shx",
        source: "autocad_fonts",
      },
    ]);
    expect(result.replacementOptionsByKind).toEqual({
      shx: [
        {
          label: "simplex.shx (AutoCAD SHX)",
          value: "simplex.shx",
          family: "simplex",
          path: "D:\\Program Files\\AUTOCAD\\AutoCAD 2022\\Fonts\\simplex.shx",
          kind: "shx",
          source: "autocad_fonts",
        },
      ],
    });
    expect(result.defaultReplacementFont).toBe("simplex.shx");
    expect(result.defaultReplacementFonts).toEqual({
      shx: "simplex.shx",
    });
    expect(result.files[0]).toEqual({
      filename: "19163RC-JGS04-WD.dwg",
      status: "missing_fonts",
      missingFonts: [
        {
          styleName: "HZTXT",
          fontName: "missing.shx",
          bigfontName: "",
          kind: "shx",
          usedInBlock: true,
        },
      ],
      detectedStyleCount: 30,
      missingStyleCount: 1,
      fontReplacementApplied: false,
      replacementFont: null,
      replacementFonts: {},
      fontCompatibilityMode: false,
      fontCompatibilityReplacements: {},
      replacedStyleCount: 0,
      verifyAfterReplace: null,
      fontReplacementIncomplete: false,
      errors: [],
    });
  });

  it("preserves non-JSON API error bodies when a request fails", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      text: async () => "<html><body>Bad Gateway</body></html>",
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const file = new File(["dwg"], "bad.dwg", {
      type: "application/acad",
    });

    await expect(adapter.preflightFonts([file])).rejects.toMatchObject({
      status: 502,
      detail: "<html><body>Bad Gateway</body></html>",
    });
  });

  it("creates grouped deliverable batches with run_audit_check=true when requested", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          batch_id: "batch-group-1",
          jobs: [
            {
              job_id: "group-1",
              group_id: "group-1",
              batch_id: "batch-group-1",
              is_group: true,
              source_filename: "18185NE-JGS11.dwg",
              source_filenames: ["18185NE-JGS11.dwg"],
              project_no: "1818",
              status: "queued",
              stage: "PREP_SOURCE",
              percent: 0,
              message: "",
              created_at: "2026-03-16T11:00:00+08:00",
              finished_at: null,
              run_audit_check: true,
              child_job_ids: ["job-deliverable-1", "job-audit-1"],
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
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const file = new File(["dwg"], "18185NE-JGS11.dwg", {
      type: "application/acad",
    });

    const created = await adapter.createBatch({ project_no: "1818" }, [file], true);

    const formData = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(formData.get("params_json")).toBe(JSON.stringify({ project_no: "1818" }));
    expect(formData.get("run_audit_check")).toBe("true");
    expect(created.jobs[0]).toMatchObject({
      jobId: "group-1",
      isGroup: true,
      groupId: "group-1",
      runAuditCheck: true,
      childJobIds: ["job-deliverable-1", "job-audit-1"],
      sourceFilenames: ["18185NE-JGS11.dwg"],
    });
  });

  it("creates split-only deliverable batches with split_only=true", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          batch_id: "batch-split-1",
          jobs: [
            {
              job_id: "split-job-1",
              batch_id: "batch-split-1",
              source_filename: "20261RS-JGS65.dwg",
              task_kind: "deliverable",
              job_mode: "split_only",
              task_role: "仅拆图",
              project_no: "2026",
              status: "queued",
              stage: "INIT",
              percent: 0,
              message: "",
              created_at: "2026-03-16T11:00:00+08:00",
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
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const file = new File(["dwg"], "20261RS-JGS65.dwg", {
      type: "application/acad",
    });

    const created = await adapter.createSplitOnlyBatch({ project_no: "2026" }, [file]);

    const formData = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(formData.get("params_json")).toBe(JSON.stringify({ project_no: "2026" }));
    expect(formData.get("split_only")).toBe("true");
    expect(created.jobs[0]).toMatchObject({
      jobId: "split-job-1",
      jobMode: "split_only",
      taskRole: "仅拆图",
    });
  });
});
