import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkloadPage } from "./WorkloadPage";

const mockGetWorkflowMonitor = vi.fn();
const mockGetWorkloadMe = vi.fn();
const mockGetWorkloadOffice = vi.fn();
const mockGetWorkloadInstitute = vi.fn();
const mockGetWorkloadAdmin = vi.fn();
const mockApproveWorkflow = vi.fn();
const mockRepairCurrentNode = vi.fn();
const mockListAccounts = vi.fn();
const mockGetFormSchema = vi.fn();
const mockRefreshCurrentAccount = vi.fn();

vi.mock("../../platform/api/useApiAdapter", () => ({
  useApiAdapter: () => ({
    getWorkflowMonitor: mockGetWorkflowMonitor,
    getWorkloadMe: mockGetWorkloadMe,
    getWorkloadOffice: mockGetWorkloadOffice,
    getWorkloadInstitute: mockGetWorkloadInstitute,
    getWorkloadAdmin: mockGetWorkloadAdmin,
    approveWorkflow: mockApproveWorkflow,
    repairCurrentNode: mockRepairCurrentNode,
    listAccounts: mockListAccounts,
    getFormSchema: mockGetFormSchema,
  }),
}));

vi.mock("../../shared/session/SessionContext", () => ({
  useSession: () => ({
    currentAccount: {
      accountId: "hbjjswd",
      displayName: "河北建筑结构所文",
      role: "管理员",
      officeCode: "25C0",
      officeName: "建筑结构所",
      pendingTodoCount: 1,
    },
    refreshCurrentAccount: mockRefreshCurrentAccount,
  }),
}));

function renderWorkloadPage(initialRoute = "/?scope=admin") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <WorkloadPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeMonitorItem() {
  return {
    groupId: "group-1",
    displayName: "2016-JG001",
    albumInternalCode: "2016-JG001",
    batchId: "batch-1",
    projectNo: "2016",
    status: "running",
    createdAt: "2026-05-29T10:00:00+08:00",
    sourceFilenames: ["workflow.dwg"],
    ownerSnapshot: null,
    creatorName: "曾添君",
    creatorAccount: "zengtj",
    creatorOffice: "建筑结构所",
    workflowStatus: "in_review",
    currentNodeKey: "one_review",
    archiveStatus: "pending",
    workload: {
      initialWorkloadA1: 1.5,
      finalWorkloadA1: 1.5,
      oneReviewFactor: 1,
      twoReviewFactor: 1,
      threeReviewFactor: 1,
      nodeFactors: {},
      settlementStatus: "pending",
      settledAt: null,
      contributorEntries: [],
    },
    effectiveWorkload: 1.5,
    canViewDetail: true,
    canSubmit: false,
    canApprove: true,
    isRelatedToCurrentUser: true,
  };
}

