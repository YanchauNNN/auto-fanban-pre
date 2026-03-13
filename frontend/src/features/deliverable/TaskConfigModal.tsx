import { useEffect, type ReactNode } from "react";

import styles from "./TaskConfigModal.module.css";

type TaskConfigModalProps = {
  title: string;
  children: ReactNode;
};

export function TaskConfigModal({ title, children }: TaskConfigModalProps) {
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  return (
    <div className={styles.backdrop}>
      <div aria-label={title} aria-modal="true" className={styles.dialog} role="dialog">
        {children}
      </div>
    </div>
  );
}
