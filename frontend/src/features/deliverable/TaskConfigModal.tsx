import { useEffect, useRef, type ReactNode } from "react";

import { lockBodyScroll } from "../../shared/documentScrollLock";
import styles from "./TaskConfigModal.module.css";

type TaskConfigModalProps = {
  title: string;
  children: ReactNode;
  dialogClassName?: string;
  dialogDataAttributes?: Record<string, string | undefined>;
  onRequestClose?: () => void;
};

type ModalStackEntry = {
  id: symbol;
};

const modalStack: ModalStackEntry[] = [];

export function TaskConfigModal({
  title,
  children,
  dialogClassName,
  dialogDataAttributes,
  onRequestClose,
}: TaskConfigModalProps) {
  const modalIdRef = useRef(Symbol("TaskConfigModal"));
  const onRequestCloseRef = useRef(onRequestClose);

  useEffect(() => {
    onRequestCloseRef.current = onRequestClose;
  }, [onRequestClose]);

  useEffect(() => {
    return lockBodyScroll();
  }, []);

  useEffect(() => {
    const entry = { id: modalIdRef.current };
    modalStack.push(entry);

    return () => {
      const index = modalStack.findIndex((item) => item.id === entry.id);
      if (index >= 0) {
        modalStack.splice(index, 1);
      }
    };
  }, []);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape" || event.defaultPrevented) {
        return;
      }

      const topModal = modalStack[modalStack.length - 1];
      if (topModal?.id !== modalIdRef.current || !onRequestCloseRef.current) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();
      onRequestCloseRef.current();
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
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
