import { startTransition, useMemo, useState } from "react";

import type {
  ApiAdapter,
  FontSyncApplyResult,
  FontSyncDependency,
  FontSyncEnvironment,
  FontSyncExportResult,
  FontSyncPreviewResult,
  FontSyncSourceScanResult,
  FontSyncTargetScanResult,
} from "../../platform/api/types";
import styles from "./FontSyncWorkspace.module.css";

function requireMethod<T>(value: T | undefined, label: string): T {
  if (value) {
    return value;
  }
  throw new Error(`当前适配器未启用 ${label} 能力。`);
}

async function copyStructuredPayload(label: string, payload: unknown) {
  const text = JSON.stringify(payload, null, 2);
  if (!navigator.clipboard?.writeText) {
    throw new Error(`${label}复制失败：当前环境不支持剪贴板写入。`);
  }
  await navigator.clipboard.writeText(text);
}

function getBundleModeLabel(mode: string) {
  return mode === "guaranteed" ? "可保证复现" : "尽力同步";
}

function getApplyStatusLabel(status: string) {
  if (status === "matched") {
    return "已对齐";
  }
  if (status === "partial") {
    return "部分对齐";
  }
  return "同步失败";
}

function getDependencyToneClass(dependency: FontSyncDependency) {
  if (dependency.resolved && dependency.copyStatus === "copied") {
    return styles.dependencyResolved;
  }
  if (dependency.resolved) {
    return styles.dependencyWarning;
  }
  return styles.dependencyMissing;
}

function formatEnvironmentSummary(environment: FontSyncEnvironment) {
  if (environment.selectedInstallation?.label) {
    return `${environment.selectedInstallation.label} / ${environment.activeProfile || "未读取到 profile"}`;
  }
  if (environment.activeProfile) {
    return environment.activeProfile;
  }
  return environment.autocadReady ? "已检测到 AutoCAD 环境" : "未就绪";
}

