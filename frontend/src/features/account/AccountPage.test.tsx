import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccountPage } from "./AccountPage";

const mockGetWorkloadMe = vi.fn();
const mockChangePassword = vi.fn();
const mockRefreshCurrentAccount = vi.fn();
const mockOpenWorkload = vi.fn();

vi.mock("../../platform/api/useApiAdapter", () => ({
  useApiAdapter: () => ({
    getWorkloadMe: mockGetWorkloadMe,
    changePassword: mockChangePassword,
  }),
}));

vi.mock("../../shared/session/SessionContext", () => ({
  useSession: () => ({
    currentAccount: {
      accountId: "wangdd",
      displayName: "王丹丹",
      role: "管理员",
      officeCode: "25C0",
      officeName: "建筑结构所",
      pendingTodoCount: 2,
    },
    refreshCurrentAccount: mockRefreshCurrentAccount,
  }),
}));

function renderAccountPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AccountPage onOpenWorkload={mockOpenWorkload} />
    </QueryClientProvider>,
  );
}

function makeWorkloadResponse() {
  return {
    scope: "me",
    filters: { startDate: null, endDate: null, status: null, validOnly: false },
    officeName: null,
    totalWorkloadA1: 3.5,
    totalsByAccount: {},
    entries: [
      {
        groupId: "group-1",
        groupDisplayName: "2016-JG001",
        albumInternalCode: "2016-JG001",
        roleKey: "initiator",
        accountId: "wangdd",
        displayName: "王丹丹",
        workloadA1: 3.5,
        settledAt: "2026-05-29T14:00:00+08:00",
        settlementStatus: "settled",
      },
    ],
  };
}

beforeEach(() => {
  mockGetWorkloadMe.mockReset();
  mockChangePassword.mockReset();
  mockRefreshCurrentAccount.mockReset();
  mockOpenWorkload.mockReset();

  mockGetWorkloadMe.mockResolvedValue(makeWorkloadResponse());
  mockChangePassword.mockResolvedValue({
    accountId: "wangdd",
    displayName: "王丹丹",
    role: "管理员",
    officeCode: "25C0",
    officeName: "建筑结构所",
    pendingTodoCount: 2,
  });
  mockRefreshCurrentAccount.mockResolvedValue(null);
});

describe("AccountPage", () => {
  it("organizes identity, security, and recent settlements into three semantic regions", async () => {
    renderAccountPage();

    const identity = screen.getByRole("region", { name: "身份摘要" });
    expect(within(identity).getByText("王丹丹")).toBeInTheDocument();
    expect(within(identity).getByText("wangdd")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "安全操作" })).toBeInTheDocument();

    const settlements = screen.getByRole("region", { name: "最近结算" });
    expect(await within(settlements).findByText("2016-JG001")).toBeInTheDocument();
    expect(within(settlements).getByText("发起人")).toBeInTheDocument();
    expect(within(settlements).getByText("已结算")).toBeInTheDocument();
    expect(within(settlements).queryByText("initiator")).not.toBeInTheDocument();
    expect(within(settlements).queryByText("settled")).not.toBeInTheDocument();
  });

  it("opens the workload module from the pending-work button", async () => {
    const user = userEvent.setup();
    renderAccountPage();

    await user.click(screen.getByRole("button", { name: "查看 2 项待办" }));

    expect(mockOpenWorkload).toHaveBeenCalledTimes(1);
  });

  it("keeps passwords masked and does not submit mismatched confirmation", async () => {
    const user = userEvent.setup();
    renderAccountPage();

    const password = screen.getByLabelText("新密码");
    const confirmation = screen.getByLabelText("确认新密码");
    expect(password).toHaveAttribute("type", "password");
    expect(confirmation).toHaveAttribute("type", "password");

    await user.type(password, "new-password");
    await user.type(confirmation, "different-password");

    expect(screen.getByText("两次输入的密码不一致。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "更新密码" })).toBeDisabled();
    expect(mockChangePassword).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "显示密码" }));
    expect(password).toHaveAttribute("type", "text");
    expect(confirmation).toHaveAttribute("type", "text");
  });

  it("submits only after the two password fields match", async () => {
    const user = userEvent.setup();
    renderAccountPage();

    await user.type(screen.getByLabelText("新密码"), "new-password");
    await user.type(screen.getByLabelText("确认新密码"), "new-password");
    await user.click(screen.getByRole("button", { name: "更新密码" }));

    await waitFor(() => {
      expect(mockChangePassword).toHaveBeenCalledWith("new-password");
    });
    expect(mockRefreshCurrentAccount).toHaveBeenCalledTimes(1);
  });

  it("announces workload loading and error states", async () => {
    let rejectWorkload: (error: Error) => void = () => undefined;
    mockGetWorkloadMe.mockReturnValue(
      new Promise((_, reject) => {
        rejectWorkload = reject;
      }),
    );
    renderAccountPage();

    expect(screen.getByRole("status", { name: "正在加载最近结算" })).toBeInTheDocument();
    rejectWorkload(new Error("offline"));

    expect(
      await screen.findByRole("alert", { name: "最近结算加载失败" }),
    ).toBeInTheDocument();
  });
});
