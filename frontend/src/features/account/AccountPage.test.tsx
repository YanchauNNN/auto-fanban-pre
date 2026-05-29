import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccountPage } from "./AccountPage";

const mockGetWorkloadMe = vi.fn();
const mockChangePassword = vi.fn();
const mockRefreshCurrentAccount = vi.fn();

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
      <AccountPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockGetWorkloadMe.mockReset();
  mockChangePassword.mockReset();
  mockRefreshCurrentAccount.mockReset();

  mockGetWorkloadMe.mockResolvedValue({
    scope: "me",
    filters: { startDate: null, endDate: null, status: null, validOnly: false },
    officeName: null,
    totalWorkloadA1: 3.5,
    totalsByAccount: {},
    entries: [
      {
        groupId: "group-1",
        roleKey: "initiator",
        accountId: "wangdd",
        displayName: "王丹丹",
        workloadA1: 3.5,
        settledAt: "2026-05-29T14:00:00+08:00",
        settlementStatus: "settled",
      },
    ],
  });
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
  it("renders identity fields and personal workload summary", async () => {
    renderAccountPage();

    expect(screen.getByRole("heading", { name: "账号模块" })).toBeInTheDocument();
    expect(screen.getByText("王丹丹")).toBeInTheDocument();
    expect(screen.getByText("wangdd")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getAllByText("3.50").length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.getByText("group-1")).toBeInTheDocument();
  });

  it("changes the current user's password", async () => {
    const user = userEvent.setup();
    renderAccountPage();

    await user.type(screen.getByLabelText("新密码"), "new-password");
    await user.click(screen.getByRole("button", { name: "更新密码" }));

    await waitFor(() => {
      expect(mockChangePassword).toHaveBeenCalledWith("new-password");
    });
    expect(mockRefreshCurrentAccount).toHaveBeenCalled();
  });
});
