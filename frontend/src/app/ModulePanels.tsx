import { lazy, Suspense } from "react";

import styles from "./App.module.css";
import { RoutePlaceholder } from "./RoutePlaceholder";

const AccountPage = lazy(async () => ({
  default: (await import("../features/account/AccountPage")).AccountPage,
}));
const AccountAdminPage = lazy(async () => ({
  default: (await import("../features/account/AccountAdminPage")).AccountAdminPage,
}));
const WorkloadPage = lazy(async () => ({
  default: (await import("../features/workload/WorkloadPage")).WorkloadPage,
}));

export type AccountPanelMode = "self" | "admin";

export function AccountModulePanel({
  isAdmin,
  mode,
  onModeChange,
  onOpenWorkload,
}: {
  isAdmin: boolean;
  mode: AccountPanelMode;
  onModeChange: (mode: AccountPanelMode) => void;
  onOpenWorkload: () => void;
}) {
  return (
    <section className={styles.modulePanel} data-testid="module-account-panel">
      <div className={styles.filterRow}>
        <button
          aria-pressed={mode === "self"}
          className={`${styles.filterButton} ${mode === "self" ? styles.filterButtonActive : ""}`}
          type="button"
          onClick={() => onModeChange("self")}
        >
          账号信息
        </button>
        {isAdmin ? (
          <button
            aria-pressed={mode === "admin"}
            className={`${styles.filterButton} ${mode === "admin" ? styles.filterButtonActive : ""}`}
            type="button"
            onClick={() => onModeChange("admin")}
          >
            管理员配置
          </button>
        ) : null}
      </div>
      <Suspense
        fallback={<RoutePlaceholder description="正在加载账号信息..." title="账号模块" />}
      >
        {mode === "admin" && isAdmin ? (
          <AccountAdminPage />
        ) : (
          <AccountPage onOpenWorkload={onOpenWorkload} />
        )}
      </Suspense>
    </section>
  );
}

export function WorkloadModulePanel() {
  return (
    <section className={styles.modulePanel} data-testid="module-workload-panel">
      <Suspense
        fallback={<RoutePlaceholder description="正在加载工作量模块..." title="工作量模块" />}
      >
        <WorkloadPage />
      </Suspense>
    </section>
  );
}
