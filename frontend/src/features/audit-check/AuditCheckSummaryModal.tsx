import type { JobDetail } from "../../platform/api/types";
import { useApiAdapter } from "../../platform/api/useApiAdapter";
import { TaskConfigModal } from "../../shared/ui/TaskConfigModal";
import styles from "./AuditCheckSummaryModal.module.css";

type AuditCheckSummaryModalProps = {
  job: JobDetail;
  onClose: () => void;
};

export function AuditCheckSummaryModal({ job, onClose }: AuditCheckSummaryModalProps) {
  const adapter = useApiAdapter();
  const reportDownloadUrl = job.artifacts.reportDownloadUrl;

  const handleReportDownload = () => {
    if (!reportDownloadUrl) {
      return;
    }

    if (adapter.downloadArtifact) {
      void adapter.downloadArtifact(reportDownloadUrl, "下载完整报告").catch((error: unknown) => {
        console.error("Failed to download audit report", error);
      });
      return;
    }

    window.location.href = reportDownloadUrl;
  };

  return (
    <TaskConfigModal
      dialogClassName={styles.summaryDialog}
      title="纠错结果摘要"
      onRequestClose={onClose}
    >
      <div className={styles.panel}>
        <header className={styles.header}>
          <div>
            <p className={styles.kicker}>Audit Summary</p>
            <h2>纠错结果摘要</h2>
            <p className={styles.description}>
              {job.sourceFilename} 已完成纠错，请先确认摘要结果，再决定是否下载完整报告。
            </p>
          </div>
        </header>

        <div className={styles.summaryGrid}>
          <div className={styles.summaryCard}>
            <span>总错误数</span>
            <strong>{job.findingsCount}</strong>
          </div>
          <div className={styles.summaryCard}>
            <span>受影响图纸数</span>
            <strong>{job.affectedDrawingsCount}</strong>
          </div>
        </div>

        <section className={styles.listSection}>
          <h3>前 10 个错误文本</h3>
          {job.topWrongTexts.length > 0 ? (
            <ul>
              {job.topWrongTexts.slice(0, 10).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : (
            <p>没有返回错误文本摘要。</p>
          )}
        </section>

        <section className={styles.listSection}>
          <h3>前 10 个受影响内部编码</h3>
          {job.topInternalCodes.length > 0 ? (
            <ul>
              {job.topInternalCodes.slice(0, 10).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : (
            <p>没有返回内部编码摘要。</p>
          )}
        </section>

        <footer className={styles.actions}>
          {reportDownloadUrl ? (
            <button
              className={styles.downloadButton}
              onClick={handleReportDownload}
              type="button"
            >
              下载完整报告
            </button>
          ) : null}
          <button className={styles.ghostButton} type="button" onClick={onClose}>
            关闭
          </button>
        </footer>
      </div>
    </TaskConfigModal>
  );
}
