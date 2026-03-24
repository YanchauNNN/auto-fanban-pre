import { useEffect, type ReactNode } from "react";

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
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.body.style.overflow = previousOverflow;
    };
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
