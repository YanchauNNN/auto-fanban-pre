import { useEffect } from "react";

import styles from "./ReplaceTaskModal.module.css";

type ReplaceTaskModalProps = {
  recommendedProjectNos: readonly string[];
  sourceProjectNo: string;
  targetProjectNo: string;
  error: string | null;
  onChange: (field: "sourceProjectNo" | "targetProjectNo", value: string) => void;
  onClose: () => void;
  onConfirm: () => void;
};

export function ReplaceTaskModal({
  recommendedProjectNos,
  sourceProjectNo,
  targetProjectNo,
  error,
  onChange,
  onClose,
  onConfirm,
}: ReplaceTaskModalProps) {
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  return (
    <div className={styles.backdrop}>
      <div aria-label="翻版配置" aria-modal="true" className={styles.dialog} role="dialog">
        <header className={styles.header}>
          <div>
            <p className={styles.kicker}>Replace Config</p>
            <h2>翻版配置</h2>
            <p className={styles.description}>
              原始项目号默认来自本次 DWG 文件名识别结果，但允许人工修正以覆盖特殊情况。
            </p>
          </div>
          <button className={styles.ghostButton} type="button" onClick={onClose}>
            关闭翻版配置
          </button>
        </header>

        <div className={styles.grid}>
          <label className={styles.field}>
            <span className={styles.label}>原始项目号</span>
            <input
              aria-label="原始项目号"
              className={styles.input}
              placeholder="请输入原始项目号"
              type="text"
              value={sourceProjectNo}
              onChange={(event) => onChange("sourceProjectNo", event.target.value)}
            />
            <span className={styles.helper}>
              默认引用本次上传 DWG 的识别结果，可按实际项目情况手动修正。
            </span>
            <div className={styles.recommendations}>
              {recommendedProjectNos.map((projectNo) => (
                <button
                  key={`source-${projectNo}`}
                  className={styles.recommendationButton}
                  type="button"
                  onClick={() => onChange("sourceProjectNo", projectNo)}
                >
                  {`将 ${projectNo} 填入原始项目号`}
                </button>
              ))}
            </div>
          </label>

          <label className={styles.field}>
            <span className={styles.label}>目标项目号</span>
            <input
              aria-label="目标项目号"
              className={styles.input}
              placeholder="请输入目标项目号"
              type="text"
              value={targetProjectNo}
              onChange={(event) => onChange("targetProjectNo", event.target.value)}
            />
            <span className={styles.helper}>
              推荐值同时包含识别结果与参数规范选项，点击即可快速填入。
            </span>
            <div className={styles.recommendations}>
              {recommendedProjectNos.map((projectNo) => (
                <button
                  key={`target-${projectNo}`}
                  className={styles.recommendationButton}
                  type="button"
                  onClick={() => onChange("targetProjectNo", projectNo)}
                >
                  {`将 ${projectNo} 填入目标项目号`}
                </button>
              ))}
            </div>
          </label>
        </div>

        {error ? <p className={styles.error}>{error}</p> : null}

        <footer className={styles.actions}>
          <button className={styles.secondaryButton} type="button" onClick={onClose}>
            取消
          </button>
          <button className={styles.primaryButton} type="button" onClick={onConfirm}>
            保存翻版配置
          </button>
        </footer>
      </div>
    </div>
  );
}