beforeEach(() => {
  mockGetWorkflowMonitor.mockReset();
  mockGetWorkloadMe.mockReset();
  mockGetWorkloadOffice.mockReset();
  mockGetWorkloadInstitute.mockReset();
  mockGetWorkloadAdmin.mockReset();
  mockApproveWorkflow.mockReset();
  mockRepairCurrentNode.mockReset();
  mockListAccounts.mockReset();
  mockGetFormSchema.mockReset();
  mockRefreshCurrentAccount.mockReset();

  mockGetWorkflowMonitor.mockResolvedValue({ total: 1, items: [makeMonitorItem()] });
  mockGetWorkloadAdmin.mockResolvedValue({
    scope: "admin",
    filters: { startDate: null, endDate: null, status: null, validOnly: false },
    officeName: null,
    totalWorkloadA1: 2.84,
    totalsByAccount: { zengtj: 1.42, hbjjswd: 1.42 },
    entries: [
      {
        groupId: "group-1",
        groupDisplayName: "2016-JG001",
        albumInternalCode: "2016-JG001",
        roleKey: "initiator",
        accountId: "zengtj",
        displayName: "曾添君",
        workloadA1: 1.42,
        settledAt: "2026-05-29T14:27:15+08:00",
        settlementStatus: "settled",
      },
    ],
  });
  mockGetWorkloadMe.mockResolvedValue({
    scope: "me",
    filters: { startDate: null, endDate: null, status: null, validOnly: false },
    officeName: null,
    totalWorkloadA1: 0,
    totalsByAccount: {},
    entries: [],
  });
  mockGetWorkloadOffice.mockResolvedValue({
    scope: "office",
    filters: { startDate: null, endDate: null, status: null, validOnly: false },
    officeName: "建筑结构所",
    totalWorkloadA1: 0,
    totalsByAccount: {},
    entries: [],
  });
  mockGetWorkloadInstitute.mockResolvedValue({
    scope: "institute",
    filters: { startDate: null, endDate: null, status: null, validOnly: false },
    officeName: null,
    totalWorkloadA1: 0,
    totalsByAccount: {},
    entries: [],
  });
  mockApproveWorkflow.mockResolvedValue(undefined);
  mockRepairCurrentNode.mockResolvedValue(undefined);
  mockListAccounts.mockResolvedValue({ total: 0, items: [] });
  mockGetFormSchema.mockResolvedValue({
    management: {
      account: {
        validRoles: ["设计人员", "管理员"],
        adminRoles: ["管理员"],
        adminCreatedDefaultPassword: "yaml-pass",
      },
      workflow: {
        terminalStatus: "three_review_approved",
        statusLabels: {
          in_review: "审批中",
          three_review_approved: "三审通过",
        },
        nodeLabels: {
          one_review: "一审",
          two_review: "二审",
          three_review: "三审",
        },
        emptyCurrentNodeLabel: "未进入审批",
        factor: {
          default: 1.15,
          min: 0.5,
          max: 1.3,
          precision: 2,
        },
      },
      workload: {
        settlementTrigger: "archive_success",
        scopeRoles: {
          office: ["管理员"],
          institute: ["管理员"],
          admin: ["管理员"],
        },
        scopeLabels: {
          me: "个人",
          office: "科室",
          institute: "全所",
          admin: "YAML 管理视图",
        },
        statusOptions: [
          { label: "全部", value: "" },
          { label: "已归档结算", value: "settled" },
        ],
      },
      archive: {
        statusLabels: {
          pending: "待归档",
          succeeded: "已归档",
          failed: "归档失败",
        },
      },
    },
  });
  mockRefreshCurrentAccount.mockResolvedValue(null);
});

describe("WorkloadPage", () => {
  it("loads monitor cards and admin workload statistics directly", async () => {
    renderWorkloadPage();

    expect(await screen.findByRole("heading", { name: "工作量模块" })).toBeInTheDocument();
    expect(await screen.findAllByText("2016-JG001")).toHaveLength(2);
    expect(screen.queryByText("group-1")).not.toBeInTheDocument();
    expect(screen.getByText("2.84")).toBeInTheDocument();
    expect(screen.getAllByText("曾添君").length).toBeGreaterThanOrEqual(1);

    expect(mockGetWorkflowMonitor).toHaveBeenCalledTimes(1);
    expect(mockGetWorkloadAdmin).toHaveBeenCalledTimes(1);
  });

  it("submits approval with the current node key and refreshes workflow views", async () => {
    const user = userEvent.setup();
    renderWorkloadPage();

    await user.click(await screen.findByRole("button", { name: "审批" }));
    const factorInput = screen.getByLabelText("审批系数");
    await user.clear(factorInput);
    await user.type(factorInput, "1.20");
    await user.click(screen.getByRole("button", { name: "确认审批" }));

    await waitFor(() => {
      expect(mockApproveWorkflow).toHaveBeenCalledWith("group-1", {
        factor: 1.2,
        nodeKey: "one_review",
      });
    });
    expect(mockRefreshCurrentAccount).toHaveBeenCalled();
  });
});
