import pdfPreviewWorkerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";
import {
  type ChangeEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Document, Page, pdfjs } from "react-pdf";

import { TaskConfigModal } from "../shared/ui/TaskConfigModal";
import { ensurePromiseWithResolvers } from "../shared/pdfPreviewCompat";
import styles from "./App.module.css";

ensurePromiseWithResolvers();

pdfjs.GlobalWorkerOptions.workerSrc = `${pdfPreviewWorkerUrl}?react-pdf-compat=5.4.296`;

type PreviewPdfModalProps = {
  title: string;
  url: string;
  readArtifact?: (url: string) => Promise<Blob>;
  onDownload?: (url: string, label: string) => void;
  onClose: () => void;
};

type HorizontalScrollState = {
  left: number;
  max: number;
};

const MIN_PREVIEW_ZOOM = 0.75;
const MAX_PREVIEW_ZOOM = 2;
const PREVIEW_ZOOM_STEP = 0.25;

function clampPreviewZoom(value: number) {
  return Math.min(MAX_PREVIEW_ZOOM, Math.max(MIN_PREVIEW_ZOOM, Number(value.toFixed(2))));
}

export function PreviewPdfModal({
  title,
  url,
  readArtifact,
  onDownload,
  onClose,
}: PreviewPdfModalProps) {
  const [pdfData, setPdfData] = useState<Uint8Array | null>(null);
  const [pageCount, setPageCount] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pageWidth, setPageWidth] = useState(960);
  const [localZoom, setLocalZoom] = useState(1);
  const [horizontalScroll, setHorizontalScroll] = useState<HorizontalScrollState>({
    left: 0,
    max: 0,
  });
  const previewPagesRef = useRef<HTMLDivElement | null>(null);
  const previewFile = useMemo(() => (pdfData ? { data: pdfData } : null), [pdfData]);
  const zoomPercent = Math.round(localZoom * 100);
  const renderedPageWidth = Math.round(pageWidth * localZoom);
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

    const loadArtifact =
      readArtifact ?? ((targetUrl: string) => readArtifactWithFetch(targetUrl, controller.signal));

    void loadArtifact(url)
      .then(async (blob) => {
        if (controller.signal.aborted) {
          return;
        }

        const buffer = await blob.arrayBuffer();
        if (controller.signal.aborted) {
          return;
        }
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
  }, [readArtifact, url]);

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

  const updateHorizontalScrollState = useCallback(() => {
    const node = previewPagesRef.current;
    if (!node) {
      return;
    }

    const max = Math.max(0, Math.round(node.scrollWidth - node.clientWidth));
    const left = Math.min(max, Math.max(0, Math.round(node.scrollLeft)));
    setHorizontalScroll((current) =>
      current.max === max && current.left === left ? current : { left, max },
    );
  }, []);

  const changeZoom = useCallback((direction: 1 | -1) => {
    setLocalZoom((value) => clampPreviewZoom(value + direction * PREVIEW_ZOOM_STEP));
  }, []);

  const decreaseZoom = () => {
    changeZoom(-1);
  };

  const increaseZoom = () => {
    changeZoom(1);
  };

  const handlePreviewWheel = useCallback((event: WheelEvent) => {
    if (!(event.ctrlKey || event.metaKey) || event.deltaY === 0) {
      return;
    }

    event.preventDefault();
    changeZoom(event.deltaY < 0 ? 1 : -1);
  }, [changeZoom]);

  useEffect(() => {
    const node = previewPagesRef.current;
    if (!node) {
      return;
    }

    node.addEventListener("wheel", handlePreviewWheel, { passive: false });
    return () => {
      node.removeEventListener("wheel", handlePreviewWheel);
    };
  }, [handlePreviewWheel]);

  useEffect(() => {
    const node = previewPagesRef.current;
    if (!node) {
      return;
    }

    const handleScroll = () => {
      updateHorizontalScrollState();
    };

    const handleResize = () => {
      updateHorizontalScrollState();
    };

    node.addEventListener("scroll", handleScroll);
    window.addEventListener("resize", handleResize);
    updateHorizontalScrollState();

    return () => {
      node.removeEventListener("scroll", handleScroll);
      window.removeEventListener("resize", handleResize);
    };
  }, [updateHorizontalScrollState]);

  useLayoutEffect(() => {
    updateHorizontalScrollState();
  }, [pageCount, renderedPageWidth, updateHorizontalScrollState]);

  const handleHorizontalScrollChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextLeft = Number(event.currentTarget.value);
    const node = previewPagesRef.current;
    if (node) {
      node.scrollLeft = nextLeft;
    }
    setHorizontalScroll((current) => ({
      max: current.max,
      left: Math.min(current.max, Math.max(0, Math.round(nextLeft))),
    }));
  };

  const handleDownloadPreview = () => {
    if (onDownload) {
      onDownload(url, "下载预览 PDF");
      return;
    }

    window.location.href = url;
  };

  const handleOpenInNewWindow = () => {
    if (!pdfData) {
      return;
    }

    const buffer = new ArrayBuffer(pdfData.byteLength);
    new Uint8Array(buffer).set(pdfData);
    const objectUrl = URL.createObjectURL(new Blob([buffer], { type: "application/pdf" }));
    window.open(objectUrl, "_blank", "noreferrer");
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
  };

  return (
    <TaskConfigModal dialogClassName={styles.previewDialog} title={title} onRequestClose={onClose}>
      <div className={styles.previewModalContent}>
        <div className={styles.previewModalHeader}>
          <div>
            <p className={styles.brandTop}>Preview PDF</p>
            <h2>{title}</h2>
          </div>
          <div className={styles.previewModalActions}>
            <button className={styles.downloadButton} onClick={handleDownloadPreview} type="button">
              下载预览 PDF
            </button>
            <button
              className={styles.downloadButton}
              disabled={!pdfData}
              onClick={handleOpenInNewWindow}
              type="button"
            >
              新窗口打开
            </button>
            <button className={styles.secondaryActionButton} onClick={onClose} type="button">
              关闭
            </button>
          </div>
        </div>
        <div className={styles.previewViewerShell}>
          <div className={styles.previewViewerControls}>
            <div className={styles.previewViewerStatusRow}>
              <span className={styles.previewStatusText}>{previewStatusText}</span>
              <div className={styles.previewZoomControls} aria-label="PDF 局部缩放">
                <span>局部缩放</span>
                <button
                  className={styles.previewZoomButton}
                  disabled={localZoom <= 0.75}
                  onClick={decreaseZoom}
                  type="button"
                >
                  缩小
                </button>
                <strong>{zoomPercent}%</strong>
                <button
                  className={styles.previewZoomButton}
                  disabled={localZoom >= 2}
                  onClick={increaseZoom}
                  type="button"
                >
                  放大
                </button>
                <button
                  className={styles.previewZoomButton}
                  disabled={localZoom === 1}
                  onClick={() => setLocalZoom(1)}
                  type="button"
                >
                  还原
                </button>
              </div>
            </div>
            <div className={styles.previewHorizontalScrollBar}>
              <input
                aria-label="PDF 横向拖动条"
                className={styles.previewHorizontalSlider}
                disabled={horizontalScroll.max <= 0}
                max={Math.max(horizontalScroll.max, 1)}
                min="0"
                step="1"
                type="range"
                value={Math.min(horizontalScroll.left, horizontalScroll.max)}
                onChange={handleHorizontalScrollChange}
              />
            </div>
          </div>
          <div
            aria-label="PDF 预览页面"
            className={styles.previewPages}
            ref={previewPagesRef}
          >
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
                    <div className={styles.previewPageZoomLayer} data-preview-page-zoom="true">
                      <Page
                        pageNumber={index + 1}
                        renderAnnotationLayer={false}
                        renderTextLayer={false}
                        width={renderedPageWidth}
                        onRenderSuccess={updateHorizontalScrollState}
                      />
                    </div>
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

async function readArtifactWithFetch(url: string, signal: AbortSignal) {
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`preview request failed with status ${response.status}`);
  }
  return response.blob();
}
