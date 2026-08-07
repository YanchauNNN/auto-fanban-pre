import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import type {
  AccountRecord,
  AccountUpdatePayload,
  InvalidAccountRow,
  ManagementSchema,
} from "../../platform/api/types";
import { useApiAdapter } from "../../platform/api/useApiAdapter";
import { useSession } from "../../shared/session/SessionContext";
import styles from "./AccountAdminPage.module.css";

const FALLBACK_ACCOUNT_FIELD_MAP: ManagementSchema["account"]["fieldMap"] = {
  officeCode: "科室编码",
  officeName: "科室",
  accountId: "账号",
  displayName: "姓名",
  role: "角色",
  password: "密码",
};

type EditorMode = "create" | "edit" | "row";
type DirectoryFilter = "all" | "valid" | "invalid";

type AccountFormState = {
  officeCode: string;
  officeName: string;
  accountId: string;
  displayName: string;
  role: string;
  password: string;
  confirmPassword: string;
};

type FeedbackState = {
  tone: "error" | "success";
  message: string;
} | null;

function buildEmptyAccountForm(role: string): AccountFormState {
  return {
    officeCode: "",
    officeName: "",
    accountId: "",
    displayName: "",
    role,
    password: "",
    confirmPassword: "",
  };
}

function getRawAccountValue(row: InvalidAccountRow, fieldName: string) {
  return String(row.raw[fieldName] ?? "").trim();
}

function buildFormFromInvalidRow(
  row: InvalidAccountRow,
  fieldMap: ManagementSchema["account"]["fieldMap"],
  roleOptions: readonly string[],
  defaultRole: string,
): AccountFormState {
  const rawRole = getRawAccountValue(row, fieldMap.role);
  return {
    officeCode: getRawAccountValue(row, fieldMap.officeCode),
    officeName: getRawAccountValue(row, fieldMap.officeName),
    accountId: getRawAccountValue(row, fieldMap.accountId),
    displayName: getRawAccountValue(row, fieldMap.displayName),
    role: rawRole && roleOptions.includes(rawRole) ? rawRole : defaultRole,
    password: "",
    confirmPassword: "",
  };
}

function formatInvalidRowErrors(errors: readonly string[]) {
  const labels: Record<string, string> = {
    duplicate_account_id: "账号重复",
    invalid_role: "角色无效",
    missing_account_id: "缺少账号",
    missing_display_name: "缺少姓名",
    missing_password: "缺少密码",
    missing_role: "缺少角色",
  };
  return errors.map((error) => labels[error] ?? error).join(" / ");
}

