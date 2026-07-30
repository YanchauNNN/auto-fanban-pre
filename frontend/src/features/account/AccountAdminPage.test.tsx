import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccountAdminPage } from "./AccountAdminPage";

const mockListAccounts = vi.fn();
const mockListInvalidAccountRows = vi.fn();
const mockGetAdminConfig = vi.fn();
const mockGetFormSchema = vi.fn();
const mockCreateAccount = vi.fn();
const mockUpdateAccount = vi.fn();
const mockUpdateAccountRow = vi.fn();
const mockPatchAdminConfig = vi.fn();
const mockRefreshCurrentAccount = vi.fn();

vi.mock("../../platform/api/useApiAdapter", () => ({
  useApiAdapter: () => ({
    listAccounts: mockListAccounts,
    listInvalidAccountRows: mockListInvalidAccountRows,
    getAdminConfig: mockGetAdminConfig,
    getFormSchema: mockGetFormSchema,
    createAccount: mockCreateAccount,
    updateAccount: mockUpdateAccount,
    updateAccountRow: mockUpdateAccountRow,
    patchAdminConfig: mockPatchAdminConfig,
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
      pendingTodoCount: 0,
    },
    refreshCurrentAccount: mockRefreshCurrentAccount,
  }),
}));

function renderAccountAdminPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AccountAdminPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockListAccounts.mockReset();
  mockListInvalidAccountRows.mockReset();
  mockGetAdminConfig.mockReset();
  mockGetFormSchema.mockReset();
  mockCreateAccount.mockReset();
  mockUpdateAccount.mockReset();
  mockUpdateAccountRow.mockReset();
  mockPatchAdminConfig.mockReset();
  mockRefreshCurrentAccount.mockReset();

  mockListAccounts.mockResolvedValue({
    total: 2,
    items: [
      {
        officeCode: "25C0",
        officeName: "建筑结构所",
        accountId: "wangdd",
        displayName: "王丹丹",
        role: "管理员",
        password: "password",
      },
      {
        officeCode: "25C1",
        officeName: "结构一室",
        accountId: "xuexh",
        displayName: "薛晓航",
        role: "设计人员",
        password: "password",
      },
    ],
  });
  mockListInvalidAccountRows.mockResolvedValue({ total: 0, items: [] });
  mockGetAdminConfig.mockResolvedValue({ archiveRootPath: "D:\\FanBanServer\\archive" });
  mockGetFormSchema.mockResolvedValue({
    management: {
      account: {
        fieldMap: {
          officeCode: "科室编码",
          officeName: "科室",
          accountId: "账号",
          displayName: "姓名",
          role: "角色",
          password: "密码",
        },
        validRoles: ["yaml-designer", "yaml-admin"],
        adminRoles: ["yaml-admin"],
        adminCreatedDefaultPassword: "yaml-pass",
      },
      workflow: {
        terminalStatus: "three_review_approved",
        statusLabels: {},
        nodeLabels: {},
        emptyCurrentNodeLabel: "",
        factor: {
          default: 1,
          min: 0.8,
          max: 1.1,
          precision: 2,
        },
      },
      workload: {
        settlementTrigger: "archive_success",
        scopeRoles: {},
        scopeLabels: {},
        statusOptions: [],
      },
      archive: {
        statusLabels: {},
      },
    },
  });
  mockCreateAccount.mockResolvedValue({
    officeCode: "25C2",
    officeName: "结构二室",
    accountId: "new-user",
    displayName: "新用户",
    role: "设计人员",
    password: "password",
  });
  mockUpdateAccount.mockResolvedValue({
    officeCode: "25C0",
    officeName: "建筑结构所",
    accountId: "wangdd",
    displayName: "王丹丹",
    role: "管理员",
    password: "password",
  });
  mockUpdateAccountRow.mockResolvedValue({
    officeCode: "25C1",
    officeName: "结构一室",
    accountId: "bad-role",
    displayName: "坏角色",
    role: "yaml-designer",
    password: "password",
  });
  mockPatchAdminConfig.mockResolvedValue({ archiveRootPath: "E:\\archive" });
  mockRefreshCurrentAccount.mockResolvedValue(null);
});

describe("AccountAdminPage", () => {
  it("renders account counts, invalid row state, and archive config", async () => {
    renderAccountAdminPage();

    expect(await screen.findByRole("heading", { name: "管理员配置" })).toBeInTheDocument();
    expect(screen.getByText("2 个账号")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /无效账号行/ })).toBeInTheDocument();
    expect(screen.getByDisplayValue("D:\\FanBanServer\\archive")).toBeInTheDocument();
  });

  it("opens the account list and switches selected account into edit mode", async () => {
    const user = userEvent.setup();
    renderAccountAdminPage();

    await user.click(await screen.findByRole("button", { name: "打开账号列表" }));
    expect(screen.getByRole("dialog", { name: "现有账号列表" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "编辑 wangdd" }));

    expect(screen.getByRole("heading", { name: "编辑账号" })).toBeInTheDocument();
    expect(screen.getByLabelText("账号")).toHaveValue("wangdd");
    expect(screen.getByLabelText("姓名")).toHaveValue("王丹丹");
  });

  it("creates a new account through the admin form", async () => {
    const user = userEvent.setup();
    renderAccountAdminPage();

    await screen.findByRole("heading", { name: "管理员配置" });
    await user.type(screen.getByLabelText("账号"), "new-user");
    await user.type(screen.getByLabelText("姓名"), "新用户");
    await user.clear(screen.getByLabelText("科室编码"));
    await user.type(screen.getByLabelText("科室编码"), "25C2");
    await user.clear(screen.getByLabelText("科室"));
    await user.type(screen.getByLabelText("科室"), "结构二室");
    await user.click(screen.getByRole("button", { name: "创建账号" }));

    await waitFor(() => {
      expect(mockCreateAccount).toHaveBeenCalledWith({
        officeCode: "25C2",
        officeName: "结构二室",
        accountId: "new-user",
        displayName: "新用户",
        role: "yaml-designer",
        password: "yaml-pass",
      });
    });
    expect(mockRefreshCurrentAccount).toHaveBeenCalled();
  });

  it("opens invalid rows as a compact tab and edits the selected CSV row", async () => {
    const user = userEvent.setup();
    mockListInvalidAccountRows.mockResolvedValue({
      total: 1,
      items: [
        {
          rowNumber: 4,
          raw: {
            科室编码: "25C1",
            科室: "结构一室",
            账号: "bad-role",
            姓名: "坏角色",
            角色: "未知角色",
            密码: "password",
          },
          errors: ["invalid_role"],
        },
      ],
    });
    renderAccountAdminPage();

    await user.click(await screen.findByRole("button", { name: /无效账号行/ }));
    expect(screen.getByRole("dialog", { name: "无效账号行" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "编辑此行" }));

    expect(screen.getByRole("heading", { name: "修复账号行" })).toBeInTheDocument();
    expect(screen.getByLabelText("账号")).toHaveValue("bad-role");
    await user.click(screen.getByRole("button", { name: "保存并修复此行" }));

    await waitFor(() => {
      expect(mockUpdateAccountRow).toHaveBeenCalledWith(4, {
        officeCode: "25C1",
        officeName: "结构一室",
        accountId: "bad-role",
        displayName: "坏角色",
        role: "yaml-designer",
        password: "password",
      });
    });
  });
});
