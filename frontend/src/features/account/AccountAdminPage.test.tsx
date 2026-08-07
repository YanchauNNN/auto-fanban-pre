import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
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
  const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");

  const rendered = render(
    <QueryClientProvider client={queryClient}>
      <AccountAdminPage />
    </QueryClientProvider>,
  );
  return { ...rendered, invalidateQueries };
}

function makeInvalidRow() {
  return {
    rowNumber: 4,
    raw: {
      科室编码: "25C1",
      科室: "结构一室",
      账号: "bad-role",
      姓名: "坏角色",
      角色: "未知角色",
      密码: "legacy-secret",
    },
    errors: ["invalid_role"],
  };
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
    items: [
      {
        officeCode: "25C0",
        officeName: "建筑结构所",
        accountId: "wangdd",
        displayName: "王丹丹",
        role: "管理员",
        password: "server-secret",
        valid: true,
        rowNumber: 2,
        errors: [],
      },
      {
        officeCode: "25C1",
        officeName: "结构一室",
        accountId: "xuexh",
        displayName: "薛晓航",
        role: "设计人员",
        password: "server-secret",
        valid: true,
        rowNumber: 3,
        errors: [],
      },
    ],
  });
  mockListInvalidAccountRows.mockResolvedValue({ items: [makeInvalidRow()] });
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
        validRoles: ["设计人员", "管理员"],
        adminRoles: ["管理员"],
        adminCreatedDefaultPassword: "yaml-pass",
      },
      workflow: {
        terminalStatus: "three_review_approved",
        statusLabels: {},
        nodeLabels: {},
        emptyCurrentNodeLabel: "",
        factor: { default: 1, min: 0.8, max: 1.1, precision: 2 },
      },
      workload: {
        settlementTrigger: "archive_success",
        scopeRoles: {},
        scopeLabels: {},
        statusOptions: [],
      },
      archive: { statusLabels: {} },
    },
  });
  mockCreateAccount.mockResolvedValue({
    officeCode: "25C2",
    officeName: "结构二室",
    accountId: "new-user",
    displayName: "新用户",
    role: "设计人员",
    password: "new-secret",
    valid: true,
    rowNumber: 5,
    errors: [],
  });
  mockUpdateAccount.mockResolvedValue({
    officeCode: "25C0",
    officeName: "建筑结构所",
    accountId: "wangdd",
    displayName: "王丹丹",
    role: "管理员",
    password: "server-secret",
    valid: true,
    rowNumber: 2,
    errors: [],
  });
  mockUpdateAccountRow.mockResolvedValue({
    officeCode: "25C1",
    officeName: "结构一室",
    accountId: "bad-role",
    displayName: "坏角色",
    role: "设计人员",
    password: "legacy-secret",
    valid: true,
    rowNumber: 4,
    errors: [],
  });
  mockPatchAdminConfig.mockResolvedValue({ archiveRootPath: "E:\\archive" });
  mockRefreshCurrentAccount.mockResolvedValue(null);
});

