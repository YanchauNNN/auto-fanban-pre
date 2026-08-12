import { useEffect, useRef, type ReactNode } from "react";

import { lockBodyScroll } from "../documentScrollLock";
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
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    onRequestCloseRef.current = onRequestClose;
  }, [onRequestClose]);

  useEffect(() => {
    return lockBodyScroll();
  }, []);

  useEffect(() => {
    const entry = { id: modalIdRef.current };
    modalStack.push(entry);
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const focusAlreadyInside = document.activeElement instanceof HTMLElement
      && dialogRef.current?.contains(document.activeElement);
    if (!focusAlreadyInside) {
      const initialFocus = getFocusableElements(dialogRef.current)[0];
      initialFocus?.focus({ preventScroll: true });
    }

    return () => {
      const index = modalStack.findIndex((item) => item.id === entry.id);
      if (index >= 0) {
        modalStack.splice(index, 1);
      }
      previousFocus?.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented) {
        return;
      }

      const topModal = modalStack[modalStack.length - 1];
      if (topModal?.id !== modalIdRef.current) {
        return;
      }

      if (event.key === "Tab") {
        const focusable = getFocusableElements(dialogRef.current);
        if (focusable.length === 0) {
          return;
        }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
        return;
      }

      if (event.key !== "Escape" || !onRequestCloseRef.current) {
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
        ref={dialogRef}
        role="dialog"
        {...dialogDataAttributes}
      >
        {children}
      </div>
    </div>
  );
}

function getFocusableElements(root: HTMLElement | null) {
  if (!root) {
    return [];
  }
  return Array.from(
    root.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => element.getAttribute("aria-hidden") !== "true");
}
