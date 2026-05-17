import pdfPreviewWorkerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";

import { TaskConfigModal } from "../features/deliverable/TaskConfigModal";
import { ensurePromiseWithResolvers } from "../shared/pdfPreviewCompat";
import styles from "./App.module.css";

ensurePromiseWithResolvers();

pdfjs.GlobalWorkerOptions.workerSrc = `${pdfPreviewWorkerUrl}?react-pdf-compat=5.4.296`;

type PreviewPdfModalProps = {
  title: string;
  url: string;
  onClose: () => void;
};

export function PreviewPdfModal({ title, url, onClose }: PreviewPdfModalProps) {
  const [pdfData, setPdfData] = useState<Uint8Array | null>(null);
  const [pageCount, setPageCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pageWidth, setPageWidth] = useState(960);
  const previewPagesRef = useRef<HTMLDivElement | null>(null);
  const previewFile = useMemo(() => (pdfData ? { data: pdfData } : null), [pdfData]);
  const previewStatusText = loadError
    ? "预览加载失败"
    : isLoading
      ? "正在加载 PDF..."
      : pageCount > 0
        ? `共 ${pageCount} 页`
        : "正在解析 PDF...";

  useEffect(() => {
    const controller = new AbortController();

    setPdfData(null);
    setPageCount(0);
    setIsLoading(true);
    setLoadError(null);

    void fetch(url, {
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`preview request failed with status ${response.status}`);
        }

        const buffer = await response.arrayBuffer();
        setPdfData(new Uint8Array(buffer));
        setIsLoading(false);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        console.error("Failed to load PDF preview", error);
        setLoadError("PDF 预览加载失败，请使用新窗口打开查看。");
        setIsLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [url]);

  useLayoutEffect(() => {
    const node = previewPagesRef.current;
    if (!node) {
      return;
    }

    const updatePageWidth = () => {
      setPageWidth(Math.max(320, Math.floor(node.clientWidth - 48)));
    };

    updatePageWidth();
    if (typeof ResizeObserver === "undefined") {
      return;
    }

    const observer = new ResizeObserver(() => {
      updatePageWidth();
    });
    observer.observe(node);

    return () => {
      observer.disconnect();
    };
  }, []);

  return (
    <TaskConfigModal dialogClassName={styles.previewDialog} title={title}>
      <div className={styles.previewModalContent}>
        <div className={styles.previewModalHeader}>
          <div>
            <p className={styles.brandTop}>Preview PDF</p>
            <h2>{title}</h2>
          </div>
          <div className={styles.previewModalActions}>
            <a
              className={styles.downloadButton}
              href={url}
              rel="noreferrer"
              target="_blank"
            >
              新窗口打开
            </a>
            <button className={styles.secondaryActionButton} onClick={onClose} type="button">
              关闭
            </button>
          </div>
        </div>
        <div className={styles.previewViewerShell}>
          <div className={styles.previewViewerStatusRow}>
            <span className={styles.previewStatusText}>{previewStatusText}</span>
          </div>
          <div className={styles.previewPages} ref={previewPagesRef}>
            {loadError ? (
              <div className={styles.previewFallback} role="status">
                <strong>预览暂时不可用</strong>
                <p>{loadError}</p>
              </div>
            ) : previewFile ? (
              <Document
                file={previewFile}
                loading={
                  <div className={styles.previewLoading} role="status">
                    正在渲染 PDF 页面...
                  </div>
                }
                onLoadError={(error) => {
                  console.error("Failed to parse PDF preview", error);
                  setLoadError("PDF 预览加载失败，请使用新窗口打开查看。");
                }}
                onLoadSuccess={({ numPages }) => {
                  setPageCount(numPages);
                }}
              >
                {Array.from({ length: Math.max(pageCount, 1) }, (_, index) => (
                  <div className={styles.previewPageCard} key={`${url}-${index + 1}`}>
                    <Page
                      pageNumber={index + 1}
                      renderAnnotationLayer={false}
                      renderTextLayer={false}
                      width={pageWidth}
                    />
                    <span className={styles.previewPageNumber}>第 {index + 1} 页</span>
                  </div>
                ))}
              </Document>
            ) : (
              <div className={styles.previewLoading} role="status">
                正在加载 PDF...
              </div>
            )}
          </div>
        </div>
      </div>
    </TaskConfigModal>
  );
}