export function AccountAdminPage() {
  const adapter = useApiAdapter();
  const queryClient = useQueryClient();
  const { currentAccount, refreshCurrentAccount } = useSession();
  const [mode, setMode] = useState<EditorMode>("create");
  const [editingAccountId, setEditingAccountId] = useState<string | null>(null);
  const [editingRowNumber, setEditingRowNumber] = useState<number | null>(null);
  const [accountForm, setAccountForm] = useState(() => buildEmptyAccountForm(""));
  const [directoryFilter, setDirectoryFilter] = useState<DirectoryFilter>("all");
  const [directorySearch, setDirectorySearch] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [archiveRootPath, setArchiveRootPath] = useState("");
  const [archiveRootPathDirty, setArchiveRootPathDirty] = useState(false);
  const [accountSubmitting, setAccountSubmitting] = useState(false);
  const [configSubmitting, setConfigSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<FeedbackState>(null);

  const accountsQuery = useQuery({
    queryKey: ["accounts"],
    queryFn: () => adapter.listAccounts(),
  });
  const invalidRowsQuery = useQuery({
    queryKey: ["invalid-account-rows"],
    queryFn: () => adapter.listInvalidAccountRows(),
  });
  const adminConfigQuery = useQuery({
    queryKey: ["admin-config"],
    queryFn: () => adapter.getAdminConfig(),
  });
  const schemaQuery = useQuery({
    queryKey: ["form-schema", "management"],
    queryFn: () => adapter.getFormSchema(),
  });

  const managementSchema = schemaQuery.data?.management;
  const accountFieldMap = managementSchema?.account.fieldMap ?? FALLBACK_ACCOUNT_FIELD_MAP;
  const roleOptions = useMemo(
    () =>
      managementSchema?.account.validRoles.length
        ? [...managementSchema.account.validRoles]
        : schemaQuery.isError && currentAccount?.role
          ? [currentAccount.role]
          : [],
    [currentAccount?.role, managementSchema, schemaQuery.isError],
  );
  const defaultRole = roleOptions[0] ?? "";
  const defaultPassword = managementSchema?.account.adminCreatedDefaultPassword ?? "";

  useEffect(() => {
    if (!archiveRootPathDirty) {
      setArchiveRootPath(adminConfigQuery.data?.archiveRootPath ?? "");
    }
  }, [adminConfigQuery.data?.archiveRootPath, archiveRootPathDirty]);

  useEffect(() => {
    if (mode !== "create") {
      return;
    }
    setAccountForm((current) => ({
      ...current,
      role: current.role && roleOptions.includes(current.role) ? current.role : defaultRole,
    }));
  }, [defaultRole, mode, roleOptions]);

  const accountItems = accountsQuery.data?.items ?? [];
  const validAccounts = useMemo(
    () => accountItems.filter((account) => account.valid !== false),
    [accountItems],
  );
  const invalidRows = invalidRowsQuery.data?.items ?? [];
  const normalizedSearch = directorySearch.trim().toLocaleLowerCase("zh-CN");

  const filteredAccounts = useMemo(() => {
    if (directoryFilter === "invalid") {
      return [];
    }
    if (!normalizedSearch) {
      return validAccounts;
    }
    return validAccounts.filter((account) =>
      [account.accountId, account.displayName, account.officeCode, account.officeName, account.role]
        .filter(Boolean)
        .join(" ")
        .toLocaleLowerCase("zh-CN")
        .includes(normalizedSearch),
    );
  }, [directoryFilter, normalizedSearch, validAccounts]);

  const filteredInvalidRows = useMemo(() => {
    if (directoryFilter === "valid") {
      return [];
    }
    if (!normalizedSearch) {
      return invalidRows;
    }
    return invalidRows.filter((row) =>
      [...Object.values(row.raw), ...row.errors]
        .join(" ")
        .toLocaleLowerCase("zh-CN")
        .includes(normalizedSearch),
    );
  }, [directoryFilter, invalidRows, normalizedSearch]);

  if (!currentAccount) {
    return null;
  }

  const isBootstrapping =
    (accountsQuery.isLoading && !accountsQuery.data) ||
    (invalidRowsQuery.isLoading && !invalidRowsQuery.data) ||
    (adminConfigQuery.isLoading && !adminConfigQuery.data) ||
    (schemaQuery.isLoading && !schemaQuery.data);

  if (isBootstrapping) {
    return (
      <main className={styles.page}>
        <p aria-label="正在加载账号管理" className={styles.stateMessage} role="status">
          正在加载账号管理...
        </p>
      </main>
    );
  }

  function switchToCreateMode() {
    setMode("create");
    setEditingAccountId(null);
    setEditingRowNumber(null);
    setPasswordVisible(false);
    setAccountForm(buildEmptyAccountForm(defaultRole));
    setFeedback(null);
  }

  function switchToEditMode(account: AccountRecord) {
    setMode("edit");
    setEditingAccountId(account.accountId);
    setEditingRowNumber(null);
    setPasswordVisible(false);
    setAccountForm({
      officeCode: account.officeCode ?? "",
      officeName: account.officeName ?? "",
      accountId: account.accountId,
      displayName: account.displayName,
      role: account.role,
      password: "",
      confirmPassword: "",
    });
    setFeedback(null);
  }

  function switchToInvalidRow(row: InvalidAccountRow) {
    setMode("row");
    setEditingAccountId(null);
    setEditingRowNumber(row.rowNumber);
    setPasswordVisible(false);
    setAccountForm(buildFormFromInvalidRow(row, accountFieldMap, roleOptions, defaultRole));
    setFeedback(null);
  }

  async function refreshManagementQueries() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["accounts"] }),
      queryClient.invalidateQueries({ queryKey: ["invalid-account-rows"] }),
      queryClient.invalidateQueries({ queryKey: ["admin-config"] }),
      queryClient.invalidateQueries({ queryKey: ["task-groups"] }),
      queryClient.invalidateQueries({ queryKey: ["workflow", "monitor"] }),
      refreshCurrentAccount(),
    ]);
  }

  const passwordProvided = Boolean(accountForm.password.trim());
  const passwordsMismatch = accountForm.password !== accountForm.confirmPassword;
  const requiredFieldsPresent = Boolean(
    accountForm.accountId.trim() && accountForm.displayName.trim() && accountForm.role,
  );
  const passwordIsValid =
    mode === "create"
      ? passwordProvided && !passwordsMismatch
      : !passwordProvided && !accountForm.confirmPassword
        ? true
        : passwordProvided && !passwordsMismatch;
  const accountSubmitDisabled = !requiredFieldsPresent || !passwordIsValid || accountSubmitting;

  async function handleAccountSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (accountSubmitDisabled) {
      return;
    }

    const basePayload: AccountUpdatePayload = {
      officeCode: accountForm.officeCode.trim() || null,
      officeName: accountForm.officeName.trim() || null,
      accountId: accountForm.accountId.trim(),
      displayName: accountForm.displayName.trim(),
      role: accountForm.role,
      ...(passwordProvided ? { password: accountForm.password.trim() } : {}),
    };

    setAccountSubmitting(true);
    setFeedback(null);
    try {
      if (mode === "row" && editingRowNumber !== null) {
        await adapter.updateAccountRow(editingRowNumber, basePayload);
        switchToCreateMode();
        setFeedback({ tone: "success", message: "无效账号行已修复。" });
      } else if (mode === "edit" && editingAccountId) {
        await adapter.updateAccount(editingAccountId, basePayload);
        setFeedback({ tone: "success", message: "账号信息已更新。" });
        setAccountForm((current) => ({ ...current, password: "", confirmPassword: "" }));
      } else {
        await adapter.createAccount({
          officeCode: basePayload.officeCode ?? null,
          officeName: basePayload.officeName ?? null,
          accountId: basePayload.accountId ?? "",
          displayName: basePayload.displayName ?? "",
          role: basePayload.role ?? "",
          password: basePayload.password ?? "",
        });
        switchToCreateMode();
        setFeedback({ tone: "success", message: "账号已创建。" });
      }
      await refreshManagementQueries();
    } catch (error) {
      const detail = resolveErrorMessage(error);
      if (mode === "create" && detail === "account_id already exists") {
        const existing = validAccounts.find((item) => item.accountId === basePayload.accountId);
        if (existing) {
          switchToEditMode(existing);
          setFeedback({ tone: "error", message: "账号已存在，已切换到编辑模式。" });
          return;
        }
      }
      setFeedback({ tone: "error", message: detail || "账号操作失败，请稍后重试。" });
    } finally {
      setAccountSubmitting(false);
    }
  }

  async function handleAdminConfigSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setConfigSubmitting(true);
    setFeedback(null);
    try {
      await adapter.patchAdminConfig({ archiveRootPath: archiveRootPath.trim() || null });
      await queryClient.invalidateQueries({ queryKey: ["admin-config"] });
      setArchiveRootPathDirty(false);
      setFeedback({ tone: "success", message: "归档配置已更新。" });
    } catch (error) {
      setFeedback({
        tone: "error",
        message: resolveErrorMessage(error) || "归档配置保存失败，请稍后重试。",
      });
    } finally {
      setConfigSubmitting(false);
    }
  }

  const formRoleOptions =
    accountForm.role && !roleOptions.includes(accountForm.role)
      ? [accountForm.role, ...roleOptions]
      : roleOptions;
  const passwordLabel =
    mode === "edit" ? "新密码（可选）" : mode === "row" ? "密码（可选）" : "密码";
  const confirmationLabel = mode === "edit" ? "确认新密码" : "确认密码";

  return (
    <main className={styles.page}>
      <header className={styles.pageHeader}>
        <div>
          <p className={styles.eyebrow}>Account Administration</p>
          <h1>账号管理</h1>
          <p>在同一工作区检索账号、修复无效行并维护归档路径。</p>
        </div>
        <dl className={styles.headerMetrics}>
          <div>
            <dt>有效账号</dt>
            <dd>{validAccounts.length}</dd>
          </div>
          <div data-tone={invalidRows.length > 0 ? "warning" : "neutral"}>
            <dt>无效行</dt>
            <dd>{invalidRows.length}</dd>
          </div>
        </dl>
      </header>

      <section
        aria-labelledby="archive-config-heading"
        className={styles.archiveStrip}
      >
        <div className={styles.stripTitle}>
          <span>系统配置</span>
          <h2 id="archive-config-heading">归档配置</h2>
        </div>
        <form className={styles.archiveForm} onSubmit={handleAdminConfigSubmit}>
          <label htmlFor="admin-archive-root-path">归档根路径</label>
          <input
            id="admin-archive-root-path"
            onChange={(event) => {
              setArchiveRootPathDirty(true);
              setArchiveRootPath(event.currentTarget.value);
            }}
            value={archiveRootPath}
          />
          <button disabled={configSubmitting} type="submit">
            {configSubmitting ? "保存中..." : "保存归档配置"}
          </button>
        </form>
      </section>

      {feedback ? (
        <p
          className={feedback.tone === "success" ? styles.feedbackSuccess : styles.feedbackError}
          role={feedback.tone === "error" ? "alert" : "status"}
        >
          {feedback.message}
        </p>
      ) : null}

      <div className={styles.managementWorkspace}>
        <section aria-labelledby="account-directory-heading" className={styles.directoryPanel}>
          <div className={styles.panelHeader}>
            <div>
              <span className={styles.panelIndex}>01</span>
              <h2 id="account-directory-heading">账号目录</h2>
            </div>
            <button className={styles.secondaryButton} onClick={switchToCreateMode} type="button">
              新建账号
            </button>
          </div>

          <label className={styles.searchField} htmlFor="account-directory-search">
            <span>搜索账号</span>
            <input
              id="account-directory-search"
              onChange={(event) => setDirectorySearch(event.currentTarget.value)}
              placeholder="账号 / 姓名 / 科室 / 角色"
              type="search"
              value={directorySearch}
            />
          </label>

          <div aria-label="账号状态筛选" className={styles.filters} role="group">
            <button
              aria-pressed={directoryFilter === "all"}
              onClick={() => setDirectoryFilter("all")}
              type="button"
            >
              全部 {validAccounts.length + invalidRows.length}
            </button>
            <button
              aria-pressed={directoryFilter === "valid"}
              onClick={() => setDirectoryFilter("valid")}
              type="button"
            >
              有效 {validAccounts.length}
            </button>
            <button
              aria-pressed={directoryFilter === "invalid"}
              data-tone={invalidRows.length > 0 ? "warning" : "neutral"}
              onClick={() => setDirectoryFilter("invalid")}
              type="button"
            >
              无效 {invalidRows.length}
            </button>
          </div>

          {accountsQuery.isError || invalidRowsQuery.isError ? (
            <p className={styles.feedbackError} role="alert">
              账号目录加载不完整，请刷新后重试。
            </p>
          ) : (
            <div className={styles.directoryList}>
              {filteredAccounts.map((account) => (
                <button
                  aria-pressed={mode === "edit" && editingAccountId === account.accountId}
                  className={styles.directoryItem}
                  key={account.accountId}
                  onClick={() => switchToEditMode(account)}
                  type="button"
                >
                  <span className={styles.directoryStatus} data-tone="valid">有效</span>
                  <span className={styles.directoryIdentity}>
                    <strong>{account.displayName}</strong>
                    <small>{account.accountId}</small>
                  </span>
                  <span className={styles.directoryDetails}>
                    <small>{account.officeName ?? account.officeCode ?? "未配置科室"}</small>
                    <small>{account.role}</small>
                  </span>
                </button>
              ))}
              {filteredInvalidRows.map((row) => (
                <button
                  aria-pressed={mode === "row" && editingRowNumber === row.rowNumber}
                  className={styles.directoryItem}
                  key={`invalid-${row.rowNumber}`}
                  onClick={() => switchToInvalidRow(row)}
                  type="button"
                >
                  <span className={styles.directoryStatus} data-tone="invalid">需修复</span>
                  <span className={styles.directoryIdentity}>
                    <strong>{`第 ${row.rowNumber} 行`}</strong>
                    <small>{getRawAccountValue(row, accountFieldMap.accountId) || "账号缺失"}</small>
                  </span>
                  <span className={styles.directoryDetails}>
                    <small>{getRawAccountValue(row, accountFieldMap.displayName) || "姓名缺失"}</small>
                    <small>{formatInvalidRowErrors(row.errors)}</small>
                  </span>
                </button>
              ))}
              {filteredAccounts.length === 0 && filteredInvalidRows.length === 0 ? (
                <p className={styles.emptyState}>没有符合当前条件的账号。</p>
              ) : null}
            </div>
          )}
        </section>

        <section
          aria-label="账号编辑器"
          className={styles.editorPanel}
        >
          <div className={styles.panelHeader}>
            <div>
              <span className={styles.panelIndex}>02</span>
              <h2 id="account-editor-heading">
                {mode === "row" ? "修复账号行" : mode === "edit" ? "编辑账号" : "创建账号"}
              </h2>
            </div>
            <div className={styles.editorActions}>
              <button
                aria-label={passwordVisible ? "隐藏密码" : "显示密码"}
                className={styles.secondaryButton}
                onClick={() => setPasswordVisible((visible) => !visible)}
                type="button"
              >
                {passwordVisible ? "隐藏密码" : "显示密码"}
              </button>
              {mode !== "create" ? (
                <button className={styles.secondaryButton} onClick={switchToCreateMode} type="button">
                  返回创建
                </button>
              ) : null}
            </div>
          </div>

          <form className={styles.accountForm} onSubmit={handleAccountSubmit}>
            <EditorField
              id="admin-account-id"
              label="账号"
              onChange={(value) => setAccountForm((current) => ({ ...current, accountId: value }))}
              value={accountForm.accountId}
            />
            <EditorField
              id="admin-display-name"
              label="姓名"
              onChange={(value) => setAccountForm((current) => ({ ...current, displayName: value }))}
              value={accountForm.displayName}
            />
            <EditorField
              id="admin-office-code"
              label="科室编码"
              onChange={(value) => setAccountForm((current) => ({ ...current, officeCode: value }))}
              value={accountForm.officeCode}
            />
            <EditorField
              id="admin-office-name"
              label="科室"
              onChange={(value) => setAccountForm((current) => ({ ...current, officeName: value }))}
              value={accountForm.officeName}
            />
            <label className={styles.formField} htmlFor="admin-role">
              <span>角色</span>
              <select
                id="admin-role"
                onChange={(event) => {
                  const value = event.currentTarget.value;
                  setAccountForm((current) => ({ ...current, role: value }));
                }}
                value={accountForm.role}
              >
                {formRoleOptions.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
            </label>
            <EditorField
              autoComplete="new-password"
              id="admin-password"
              label={passwordLabel}
              onChange={(value) => setAccountForm((current) => ({ ...current, password: value }))}
              type={passwordVisible ? "text" : "password"}
              value={accountForm.password}
            />
            <EditorField
              autoComplete="new-password"
              id="admin-confirm-password"
              label={confirmationLabel}
              onChange={(value) =>
                setAccountForm((current) => ({ ...current, confirmPassword: value }))
              }
              type={passwordVisible ? "text" : "password"}
              value={accountForm.confirmPassword}
            />

            <div className={styles.formFooter}>
              <div className={styles.formGuidance} aria-live="polite">
                {mode === "edit" ? <p>留空则保持原密码不变。</p> : null}
                {mode === "row" ? <p>留空时由后端沿用原行密码。</p> : null}
                {mode === "create" ? (
                  <p>{`请显式填写并确认密码。参数规范默认值：${defaultPassword || "未配置"}。`}</p>
                ) : null}
                {(accountForm.password || accountForm.confirmPassword) && passwordsMismatch ? (
                  <p className={styles.validationError}>两次输入的密码不一致。</p>
                ) : null}
              </div>
              <button className={styles.primaryButton} disabled={accountSubmitDisabled} type="submit">
                {accountSubmitting
                  ? "提交中..."
                  : mode === "row"
                    ? "保存并修复"
                    : mode === "edit"
                      ? "保存修改"
                      : "创建账号"}
              </button>
            </div>
          </form>
        </section>
      </div>
    </main>
  );
}

function EditorField({
  autoComplete,
  id,
  label,
  onChange,
  type = "text",
  value,
}: {
  autoComplete?: string;
  id: string;
  label: string;
  onChange: (value: string) => void;
  type?: string;
  value: string;
}) {
  return (
    <label className={styles.formField} htmlFor={id}>
      <span>{label}</span>
      <input
        autoComplete={autoComplete}
        id={id}
        onChange={(event) => onChange(event.currentTarget.value)}
        type={type}
        value={value}
      />
    </label>
  );
}

function resolveErrorMessage(error: unknown) {
  if (
    typeof error === "object" &&
    error &&
    "detail" in error &&
    typeof (error as { detail?: unknown }).detail === "string"
  ) {
    return (error as { detail: string }).detail;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "";
}
