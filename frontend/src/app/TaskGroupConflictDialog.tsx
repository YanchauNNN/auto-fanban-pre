import { useEffect, useRef } from "react";

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
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const confirmButtonRef = useRef<HTMLButtonElement>(null);
  const title = kind === "archive" ? "归档冲突确认" : "重复流程确认";
  const description =
    kind === "archive"
      ? "归档目标已存在，是否覆盖归档后继续提交？"
      : "已有同图册流程正在执行，是否取消旧流程并重新提交？";
  const confirmLabel = kind === "archive" ? "继续提交" : "取消旧流程并重提";

  useEffect(() => {
    cancelButtonRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }

      const cancelButton = cancelButtonRef.current;
      const confirmButton = confirmButtonRef.current;
      if (!cancelButton || !confirmButton) {
        return;
      }

      const activeElement = document.activeElement;
      if (event.shiftKey && activeElement === cancelButton) {
        event.preventDefault();
        confirmButton.focus();
      } else if (!event.shiftKey && activeElement === confirmButton) {
        event.preventDefault();
        cancelButton.focus();
      } else if (activeElement !== cancelButton && activeElement !== confirmButton) {
        event.preventDefault();
        (event.shiftKey ? confirmButton : cancelButton).focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className={styles.jobsModalBackdrop}>
      <div
        aria-label={title}
        aria-modal="true"
        className={`${styles.jobsModal} ${styles.conflictDialog}`}
        role="dialog"
      >
        <header className={styles.jobsModalHeader}>
          <div>
            <p className={styles.brandTop}>Submit Conflict</p>
            <h2>{title}</h2>
          </div>
        </header>
        <p className={styles.jobMessage}>{description}</p>
        <div className={styles.jobsModalActions}>
          <button
            ref={cancelButtonRef}
            className={styles.secondaryActionButton}
            type="button"
            onClick={onClose}
          >
            取消
          </button>
          <button
            ref={confirmButtonRef}
            className={styles.primaryActionButton}
            type="button"
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
