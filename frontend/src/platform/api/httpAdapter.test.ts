import { afterEach, describe, expect, it, vi } from "vitest";

import { HttpAdapter } from "./httpAdapter";

describe("HttpAdapter", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("keeps public account DTOs and invalid-row raw data free of passwords", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            items: [
              {
                office_code: "S01",
                office_name: "结构一室",
                account_id: "user-a",
                display_name: "用户甲",
                role: "设计人员",
                password: "server-secret",
                valid: true,
                row_number: 2,
                errors: [],
              },
            ],
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            items: [
              {
                row_number: 3,
                raw: {
                  账号: "broken-user",
                  密码: "raw-secret",
                  PASSWORD: "raw-secret-2",
                  api_secret: "raw-secret-3",
                },
                errors: ["invalid_role"],
              },
            ],
          }),
      });
    vi.stubGlobal("fetch", fetchMock);
    const adapter = new HttpAdapter("http://127.0.0.1:8000/");

    const accounts = await adapter.listAccounts();
    const invalidRows = await adapter.listInvalidAccountRows();

    expect(accounts.items[0]).not.toHaveProperty("password");
    expect(invalidRows.items[0].raw).toEqual({ 账号: "broken-user" });
    expect(JSON.stringify({ accounts, invalidRows })).not.toContain("server-secret");
    expect(JSON.stringify({ accounts, invalidRows })).not.toContain("raw-secret");
  });

  it("omits an absent account password from create requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          office_code: "S01",
          office_name: "结构一室",
          account_id: "created-user",
          display_name: "新建用户",
          role: "设计人员",
          valid: true,
          row_number: 4,
          errors: [],
        }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const adapter = new HttpAdapter("http://127.0.0.1:8000/");

    await adapter.createAccount({
      officeCode: "S01",
      officeName: "结构一室",
      accountId: "created-user",
      displayName: "新建用户",
      role: "设计人员",
      password: "",
    });

    const requestBody = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(requestBody).not.toHaveProperty("password");
  });

  it("normalizes task-group submission blockers from management detail", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          group_id: "group-1",
          status: "succeeded",
          can_submit: false,
          submit_blockers: ["deliverable_package_not_found", "shared_prep_invalid"],
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const detail = await new HttpAdapter("http://127.0.0.1:8000/").getTaskGroupDetail(
      "group-1",
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/task-groups/group-1",
      undefined,
    );
    expect(detail.submitBlockers).toEqual([
      "deliverable_package_not_found",
      "shared_prep_invalid",
    ]);
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

  it("forwards a caller cancellation signal for AI message POST requests", async () => {
    const fetchMock = vi.fn((_url: string, init?: RequestInit) =>
      new Promise((_, reject) => {
        const signal = init?.signal;
        signal?.addEventListener(
          "abort",
          () => reject(new DOMException("The request was aborted.", "AbortError")),
          { once: true },
        );
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const controller = new AbortController();
    const request = adapter.sendAiMessage(
      "conversation-1",
      { content: "请停止等待" },
      controller.signal,
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/ai/conversations/conversation-1/messages",
      expect.objectContaining({ method: "POST", signal: expect.any(AbortSignal) }),
    );
    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
    expect((fetchMock.mock.calls[0]?.[1] as RequestInit).signal?.aborted).toBe(true);
  });

  it("uploads an AI attachment with browser-managed multipart headers", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          attachment_id: "attachment-1",
          conversation_id: "conversation-1",
          message_id: null,
          original_name: "说明.txt",
          media_type: "text/plain",
          kind: "document",
          size_bytes: 12,
          sha256: "abc123",
          status: "ready",
          metadata: {},
          error_code: null,
          created_at: "2026-07-22T10:00:00+08:00",
        }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const file = new File(["AI-FILE-0711"], "说明.txt", { type: "text/plain" });

    const attachment = await adapter.uploadAiAttachment("conversation-1", file);

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "http://127.0.0.1:8000/api/ai/conversations/conversation-1/attachments",
    );
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
    expect(attachment).toMatchObject({
      attachmentId: "attachment-1",
      originalName: "说明.txt",
      status: "ready",
    });
  });

  it("includes attachment ids in an AI message request", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          conversation_id: "conversation-1",
          user_message: {
            message_id: "user-1",
            role: "user",
            content: "",
            created_at: "2026-07-22T10:00:00+08:00",
          },
          assistant_message: {
            message_id: "assistant-1",
            role: "assistant",
            content: "已读取",
            created_at: "2026-07-22T10:00:01+08:00",
          },
          memory: { used_history_messages: 0 },
        }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const adapter = new HttpAdapter("http://127.0.0.1:8000/");

    await adapter.sendAiMessage("conversation-1", {
      content: "",
      attachmentIds: ["attachment-1"],
    });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toMatchObject({
      content: "",
      attachment_ids: ["attachment-1"],
    });
  });

  it("creates a calculation-book task with params_json and one ZIP archive", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          batch_id: "batch-calc-1",
          jobs: [
            {
              job_id: "calc-1",
              batch_id: "batch-calc-1",
              source_filename: "calculation.zip",
              task_kind: "calculation_book",
              job_mode: "calculation_book",
              project_no: "2016",
              status: "queued",
              stage: "INIT",
              percent: 0,
              message: "",
              created_at: "2026-07-23T10:00:00+08:00",
              finished_at: null,
              findings_count: 0,
              affected_drawings_count: 0,
              artifacts: {
                package_available: false,
                ied_available: false,
                report_available: false,
                replaced_dwg_available: false,
                calculation_docx_available: false,
              },
              retry_available: false,
            },
          ],
        }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const adapter = new HttpAdapter("http://127.0.0.1:8000");

    const result = await adapter.createCalculationBook({
      project_no: "2016",
      template_type: "internal_structure",
    });

    expect(result.jobs[0]?.taskKind).toBe("calculation_book");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:8000/api/jobs/calculation-books");
    const formData = init.body as FormData;
    expect(formData.has("archive")).toBe(false);
    expect(JSON.parse(String(formData.get("params_json")))).toEqual({
      project_no: "2016",
      template_type: "internal_structure",
    });
  });

  it("preflights a calculation-book archive and normalizes review evidence", async () => {
    const directions = {
      X: {
        image_filename: "N5012-X.JPEG",
        smn: 0,
        smx: 2504,
        legend_values: [0, 278, 556, 835, 1113, 1391, 1669, 1948, 2226, 2504],
        is_zero_result: false,
        source_cell: "B2",
        original_text: "1D32间距200",
        canonical_specification: "1D32间距200",
        narrative_specification: "1排32@200",
        actual_area: 4021.2,
      },
      Y: {
        image_filename: "N5012-Y.JPEG",
        smn: 0,
        smx: 2208,
        legend_values: [0, 245, 491, 736, 981, 1227, 1472, 1717, 1963, 2208],
        is_zero_result: false,
        source_cell: "C2",
        original_text: "1D28间距200",
        canonical_specification: "1D28间距200",
        narrative_specification: "1排28@200",
        actual_area: 3078.8,
      },
      Z: {
        image_filename: "N5012-Z.JPEG",
        smn: 0,
        smx: 0,
        legend_values: [],
        is_zero_result: true,
        source_cell: "",
        original_text: "1A14间距400*400#",
        canonical_specification: "1C14间距400*400",
        narrative_specification: "1排14@400x400",
        actual_area: "",
      },
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          preflight_token: "preflight-1",
          reinforcement_source: "provided",
          requires_ai_recommendation: false,
          figure_count: 3,
          wall_direction_figure_count: 3,
          zero_figure_count: 1,
          z_zero_or_missing_smx_count: 1,
          wall_count: 1,
          reinforcement_source_row_count: 315,
          reinforcement_normalized_row_count: 314,
          reinforcement_issue_row_count: 1,
          reinforcement_unique_wall_count: 314,
          normalization_triggered: true,
          normalization_skill_id: "reinforcement_table_normalizer",
          requires_ai_normalization: true,
          ai_reinforcement_expected_source_row_count: 315,
          ai_confirmation_message: "您上传的墙体配筋表非标准格式，程序将启动人工智能。",
          format_inspection: {
            wall_sheet: "墙体配筋",
            slab_sheet: null,
            reasons: [
              {
                scope: "wall",
                code: "wall_layout_nonstandard",
                sheet: "墙体配筋",
                message: "不是标准四列墙体配筋模板",
              },
            ],
          },
          normalization_issues: [
            {
              source_sheet: "墙体配筋",
              source_row: 8,
              source_cells: { wall: "A8", X: "B8", Y: "C8", Z: "D8" },
              original_values: {
                wall: "N5008",
                X: "1D22间距200",
                Y: "直径22双层@二百",
                Z: "1C8间距400*400",
              },
              original_wall_text: "N5008",
              wall_id: "N5008",
              error: "竖向配筋格式无法确定",
            },
          ],
          image_wall_group_count: 58,
          image_unique_wall_count: 58,
          matched_unique_wall_count: 54,
          image_only_wall_ids: ["N5003A"],
          workbook_only_wall_ids: ["N0001"],
          requires_wall_count_confirmation: true,
          slab_figure_count: 1,
          slab_zero_figure_count: 0,
          slab_elevation_count: 1,
          slab_actual_group_count: 1,
          reinforcement_workbook: "计算书模板文件.xlsx",
          requires_manual_confirmation: false,
          confirmations: [],
          warnings: [
            {
              code: "duplicate_reinforcement_rows",
              scope: "wall",
              identity: "N5012",
              direction: null,
              source_sheet: "墙体配筋",
              source_row: null,
              source_cells: {},
              reason: "同一墙体存在重复配筋行，相关配筋字段已留空",
              blank_fields: ["X", "Y", "Z"],
            },
          ],
          walls: [
            {
              wall_id: "N5012",
              base_wall_id: "N5012",
              group_index: null,
              suggested_source_row: null,
              directions,
            },
          ],
          slabs: [
            {
              elevation: "11.45",
              key: "top_x",
              position: "TOP",
              direction: "X",
              image_filename: "11.45-TOP-X.png",
              smn: 0,
              smx: 4888,
              legend_values: [0, 4888],
              is_zero_result: false,
              source_row: null,
              source_cell: "",
              original_text: "1D36@200",
              canonical_specification: "1D36间距200",
              narrative_specification: "1排36@200",
              actual_area: null,
            },
          ],
        }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const adapter = new HttpAdapter("http://127.0.0.1:8000");
    const archive = new File(["zip"], "calculation.zip", { type: "application/zip" });

    const result = await adapter.preflightCalculationBook(archive, {
      includeSlabStress: true,
      reinforcementSource: "provided",
    });

    expect(result.preflightToken).toBe("preflight-1");
    expect(result).toEqual(
      expect.objectContaining({
        reinforcementSource: "provided",
        requiresAiRecommendation: false,
        wallDirectionFigureCount: 3,
        zZeroOrMissingSmxCount: 1,
        slabZeroFigureCount: 0,
        slabActualGroupCount: 1,
        reinforcementSourceRowCount: 315,
        reinforcementNormalizedRowCount: 314,
        reinforcementUniqueWallCount: 314,
        imageUniqueWallCount: 58,
        matchedUniqueWallCount: 54,
        imageOnlyWallIds: ["N5003A"],
        workbookOnlyWallIds: ["N0001"],
        requiresWallCountConfirmation: true,
        requiresAiNormalization: true,
        aiReinforcementExpectedSourceRowCount: 315,
        aiConfirmationMessage: "您上传的墙体配筋表非标准格式，程序将启动人工智能。",
        formatInspection: {
          wallSheet: "墙体配筋",
          slabSheet: null,
          reasons: [
            {
              scope: "wall",
              code: "wall_layout_nonstandard",
              sheet: "墙体配筋",
              message: "不是标准四列墙体配筋模板",
            },
          ],
        },
      }),
    );
    expect(result.normalizationIssues[0]).toEqual(
      expect.objectContaining({
        sourceRow: 8,
        sourceCells: { wall: "A8", X: "B8", Y: "C8", Z: "D8" },
        originalValues: {
          wall: "N5008",
          X: "1D22间距200",
          Y: "直径22双层@二百",
          Z: "1C8间距400*400",
        },
      }),
    );
    expect(result.walls[0]?.directions.Z).toEqual(
      expect.objectContaining({
        imageFilename: "N5012-Z.JPEG",
        isZeroResult: true,
        canonicalSpecification: "1C14间距400*400",
        sourceCell: "",
        actualArea: null,
      }),
    );
    expect(result.walls[0]?.suggestedSourceRow).toBeNull();
    expect(result.slabs[0]).toEqual(
      expect.objectContaining({
        elevation: "11.45",
        key: "top_x",
        imageFilename: "11.45-TOP-X.png",
        canonicalSpecification: "1D36间距200",
        sourceRow: null,
        sourceCell: "",
        actualArea: null,
      }),
    );
    expect(result.warnings).toEqual([
      expect.objectContaining({
        code: "duplicate_reinforcement_rows",
        filenames: [],
      }),
    ]);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:8000/api/jobs/calculation-books/preflight");
    expect((init.body as FormData).get("archive")).toBe(archive);
    expect((init.body as FormData).get("include_slab_stress")).toBe("true");
    expect((init.body as FormData).get("reinforcement_source")).toBe("provided");
  });

  it("maps an image-only AI preflight without inventing an Excel workbook", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({
        preflight_token: "preflight-ai-1",
        reinforcement_source: "ai_suggested",
        requires_ai_recommendation: true,
        requires_ai_normalization: false,
        figure_count: 177,
        wall_direction_figure_count: 177,
        zero_figure_count: 2,
        z_zero_or_missing_smx_count: 3,
        wall_count: 59,
        reinforcement_workbook: null,
        reinforcement_source_row_count: 0,
        reinforcement_normalized_row_count: 0,
        reinforcement_issue_row_count: 0,
        reinforcement_unique_wall_count: 0,
        normalization_triggered: false,
        normalization_skill_id: null,
        normalization_issues: [],
        image_wall_group_count: 59,
        image_unique_wall_count: 59,
        matched_unique_wall_count: 0,
        image_only_wall_ids: [],
        workbook_only_wall_ids: [],
        requires_wall_count_confirmation: false,
        requires_manual_confirmation: false,
        requires_ocr_review: true,
        confirmations: [],
        walls: [],
        slab_figure_count: 5,
        slab_zero_figure_count: 1,
        slab_elevation_count: 1,
        slab_actual_group_count: 1,
        slabs: [],
        ignored_root_images: ["preview.png"],
        review_items: [{
          code: "split_image_group",
          scope: "wall",
          identity: "N5012-1",
          direction: "X",
          image_filename: "N5012-1-X.png",
          reason: "-1/-2 图片组需要人工确认",
        }],
        warnings: [{ code: "ocr_review_required", filenames: ["N5012-1-X.png"] }],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const adapter = new HttpAdapter("http://127.0.0.1:8000");
    const archive = new File(["rar"], "calculation.rar");

    const result = await adapter.preflightCalculationBook(archive, {
      includeSlabStress: true,
      reinforcementSource: "ai_suggested",
      params: {
        document_name: "11.450m~15.950m配筋计算书",
        roof_top_elevation: 15.95,
      },
    });

    expect(result).toEqual(expect.objectContaining({
      reinforcementSource: "ai_suggested",
      requiresAiRecommendation: true,
      requiresAiNormalization: false,
      reinforcementWorkbook: null,
      wallDirectionFigureCount: 177,
      zZeroOrMissingSmxCount: 3,
      slabFigureCount: 5,
      slabZeroFigureCount: 1,
      slabActualGroupCount: 1,
      requiresOcrReview: true,
      ignoredRootImages: ["preview.png"],
      reviewItems: [expect.objectContaining({
        code: "split_image_group",
        identity: "N5012-1",
      })],
    }));
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = init.body as FormData;
    expect(body.get("reinforcement_source")).toBe("ai_suggested");
    expect(JSON.parse(String(body.get("params_json")))).toEqual({
      document_name: "11.450m~15.950m配筋计算书",
      roof_top_elevation: 15.95,
    });
  });

  it("maps calculation-book AI normalization warnings from completed task details", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({
        job_id: "calculation-ai-1",
        batch_id: "batch-ai-1",
        source_filename: "计算书.rar",
        task_kind: "calculation_book",
        job_mode: "calculation_book",
        project_no: "2016",
        status: "succeeded",
        stage: "CALCULATION_BOOK_COMPLETE",
        percent: 100,
        message: "done",
        created_at: "2026-08-01T12:00:00+08:00",
        finished_at: "2026-08-01T12:01:00+08:00",
        artifacts: {
          package_available: false,
          ied_available: false,
          report_available: false,
          replaced_dwg_available: false,
          calculation_docx_available: true,
          calculation_log_available: true,
          calculation_log_download_url:
            "/api/jobs/calculation-ai-1/download/calculation-book-log",
        },
        retry_available: false,
        calculation_book_output: {
          reinforcement_source: "ai_suggested",
          figure_count: 174,
          template_type: "internal_structure",
          output_filename: "计算书.docx",
          ai_normalized: true,
          warning_count: 1,
          warnings: [
            {
              code: "image_only_wall",
              scope: "wall",
              identity: "N5012",
              direction: null,
              source_sheet: null,
              source_row: null,
              source_cells: {},
              reason: "应力图中存在该墙体，但配筋表没有对应数据，相关配筋字段已留空",
              blank_fields: ["X", "Y", "Z"],
            },
          ],
          ai_normalization: {
            skill_id: "reinforcement_table_normalizer",
            model: "structured-test",
            profile: "intranet-test",
            call_count: 1,
            source_row_count: 315,
            normalized_wall_count: 314,
            normalized_slab_count: 0,
            review_warning_count: 1,
            duration_ms: 125,
            validation: "passed",
          },
          ai_rebar_suggestion: {
            skill_id: "recommend-rebar-from-smx",
            skill_version: "1.0.0",
            skill_sha256: "abc123",
            model: "structured-test",
            call_count: 6,
            suggested_direction_count: 181,
            blank_direction_count: 1,
            repair_round_count: 2,
            validation: "passed_with_warnings",
          },
        },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const detail = await new HttpAdapter("http://127.0.0.1:8000").getJobDetail(
      "calculation-ai-1",
    );

    expect(detail.calculationBookOutput).toEqual(
      expect.objectContaining({
        reinforcementSource: "ai_suggested",
        aiNormalized: true,
        warningCount: 1,
        warnings: [
          expect.objectContaining({
            identity: "N5012",
            sourceSheet: null,
            sourceRow: null,
            blankFields: ["X", "Y", "Z"],
          }),
        ],
        aiNormalization: expect.objectContaining({
          skillId: "reinforcement_table_normalizer",
          sourceRowCount: 315,
          normalizedWallCount: 314,
        }),
        aiRebarSuggestion: expect.objectContaining({
          skillId: "recommend-rebar-from-smx",
          skillVersion: "1.0.0",
          skillSha256: "abc123",
          callCount: 6,
          suggestedDirectionCount: 181,
          blankDirectionCount: 1,
          repairRoundCount: 2,
          validation: "passed_with_warnings",
        }),
      }),
    );
    expect(detail.artifacts).toEqual(expect.objectContaining({
      calculationLogAvailable: true,
      calculationLogDownloadUrl:
        "http://127.0.0.1:8000/api/jobs/calculation-ai-1/download/calculation-book-log",
    }));
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

  it("reads protected artifacts with the current bearer token", async () => {
    const artifact = new Blob(["zip-content"], { type: "application/zip" });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => artifact,
      headers: new Headers({ "Content-Disposition": 'attachment; filename="package.zip"' }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/", {
      getAccessToken: () => "access-token",
    });

    await expect(adapter.readArtifact("/api/jobs/job-1/download/package")).resolves.toBe(artifact);

    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://127.0.0.1:8000/api/jobs/job-1/download/package");
    expect(new Headers(request.headers).get("Authorization")).toBe("Bearer access-token");
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

  it("renames an AI conversation with a mutating PATCH request", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          conversation_id: "conv-1",
          title: "规则提炼会话",
          created_at: "2026-07-11T10:00:00+08:00",
          updated_at: "2026-07-11T10:04:00+08:00",
          message_count: 2,
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    const renamed = await adapter.renameAiConversation("conv-1", "规则提炼会话");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/ai/conversations/conv-1",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ title: "规则提炼会话" }),
      }),
    );
    expect(renamed).toEqual({
      conversationId: "conv-1",
      title: "规则提炼会话",
      createdAt: "2026-07-11T10:00:00+08:00",
      updatedAt: "2026-07-11T10:04:00+08:00",
      messageCount: 2,
    });
  });

  it("deletes an AI conversation with a bounded DELETE request", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({ ok: true }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");
    await adapter.deleteAiConversation("conv-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/ai/conversations/conv-1",
      expect.objectContaining({ method: "DELETE", signal: expect.any(AbortSignal) }),
    );
  });

  it("propagates an external abort signal to AI GET requests", async () => {
    let requestSignal: AbortSignal | undefined;
    let resolveFetch: ((value: unknown) => void) | undefined;
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      requestSignal = init?.signal ?? undefined;
      return new Promise((resolve) => {
        resolveFetch = resolve;
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const adapter = new HttpAdapter("http://127.0.0.1:8000/");

    const pending = adapter.getAiState(controller.signal);
    controller.abort();
    const abortWasPropagated = requestSignal?.aborted;
    resolveFetch?.({
      ok: true,
      text: async () =>
        JSON.stringify({
          enabled: true,
          profile: "development_minimax",
          model: "MiniMax-M3",
          owner_key: "ip:127.0.0.1",
          default_agent: "platform_assistant",
          agents: [],
          skills: [],
          mcp_servers: [],
        }),
    });
    await pending;

    expect(abortWasPropagated).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("applies a timeout signal to AI control mutations", async () => {
    let requestSignal: AbortSignal | undefined;
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      requestSignal = init?.signal ?? undefined;
      return Promise.resolve({
        ok: true,
        text: async () =>
          JSON.stringify({
            conversation_id: "conv-new",
            title: "新会话",
            created_at: "2026-07-12T12:00:00+08:00",
            updated_at: "2026-07-12T12:00:00+08:00",
            message_count: 0,
          }),
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const adapter = new HttpAdapter("http://127.0.0.1:8000/");

    await adapter.createAiConversation("新会话");

    expect(requestSignal).toBeInstanceOf(AbortSignal);
    expect(fetchMock).toHaveBeenCalledTimes(1);
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
