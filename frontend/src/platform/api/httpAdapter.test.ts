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
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
    expect(detail.artifacts.packageDownloadUrl).toBe(
      "http://127.0.0.1:8000/api/jobs/job-1/download/package",
    );
    expect(detail.artifacts.iedDownloadUrl).toBe(
      "http://127.0.0.1:8000/api/jobs/job-1/download/ied",
    );
    expect(detail.deliverableOutputs?.drawings[0]).toMatchObject({
      internalCode: "20261RS-JGS65-001",
      dwgName: "A01.dwg",
      pageTotal: 2,
    });
  });

  it("authenticates with bearer headers and supports login plus current-account fetch", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            token: "session-token",
            account: {
              account_id: "zhangsan",
              display_name: "张三",
              role: "设计人员",
              office_code: "HB-JG",
              office_name: "河北分公司-建筑结构所",
              valid: true,
            },
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            account_id: "zhangsan",
            display_name: "张三",
            role: "设计人员",
            office_code: "HB-JG",
            office_name: "河北分公司-建筑结构所",
            valid: true,
            pending_todo_count: 3,
          }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/", {
      getAccessToken: () => "session-token",
    });

    const loginResult = await adapter.login({
      accountId: "zhangsan",
      password: "password",
    });
    const me = await adapter.getMe();

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/api/auth/login",
      expect.objectContaining({
        method: "POST",
        headers: expect.any(Headers),
        body: JSON.stringify({
          account_id: "zhangsan",
          password: "password",
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/api/auth/me",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
    const loginHeaders = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    const meHeaders = fetchMock.mock.calls[1]?.[1]?.headers as Headers;
    expect(loginHeaders.get("Content-Type")).toBe("application/json");
    expect(meHeaders.get("Authorization")).toBe("Bearer session-token");
    expect(loginResult).toEqual({
      token: "session-token",
      account: {
        accountId: "zhangsan",
        displayName: "张三",
        role: "设计人员",
        officeCode: "HB-JG",
        officeName: "河北分公司-建筑结构所",
        valid: true,
        pendingTodoCount: 0,
      },
    });
    expect(me.pendingTodoCount).toBe(3);
  });

  it("normalizes personnel inputs and returns candidate snapshots", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          normalized: {
            field_name: "ied_checked_by",
            raw_value: "重名",
            normalized_value: null,
            matched_account: null,
            matched_name: null,
            match_strategy: null,
            status: "ambiguous",
            errors: ["duplicate_name_needs_selection"],
          },
          candidates: [
            {
              account_id: "dup-1",
              display_name: "重名",
              role: "设计人员",
              office_code: "S01",
              office_name: "结构一室",
              valid: true,
            },
            {
              account_id: "dup-2",
              display_name: "重名",
              role: "设计人员",
              office_code: "S02",
              office_name: "结构二室",
              valid: true,
            },
          ],
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/", {
      getAccessToken: () => "session-token",
    });

    const result = await (adapter as HttpAdapter & {
      normalizePersonnel: (fieldName: string, rawValue: string | null) => Promise<unknown>;
    }).normalizePersonnel("ied_checked_by", "重名");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/accounts/normalize-personnel",
      expect.objectContaining({
        method: "POST",
        headers: expect.any(Headers),
        body: JSON.stringify({
          field_name: "ied_checked_by",
          raw_value: "重名",
        }),
      }),
    );
    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer session-token");
    expect(result).toEqual({
      normalized: {
        fieldName: "ied_checked_by",
        rawValue: "重名",
        normalizedValue: null,
        matchedAccount: null,
        matchedName: null,
        matchStrategy: null,
        status: "ambiguous",
        errors: ["duplicate_name_needs_selection"],
      },
      candidates: [
        {
          accountId: "dup-1",
          displayName: "重名",
          role: "设计人员",
          officeCode: "S01",
          officeName: "结构一室",
          valid: true,
        },
        {
          accountId: "dup-2",
          displayName: "重名",
          role: "设计人员",
          officeCode: "S02",
          officeName: "结构二室",
          valid: true,
        },
      ],
    });
  });

  it("loads personal workload summaries with normalized query filters", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          scope: "me",
          filters: {
            start_date: "2026-01-01",
            end_date: "2026-03-31",
            status: "settled",
            valid_only: true,
          },
          total_workload_a1: 2.6,
          entries: [
            {
              role_key: "ied_prepared_by",
              account_id: "zhangsan",
              display_name: "寮犱笁",
              workload_a1: 1.4,
              settled_at: "2026-03-20T10:20:30+08:00",
              group_id: "group-1",
              settlement_status: "settled",
            },
            {
              role_key: "ied_checked_by",
              account_id: "zhangsan",
              display_name: "寮犱笁",
              workload_a1: 1.2,
              settled_at: "2026-03-22T10:20:30+08:00",
              group_id: "group-2",
              settlement_status: "settled",
            },
          ],
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/", {
      getAccessToken: () => "session-token",
    });

    const result = await (adapter as HttpAdapter & {
      getWorkloadMe: (filters?: {
        startDate?: string;
        endDate?: string;
        status?: string;
        validOnly?: boolean;
      }) => Promise<unknown>;
    }).getWorkloadMe({
      startDate: "2026-01-01",
      endDate: "2026-03-31",
      status: "settled",
      validOnly: true,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/workload/me?start_date=2026-01-01&end_date=2026-03-31&status=settled&valid_only=true",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer session-token");
    expect(result).toEqual({
      scope: "me",
      filters: {
        startDate: "2026-01-01",
        endDate: "2026-03-31",
        status: "settled",
        validOnly: true,
      },
      totalWorkloadA1: 2.6,
      officeName: null,
      totalsByAccount: {},
      entries: [
        {
          roleKey: "ied_prepared_by",
          accountId: "zhangsan",
          displayName: "寮犱笁",
          workloadA1: 1.4,
          settledAt: "2026-03-20T10:20:30+08:00",
          groupId: "group-1",
          settlementStatus: "settled",
        },
        {
          roleKey: "ied_checked_by",
          accountId: "zhangsan",
          displayName: "寮犱笁",
          workloadA1: 1.2,
          settledAt: "2026-03-22T10:20:30+08:00",
          groupId: "group-2",
          settlementStatus: "settled",
        },
      ],
    });
  });

  it("loads workflow monitor items through the task-group serializer", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () =>
        JSON.stringify({
          total: 1,
          items: [
            {
              group_id: "group-monitor-1",
              batch_id: "batch-monitor-1",
              project_no: "2026",
              status: "running",
              created_at: "2026-03-25T10:20:30+08:00",
              source_filenames: ["20261RS-JGS65.dwg"],
              owner_snapshot: {
                creator_account: "zhangsan",
                creator_name: "张三",
                creator_role: "设计人员",
                creator_office: "河北分公司-建筑结构所",
                created_by_scope: "self_only",
                submitted_at: "2026-03-25T10:25:30+08:00",
              },
              creator_name: "张三",
              creator_account: "zhangsan",
              creator_office: "河北分公司-建筑结构所",
              workflow_status: "in_review",
              current_node_key: "one_review",
              archive_status: "pending",
              workload: {
                initial_workload_a1: 1.2,
                final_workload_a1: 1.35,
                one_review_factor: 1,
                two_review_factor: 1,
                three_review_factor: 1,
                settlement_status: "pending",
                settled_at: null,
                contributor_entries: [],
              },
              effective_workload: 1.35,
              can_view_detail: true,
              can_submit: false,
              can_approve: true,
              is_related_to_current_user: true,
            },
          ],
        }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/", {
      getAccessToken: () => "session-token",
    });

    const result = await (adapter as HttpAdapter & {
      getWorkflowMonitor: () => Promise<unknown>;
    }).getWorkflowMonitor();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/workflow/monitor",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer session-token");
    expect(result).toEqual({
      total: 1,
      items: [
        expect.objectContaining({
          groupId: "group-monitor-1",
          workflowStatus: "in_review",
          currentNodeKey: "one_review",
          canApprove: true,
          isRelatedToCurrentUser: true,
        }),
      ],
    });
  });

  it("posts workflow approvals with factor and node key", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({ ok: true }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/", {
      getAccessToken: () => "session-token",
    });

    await (adapter as HttpAdapter & {
      approveWorkflow: (groupId: string, payload: { factor: number; nodeKey?: string | null }) => Promise<void>;
    }).approveWorkflow("group-monitor-1", {
      factor: 1.05,
      nodeKey: "one_review",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/workflow/group-monitor-1/approve",
      expect.objectContaining({
        method: "POST",
        headers: expect.any(Headers),
        body: JSON.stringify({
          factor: 1.05,
          node_key: "one_review",
        }),
      }),
    );
    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer session-token");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("loads accounts, invalid rows, and admin config through management endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            items: [
              {
                office_code: "HB-JG",
                office_name: "河北分公司-建筑结构所",
                account_id: "existing-user",
                display_name: "现有账号",
                role: "设计人员",
                password: "password",
                valid: true,
                row_number: 8,
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
                row_number: 18,
                raw: {
                  account_id: "",
                  display_name: "缺失账号",
                },
                errors: ["missing_account_id"],
              },
            ],
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            archive_root_path: "\\\\fileserver\\archive\\drawings",
          }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/", {
      getAccessToken: () => "session-token",
    });

    const accounts = await (adapter as HttpAdapter & {
      listAccounts: () => Promise<unknown>;
    }).listAccounts();
    const invalidRows = await (adapter as HttpAdapter & {
      listInvalidAccountRows: () => Promise<unknown>;
    }).listInvalidAccountRows();
    const config = await (adapter as HttpAdapter & {
      getAdminConfig: () => Promise<unknown>;
    }).getAdminConfig();

    expect(accounts).toEqual({
      items: [
        {
          officeCode: "HB-JG",
          officeName: "河北分公司-建筑结构所",
          accountId: "existing-user",
          displayName: "现有账号",
          role: "设计人员",
          password: "password",
          valid: true,
          rowNumber: 8,
          errors: [],
        },
      ],
    });
    expect(invalidRows).toEqual({
      items: [
        {
          rowNumber: 18,
          raw: {
            account_id: "",
            display_name: "缺失账号",
          },
          errors: ["missing_account_id"],
        },
      ],
    });
    expect(config).toEqual({
      archiveRootPath: "\\\\fileserver\\archive\\drawings",
    });
  });

  it("creates and updates accounts plus patches admin config with normalized payloads", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({
        ok: true,
        text: async () =>
          JSON.stringify({
            office_code: "HB-JG",
            office_name: "河北分公司-建筑结构所",
            account_id: "existing-user",
            display_name: "现有账号",
            role: "设计人员",
            password: "password",
            valid: true,
            row_number: 8,
            errors: [],
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            office_code: "HB-JG",
            office_name: "河北分公司-建筑结构所",
            account_id: "new-user",
            display_name: "新账号",
            role: "设计人员",
            password: "password",
            valid: true,
            row_number: 19,
            errors: [],
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            office_code: "HB-JG",
            office_name: "河北分公司-建筑结构所",
            account_id: "existing-user",
            display_name: "现有账号-更新",
            role: "设计人员",
            password: "new-password",
            valid: true,
            row_number: 8,
            errors: [],
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            archive_root_path: "\\\\fileserver\\archive\\next",
          }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/", {
      getAccessToken: () => "session-token",
    });

    await (adapter as HttpAdapter & {
      createAccount: (payload: Record<string, string>) => Promise<unknown>;
    }).createAccount({
      officeCode: "HB-JG",
      officeName: "河北分公司-建筑结构所",
      accountId: "new-user",
      displayName: "新账号",
      role: "设计人员",
      password: "password",
    });
    await (adapter as HttpAdapter & {
      updateAccount: (accountId: string, payload: Record<string, string>) => Promise<unknown>;
    }).updateAccount("existing-user", {
      displayName: "现有账号-更新",
      password: "new-password",
    });
    await (adapter as HttpAdapter & {
      patchAdminConfig: (payload: { archiveRootPath: string }) => Promise<unknown>;
    }).patchAdminConfig({
      archiveRootPath: "\\\\fileserver\\archive\\next",
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://127.0.0.1:8000/api/accounts");
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBe(
      JSON.stringify({
        office_code: "HB-JG",
        office_name: "河北分公司-建筑结构所",
        account_id: "new-user",
        display_name: "新账号",
        role: "设计人员",
        password: "password",
      }),
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe(
      "http://127.0.0.1:8000/api/accounts/existing-user",
    );
    expect(fetchMock.mock.calls[1]?.[1]?.body).toBe(
      JSON.stringify({
        display_name: "现有账号-更新",
        password: "new-password",
      }),
    );
    expect(fetchMock.mock.calls[2]?.[0]).toBe("http://127.0.0.1:8000/api/admin/config");
    expect(fetchMock.mock.calls[2]?.[1]?.body).toBe(
      JSON.stringify({
        archive_root_path: "\\\\fileserver\\archive\\next",
      }),
    );
  });

  it("repairs current workflow nodes with either replacement accounts or inline account creation", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({
        ok: true,
        text: async () => JSON.stringify({ ok: true }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/", {
      getAccessToken: () => "session-token",
    });

    await (adapter as HttpAdapter & {
      repairCurrentNode: (groupId: string, payload: Record<string, unknown>) => Promise<void>;
    }).repairCurrentNode("group-1", {
      replaceWithAccountId: "lisi",
    });
    await (adapter as HttpAdapter & {
      repairCurrentNode: (groupId: string, payload: Record<string, unknown>) => Promise<void>;
    }).repairCurrentNode("group-1", {
      createAccountPayload: {
        officeCode: "HB-JG",
        officeName: "河北分公司-建筑结构所",
        accountId: "repair-user",
        displayName: "修复账号",
        role: "设计人员",
        password: "password",
      },
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "http://127.0.0.1:8000/api/workflow/group-1/repair-current-node",
    );
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBe(
      JSON.stringify({
        replace_with_account_id: "lisi",
      }),
    );
    expect(fetchMock.mock.calls[1]?.[1]?.body).toBe(
      JSON.stringify({
        create_account_payload: {
          office_code: "HB-JG",
          office_name: "河北分公司-建筑结构所",
          account_id: "repair-user",
          display_name: "修复账号",
          role: "设计人员",
          password: "password",
        },
      }),
    );
  });

  it("lists task groups and loads task-group detail payloads", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            total: 1,
            items: [
              {
                group_id: "group-1",
                batch_id: "batch-1",
                project_no: "2026",
                status: "running",
                created_at: "2026-03-25T10:00:00+08:00",
                source_filenames: ["album-1.dwg"],
                owner_snapshot: {
                  creator_account: "zhangsan",
                  creator_name: "张三",
                  creator_role: "设计人员",
                  creator_office: "河北分公司-建筑结构所",
                  created_by_scope: "current_login_user",
                  submitted_at: null,
                },
                creator_name: "张三",
                creator_account: "zhangsan",
                creator_office: "河北分公司-建筑结构所",
                workflow_status: "in_review",
                current_node_key: "one_review",
                archive_status: "pending",
                workload: {
                  initial_workload_a1: 1.2,
                  final_workload_a1: 1.35,
                  one_review_factor: 1,
                  two_review_factor: 1,
                  three_review_factor: 1,
                  settlement_status: "pending",
                  settled_at: null,
                  contributor_entries: [],
                },
                effective_workload: 1.35,
                can_view_detail: true,
                can_submit: false,
                can_approve: true,
                is_related_to_current_user: true,
              },
            ],
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () =>
          JSON.stringify({
            group_id: "group-1",
            batch_id: "batch-1",
            project_no: "2026",
            status: "running",
            created_at: "2026-03-25T10:00:00+08:00",
            source_filenames: ["album-1.dwg"],
            owner_snapshot: {
              creator_account: "zhangsan",
              creator_name: "张三",
              creator_role: "设计人员",
              creator_office: "河北分公司-建筑结构所",
              created_by_scope: "current_login_user",
              submitted_at: null,
            },
            creator_name: "张三",
            creator_account: "zhangsan",
            creator_office: "河北分公司-建筑结构所",
            workflow_status: "in_review",
            current_node_key: "one_review",
            archive_status: "pending",
            workload: {
              initial_workload_a1: 1.2,
              final_workload_a1: 1.35,
              one_review_factor: 1,
              two_review_factor: 1,
              three_review_factor: 1,
              settlement_status: "pending",
              settled_at: null,
              contributor_entries: [],
            },
            effective_workload: 1.35,
            can_view_detail: true,
            can_submit: false,
            can_approve: true,
            is_related_to_current_user: true,
            child_job_ids: ["deliverable-1", "audit-1"],
            personnel_snapshot: {
              members: {
                ied_prepared_by: {
                  field_name: "ied_prepared_by",
                  raw_value: "张三",
                  normalized_value: "张三@zhangsan",
                  matched_account: "zhangsan",
                  matched_name: "张三",
                  match_strategy: "exact",
                  status: "matched",
                  errors: [],
                },
              },
            },
            workflow: {
              status: "submitted",
              initiated_at: "2026-03-25T10:05:00+08:00",
              initiated_by_account: "zhangsan",
              initiated_by_name: "张三",
              duplicate_policy: null,
              overwrite_archive_target: null,
              current_node_key: "one_review",
              nodes: [],
              archive_status: null,
              archive_retry_count: 0,
              archive_last_error: null,
              archive_last_attempt_at: null,
            },
            archive: {
              archive_root_path: "D:\\Archive",
              target_dir: "D:\\Archive\\2026\\album-1",
              status: "pending",
              overwrite_mode: null,
              started_at: null,
              completed_at: null,
              last_error: null,
              retry_count: 0,
              last_attempt_at: null,
              archived_files: [],
            },
            replacement: {
              album_internal_code: null,
              revision: null,
              replaced_group_id: null,
              replaced_record_pending_delete: false,
            },
            legacy_visibility: {
              scope: "owner_only",
              reason: null,
            },
          }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/", {
      getAccessToken: () => "session-token",
    });

    const list = await adapter.listTaskGroups();
    const detail = await adapter.getTaskGroupDetail("group-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/api/task-groups",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/api/task-groups/group-1",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
    const listHeaders = fetchMock.mock.calls[0]?.[1]?.headers as Headers;
    expect(listHeaders.get("Authorization")).toBe("Bearer session-token");
    expect(list.items[0]).toMatchObject({
      groupId: "group-1",
      sourceFilenames: ["album-1.dwg"],
      workflowStatus: "in_review",
      archiveStatus: "pending",
      effectiveWorkload: 1.35,
      canApprove: true,
    });
    expect(detail.childJobIds).toEqual(["deliverable-1", "audit-1"]);
    expect(detail.workflow.currentNodeKey).toBe("one_review");
    expect(detail.archive.targetDir).toBe("D:\\Archive\\2026\\album-1");
    expect(detail.personnelSnapshot.members.ied_prepared_by?.normalizedValue).toBe("张三@zhangsan");
  });

  it("submits and restart-submits task groups with explicit conflict flags", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({
        ok: true,
        text: async () =>
          JSON.stringify({
            group_id: "group-1",
            batch_id: "batch-1",
            project_no: "2026",
            status: "running",
            created_at: "2026-03-25T10:00:00+08:00",
            source_filenames: ["album-1.dwg"],
            owner_snapshot: null,
            creator_name: null,
            creator_account: null,
            creator_office: null,
            workflow_status: "submitted",
            current_node_key: "one_review",
            archive_status: "pending",
            workload: {
              initial_workload_a1: 1.2,
              final_workload_a1: 1.35,
              one_review_factor: 1,
              two_review_factor: 1,
              three_review_factor: 1,
              settlement_status: "pending",
              settled_at: null,
              contributor_entries: [],
            },
            effective_workload: 1.35,
            can_view_detail: true,
            can_submit: false,
            can_approve: false,
            is_related_to_current_user: true,
            child_job_ids: [],
            personnel_snapshot: {
              members: {},
            },
            workflow: {
              status: "submitted",
              initiated_at: "2026-03-25T10:05:00+08:00",
              initiated_by_account: "zhangsan",
              initiated_by_name: "张三",
              duplicate_policy: null,
              overwrite_archive_target: null,
              current_node_key: "one_review",
              nodes: [],
              archive_status: null,
              archive_retry_count: 0,
              archive_last_error: null,
              archive_last_attempt_at: null,
            },
            archive: {
              archive_root_path: "D:\\Archive",
              target_dir: "D:\\Archive\\2026\\album-1",
              status: "pending",
              overwrite_mode: null,
              started_at: null,
              completed_at: null,
              last_error: null,
              retry_count: 0,
              last_attempt_at: null,
              archived_files: [],
            },
            replacement: {
              album_internal_code: null,
              revision: null,
              replaced_group_id: null,
              replaced_record_pending_delete: false,
            },
            legacy_visibility: {
              scope: "owner_only",
              reason: null,
            },
          }),
      });
    vi.stubGlobal("fetch", fetchMock);

    const adapter = new HttpAdapter("http://127.0.0.1:8000/");

    await adapter.submitTaskGroup("group-1", {
      overwriteArchiveExisting: true,
      cancelExistingInProgress: false,
    });
    await adapter.restartSubmitTaskGroup("group-1", {
      overwriteArchiveExisting: false,
      cancelExistingInProgress: true,
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/api/task-groups/group-1/submit",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          overwrite_archive_existing: true,
          cancel_existing_in_progress: false,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/api/task-groups/group-1/restart-submit",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          overwrite_archive_existing: false,
          cancel_existing_in_progress: true,
        }),
      }),
    );
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

    const created = await adapter.createAuditCheck("2026", [file], "batch-shared-1");
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
      JSON.stringify({ project_no: "2026", batch_id: "batch-shared-1" }),
    );
    expect(formData.getAll("files[]")).toHaveLength(1);

    expect(created.jobs[0]?.taskKind).toBe("audit_check");
    expect(jobs.items[0]?.findingsCount).toBe(12);
    expect(jobs.items[0]?.affectedDrawingsCount).toBe(4);
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
      targetProjectNo: "2016",
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
        target_project_no: "2016",
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
      targetProjectNo: "2016",
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
        target_project_no: "2016",
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
      replacedStyleCount: 0,
      errors: [],
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
});
