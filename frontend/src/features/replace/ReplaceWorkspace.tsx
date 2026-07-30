import { startTransition, useEffect, useMemo, useState } from "react";

import type { ApiAdapter, CreateBatchPayload, FormSchema } from "../../platform/api/types";
import { TaskConfigModal } from "../../shared/ui/TaskConfigModal";
import {
  inferProjectNumbers,
  inferReplaceBatchIdentity,
} from "../deliverable/uploadInference";
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
      unitFactoryCodes?: readonly string[];
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
  factoryCodesText: string;
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
    factoryCode: false,
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const projectOptions = (schema.auditReplaceProjectOptions ?? []).filter((option) => option.trim());
  const sourceIslandOptions = getSourceIslandOptions(schema, draft.sourceProjectNo);
  const sourceIslandLabel = getUnitFieldLabel("来源");
  const sourceSelectionRequired = sourceIslandOptions.length > 0;
  const targetIslandOptions = getTargetIslandOptions(schema, draft.targetProjectNo);
  const targetIslandLabel = getUnitFieldLabel("目标");
  const islandSelectionRequired = targetIslandOptions.length > 0;
  const factoryCodeOptions = schema.auditReplaceUnitFactoryCodes ?? [];
  const unitFactoryCodes = parseFactoryCodes(draft.factoryCodesText);
  const batchIdentity = useMemo(
    () =>
      inferReplaceBatchIdentity(
        draft.files,
        schema.auditReplaceBatchFilenameIdentityRegex,
      ),
    [draft.files, schema.auditReplaceBatchFilenameIdentityRegex],
  );

  useEffect(() => {
    onDraftAvailabilityChange(
      Boolean(draft.sourceProjectNo.trim()) ||
        Boolean(draft.sourceIslandNo.trim()) ||
        Boolean(draft.targetProjectNo.trim()) ||
        Boolean(draft.targetIslandNo.trim()) ||
        Boolean(draft.factoryCodesText.trim()) ||
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
    draft.factoryCodesText,
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
    draft.factoryCodesText,
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
    if (unitFactoryCodes.length !== 1) {
      nextFieldErrors.unit_factory_codes = [
        unitFactoryCodes.length === 0 ? "required" : "single_factory_code_required",
      ];
    }
    const normalizedSourceProjectNo = draft.sourceProjectNo.trim();
    const normalizedTargetProjectNo = draft.targetProjectNo.trim();
    const normalizedSourceIslandNo = normalizeSourceIslandNo(
      schema,
      draft.sourceProjectNo,
      draft.sourceIslandNo,
    );
    const normalizedTargetIslandNo = normalizeTargetIslandNo(
      schema,
      draft.targetProjectNo,
      draft.targetIslandNo,
    );
    if (
      normalizedSourceProjectNo &&
      normalizedTargetProjectNo &&
      normalizedSourceProjectNo === normalizedTargetProjectNo
    ) {
      if (!normalizedSourceIslandNo && !normalizedTargetIslandNo) {
        nextFieldErrors.target_project_no = ["must_differ_from_source_project_no"];
      } else if (
        normalizedSourceIslandNo &&
        normalizedTargetIslandNo &&
        normalizedSourceIslandNo === normalizedTargetIslandNo
      ) {
        nextFieldErrors.target_island_no = ["must_differ_from_source_island_no"];
      }
    }
    if (draft.files.length === 0) {
      nextFormErrors.push("请至少上传一个 DWG 文件。");
    }
    if (draft.files.length > schema.uploadLimits.maxFiles) {
      nextFormErrors.push(`单次最多上传 ${schema.uploadLimits.maxFiles} 个 DWG 文件。`);
    }
    nextFormErrors.push(
      ...buildBatchIdentityErrors({
        inference: batchIdentity,
        sourceProjectNo: normalizedSourceProjectNo,
        sourceUnitNo: normalizedSourceIslandNo,
        factoryCode: unitFactoryCodes[0] ?? "",
      }),
    );

    const invalidFiles = draft.files.filter(
      (file) => !schema.uploadLimits.allowedExts.includes(getExtension(file.name)),
    );
    if (invalidFiles.length > 0) {
      nextFormErrors.push("只能上传 DWG 文件。");
    }

    const totalBytes = draft.files.reduce((sum, file) => sum + file.size, 0);
    if (totalBytes > schema.uploadLimits.maxTotalMb * 1024 * 1024) {
      nextFormErrors.push(`文件总大小不能超过 ${schema.uploadLimits.maxTotalMb} MB。`);
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
      setIsSubmitting(true);
      try {
        await rememberFactoryCodes(unitFactoryCodes);
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
              unitFactoryCodes,
              runDeliverable: true,
            },
          }),
        );
        onClose();
      } catch {
        setDraft((current) => ({
          ...current,
          fieldErrors: { ...current.fieldErrors, unit_factory_codes: ["remember_failed"] },
        }));
      } finally {
        setIsSubmitting(false);
      }
      return;
    }

    setIsSubmitting(true);

    try {
      await rememberFactoryCodes(unitFactoryCodes);
      const payload = await adapter.createAuditReplace({
        sourceProjectNo: draft.sourceProjectNo.trim(),
        sourceIslandNo: normalizeSourceIslandNo(schema, draft.sourceProjectNo, draft.sourceIslandNo),
        targetProjectNo: draft.targetProjectNo.trim(),
        targetIslandNo: normalizeTargetIslandNo(schema, draft.targetProjectNo, draft.targetIslandNo),
        unitFactoryCodes,
        files: draft.files,
        runDeliverable: false,
      });
      clearPersistedReplaceDraft();
      setDraft(createReplaceDraft());
      setManualFields({ sourceProjectNo: false, sourceIslandNo: false, factoryCode: false });
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
    field: "sourceProjectNo" | "sourceIslandNo" | "targetProjectNo" | "targetIslandNo" | "factoryCodesText",
    value: string,
  ) {
    if (
      field === "sourceProjectNo" ||
      field === "sourceIslandNo" ||
      field === "factoryCodesText"
    ) {
      setManualFields((current) => ({
        ...current,
        [field === "factoryCodesText" ? "factoryCode" : field]: true,
      }));
    }
    const errorKey =
      field === "sourceProjectNo"
        ? "source_project_no"
        : field === "sourceIslandNo"
          ? "source_island_no"
          : field === "targetProjectNo"
            ? "target_project_no"
            : field === "targetIslandNo"
              ? "target_island_no"
              : "unit_factory_codes";
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

  async function rememberFactoryCodes(codes: readonly string[]) {
    if (codes.length === 0) {
      return;
    }
    await adapter.rememberAuditReplaceFactoryCodes(codes);
  }

  function handleFilesReplace(files: File[]) {
    if (files.length === 0) {
      return;
    }
    const inference = inferProjectNumbers(files);
    const identity = inferReplaceBatchIdentity(
      files,
      schema.auditReplaceBatchFilenameIdentityRegex,
    );
    setDraft((current) => {
      const shouldUseInferredProjectNo =
        Boolean(identity.primaryProjectNo || inference.primaryProjectNo) &&
        (!manualFields.sourceProjectNo || !current.sourceProjectNo.trim());
      const inferredProjectNo = identity.primaryProjectNo || inference.primaryProjectNo;
      const nextSourceProjectNo = shouldUseInferredProjectNo
        ? inferredProjectNo
        : current.sourceProjectNo;
      const nextSourceIslandOptions = getSourceIslandOptions(schema, nextSourceProjectNo);
      const inferredSourceIslandNo = nextSourceIslandOptions.some(
        (option) => option.value === (identity.primaryUnitNo || inference.primaryUnitNo),
      )
        ? identity.primaryUnitNo || inference.primaryUnitNo
        : "";
      const shouldUseInferredSourceIslandNo =
        Boolean(inferredSourceIslandNo) &&
        (!manualFields.sourceIslandNo || !current.sourceIslandNo.trim());
      const keepCurrentSourceIsland =
        !shouldUseInferredSourceIslandNo && nextSourceProjectNo === current.sourceProjectNo;
      const nextFactoryCode =
        identity.primaryFactoryCode &&
        (!manualFields.factoryCode || !current.factoryCodesText.trim())
          ? identity.primaryFactoryCode
          : current.factoryCodesText;

      return {
        ...current,
        files,
        sourceProjectNo: nextSourceProjectNo,
        sourceIslandNo: shouldUseInferredSourceIslandNo
          ? inferredSourceIslandNo
          : keepCurrentSourceIsland
            ? current.sourceIslandNo
            : "",
        factoryCodesText: nextFactoryCode,
        fieldErrors: {
          ...current.fieldErrors,
          source_project_no: [],
          source_island_no: [],
          unit_factory_codes: [],
        },
        formErrors: buildBatchIdentityErrors({
          inference: identity,
          sourceProjectNo: shouldUseInferredProjectNo
            ? inferredProjectNo
            : current.sourceProjectNo.trim(),
          sourceUnitNo: shouldUseInferredSourceIslandNo
            ? inferredSourceIslandNo
            : current.sourceIslandNo.trim(),
          factoryCode: nextFactoryCode.trim().toUpperCase(),
        }),
      };
    });
  }

  function handleClearDraft() {
    clearPersistedReplaceDraft();
    setDraft(createReplaceDraft());
    setManualFields({ sourceProjectNo: false, sourceIslandNo: false, factoryCode: false });
    onDraftAvailabilityChange(false);
    onClose();
  }

  return (
    <TaskConfigModal title="标准化出图配置" onRequestClose={onClose}>
      <div className={`${styles.layout} ${styles.replaceLayout}`}>
        <header className={styles.header}>
          <div>
            <p className={styles.kicker}>Drawing Standardization</p>
            <h2>标准化出图配置</h2>
            <p className={styles.description}>
              支持单批最多 {schema.uploadLimits.maxFiles} 个 DWG。同一批文件须来自同一项目、同一机组号或岛号和同一厂房代码，并统一转换到同一目标项目。
            </p>
          </div>
          <div className={styles.headerActions}>
            <button className={styles.ghostButton} type="button" onClick={onClose}>
              关闭标准化出图配置
            </button>
          </div>
        </header>

        <form onSubmit={handleSubmit}>
          <div className={`${styles.content} ${styles.replaceContent}`}>
            <section className={`${styles.summaryCard} ${styles.replaceSummaryCard}`}>
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
                <p className={styles.emptyState}>当前还没有待标准化的文件。</p>
              )}
              <div className={styles.summaryActions}>
                <label className={`${styles.fileButton} ${styles.filePickerButton}`}>
                  <span>选择标准化出图 DWG 文件</span>
                  <input
                    accept=".dwg"
                    aria-label="选择标准化出图 DWG 文件"
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
              <div className={styles.replaceFactoryCodes}>
                <div className={styles.fieldHeader}>
                  <label className={styles.fieldLabel} htmlFor="replace-factory-codes">
                    <span>厂房代码</span>
                  </label>
                </div>
                <input
                  aria-label="厂房代码"
                  className={styles.input}
                  id="replace-factory-codes"
                  list="replace-factory-code-options"
                  placeholder="例如 RC"
                  type="text"
                  value={draft.factoryCodesText}
                  onChange={(event) => handleFieldChange("factoryCodesText", event.target.value)}
                />
                <datalist id="replace-factory-code-options">
                  {factoryCodeOptions.map((code) => (
                    <option key={code} value={code} />
                  ))}
                </datalist>
                {factoryCodeOptions.length > 0 ? (
                  <div className={styles.compactChips}>
                    {factoryCodeOptions.map((code) => (
                      <button
                        key={code}
                        className={styles.recommendationChip}
                        type="button"
                        onClick={() =>
                          handleFieldChange("factoryCodesText", code)
                        }
                      >
                        {code}
                      </button>
                    ))}
                  </div>
                ) : null}
                <span className={styles.helperText}>
                  每批只能填写一个厂房代码，系统会将同一批图纸按统一规则处理。
                </span>
                {draft.fieldErrors.unit_factory_codes?.[0] ? (
                  <span className={styles.errorText}>
                    {formatReplaceValidationMessage(draft.fieldErrors.unit_factory_codes[0])}
                  </span>
                ) : null}
              </div>
            </section>

            <section className={`${styles.formCard} ${styles.replaceFormCard}`}>
              <h3>标准化参数</h3>

              {draft.formErrors.length > 0 ? (
                <div className={styles.formErrorPanel}>
                  {draft.formErrors.map((error) => (
                    <p key={error}>{formatReplaceValidationMessage(error)}</p>
                  ))}
                </div>
              ) : null}

              <div className={`${styles.fieldStack} ${styles.replaceFieldStack}`}>
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
                      仅标准化出图
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
                      标准化后继续出图
                    </button>
                  </div>
                  <span className={styles.helperText}>
                    {draft.mode === "replace_only"
                      ? "提交后直接创建标准化出图任务。"
                      : "先确认来源和目标信息，再进入出图配置，系统将依次完成标准化处理和出图。"}
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
                    同一批文件必须来自这里选择的项目。
                  </span>
                  {draft.fieldErrors.source_project_no?.[0] ? (
                    <span className={styles.errorText}>
                      {formatReplaceValidationMessage(draft.fieldErrors.source_project_no[0])}
                    </span>
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
                      同一批文件必须使用这里选择的来源机组号或岛号。
                    </span>
                    {draft.fieldErrors.source_island_no?.[0] ? (
                      <span className={styles.errorText}>
                        {formatReplaceValidationMessage(draft.fieldErrors.source_island_no[0])}
                      </span>
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
                    同一批文件将统一转换到这里选择的目标项目。
                  </span>
                  {draft.fieldErrors.target_project_no?.[0] ? (
                    <span className={styles.errorText}>
                      {formatReplaceValidationMessage(draft.fieldErrors.target_project_no[0])}
                    </span>
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
                      同一批文件将统一转换为这里选择的目标机组号或岛号。
                    </span>
                    {draft.fieldErrors.target_island_no?.[0] ? (
                      <span className={styles.errorText}>
                        {formatReplaceValidationMessage(draft.fieldErrors.target_island_no[0])}
                      </span>
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

          <footer className={`${styles.actions} ${styles.replaceActions}`}>
            <button className={styles.primaryButton} disabled={isSubmitting} type="submit">
              {draft.mode === "replace_only"
                ? isSubmitting
                  ? "创建中..."
                  : "开始标准化出图"
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
      | "mode"
      | "sourceProjectNo"
      | "sourceIslandNo"
      | "targetProjectNo"
      | "targetIslandNo"
      | "factoryCodesText"
    >
  >,
): ReplaceDraft {
  return {
    mode: persistedDraft?.mode ?? "replace_only",
    sourceProjectNo: persistedDraft?.sourceProjectNo ?? "",
    sourceIslandNo: persistedDraft?.sourceIslandNo ?? "",
    targetProjectNo: persistedDraft?.targetProjectNo ?? "",
    targetIslandNo: persistedDraft?.targetIslandNo ?? "",
    factoryCodesText: persistedDraft?.factoryCodesText ?? "",
    files: [],
    fieldErrors: {},
    formErrors: [],
  };
}

function loadPersistedReplaceDraft(): Partial<
    Pick<
      ReplaceDraft,
      | "mode"
      | "sourceProjectNo"
      | "sourceIslandNo"
      | "targetProjectNo"
      | "targetIslandNo"
      | "factoryCodesText"
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
      factoryCodesText:
        typeof parsed.factoryCodesText === "string" ? parsed.factoryCodesText : "",
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
    factoryCodesText: draft.factoryCodesText.trim(),
  } as const;

  if (
    normalizedDraft.mode === "replace_only" &&
    !normalizedDraft.sourceProjectNo &&
    !normalizedDraft.sourceIslandNo &&
    !normalizedDraft.targetProjectNo &&
    !normalizedDraft.targetIslandNo &&
    !normalizedDraft.factoryCodesText
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
  const projectUnits = schema.auditReplaceProjectUnits?.[normalizedProjectNo];
  if (projectUnits) {
    return buildVariantOptions(projectUnits);
  }
  return buildVariantOptions(schema.auditReplaceFactoryIndexMaps?.targetVariantOptions[normalizedProjectNo]);
}

function getSourceIslandOptions(schema: FormSchema, sourceProjectNo: string) {
  const normalizedProjectNo = sourceProjectNo.trim();
  const configuredOptions = schema.auditReplaceSourceUnitOptions?.[normalizedProjectNo];
  if (configuredOptions) {
    return normalizeUnitOptions(configuredOptions);
  }
  const projectUnits = schema.auditReplaceProjectUnits?.[normalizedProjectNo];
  if (projectUnits) {
    return buildVariantOptions(projectUnits);
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

function parseFactoryCodes(value: string) {
  const seen = new Set<string>();
  const codes: string[] = [];
  for (const part of value.split(/[\s,，;；、]+/)) {
    const normalized = part.trim().toUpperCase();
    if (!/^(?:[A-Z][A-Z0-9]{1,3}|\d{3})$/.test(normalized) || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    codes.push(normalized);
  }
  return codes;
}

function buildBatchIdentityErrors({
  inference,
  sourceProjectNo,
  sourceUnitNo,
  factoryCode,
}: {
  inference: ReturnType<typeof inferReplaceBatchIdentity>;
  sourceProjectNo: string;
  sourceUnitNo: string;
  factoryCode: string;
}) {
  const errors: string[] = [];
  if (inference.hasProjectConflict) {
    errors.push("同一批文件只能来自同一个来源项目。");
  } else if (
    inference.primaryProjectNo &&
    sourceProjectNo &&
    inference.primaryProjectNo !== sourceProjectNo
  ) {
    errors.push(`文件名识别到的来源项目为 ${inference.primaryProjectNo}，与当前选择不一致。`);
  }
  if (inference.hasUnitConflict) {
    errors.push("同一批文件只能来自同一个机组号或岛号。");
  } else if (
    inference.primaryUnitNo &&
    sourceUnitNo &&
    inference.primaryUnitNo !== sourceUnitNo
  ) {
    errors.push(`文件名识别到的来源机组号或岛号为 ${inference.primaryUnitNo}，与当前选择不一致。`);
  }
  if (inference.hasFactoryConflict) {
    errors.push("同一批文件只能使用同一个厂房代码。");
  } else if (
    inference.primaryFactoryCode &&
    factoryCode &&
    inference.primaryFactoryCode !== factoryCode
  ) {
    errors.push(`文件名识别到的厂房代码为 ${inference.primaryFactoryCode}，与当前选择不一致。`);
  }
  return errors;
}

function formatReplaceValidationMessage(message: string) {
  const messages: Record<string, string> = {
    required: "此项为必填项。",
    required_for_replace: "此项为标准化出图必填项。",
    required_for_source_project: "请选择来源机组号或岛号。",
    required_for_target_project: "请选择目标机组号或岛号。",
    single_factory_code_required: "每批只能填写一个厂房代码。",
    invalid_factory_code: "厂房代码格式不正确。",
    remember_failed: "厂房代码保存失败，请重试。",
    must_differ_from_source_project_no: "目标项目必须与来源项目不同。",
    must_differ_from_source_island_no: "同项目标准化时，目标机组号或岛号必须与来源不同。",
    unsupported_source_island_no: "来源机组号或岛号不在当前项目的可选范围内。",
    unsupported_target_island_no: "目标机组号或岛号不在当前项目的可选范围内。",
    mixed_source_projects: "同一批文件只能来自同一个来源项目。",
    mixed_source_units: "同一批文件只能来自同一个机组号或岛号。",
    mixed_factory_codes: "同一批文件只能使用同一个厂房代码。",
    source_project_mismatch: "文件来源项目与当前选择不一致。",
    source_unit_mismatch: "文件来源机组号或岛号与当前选择不一致。",
    factory_code_mismatch: "文件厂房代码与当前选择不一致。",
  };
  return messages[message] ?? message;
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
