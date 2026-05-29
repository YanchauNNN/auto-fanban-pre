import { startTransition, useEffect, useState } from "react";

import type { ApiAdapter, CreateBatchPayload, FormSchema } from "../../platform/api/types";
import { TaskConfigModal } from "../deliverable/TaskConfigModal";
import { inferProjectNumbers } from "../deliverable/uploadInference";
import styles from "../audit-check/AuditCheckWorkspace.module.css";

type ReplaceMode = "replace_only" | "replace_with_deliverable";

type ReplaceWorkspaceProps = {
  adapter: ApiAdapter;
  schema: FormSchema;
  isOpen: boolean;
  onBatchCreated: (payload: CreateBatchPayload) => void;
  onClose: () => void;
  onContinueToDeliverable: (payload: {
    files: File[];
    replaceConfig: {
      sourceProjectNo: string;
      sourceIslandNo: string;
      targetProjectNo: string;
      targetIslandNo: string;
      runDeliverable: boolean;
    };
  }) => void;
  onDraftAvailabilityChange: (available: boolean) => void;
};

type ReplaceDraft = {
  mode: ReplaceMode;
  sourceProjectNo: string;
  sourceIslandNo: string;
  targetProjectNo: string;
  targetIslandNo: string;
  files: File[];
  fieldErrors: Record<string, string[]>;
  formErrors: string[];
};

