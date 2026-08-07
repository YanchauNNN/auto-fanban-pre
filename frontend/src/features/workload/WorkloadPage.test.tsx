import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkloadPage } from "./WorkloadPage";
import type { TaskGroupSummary } from "../../platform/api/types";

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

function makeMonitorItem(overrides: Partial<TaskGroupSummary> = {}): TaskGroupSummary {
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
    submitBlockers: [],
    canApprove: true,
    isRelatedToCurrentUser: true,
    ...overrides,
  };
}

function makeFormSchema() {
  return {
    management: {
      account: {
        validRoles: ["设计人员", "管理员"],
        adminRoles: ["管理员"],
        adminCreatedDefaultPassword: "yaml-pass",
      },
      workflow: {
        terminalStatus: "three_review_approved",
        nodes: [
          {
            nodeKey: "one_review",
            nodeLabel: "一审",
            roleField: "ied_checked_by",
            factorKey: "one_review_factor",
          },
          {
            nodeKey: "two_review",
            nodeLabel: "二审",
            roleField: "ied_reviewed_by",
            factorKey: "two_review_factor",
          },
          {
            nodeKey: "three_review",
            nodeLabel: "三审",
            roleField: "ied_approved_by",
            factorKey: "three_review_factor",
          },
        ],
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
  mockGetFormSchema.mockResolvedValue(makeFormSchema());
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
    const factorInput = screen.getByLabelText("当前输入系数");
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

  it("shows exactly four decision metrics", async () => {
    renderWorkloadPage();

    const overview = await screen.findByRole("region", { name: "工作量概览" });
    expect(within(overview).getAllByTestId("workload-metric")).toHaveLength(4);
    expect(within(overview).getByText("待我审批")).toBeInTheDocument();
    expect(within(overview).getByText("流程中")).toBeInTheDocument();
    expect(within(overview).getByText("归档异常")).toBeInTheDocument();
    expect(within(overview).getByText("当前范围累计 A1")).toBeInTheDocument();
    expect(within(overview).queryByText("可见流程")).not.toBeInTheDocument();
    expect(within(overview).queryByText("历史记录")).not.toBeInTheDocument();
  });

  it("orders approvable, failed, related, and ordinary workflows for action", async () => {
    mockGetWorkflowMonitor.mockResolvedValue({
      total: 4,
      items: [
        makeMonitorItem({
          groupId: "ordinary",
          displayName: "普通流程",
          canApprove: false,
          isRelatedToCurrentUser: false,
        }),
        makeMonitorItem({
          groupId: "related",
          displayName: "相关流程",
          canApprove: false,
          isRelatedToCurrentUser: true,
        }),
        makeMonitorItem({
          groupId: "failed",
          displayName: "异常流程",
          canApprove: false,
          isRelatedToCurrentUser: false,
          archiveStatus: "failed",
        }),
        makeMonitorItem({ groupId: "approval", displayName: "待审批流程" }),
      ],
    });
    renderWorkloadPage();

    const monitor = await screen.findByRole("region", { name: "流程监控列表" });
    expect(within(monitor).getAllByTestId("workflow-item").map((item) => item.textContent)).toEqual([
      expect.stringContaining("待审批流程"),
      expect.stringContaining("异常流程"),
      expect.stringContaining("相关流程"),
      expect.stringContaining("普通流程"),
    ]);
  });

  it("renders custom workflow nodes in schema order and marks the current step", async () => {
    mockGetWorkflowMonitor.mockResolvedValue({
      total: 1,
      items: [makeMonitorItem({ currentNodeKey: "chief_review" })],
    });
    const schema = makeFormSchema();
    mockGetFormSchema.mockResolvedValue({
      management: {
        ...schema.management,
        workflow: {
          ...schema.management.workflow,
          nodes: [
            {
              nodeKey: "quality_gate",
              nodeLabel: "质量复核",
              roleField: "ied_reviewed_by",
              factorKey: "quality_gate_factor",
            },
            {
              nodeKey: "chief_review",
              nodeLabel: "总师审定",
              roleField: "ied_approved_by",
              factorKey: "chief_review_factor",
            },
          ],
          nodeLabels: { quality_gate: "质量复核", chief_review: "总师审定" },
        },
      },
    });

    renderWorkloadPage();

    const rail = await screen.findByRole("list", { name: "任务流程" });
    expect(within(rail).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      expect.stringContaining("质量复核"),
      expect.stringContaining("总师审定"),
      expect.stringContaining("归档"),
    ]);
    expect(within(rail).getAllByRole("listitem")[1]).toHaveAttribute("aria-current", "step");
  });

  it("previews final A1 live and keeps the custom node key on approval", async () => {
    const user = userEvent.setup();
    mockGetWorkflowMonitor.mockResolvedValue({
      total: 1,
      items: [
        makeMonitorItem({
          currentNodeKey: "quality_gate",
          effectiveWorkload: 1.65,
          workload: {
            ...makeMonitorItem().workload,
            initialWorkloadA1: 1.5,
            finalWorkloadA1: 1.65,
            nodeFactors: { precheck: 1.1 },
          },
        }),
      ],
    });
    renderWorkloadPage();

    const trigger = await screen.findByRole("button", { name: "审批" });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "审批当前节点" });
    expect(within(dialog).getByText("1.50 A1")).toBeInTheDocument();
    expect(within(dialog).getByText("1.10")).toBeInTheDocument();
    const factorInput = within(dialog).getByLabelText("当前输入系数");
    expect(factorInput).toHaveFocus();
    await user.clear(factorInput);
    await user.type(factorInput, "1.20");
    expect(within(dialog).getByText("1.98 A1")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "确认审批" }));

    await waitFor(() => {
      expect(mockApproveWorkflow).toHaveBeenCalledWith("group-1", {
        factor: 1.2,
        nodeKey: "quality_gate",
      });
    });
  });

  it("shows natural language roles and settlement states in the ledger", async () => {
    renderWorkloadPage();

    const ledger = await screen.findByRole("region", { name: "工作量记录" });
    expect(within(ledger).getByText("发起人")).toBeInTheDocument();
    expect(within(ledger).getByText("已结算")).toBeInTheDocument();
    expect(within(ledger).queryByText("initiator")).not.toBeInTheDocument();
    expect(within(ledger).queryByText("settled")).not.toBeInTheDocument();
    expect(ledger).toHaveAttribute("tabindex", "0");
    expect(await screen.findByRole("region", { name: "流程监控列表" })).toHaveAttribute(
      "tabindex",
      "0",
    );
  });

  it("exposes loading and error feedback with status semantics", async () => {
    mockGetWorkflowMonitor.mockImplementation(() => new Promise(() => undefined));
    const { unmount } = renderWorkloadPage();
    expect(await screen.findByRole("status", { name: "正在加载流程监控" })).toBeInTheDocument();
    unmount();

    mockGetWorkflowMonitor.mockRejectedValue(new Error("network"));
    renderWorkloadPage();
    expect(await screen.findByRole("alert", { name: "流程监控加载失败" })).toBeInTheDocument();
  });

  it("closes approval and repair dialogs with Escape and restores trigger focus", async () => {
    const user = userEvent.setup();
    renderWorkloadPage();

    const approvalTrigger = await screen.findByRole("button", { name: "审批" });
    await user.click(approvalTrigger);
    expect(screen.getByRole("dialog", { name: "审批当前节点" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "审批当前节点" })).not.toBeInTheDocument();
    expect(approvalTrigger).toHaveFocus();

    const repairTrigger = screen.getByRole("button", { name: "修复当前节点" });
    await user.click(repairTrigger);
    expect(screen.getByRole("dialog", { name: "修复当前节点" })).toBeInTheDocument();
    expect(screen.getByLabelText("替换账号")).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "修复当前节点" })).not.toBeInTheDocument();
    expect(repairTrigger).toHaveFocus();
  });
});
