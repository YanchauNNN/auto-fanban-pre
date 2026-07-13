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
          finding_groups: [
            {
              matched_text: "GB 51058-2011",
              count: 1,
              internal_codes: ["18185NF-JGS19-003"],
              category: "规范审查",
              context_kind: "standard_review_year",
              issue_type: "year_mismatch",
              summary: "标准号年限不一致：GB 51058-2011 应为 GB 51058-2014",
              details: ["实际标准号：GB 51058-2011", "期望标准号：GB 51058-2014"],
            },
          ],
          workload: {
            initial_workload_a1: 2.5,
            final_workload_a1: 2.7,
            one_review_factor: 1,
            two_review_factor: 1.08,
            three_review_factor: 1,
            settlement_status: "pending",
            settled_at: null,
          },
          effective_workload: 2.7,
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
          diagnostics: [
            {
              kind: "duplicate_code",
              severity: "error",
              title: "检测到重复编码",
              summary: "发现 0 个重复内部编码、1 个重复外部编码。",
              suggestion: "请检查图签中的内部编码/外部编码。",
              details: [
                {
                  label: "外部编码 PC5NPM12004B25C42SD",
                  items: ["18185NP-JGS44-024", "18185NP-JGS44-026"],
                },
              ],
              raw_items: ["检测到重复编码"],
            },
          ],
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
    expect(detail.workload).toMatchObject({
      initialWorkloadA1: 2.5,
      finalWorkloadA1: 2.7,
      twoReviewFactor: 1.08,
      settlementStatus: "pending",
    });
    expect(detail.effectiveWorkload).toBe(2.7);
    expect(detail.findingGroups?.[0]).toMatchObject({
      matchedText: "GB 51058-2011",
      category: "规范审查",
      contextKind: "standard_review_year",
      issueType: "year_mismatch",
      summary: "标准号年限不一致：GB 51058-2011 应为 GB 51058-2014",
      details: ["实际标准号：GB 51058-2011", "期望标准号：GB 51058-2014"],
    });
    expect((detail as any).diagnostics?.[0]).toMatchObject({
      kind: "duplicate_code",
      severity: "error",
      title: "检测到重复编码",
      details: [
        {
          label: "外部编码 PC5NPM12004B25C42SD",
          items: ["18185NP-JGS44-024", "18185NP-JGS44-026"],
        },
      ],
      rawItems: ["检测到重复编码"],
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

  it("passes created-at sorting to listJobs when requested", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          total: 0,
          items: [],
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    await adapter.listJobs(undefined, 0, 100, "created_at");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/jobs?offset=0&limit=100&sort=created_at",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("fetches lightweight jobs activity marker", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          total: 12,
          active: 2,
          last_changed_at: "2026-07-05T12:34:56+08:00",
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const activity = await adapter.getJobsActivity();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/jobs/activity",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(activity).toEqual({
      total: 12,
      active: 2,
      lastChangedAt: "2026-07-05T12:34:56+08:00",
    });
  });

  it("subscribes to jobs activity SSE and closes cleanly", () => {
    const instances: FakeEventSource[] = [];

    class FakeEventSource {
      readonly url: string;
      onerror: ((event: Event) => void) | null = null;
      closed = false;
      private readonly listeners = new Map<string, EventListener[]>();

      constructor(url: string) {
        this.url = url;
        instances.push(this);
      }

      addEventListener(type: string, listener: EventListener) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }

      removeEventListener(type: string, listener: EventListener) {
        this.listeners.set(
          type,
          (this.listeners.get(type) ?? []).filter((candidate) => candidate !== listener),
        );
      }

      close() {
        this.closed = true;
      }

      emit(type: string, data: string) {
        const event = new MessageEvent(type, { data });
        for (const listener of this.listeners.get(type) ?? []) {
          listener(event);
        }
      }
    }

    vi.stubGlobal("EventSource", FakeEventSource);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const onActivity = vi.fn();
    const onError = vi.fn();
    const unsubscribe = adapter.subscribeJobsActivity(onActivity, onError);

    expect(instances).toHaveLength(1);
    expect(instances[0].url).toBe("http://127.0.0.1:8000/api/jobs/activity/stream");

    instances[0].emit(
      "jobs_activity",
      JSON.stringify({
        total: 12,
        active: 2,
        last_changed_at: "2026-07-05T12:34:56+08:00",
      }),
    );

    expect(onActivity).toHaveBeenCalledWith({
      total: 12,
      active: 2,
      lastChangedAt: "2026-07-05T12:34:56+08:00",
    });

    instances[0].onerror?.(new Event("error"));
    expect(onError).toHaveBeenCalledTimes(1);
    expect(instances[0].closed).toBe(false);

    unsubscribe();

    expect(instances[0].closed).toBe(true);
    instances[0].emit(
      "jobs_activity",
      JSON.stringify({
        total: 13,
        active: 0,
        last_changed_at: "2026-07-05T12:35:00+08:00",
      }),
    );
    expect(onActivity).toHaveBeenCalledTimes(1);
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
        unit_factory_codes: [],
        run_deliverable: false,
      }),
    );
    expect(created.jobs[0]?.taskKind).toBe("audit_replace");
  });

  it("sends factory-code unit replacement whitelist for replace jobs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          batch_id: "batch-replace-2",
          jobs: [
            {
              job_id: "job-replace-2",
              batch_id: "batch-replace-2",
              source_filename: "sample.dwg",
              project_no: "2016",
              task_kind: "audit_replace",
              status: "queued",
              stage: "PREP_SOURCE",
              percent: 0,
              message: "",
              created_at: "2026-03-24T09:01:00+08:00",
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
    await adapter.createAuditReplace({
      sourceProjectNo: "2016",
      sourceIslandNo: "1",
      targetProjectNo: "2026",
      targetIslandNo: "2",
      unitFactoryCodes: ["hl", "HL", "RX"],
      files: [new File(["dwg"], "sample.dwg")],
      runDeliverable: false,
    });

    const formData = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(formData.get("params_json")).toBe(
      JSON.stringify({
        source_project_no: "2016",
        source_island_no: "1",
        target_project_no: "2026",
        target_island_no: "2",
        unit_factory_codes: ["HL", "RX"],
        run_deliverable: false,
      }),
    );
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
        unit_factory_codes: [],
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
              font_compatibility_required: true,
              empty_style_entity_replaced_count: 2,
              empty_style_style_patched_count: 1,
              empty_style_shared_skipped_count: 1,
              empty_style_shared_styles: ["汉字"],
              empty_style_target_regions_count: 3,
              empty_style_global_replaced_count: 0,
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
      fontCompatibilityRequired: true,
      emptyStyleEntityReplacedCount: 2,
      emptyStyleStylePatchedCount: 1,
      emptyStyleSharedSkippedCount: 1,
      emptyStyleSharedStyles: ["汉字"],
      emptyStyleTargetRegionsCount: 3,
      emptyStyleGlobalReplacedCount: 0,
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