export function FontSyncWorkspace({ adapter }: { adapter: ApiAdapter }) {
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [bundleFile, setBundleFile] = useState<File | null>(null);
  const [sourceScan, setSourceScan] = useState<FontSyncSourceScanResult | null>(null);
  const [exportResult, setExportResult] = useState<FontSyncExportResult | null>(null);
  const [targetScan, setTargetScan] = useState<FontSyncTargetScanResult | null>(null);
  const [previewResult, setPreviewResult] = useState<FontSyncPreviewResult | null>(null);
  const [applyResult, setApplyResult] = useState<FontSyncApplyResult | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [noticeMessage, setNoticeMessage] = useState<string | null>(null);

  const sourceResolvedCount = useMemo(
    () => sourceScan?.fontDependencies.filter((item) => item.resolved).length ?? 0,
    [sourceScan],
  );
  const sourceMissingCount = useMemo(
    () => sourceScan?.fontDependencies.filter((item) => !item.resolved).length ?? 0,
    [sourceScan],
  );

  async function handleCopy(label: string, payload: unknown) {
    setErrorMessage(null);
    try {
      await copyStructuredPayload(label, payload);
      setNoticeMessage(`${label}已复制到剪贴板。`);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : `${label}复制失败。`);
    }
  }

  async function handleSourceScan() {
    if (!sourceFile) {
      setErrorMessage("请先选择一张 DWG 图纸。");
      return;
    }
    setBusyAction("source-scan");
    setErrorMessage(null);
    setNoticeMessage(null);
    try {
      const run = requireMethod(adapter.scanFontSyncSource, "源机扫描");
      const result = await run(sourceFile);
      startTransition(() => {
        setSourceScan(result);
        setExportResult(null);
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "源机扫描失败。");
    } finally {
      setBusyAction(null);
    }
  }

  async function handleExportBundle() {
    if (!sourceFile) {
      setErrorMessage("请先选择一张 DWG 图纸。");
      return;
    }
    setBusyAction("export");
    setErrorMessage(null);
    setNoticeMessage(null);
    try {
      const run = requireMethod(adapter.exportFontSyncBundle, "bundle 导出");
      const result = await run(sourceFile);
      startTransition(() => {
        setExportResult(result);
        setSourceScan(result);
      });
      setNoticeMessage("同步记录包已生成，可以复制摘要或直接下载。");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "导出同步记录包失败。");
    } finally {
      setBusyAction(null);
    }
  }

  async function handleTargetScan() {
    setBusyAction("target-scan");
    setErrorMessage(null);
    setNoticeMessage(null);
    try {
      const run = requireMethod(adapter.scanFontSyncTarget, "目标机扫描");
      const result = await run();
      startTransition(() => {
        setTargetScan(result);
      });
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "目标机扫描失败。");
    } finally {
      setBusyAction(null);
    }
  }

  async function handlePreviewBundle() {
    if (!bundleFile) {
      setErrorMessage("请先选择一份 .fanfontsync 同步记录包。");
      return;
    }
    setBusyAction("preview");
    setErrorMessage(null);
    setNoticeMessage(null);
    try {
      const run = requireMethod(adapter.previewFontSyncBundle, "导入预览");
      const result = await run(bundleFile);
      startTransition(() => {
        setPreviewResult(result);
        setApplyResult(null);
      });
      setNoticeMessage("已生成导入预览，可以继续应用同步。");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "导入预览失败。");
    } finally {
      setBusyAction(null);
    }
  }

  async function handleApplyBundle() {
    if (!previewResult) {
      setErrorMessage("请先完成导入预览。");
      return;
    }
    setBusyAction("apply");
    setErrorMessage(null);
    setNoticeMessage(null);
    try {
      const run = requireMethod(adapter.applyFontSyncBundle, "应用同步");
      const result = await run(previewResult.importId);
      startTransition(() => {
        setApplyResult(result);
      });
      setNoticeMessage("目标机字体环境已尝试同步，建议复制结果并留档。");
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "应用同步失败。");
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <section className={styles.workspace} data-testid="font-sync-workspace">
      <section className={styles.hero}>
        <div>
          <p className={styles.kicker}>CAD Font Sync</p>
          <h2>把字体相关设置做成可复制、可导入、可复检的同步包</h2>
          <p className={styles.heroText}>
            这套验证版专门对齐 AutoCAD 字体搜索路径、FontMap、AltFont 和图纸文字样式依赖。
            先在源机导出一份记录包，再在目标机导入并复检，让两台机器的字体行为尽可能一致。
          </p>
        </div>
        <div className={styles.heroAside}>
          <StatBadge label="当前阶段" value="EXE 验证版" />
          <StatBadge label="同步范围" value="字体环境" />
          <StatBadge label="图纸策略" value="只读分析" />
        </div>
      </section>

      {errorMessage ? (
        <div className={styles.errorBanner} role="alert">
          {errorMessage}
        </div>
      ) : null}
      {noticeMessage ? <div className={styles.noticeBanner}>{noticeMessage}</div> : null}

      <div className={styles.grid}>
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.kicker}>Source Machine</p>
              <h3>源机扫描与导出</h3>
            </div>
            <span className={styles.panelBadge}>DWG</span>
          </div>
          <label className={styles.fileField}>
            <span>选择源 DWG 图纸</span>
            <input
              accept=".dwg"
              onChange={(event) => setSourceFile(event.target.files?.[0] ?? null)}
              type="file"
            />
          </label>
          <div className={styles.fileMeta}>
            <strong>{sourceFile?.name ?? "尚未选择图纸"}</strong>
            <span>{sourceFile ? `${Math.ceil(sourceFile.size / 1024)} KB` : "请选择一张图纸开始检测"}</span>
          </div>
          <div className={styles.actions}>
            <button
              className={styles.primaryButton}
              disabled={!sourceFile || busyAction !== null}
              onClick={() => void handleSourceScan()}
              type="button"
            >
              {busyAction === "source-scan" ? "正在扫描..." : "开始扫描"}
            </button>
            <button
              className={styles.secondaryButton}
              disabled={!sourceFile || busyAction !== null}
              onClick={() => void handleExportBundle()}
              type="button"
            >
              {busyAction === "export" ? "正在导出..." : "导出同步包"}
            </button>
          </div>
          {sourceScan ? (
            <div className={styles.summaryStack}>
              <div className={styles.summaryGrid}>
                <InfoCard label="同步判定" value={getBundleModeLabel(sourceScan.bundleMode)} />
                <InfoCard label="已解析依赖" value={String(sourceResolvedCount)} />
                <InfoCard label="未解析依赖" value={String(sourceMissingCount)} />
                <InfoCard
                  label="环境摘要"
                  value={formatEnvironmentSummary(sourceScan.environment)}
                />
              </div>
              <div className={styles.inlineActions}>
                <button
                  className={styles.ghostButton}
                  onClick={() => void handleCopy("源机扫描摘要", sourceScan)}
                  type="button"
                >
                  复制扫描摘要
                </button>
                {exportResult?.bundleDownloadUrl ? (
                  <a className={styles.downloadButton} href={exportResult.bundleDownloadUrl}>
                    下载同步包
                  </a>
                ) : null}
              </div>
              <FontDependencyList dependencies={sourceScan.fontDependencies} />
            </div>
          ) : null}
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.kicker}>Target Machine</p>
              <h3>目标机预览与应用</h3>
            </div>
            <span className={styles.panelBadge}>.fanfontsync</span>
          </div>
          <div className={styles.actions}>
            <button
              className={styles.secondaryButton}
              disabled={busyAction !== null}
              onClick={() => void handleTargetScan()}
              type="button"
            >
              {busyAction === "target-scan" ? "正在检测..." : "检测本机 CAD 设置"}
            </button>
            {targetScan ? (
              <button
                className={styles.ghostButton}
                onClick={() => void handleCopy("目标机环境快照", targetScan)}
                type="button"
              >
                复制环境快照
              </button>
            ) : null}
          </div>
          <label className={styles.fileField}>
            <span>选择同步记录包</span>
            <input
              accept=".fanfontsync"
              onChange={(event) => setBundleFile(event.target.files?.[0] ?? null)}
              type="file"
            />
          </label>
          <div className={styles.fileMeta}>
            <strong>{bundleFile?.name ?? "尚未选择同步包"}</strong>
            <span>{bundleFile ? `${Math.ceil(bundleFile.size / 1024)} KB` : "选择另一台机器导出的同步记录包"}</span>
          </div>
          <div className={styles.actions}>
            <button
              className={styles.primaryButton}
              disabled={!bundleFile || busyAction !== null}
              onClick={() => void handlePreviewBundle()}
              type="button"
            >
              {busyAction === "preview" ? "正在预览..." : "导入预览"}
            </button>
            <button
              className={styles.secondaryButton}
              disabled={!previewResult || busyAction !== null}
              onClick={() => void handleApplyBundle()}
              type="button"
            >
              {busyAction === "apply" ? "正在应用..." : "应用同步"}
            </button>
          </div>
          {previewResult ? (
            <div className={styles.previewCard}>
              <div className={styles.previewHeader}>
                <strong>{previewResult.bundleFilename}</strong>
                <span className={styles.modePill}>{getBundleModeLabel(previewResult.bundleMode)}</span>
              </div>
              <dl className={styles.diffList}>
                <div>
                  <dt>Support Path</dt>
                  <dd>{previewResult.diff.supportPathChanged ? "将追加托管字体目录" : "无需改动"}</dd>
                </div>
                <div>
                  <dt>FontMap</dt>
                  <dd>{previewResult.diff.fontFileMapChanged ? "将切换到托管 FontMap" : "无需改动"}</dd>
                </div>
                <div>
                  <dt>AltFont</dt>
                  <dd>{previewResult.diff.altFontFileChanged ? "将更新替代字体" : "无需改动"}</dd>
                </div>
              </dl>
              <div className={styles.inlineActions}>
                <button
                  className={styles.ghostButton}
                  onClick={() => void handleCopy("导入预览", previewResult)}
                  type="button"
                >
                  复制导入预览
                </button>
              </div>
            </div>
          ) : null}
        </section>
      </div>

      <div className={styles.grid}>
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.kicker}>Environment</p>
              <h3>目标机当前状态</h3>
            </div>
          </div>
          {targetScan ? (
            <EnvironmentPanel environment={targetScan.environment} />
          ) : (
            <p className={styles.emptyText}>还没有目标机快照，点击上方按钮即可读取本机 CAD 字体环境。</p>
          )}
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.kicker}>Apply Result</p>
              <h3>同步复检结果</h3>
            </div>
          </div>
          {applyResult ? (
            <div className={styles.summaryStack}>
              <div className={styles.summaryGrid}>
                <InfoCard label="同步结果" value={getApplyStatusLabel(applyResult.status)} />
                <InfoCard label="bundle 判定" value={getBundleModeLabel(applyResult.bundleMode)} />
                <InfoCard label="回滚备份" value={applyResult.profileBackupPath} />
                <InfoCard label="托管字体目录" value={applyResult.managedFontsDir} />
              </div>
              <div className={styles.inlineActions}>
                <button
                  className={styles.ghostButton}
                  onClick={() => void handleCopy("同步应用结果", applyResult)}
                  type="button"
                >
                  复制应用结果
                </button>
              </div>
            </div>
          ) : (
            <p className={styles.emptyText}>完成导入预览后，这里会显示“已对齐 / 部分对齐 / 失败”的复检结论。</p>
          )}
        </section>
      </div>
    </section>
  );
}

