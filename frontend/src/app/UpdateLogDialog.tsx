import { useEffect, useRef } from "react";
import Markdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import projectUpdateLog from "../../../documents/项目更新日志.md?raw";
import styles from "./UpdateLogDialog.module.css";

type UpdateLogDialogProps = {
  onClose: () => void;
};

const updateLogContent = projectUpdateLog.replace(/^\uFEFF?# 项目更新日志\s*/, "");

export function UpdateLogDialog({ onClose }: UpdateLogDialogProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previousActiveElement = document.activeElement as HTMLElement | null;
    const previousBodyOverflow = document.body.style.overflow;
    closeButtonRef.current?.focus();
    document.body.style.overflow = "hidden";

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        return;
      }

      if (event.key === "Tab") {
        const dialog = closeButtonRef.current?.closest<HTMLElement>('[role="dialog"]');
        const focusable = dialog?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        );
        if (!focusable?.length) {
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
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousBodyOverflow;
      previousActiveElement?.focus();
    };
  }, [onClose]);

  return (
    <div
      className={styles.backdrop}
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) {
          onClose();
        }
      }}
    >
      <section
        aria-label="更新日志"
        aria-modal="true"
        className={styles.dialog}
        role="dialog"
      >
        <header className={styles.header}>
          <div>
            <p>Project History</p>
            <h2 id="project-update-log-title">项目更新日志</h2>
          </div>
          <button
            aria-label="关闭更新日志"
            className={styles.closeButton}
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
          >
            ×
          </button>
        </header>
        <div className={styles.scroller}>
          <article className={styles.content}>
            <Markdown
              components={{
                a({ children, href, ...props }) {
                  return (
                    <a {...props} href={href} rel="noopener noreferrer" target="_blank">
                      {children}
                    </a>
                  );
                },
              }}
              rehypePlugins={[rehypeSanitize]}
              remarkPlugins={[remarkGfm]}
              skipHtml
            >
              {updateLogContent}
            </Markdown>
          </article>
        </div>
      </section>
    </div>
  );
}