describe("AccountAdminPage", () => {
  it("keeps archive configuration, account directory, and editor visible together", async () => {
    renderAccountAdminPage();

    expect(await screen.findByRole("heading", { name: "账号管理" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "归档配置" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "账号目录" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "账号编辑器" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "无效 1" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("filters the already-loaded directory by account, name, office, and role without refetching", async () => {
    const user = userEvent.setup();
    renderAccountAdminPage();
    const directory = await screen.findByRole("region", { name: "账号目录" });
    const search = within(directory).getByRole("searchbox", { name: "搜索账号" });

    expect(within(directory).getByRole("button", { name: /王丹丹/ })).toBeInTheDocument();
    expect(within(directory).getByRole("button", { name: /薛晓航/ })).toBeInTheDocument();

    for (const query of ["xuexh", "薛晓航", "结构一室", "设计人员"]) {
      await user.clear(search);
      await user.type(search, query);
      expect(within(directory).getByRole("button", { name: /薛晓航/ })).toBeInTheDocument();
      expect(within(directory).queryByRole("button", { name: /王丹丹/ })).not.toBeInTheDocument();
    }
    expect(mockListAccounts).toHaveBeenCalledTimes(1);
    expect(mockListInvalidAccountRows).toHaveBeenCalledTimes(1);
  });

  it("selects an active account for editing without exposing its stored password", async () => {
    const user = userEvent.setup();
    renderAccountAdminPage();
    const directory = await screen.findByRole("region", { name: "账号目录" });

    await user.click(within(directory).getByRole("button", { name: /王丹丹/ }));

    expect(screen.getByRole("heading", { name: "编辑账号" })).toBeInTheDocument();
    expect(screen.getByLabelText("账号")).toHaveValue("wangdd");
    expect(screen.getByLabelText("新密码（可选）")).toHaveValue("");
    expect(screen.getByLabelText("新密码（可选）")).toHaveAttribute("type", "password");
    expect(screen.queryByDisplayValue("server-secret")).not.toBeInTheDocument();
    expect(screen.getByText("留空则保持原密码不变。")).toBeInTheDocument();
  });

  it("keeps invalid rows visible and opens the selected row in repair mode", async () => {
    const user = userEvent.setup();
    renderAccountAdminPage();
    const directory = await screen.findByRole("region", { name: "账号目录" });

    await user.click(within(directory).getByRole("button", { name: "无效 1" }));
    await user.click(within(directory).getByRole("button", { name: /第 4 行/ }));

    expect(screen.getByRole("heading", { name: "修复账号行" })).toBeInTheDocument();
    expect(screen.getByLabelText("账号")).toHaveValue("bad-role");
    expect(screen.getByLabelText("密码（可选）")).toHaveValue("");
    expect(screen.queryByDisplayValue("legacy-secret")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("角色"), "设计人员");
    await user.click(screen.getByRole("button", { name: "保存并修复" }));

    await waitFor(() => {
      expect(mockUpdateAccountRow).toHaveBeenCalledWith(4, {
        officeCode: "25C1",
        officeName: "结构一室",
        accountId: "bad-role",
        displayName: "坏角色",
        role: "设计人员",
      });
    });
  });

  it("requires a matching password confirmation when creating an account", async () => {
    const user = userEvent.setup();
    renderAccountAdminPage();
    await screen.findByRole("heading", { name: "创建账号" });

    await user.type(screen.getByLabelText("账号"), "new-user");
    await user.type(screen.getByLabelText("姓名"), "新用户");
    await user.type(screen.getByLabelText("密码"), "new-secret");
    await user.type(screen.getByLabelText("确认密码"), "wrong-secret");
    expect(screen.getByRole("button", { name: "创建账号" })).toBeDisabled();
    expect(mockCreateAccount).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("确认密码"));
    await user.type(screen.getByLabelText("确认密码"), "new-secret");
    await user.click(screen.getByRole("button", { name: "创建账号" }));

    await waitFor(() => {
      expect(mockCreateAccount).toHaveBeenCalledWith({
        officeCode: null,
        officeName: null,
        accountId: "new-user",
        displayName: "新用户",
        role: "设计人员",
        password: "new-secret",
      });
    });
    expect(await screen.findByRole("status")).toHaveTextContent("账号已创建。");
  });

  it("preserves query invalidation after updating an account", async () => {
    const user = userEvent.setup();
    const { invalidateQueries } = renderAccountAdminPage();
    const directory = await screen.findByRole("region", { name: "账号目录" });
    await user.click(within(directory).getByRole("button", { name: /王丹丹/ }));
    await user.clear(screen.getByLabelText("姓名"));
    await user.type(screen.getByLabelText("姓名"), "王丹");
    await user.click(screen.getByRole("button", { name: "保存修改" }));

    await waitFor(() => {
      expect(mockUpdateAccount).toHaveBeenCalledWith("wangdd", {
        officeCode: "25C0",
        officeName: "建筑结构所",
        accountId: "wangdd",
        displayName: "王丹",
        role: "管理员",
      });
    });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["accounts"] });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["invalid-account-rows"] });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["task-groups"] });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["workflow", "monitor"] });
  });

  it("saves archive configuration from the compact system strip", async () => {
    const user = userEvent.setup();
    renderAccountAdminPage();
    const archive = await screen.findByRole("region", { name: "归档配置" });
    const input = within(archive).getByLabelText("归档根路径");

    await user.clear(input);
    await user.type(input, "E:\\archive");
    await user.click(within(archive).getByRole("button", { name: "保存归档配置" }));

    await waitFor(() => {
      expect(mockPatchAdminConfig).toHaveBeenCalledWith({ archiveRootPath: "E:\\archive" });
    });
  });
});