const REPLACE_DRAFT_STORAGE_KEY = "auto-fanban.replace-draft";
export function ReplaceWorkspace({
  adapter,
  schema,
  isOpen,
  onBatchCreated,
  onClose,
  onContinueToDeliverable,
  onDraftAvailabilityChange,
}: ReplaceWorkspaceProps) {
  const [draft, setDraft] = useState<ReplaceDraft>(() =>
    createReplaceDraft(loadPersistedReplaceDraft()),
  );
  const [manualFields, setManualFields] = useState({
    sourceProjectNo: false,
    sourceIslandNo: false,
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const projectOptions = (schema.auditReplaceProjectOptions ?? []).filter((option) => option.trim());
  const sourceIslandOptions = getSourceIslandOptions(schema, draft.sourceProjectNo);
  const sourceIslandLabel = getUnitFieldLabel("来源");
  const sourceSelectionRequired = sourceIslandOptions.length > 0;
  const targetIslandOptions = getTargetIslandOptions(schema, draft.targetProjectNo);
  const targetIslandLabel = getUnitFieldLabel("目标");
  const islandSelectionRequired = targetIslandOptions.length > 0;

  useEffect(() => {
    onDraftAvailabilityChange(
      Boolean(draft.sourceProjectNo.trim()) ||
        Boolean(draft.sourceIslandNo.trim()) ||
        Boolean(draft.targetProjectNo.trim()) ||
        Boolean(draft.targetIslandNo.trim()) ||
        draft.files.length > 0 ||
        draft.mode === "replace_with_deliverable",
    );
  }, [
    draft.files.length,
    draft.mode,
    draft.sourceProjectNo,
    draft.sourceIslandNo,
    draft.targetProjectNo,
    draft.targetIslandNo,
    onDraftAvailabilityChange,
  ]);

  useEffect(() => {
    persistReplaceDraft(draft);
  }, [
    draft.mode,
    draft.sourceProjectNo,
    draft.sourceIslandNo,
    draft.targetProjectNo,
    draft.targetIslandNo,
  ]);

  if (!isOpen) {
    return null;
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextFieldErrors: Record<string, string[]> = {};
    const nextFormErrors: string[] = [];

    if (!draft.sourceProjectNo.trim()) {
      nextFieldErrors.source_project_no = ["required"];
    }
    if (
      sourceSelectionRequired &&
      !sourceIslandOptions.some((option) => option.value === draft.sourceIslandNo.trim())
    ) {
      nextFieldErrors.source_island_no = ["required"];
    }
    if (!draft.targetProjectNo.trim()) {
      nextFieldErrors.target_project_no = ["required"];
    }
    if (
      islandSelectionRequired &&
      !draft.targetIslandNo.trim()
    ) {
      nextFieldErrors.target_island_no = ["required"];
    }
    if (
      draft.sourceProjectNo.trim() &&
      draft.targetProjectNo.trim() &&
      draft.sourceProjectNo.trim() === draft.targetProjectNo.trim()
    ) {
      nextFieldErrors.target_project_no = ["must_differ_from_source_project_no"];
    }
    if (draft.files.length === 0) {
      nextFormErrors.push("请至少上传一个 DWG 文件。");
    }

    const invalidFiles = draft.files.filter(
      (file) => !schema.uploadLimits.allowedExts.includes(getExtension(file.name)),
    );
    if (invalidFiles.length > 0) {
      nextFormErrors.push("only .dwg files are allowed");
    }

    const totalBytes = draft.files.reduce((sum, file) => sum + file.size, 0);
    if (totalBytes > schema.uploadLimits.maxTotalMb * 1024 * 1024) {
      nextFormErrors.push(`total upload exceeds ${schema.uploadLimits.maxTotalMb} MB`);
    }

    if (Object.keys(nextFieldErrors).length > 0 || nextFormErrors.length > 0) {
      setDraft((current) => ({
        ...current,
        fieldErrors: nextFieldErrors,
        formErrors: nextFormErrors,
      }));
      return;
    }

    setDraft((current) => ({
      ...current,
      fieldErrors: {},
      formErrors: [],
    }));

    if (draft.mode === "replace_with_deliverable") {
      startTransition(() =>
        onContinueToDeliverable({
          files: draft.files,
          replaceConfig: {
            sourceProjectNo: draft.sourceProjectNo.trim(),
            sourceIslandNo: normalizeSourceIslandNo(
              schema,
              draft.sourceProjectNo,
              draft.sourceIslandNo,
            ),
            targetProjectNo: draft.targetProjectNo.trim(),
            targetIslandNo: normalizeTargetIslandNo(
              schema,
              draft.targetProjectNo,
              draft.targetIslandNo,
            ),
            runDeliverable: true,
          },
        }),
      );
      onClose();
      return;
    }

    setIsSubmitting(true);

    try {
      const payload = await adapter.createAuditReplace({
        sourceProjectNo: draft.sourceProjectNo.trim(),
        sourceIslandNo: normalizeSourceIslandNo(schema, draft.sourceProjectNo, draft.sourceIslandNo),
        targetProjectNo: draft.targetProjectNo.trim(),
        targetIslandNo: normalizeTargetIslandNo(schema, draft.targetProjectNo, draft.targetIslandNo),
        files: draft.files,
        runDeliverable: false,
      });
      clearPersistedReplaceDraft();
      setDraft(createReplaceDraft());
      setManualFields({ sourceProjectNo: false, sourceIslandNo: false });
      startTransition(() => onBatchCreated(payload));
      onClose();
    } catch (error) {
      const detail =
        typeof error === "object" && error && "detail" in error
          ? (error as {
              detail?: {
                upload_errors?: Record<string, string[]>;
                param_errors?: Record<string, string[]>;
              };
            }).detail
          : undefined;

      setDraft((current) => ({
        ...current,
        fieldErrors: detail?.param_errors ?? {},
        formErrors: Object.values(detail?.upload_errors ?? {}).flat(),
      }));
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleModeChange(mode: ReplaceMode) {
    setDraft((current) => ({
      ...current,
      mode,
    }));
  }

  function handleFieldChange(
    field: "sourceProjectNo" | "sourceIslandNo" | "targetProjectNo" | "targetIslandNo",
    value: string,
  ) {
    if (field === "sourceProjectNo" || field === "sourceIslandNo") {
      setManualFields((current) => ({
        ...current,
        [field]: true,
      }));
    }
    const errorKey =
      field === "sourceProjectNo"
        ? "source_project_no"
        : field === "sourceIslandNo"
          ? "source_island_no"
          : field === "targetProjectNo"
            ? "target_project_no"
            : "target_island_no";
    setDraft((current) => ({
      ...current,
      [field]: value,
      ...(field === "sourceProjectNo" ? { sourceIslandNo: "" } : {}),
      ...(field === "targetProjectNo" ? { targetIslandNo: "" } : {}),
      fieldErrors: {
        ...current.fieldErrors,
        [errorKey]: [],
        ...(field === "sourceProjectNo" ? { source_island_no: [] } : {}),
        ...(field === "targetProjectNo" ? { target_island_no: [] } : {}),
      },
    }));
  }

  function handleFilesReplace(files: File[]) {
    if (files.length === 0) {
      return;
    }
    const inference = inferProjectNumbers(files);
    setDraft((current) => {
      const shouldUseInferredProjectNo =
        Boolean(inference.primaryProjectNo) &&
        (!manualFields.sourceProjectNo || !current.sourceProjectNo.trim());
      const nextSourceProjectNo = shouldUseInferredProjectNo
        ? inference.primaryProjectNo
        : current.sourceProjectNo;
      const nextSourceIslandOptions = getSourceIslandOptions(schema, nextSourceProjectNo);
      const inferredSourceIslandNo = nextSourceIslandOptions.some(
        (option) => option.value === inference.primaryUnitNo,
      )
        ? inference.primaryUnitNo
        : "";
      const shouldUseInferredSourceIslandNo =
        Boolean(inferredSourceIslandNo) &&
        (!manualFields.sourceIslandNo || !current.sourceIslandNo.trim());
      const keepCurrentSourceIsland =
        !shouldUseInferredSourceIslandNo && nextSourceProjectNo === current.sourceProjectNo;

      return {
        ...current,
        files,
        sourceProjectNo: nextSourceProjectNo,
        sourceIslandNo: shouldUseInferredSourceIslandNo
          ? inferredSourceIslandNo
          : keepCurrentSourceIsland
            ? current.sourceIslandNo
            : "",
        formErrors: [],
      };
    });
  }

  function handleClearDraft() {
    clearPersistedReplaceDraft();
    setDraft(createReplaceDraft());
    setManualFields({ sourceProjectNo: false, sourceIslandNo: false });
    onClose();
  }

  return (
    <TaskConfigModal title="翻版配置" onRequestClose={onClose}>
      <div className={styles.layout}>
        <header className={styles.header}>
          <div>
            <p className={styles.kicker}>Audit Replace</p>
            <h2>翻版配置</h2>
            <p className={styles.description}>
              本轮只接现有翻版 MVP，不做块替换配置。可选择仅翻版，或先翻版再进入现有出图配置。
            </p>
          </div>
          <div className={styles.headerActions}>
            <button className={styles.ghostButton} type="button" onClick={onClose}>
              关闭翻版配置
            </button>
          </div>
        </header>

        <form onSubmit={handleSubmit}>
          <div className={styles.content}>
            <section className={styles.summaryCard}>
              <div className={styles.summaryHeader}>
                <h3>文件摘要</h3>
                <span>{draft.files.length} 个</span>
              </div>
              <p className={styles.hint}>
                当前最多可上传 {schema.uploadLimits.maxFiles} 个 DWG，总大小不超过{" "}
                {schema.uploadLimits.maxTotalMb} MB。
              </p>
              {draft.files.length > 0 ? (
                <ul className={styles.fileList}>
                  {draft.files.map((file) => (
                    <li key={`${file.name}-${file.size}`}>
                      <span>{file.name}</span>
                      <span>{Math.max(1, Math.round(file.size / 1024))} KB</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className={styles.emptyState}>当前还没有翻版文件草稿。</p>
              )}
              <div className={styles.summaryActions}>
                <label className={`${styles.fileButton} ${styles.filePickerButton}`}>
                  <span>选择翻版 DWG 文件</span>
                  <input
                    accept=".dwg"
                    aria-label="选择翻版 DWG 文件"
                    className={styles.fileInputOverlay}
                    data-testid="replace-file-input"
                    multiple
                    type="file"
                    onChange={(event) => {
                      handleFilesReplace(Array.from(event.target.files ?? []));
                      event.currentTarget.value = "";
                    }}
                  />
                </label>
                <button className={styles.ghostButton} type="button" onClick={handleClearDraft}>
                  清空草稿
                </button>
              </div>
            </section>

            <section className={styles.formCard}>
              <h3>翻版参数</h3>

              {draft.formErrors.length > 0 ? (
                <div className={styles.formErrorPanel}>
                  {draft.formErrors.map((error) => (
                    <p key={error}>{error}</p>
                  ))}
                </div>
              ) : null}

              <div className={styles.fieldStack}>
                <div className={styles.field}>
                  <span className={styles.hintStrong}>执行模式</span>
                  <div className={styles.recommendations}>
                    <button
                      aria-pressed={draft.mode === "replace_only"}
                      className={`${styles.recommendationChip} ${
                        draft.mode === "replace_only" ? styles.recommendationChipActive : ""
                      }`}
                      type="button"
                      onClick={() => handleModeChange("replace_only")}
                    >
                      仅翻版
                    </button>
                    <button
                      aria-pressed={draft.mode === "replace_with_deliverable"}
                      className={`${styles.recommendationChip} ${
                        draft.mode === "replace_with_deliverable"
                          ? styles.recommendationChipActive
                          : ""
                      }`}
                      type="button"
                      onClick={() => handleModeChange("replace_with_deliverable")}
                    >
                      同步出图和翻版
                    </button>
                  </div>
                  <span className={styles.helperText}>
                    {draft.mode === "replace_only"
                      ? "提交后直接创建翻版任务。"
                      : "先确认源/目标项目号，再进入现有出图配置，最终由后端统一执行翻版+出图。"}
                  </span>
                </div>

                <div className={styles.field}>
                  <div className={styles.fieldHeader}>
                    <label className={styles.fieldLabel} htmlFor="replace-source-project-no">
                      <span>原始项目号</span>
                    </label>
                  </div>
                  <input
                    aria-label="原始项目号"
                    className={styles.input}
                    id="replace-source-project-no"
                    placeholder="请输入原始项目号"
                    type="text"
                    value={draft.sourceProjectNo}
                    onChange={(event) => handleFieldChange("sourceProjectNo", event.target.value)}
                  />
                  <span className={styles.helperText}>
                    与后端 `source_project_no` 对应。
                  </span>
                  {draft.fieldErrors.source_project_no?.[0] ? (
                    <span className={styles.errorText}>{draft.fieldErrors.source_project_no[0]}</span>
                  ) : null}
                </div>

                {sourceIslandOptions.length > 0 ? (
                  <div className={styles.field}>
                    <div className={styles.fieldHeader}>
                      <label className={styles.fieldLabel} htmlFor="replace-source-island-no">
                        <span>{sourceIslandLabel}</span>
                      </label>
                    </div>
                    <select
                      aria-label={sourceIslandLabel}
                      className={styles.input}
                      id="replace-source-island-no"
                      value={draft.sourceIslandNo}
                      onChange={(event) => handleFieldChange("sourceIslandNo", event.target.value)}
                    >
                      <option value="">{`请选择${sourceIslandLabel}`}</option>
                      {sourceIslandOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                    <span className={styles.helperText}>
                      当前来源项目需要区分机组或岛号，提交时会一并发送 <code>source_island_no</code>。
                    </span>
                    {draft.fieldErrors.source_island_no?.[0] ? (
                      <span className={styles.errorText}>{draft.fieldErrors.source_island_no[0]}</span>
                    ) : null}
                  </div>
                ) : null}

                <div className={styles.field}>
                  <div className={styles.fieldHeader}>
                    <label className={styles.fieldLabel} htmlFor="replace-target-project-no">
                      <span>目标项目号</span>
                    </label>
                  </div>
                  <input
                    aria-label="目标项目号"
                    className={styles.input}
                    id="replace-target-project-no"
                    placeholder="请输入目标项目号"
                    type="text"
                    value={draft.targetProjectNo}
                    onChange={(event) => handleFieldChange("targetProjectNo", event.target.value)}
                  />
                  <span className={styles.helperText}>
                    与后端 `target_project_no` 对应。
                  </span>
                  {draft.fieldErrors.target_project_no?.[0] ? (
                    <span className={styles.errorText}>{draft.fieldErrors.target_project_no[0]}</span>
                  ) : null}
                </div>

                {targetIslandOptions.length > 0 ? (
                  <div className={styles.field}>
                    <div className={styles.fieldHeader}>
                      <label className={styles.fieldLabel} htmlFor="replace-target-island-no">
                        <span>{targetIslandLabel}</span>
                      </label>
                    </div>
                    <input
                      aria-label={targetIslandLabel}
                      className={styles.input}
                      id="replace-target-island-no"
                      list="replace-target-island-options"
                      placeholder={`输入或选择${targetIslandLabel}`}
                      type="text"
                      value={draft.targetIslandNo}
                      onChange={(event) => handleFieldChange("targetIslandNo", event.target.value)}
                    />
                    <datalist id="replace-target-island-options">
                      {targetIslandOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </datalist>
                    <span className={styles.helperText}>
                      当前目标项目需要区分机组或岛号，提交时会一并发送 <code>target_island_no</code>。
                    </span>
                    {draft.fieldErrors.target_island_no?.[0] ? (
                      <span className={styles.errorText}>{draft.fieldErrors.target_island_no[0]}</span>
                    ) : null}
                  </div>
                ) : null}

                <div className={styles.field}>
                  <span className={styles.hintStrong}>推荐项目号</span>
                  <div className={styles.recommendations}>
                    {projectOptions.map((option) => (
                      <button
                        key={option}
                        className={styles.recommendationChip}
                        type="button"
                        onClick={() => {
                          if (!draft.sourceProjectNo.trim()) {
                            handleFieldChange("sourceProjectNo", option);
                            return;
                          }
                          handleFieldChange("targetProjectNo", option);
                        }}
                      >
                        {option}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </section>
          </div>

          <footer className={styles.actions}>
            <button className={styles.primaryButton} disabled={isSubmitting} type="submit">
              {draft.mode === "replace_only"
                ? isSubmitting
                  ? "创建中..."
                  : "开始翻版"
                : "出图"}
            </button>
          </footer>
        </form>
      </div>
    </TaskConfigModal>
  );
}

function createReplaceDraft(
  persistedDraft?: Partial<
    Pick<
      ReplaceDraft,
      "mode" | "sourceProjectNo" | "sourceIslandNo" | "targetProjectNo" | "targetIslandNo"
    >
  >,
): ReplaceDraft {
  return {
    mode: persistedDraft?.mode ?? "replace_only",
    sourceProjectNo: persistedDraft?.sourceProjectNo ?? "",
    sourceIslandNo: persistedDraft?.sourceIslandNo ?? "",
    targetProjectNo: persistedDraft?.targetProjectNo ?? "",
    targetIslandNo: persistedDraft?.targetIslandNo ?? "",
    files: [],
    fieldErrors: {},
    formErrors: [],
  };
}

function loadPersistedReplaceDraft(): Partial<
  Pick<
    ReplaceDraft,
    "mode" | "sourceProjectNo" | "sourceIslandNo" | "targetProjectNo" | "targetIslandNo"
  >
> {
  if (typeof window === "undefined") {
    return {};
  }

  try {
    const raw = window.localStorage.getItem(REPLACE_DRAFT_STORAGE_KEY);
    if (!raw) {
      return {};
    }

    const parsed = JSON.parse(raw) as Partial<ReplaceDraft> | null;
    if (!parsed || typeof parsed !== "object") {
      return {};
    }

    return {
      mode:
        parsed.mode === "replace_with_deliverable" ? "replace_with_deliverable" : "replace_only",
      sourceProjectNo:
        typeof parsed.sourceProjectNo === "string" ? parsed.sourceProjectNo : "",
      sourceIslandNo:
        typeof parsed.sourceIslandNo === "string" ? parsed.sourceIslandNo : "",
      targetProjectNo:
        typeof parsed.targetProjectNo === "string" ? parsed.targetProjectNo : "",
      targetIslandNo:
        typeof parsed.targetIslandNo === "string" ? parsed.targetIslandNo : "",
    };
  } catch {
    return {};
  }
}

function persistReplaceDraft(draft: ReplaceDraft) {
  if (typeof window === "undefined") {
    return;
  }

  const normalizedDraft = {
    mode: draft.mode,
    sourceProjectNo: draft.sourceProjectNo.trim(),
    sourceIslandNo: draft.sourceIslandNo.trim(),
    targetProjectNo: draft.targetProjectNo.trim(),
    targetIslandNo: draft.targetIslandNo.trim(),
  } as const;

  if (
    normalizedDraft.mode === "replace_only" &&
    !normalizedDraft.sourceProjectNo &&
    !normalizedDraft.sourceIslandNo &&
    !normalizedDraft.targetProjectNo &&
    !normalizedDraft.targetIslandNo
  ) {
    window.localStorage.removeItem(REPLACE_DRAFT_STORAGE_KEY);
    return;
  }

  window.localStorage.setItem(REPLACE_DRAFT_STORAGE_KEY, JSON.stringify(normalizedDraft));
}

function clearPersistedReplaceDraft() {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.removeItem(REPLACE_DRAFT_STORAGE_KEY);
}

function getExtension(filename: string) {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot).toLowerCase() : "";
}

function getTargetIslandOptions(schema: FormSchema, targetProjectNo: string) {
  const normalizedProjectNo = targetProjectNo.trim();
  const configuredOptions = schema.auditReplaceTargetUnitOptions?.[normalizedProjectNo];
  if (configuredOptions) {
    return normalizeUnitOptions(configuredOptions);
  }
  return buildVariantOptions(schema.auditReplaceFactoryIndexMaps?.targetVariantOptions[normalizedProjectNo]);
}

function getSourceIslandOptions(schema: FormSchema, sourceProjectNo: string) {
  const normalizedProjectNo = sourceProjectNo.trim();
  const configuredOptions = schema.auditReplaceSourceUnitOptions?.[normalizedProjectNo];
  if (configuredOptions) {
    return normalizeUnitOptions(configuredOptions);
  }
  return buildVariantOptions(schema.auditReplaceFactoryIndexMaps?.sourceVariantOptions[normalizedProjectNo]);
}

function buildVariantOptions(values: readonly string[] | undefined) {
  return (values ?? []).map((value) => ({
    value,
    label: `${value}号机组/岛`,
  }));
}

function normalizeUnitOptions(options: readonly { value: string; label: string }[]) {
  return options
    .map((option) => ({
      value: option.value.trim(),
      label: option.label.trim(),
    }))
    .filter((option) => option.value && option.label);
}

function getUnitFieldLabel(prefix: "来源" | "目标") {
  return `${prefix}机组号/岛号`;
}

function normalizeSourceIslandNo(schema: FormSchema, sourceProjectNo: string, sourceIslandNo: string) {
  const normalizedIslandNo = sourceIslandNo.trim();
  return getSourceIslandOptions(schema, sourceProjectNo).some(
    (option) => option.value === normalizedIslandNo,
  )
    ? normalizedIslandNo
    : "";
}

function normalizeTargetIslandNo(schema: FormSchema, targetProjectNo: string, targetIslandNo: string) {
  return targetIslandNo.trim();
}
