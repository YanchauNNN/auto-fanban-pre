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
const SOURCE_ISLAND_OPTIONS_BY_PROJECT = {
  "1916": [
    { value: "3", label: "3号岛" },
    { value: "4", label: "4号岛" },
  ],
  "2016": [
    { value: "1", label: "1号机组" },
    { value: "2", label: "2号机组" },
  ],
} as const;
const ISLAND_OPTIONS_BY_PROJECT = {
  "1916": [
    { value: "3", label: "3号岛" },
    { value: "4", label: "4号岛" },
  ],
  "2016": [
    { value: "1", label: "1号岛" },
    { value: "2", label: "2号岛" },
  ],
} as const;

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
  const [isSubmitting, setIsSubmitting] = useState(false);
  const projectOptions = (schema.auditReplaceProjectOptions ?? []).filter((option) => option.trim());
  const sourceIslandOptions = getSourceIslandOptions(draft.sourceProjectNo);
  const sourceSelectionRequired = sourceIslandOptions.length > 0;
  const targetIslandOptions = getTargetIslandOptions(draft.targetProjectNo);
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
      !targetIslandOptions.some((option) => option.value === draft.targetIslandNo.trim())
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
              draft.sourceProjectNo,
              draft.sourceIslandNo,
            ),
            targetProjectNo: draft.targetProjectNo.trim(),
            targetIslandNo: normalizeTargetIslandNo(
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
        sourceIslandNo: normalizeSourceIslandNo(draft.sourceProjectNo, draft.sourceIslandNo),
        targetProjectNo: draft.targetProjectNo.trim(),
        targetIslandNo: normalizeTargetIslandNo(draft.targetProjectNo, draft.targetIslandNo),
        files: draft.files,
        runDeliverable: false,
      });
      clearPersistedReplaceDraft();
      setDraft(createReplaceDraft());
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
    setDraft((current) => ({
      ...current,
      files,
      sourceProjectNo:
        current.sourceProjectNo.trim() || !inference.primaryProjectNo
          ? current.sourceProjectNo
          : inference.primaryProjectNo,
      formErrors: [],
    }));
  }

  function handleClearDraft() {
    clearPersistedReplaceDraft();
    setDraft(createReplaceDraft());
    onClose();
  }

  return (
    <TaskConfigModal title="翻版配置">
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
                <label className={styles.fileButton}>
                  选择翻版 DWG 文件
                  <input
                    accept=".dwg"
                    aria-label="选择翻版 DWG 文件"
                    className={styles.fileInput}
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
                        <span>{draft.sourceProjectNo.trim() === "2016" ? "来源机组号" : "来源岛号"}</span>
                      </label>
                    </div>
                    <select
                      aria-label={draft.sourceProjectNo.trim() === "2016" ? "来源机组号" : "来源岛号"}
                      className={styles.input}
                      id="replace-source-island-no"
                      value={draft.sourceIslandNo}
                      onChange={(event) => handleFieldChange("sourceIslandNo", event.target.value)}
                    >
                      <option value="">请选择{draft.sourceProjectNo.trim() === "2016" ? "来源机组号" : "来源岛号"}</option>
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
                        <span>目标岛号</span>
                      </label>
                    </div>
                    <select
                      aria-label="目标岛号"
                      className={styles.input}
                      id="replace-target-island-no"
                      value={draft.targetIslandNo}
                      onChange={(event) => handleFieldChange("targetIslandNo", event.target.value)}
                    >
                      <option value="">请选择目标岛号</option>
                      {targetIslandOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                    <span className={styles.helperText}>
                      当前目标项目需要区分岛号，提交时会一并发送 <code>target_island_no</code>。
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

function getTargetIslandOptions(targetProjectNo: string) {
  const normalizedProjectNo = targetProjectNo.trim();
  return ISLAND_OPTIONS_BY_PROJECT[
    normalizedProjectNo as keyof typeof ISLAND_OPTIONS_BY_PROJECT
  ] ?? [];
}

function getSourceIslandOptions(sourceProjectNo: string) {
  const normalizedProjectNo = sourceProjectNo.trim();
  return SOURCE_ISLAND_OPTIONS_BY_PROJECT[
    normalizedProjectNo as keyof typeof SOURCE_ISLAND_OPTIONS_BY_PROJECT
  ] ?? [];
}

function normalizeSourceIslandNo(sourceProjectNo: string, sourceIslandNo: string) {
  const normalizedIslandNo = sourceIslandNo.trim();
  return getSourceIslandOptions(sourceProjectNo).some((option) => option.value === normalizedIslandNo)
    ? normalizedIslandNo
    : "";
}

function normalizeTargetIslandNo(targetProjectNo: string, targetIslandNo: string) {
  const normalizedIslandNo = targetIslandNo.trim();
  return getTargetIslandOptions(targetProjectNo).some((option) => option.value === normalizedIslandNo)
    ? normalizedIslandNo
    : "";
}
