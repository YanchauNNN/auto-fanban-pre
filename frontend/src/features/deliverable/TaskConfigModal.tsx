import { useEffect, type ReactNode } from "react";

import { lockBodyScroll } from "../../shared/documentScrollLock";
import styles from "./TaskConfigModal.module.css";

type TaskConfigModalProps = {
  title: string;
  children: ReactNode;
  dialogClassName?: string;
  dialogDataAttributes?: Record<string, string | undefined>;
};

export function TaskConfigModal({
  title,
  children,
  dialogClassName,
  dialogDataAttributes,
}: TaskConfigModalProps) {
  useEffect(() => {
    return lockBodyScroll();
  }, []);

  return (
    <div className={styles.backdrop}>
      <div
        aria-label={title}
        aria-modal="true"
        className={[styles.dialog, dialogClassName].filter(Boolean).join(" ")}
        role="dialog"
        {...dialogDataAttributes}
      >
        {children}
      </div>
    </div>
  );
}