function StatBadge({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.statBadge}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.infoCard}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function FontDependencyList({ dependencies }: { dependencies: FontSyncDependency[] }) {
  return (
    <div className={styles.dependencyList}>
      {dependencies.map((dependency) => (
        <div
          className={`${styles.dependencyCard} ${getDependencyToneClass(dependency)}`}
          key={dependency.dependencyId}
        >
          <div className={styles.dependencyHeader}>
            <strong>{dependency.styleName || "未命名样式"}</strong>
            <span>{dependency.role === "bigfont" ? "BigFont" : dependency.kind.toUpperCase()}</span>
          </div>
          <p>{dependency.fontName || "-"}</p>
          <small>{dependency.resolvedPath || "未找到可复制字体文件"}</small>
        </div>
      ))}
    </div>
  );
}

function EnvironmentPanel({ environment }: { environment: FontSyncEnvironment }) {
  return (
    <div className={styles.environmentPanel}>
      <div className={styles.summaryGrid}>
        <InfoCard label="AutoCAD 就绪" value={environment.autocadReady ? "是" : "否"} />
        <InfoCard label="当前 Profile" value={environment.activeProfile || "-"} />
        <InfoCard label="FontMap" value={environment.fontFileMap || "-"} />
        <InfoCard label="AltFont" value={environment.altFontFile || "-"} />
      </div>
      <div className={styles.pathBlock}>
        <strong>Support Path</strong>
        <p>{environment.supportPath || "未读取到 Support Path"}</p>
      </div>
      <div className={styles.pathBlock}>
        <strong>字体搜索根目录</strong>
        {environment.fontSearchRoots.length > 0 ? (
          <ul className={styles.pathList}>
            {environment.fontSearchRoots.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : (
          <p>暂无搜索根目录。</p>
        )}
      </div>
    </div>
  );
}
