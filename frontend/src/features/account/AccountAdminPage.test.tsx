import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
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
        adminCreatedDefaultPasswordConfigured: true,
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
    valid: true,
    rowNumber: 4,
    errors: [],
  });
  mockPatchAdminConfig.mockResolvedValue({ archiveRootPath: "E:\\archive" });
  mockRefreshCurrentAccount.mockResolvedValue(null);
});

describe("AccountAdminPage", () => {
  it("keeps archive configuration, account directory, and editor visible together", async () => {
    const { container } = renderAccountAdminPage();

    expect(container.firstElementChild?.tagName).toBe("SECTION");
    expect(await screen.findByRole("heading", { name: "账号管理" })).toBeInTheDocument();
    expect(screen.getByText("账号与权限")).toBeInTheDocument();
    expect(screen.queryByText("Account Administration")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "归档配置" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "账号目录" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "账号编辑器" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "无效 1" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText("yaml-pass")).not.toBeInTheDocument();
    expect(screen.getByText("系统默认密码策略已配置，创建时仍需显式填写密码。")).toBeInTheDocument();
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

  it("disables related writes and announces failures when config or schema cannot load", async () => {
    mockGetAdminConfig.mockRejectedValueOnce(new Error("private archive error"));
    mockGetFormSchema.mockRejectedValueOnce(new Error("private schema error"));
    renderAccountAdminPage();

    expect(
      await screen.findByText("归档配置加载失败，已停用保存，避免覆盖现有配置。"),
    ).toHaveAttribute("role", "alert");
    expect(
      screen.getByText("账号规则加载失败，已停用账号保存，避免提交无效配置。"),
    ).toHaveAttribute("role", "alert");
    expect(screen.getByRole("button", { name: "保存归档配置" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "创建账号" })).toBeDisabled();
    expect(screen.queryByText(/private archive error|private schema error/)).not.toBeInTheDocument();
    expect(mockPatchAdminConfig).not.toHaveBeenCalled();
    expect(mockCreateAccount).not.toHaveBeenCalled();
  });

  it("marks account counts unavailable instead of reporting false zeroes after query failures", async () => {
    mockListAccounts.mockRejectedValueOnce(new Error("accounts offline"));
    mockListInvalidAccountRows.mockRejectedValueOnce(new Error("invalid rows offline"));

    renderAccountAdminPage();

    expect(await screen.findByText("账号目录加载不完整，请刷新后重试。")).toHaveAttribute(
      "role",
      "alert",
    );
    expect(screen.getByLabelText("有效账号数量不可用")).toHaveTextContent("—");
    expect(screen.getByLabelText("无效行数量不可用")).toHaveTextContent("—");
    expect(screen.getByRole("button", { name: "有效 不可用" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "无效 不可用" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "有效 0" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "无效 0" })).not.toBeInTheDocument();
  });

  it("requires an exact password and confirmation when repairing a missing-password row", async () => {
    const user = userEvent.setup();
    mockListInvalidAccountRows.mockResolvedValueOnce({
      items: [
        {
          ...makeInvalidRow(),
          raw: {
            ...makeInvalidRow().raw,
            账号: "missing-password",
            姓名: "缺少密码",
            角色: "设计人员",
          },
          errors: ["missing_password"],
        },
      ],
    });
    renderAccountAdminPage();
    const directory = await screen.findByRole("region", { name: "账号目录" });
    await user.click(within(directory).getByRole("button", { name: "无效 1" }));
    await user.click(within(directory).getByRole("button", { name: /第 4 行/ }));

    const password = screen.getByLabelText("密码（必填）");
    const confirmation = screen.getByLabelText("确认密码（必填）");
    expect(screen.getByRole("button", { name: "保存并修复" })).toBeDisabled();
    await user.type(password, "  repair secret  ");
    await user.type(confirmation, "  repair secret  ");
    await user.click(screen.getByRole("button", { name: "保存并修复" }));

    await waitFor(() => {
      expect(mockUpdateAccountRow).toHaveBeenCalledWith(4, {
        officeCode: "25C1",
        officeName: "结构一室",
        accountId: "missing-password",
        displayName: "缺少密码",
        role: "设计人员",
        password: "  repair secret  ",
      });
    });
  });

  it("uses roving tabindex and keyboard navigation before focusing the selected editor", async () => {
    const user = userEvent.setup();
    renderAccountAdminPage();
    const directory = await screen.findByRole("region", { name: "账号目录" });
    const firstAccount = within(directory).getByRole("button", { name: /王丹丹/ });
    const secondAccount = within(directory).getByRole("button", { name: /薛晓航/ });
    const invalidRow = within(directory).getByRole("button", { name: /第 4 行/ });

    expect(firstAccount).toHaveAttribute("tabindex", "0");
    expect(secondAccount).toHaveAttribute("tabindex", "-1");
    act(() => firstAccount.focus());
    await user.keyboard("{ArrowUp}");
    expect(invalidRow).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(firstAccount).toHaveFocus();
    await user.keyboard("{End}");
    expect(invalidRow).toHaveFocus();
    await user.keyboard("{Home}");
    expect(firstAccount).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(secondAccount).toHaveFocus();
    expect(secondAccount).toHaveAttribute("tabindex", "0");
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("heading", { name: "编辑账号" })).toBeInTheDocument();
    expect(screen.getByLabelText("账号")).toHaveFocus();

    await user.click(within(directory).getByRole("button", { name: "新建账号" }));
    expect(screen.getByRole("heading", { name: "创建账号" })).toBeInTheDocument();
    expect(screen.getByLabelText("账号")).toHaveFocus();
  });

  it("rebinds editor selection to the account id returned by an update", async () => {
    const user = userEvent.setup();
    mockUpdateAccount.mockResolvedValue({
      officeCode: "25C0",
      officeName: "建筑结构所",
      accountId: "wangdd-renamed",
      displayName: "王丹丹",
      role: "管理员",
      valid: true,
      rowNumber: 2,
      errors: [],
    });
    renderAccountAdminPage();
    const directory = await screen.findByRole("region", { name: "账号目录" });
    await user.click(within(directory).getByRole("button", { name: /王丹丹/ }));
    await user.clear(screen.getByLabelText("账号"));
    await user.type(screen.getByLabelText("账号"), "wangdd-renamed");
    await user.click(screen.getByRole("button", { name: "保存修改" }));
    await waitFor(() => expect(mockUpdateAccount).toHaveBeenCalledTimes(1));

    await user.clear(screen.getByLabelText("姓名"));
    await user.type(screen.getByLabelText("姓名"), "王丹");
    await user.click(screen.getByRole("button", { name: "保存修改" }));

    await waitFor(() => {
      expect(mockUpdateAccount).toHaveBeenLastCalledWith(
        "wangdd-renamed",
        expect.objectContaining({ accountId: "wangdd-renamed", displayName: "王丹" }),
      );
    });
  });

  it("translates unknown invalid-row and backend errors with safe Chinese fallbacks", async () => {
    const user = userEvent.setup();
    mockListInvalidAccountRows.mockResolvedValueOnce({
      items: [{ ...makeInvalidRow(), errors: ["private_stack_trace"] }],
    });
    mockUpdateAccount.mockRejectedValueOnce({ detail: "database password=super-secret" });
    renderAccountAdminPage();
    const directory = await screen.findByRole("region", { name: "账号目录" });
    expect(await within(directory).findByText("账号数据异常，请核对并修复")).toBeInTheDocument();
    expect(screen.queryByText("private_stack_trace")).not.toBeInTheDocument();

    await user.click(within(directory).getByRole("button", { name: /王丹丹/ }));
    await user.clear(screen.getByLabelText("姓名"));
    await user.type(screen.getByLabelText("姓名"), "王丹");
    await user.click(screen.getByRole("button", { name: "保存修改" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("账号操作失败，请稍后重试。");
    expect(screen.queryByText(/database password|super-secret/)).not.toBeInTheDocument();
  });

  it("submits administrator passwords exactly as confirmed", async () => {
    const user = userEvent.setup();
    renderAccountAdminPage();
    await screen.findByRole("heading", { name: "创建账号" });

    await user.type(screen.getByLabelText("账号"), "exact-user");
    await user.type(screen.getByLabelText("姓名"), "精确密码用户");
    await user.type(screen.getByLabelText("密码"), "  exact secret  ");
    await user.type(screen.getByLabelText("确认密码"), "  exact secret  ");
    await user.click(screen.getByRole("button", { name: "创建账号" }));

    await waitFor(() => {
      expect(mockCreateAccount).toHaveBeenCalledWith(
        expect.objectContaining({ password: "  exact secret  " }),
      );
    });
  });
});
