import styles from "./App.module.css";

type TaskGroupConflictDialogProps = {
  kind: "archive" | "duplicate";
  onClose: () => void;
  onConfirm: () => void;
};

export function TaskGroupConflictDialog({
  kind,
  onClose,
  onConfirm,
}: TaskGroupConflictDialogProps) {
  const title = kind === "archive" ? "归档冲突确认" : "重复流程确认";
  const description =
    kind === "archive"
      ? "归档目标已存在，是否覆盖归档后继续提交？"
      : "已有同图册流程在执行中，是否取消旧流程并重新提交？";
  const confirmLabel = kind === "archive" ? "继续提交" : "取消旧流程并重提";

  return (
    <div className={styles.jobsModalBackdrop}>
      <div aria-label={title} aria-modal="true" className={styles.jobsModal} role="dialog">
        <header className={styles.jobsModalHeader}>
          <div>
            <p className={styles.brandTop}>Submit Conflict</p>
            <h2>{title}</h2>
          </div>
        </header>
        <p className={styles.jobMessage}>{description}</p>
        <div className={styles.jobsModalActions}>
          <button className={styles.secondaryActionButton} type="button" onClick={onClose}>
            取消
          </button>
          <button className={styles.primaryActionButton} type="button" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
