import {
  startTransition,
  useDeferredValue,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  evaluateRequiredWhen,
  isAdvancedField,
  isCustomRenderedField,
} from "../schema/schema";
import type {
  ApiAdapter,
  CreateBatchPayload,
  FormField,
  FormSchema,
  TaskConfigDraft,
  TaskConfigPreset,
} from "../../platform/api/types";
import {
  applyTaskPreset,
  createTaskPreset,
  deleteTaskPreset,
  loadTaskPresets,
  renameTaskPreset,
  saveTaskPreset,
  updateTaskPreset,
} from "./taskPresets";
import { createTaskConfigDraft, getDefaultTaskValues, syncTaskConfigDraft } from "./taskDraft";
import { inferProjectNumbers } from "./uploadInference";
import { TaskConfigModal } from "./TaskConfigModal";
import styles from "./DeliverableWorkspace.module.css";

type DeliverableWorkspaceProps = {
  adapter: ApiAdapter;
  schema: FormSchema;
  isOpen: boolean;
  incomingFiles: File[];
  pendingReplaceConfig?: {
    sourceProjectNo: string;
    targetProjectNo: string;
    runDeliverable: boolean;
  } | null;
  onBatchCreated: (payload: CreateBatchPayload) => void;
  onNotice?: (message: string) => void;
  onClearPendingReplaceFlow?: () => void;
  onClose: () => void;
  onDraftAvailabilityChange: (available: boolean) => void;
};

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const NAME_ID_PATTERN = /^.+@.+$/;
const MAX_COMBO_OPTIONS = 10;
const FULL_MENU_COMBOBOX_FIELDS = new Set(["project_no", "cover_variant"]);
const SCROLLABLE_FULL_OPTION_FIELDS = new Set(["file_category"]);
const LEGACY_UPGRADE_KEYS = new Set([
  "upgrade_start_seq",
  "upgrade_end_seq",
  "upgrade_revision",
  "upgrade_note_text",
]);
const PLOT_STYLE_OPTIONS = [
  { key: "red_wider", label: "红色更宽" },
  { key: "same_width", label: "同线宽" },
  { key: "review_white", label: "交审图" },
] as const;

export function DeliverableWorkspace({
  adapter,
  schema,
  isOpen,
  incomingFiles,
  pendingReplaceConfig = null,
  onBatchCreated,
  onNotice,
  onClearPendingReplaceFlow,
  onClose,
  onDraftAvailabilityChange,
}: DeliverableWorkspaceProps) {
  const [draft, setDraft] = useState<TaskConfigDraft>(() => createTaskConfigDraft(schema));
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [savedPresets, setSavedPresets] = useState<TaskConfigPreset[]>(() => loadTaskPresets());
  const [selectedPresetId, setSelectedPresetId] = useState("");
  const [presetName, setPresetName] = useState("");
  const [presetError, setPresetError] = useState<string | null>(null);
  const [presetUpdatedNotice, setPresetUpdatedNotice] = useState(false);

  useEffect(() => {
    setDraft((current) => syncTaskConfigDraft(schema, current));
  }, [schema]);

  useEffect(() => {
    if (incomingFiles.length === 0) {
      return;
    }

    setDraft((current) =>
      applyFilesToDraft(syncTaskConfigDraft(schema, current), incomingFiles, pendingReplaceConfig),
    );
  }, [incomingFiles, pendingReplaceConfig, schema]);

  const primarySections = useMemo(
    () => filterSections(schema, draft.values, false),
    [draft.values, schema],
  );
  const advancedSections = useMemo(
    () => filterSections(schema, draft.values, true),
    [draft.values, schema],
  );
  const coverRevisionField = useMemo(
    () => findSchemaField(schema, "cover_revision"),
    [schema],
  );
  const upgradeSheetCodesField = useMemo(
    () => findSchemaField(schema, "upgrade_sheet_codes"),
    [schema],
  );
  const upgradeEnabled = draft.values.is_upgrade === "true";
  const selectedPreset = useMemo(
    () => savedPresets.find((preset) => preset.id === selectedPresetId) ?? null,
    [savedPresets, selectedPresetId],
  );

  useEffect(() => {
    if (!upgradeEnabled) {
      return;
    }

    const schemaDefault = coverRevisionField?.defaultValue?.trim() ?? "";
    const currentCoverRevision = draft.values.cover_revision?.trim() ?? "";
    if (
      currentCoverRevision &&
      currentCoverRevision !== schemaDefault &&
      currentCoverRevision !== "A"
    ) {
      return;
    }

    setDraft((current) => {
      const nextCurrentCover = current.values.cover_revision?.trim() ?? "";
      if (
        nextCurrentCover &&
        nextCurrentCover !== schemaDefault &&
        nextCurrentCover !== "A"
      ) {
        return current;
      }

      return {
        ...current,
        values: {
          ...current.values,
          cover_revision: "B",
        },
        fieldErrors: {
          ...current.fieldErrors,
          cover_revision: [],
        },
      };
    });
  }, [coverRevisionField?.defaultValue, draft.values.cover_revision, upgradeEnabled]);

  useEffect(() => {
    onDraftAvailabilityChange(hasTaskConfigDraft(schema, draft));
  }, [draft, onDraftAvailabilityChange, schema]);

  if (!isOpen) {
    return null;
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextFieldErrors: Record<string, string[]> = {};
    const nextFormErrors: string[] = [];

    for (const field of schema.sections.flatMap((section) => section.fields)) {
      const value = draft.values[field.key]?.trim() ?? "";
      const required =
        field.required || evaluateRequiredWhen(field.requiredWhen, draft.values);

      if (required && !value) {
        nextFieldErrors[field.key] = ["required"];
        continue;
      }

      if (value && field.type === "date" && !DATE_PATTERN.test(value)) {
        nextFieldErrors[field.key] = ["YYYY-MM-DD"];
      }

      if (value && field.type === "nameId" && !NAME_ID_PATTERN.test(value)) {
        nextFieldErrors[field.key] = ["姓名@ID"];
      }
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
    setIsSubmitting(true);

    const submissionValues = buildSubmissionValues(draft.values);

    try {
      const payload = pendingReplaceConfig?.runDeliverable
        ? await adapter.createAuditReplace({
            sourceProjectNo: pendingReplaceConfig.sourceProjectNo,
            targetProjectNo: pendingReplaceConfig.targetProjectNo,
            files: draft.files,
            runDeliverable: true,
            deliverableParams: submissionValues,
          })
        : await adapter.createBatch(submissionValues, draft.files, draft.runAuditCheck);
      onNotice?.(
        pendingReplaceConfig?.runDeliverable
          ? "翻版与出图任务包已创建。"
          : draft.runAuditCheck
            ? "出图与纠错任务包已创建。"
            : "出图任务已创建。",
      );

      setDraft(createTaskConfigDraft(schema));
      setShowAdvanced(false);
      onClearPendingReplaceFlow?.();
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

  function handleFieldChange(key: string, value: string) {
    setPresetUpdatedNotice(false);
    setDraft((current) => ({
      ...current,
      values: {
        ...current.values,
        [key]: value,
      },
      fieldErrors: {
        ...current.fieldErrors,
        [key]: [],
      },
    }));
  }

  function handleUpgradeToggle() {
    setPresetUpdatedNotice(false);
    const schemaDefault = coverRevisionField?.defaultValue?.trim() ?? "";
    setDraft((current) => ({
      ...current,
      values: {
        ...current.values,
        is_upgrade: current.values.is_upgrade === "true" ? "false" : "true",
        cover_revision:
          current.values.is_upgrade === "true"
            ? current.values.cover_revision ?? ""
            : !current.values.cover_revision?.trim() ||
                current.values.cover_revision?.trim() === schemaDefault ||
                current.values.cover_revision?.trim() === "A"
              ? "B"
              : current.values.cover_revision,
      },
      fieldErrors: {
        ...current.fieldErrors,
        is_upgrade: [],
        upgrade_sheet_codes: [],
      },
    }));
  }

  function handleReplaceFiles(files: File[]) {
    if (files.length === 0) {
      return;
    }

    setPresetUpdatedNotice(false);
    setDraft((current) =>
      applyFilesToDraft(syncTaskConfigDraft(schema, current), files, pendingReplaceConfig),
    );
  }

  function handleClearDraft() {
    setPresetUpdatedNotice(false);
    setDraft(createTaskConfigDraft(schema));
    setShowAdvanced(false);
    setPresetError(null);
    onClearPendingReplaceFlow?.();
    onClose();
  }

  function handleClose() {
    setPresetError(null);
    onClose();
  }

  function handleAuditToggle() {
    setPresetUpdatedNotice(false);
    setDraft((current) => ({
      ...current,
      runAuditCheck: !current.runAuditCheck,
    }));
  }

  function handlePresetSelectionChange(nextId: string) {
    setPresetUpdatedNotice(false);
    setSelectedPresetId(nextId);
    setPresetName(savedPresets.find((preset) => preset.id === nextId)?.name ?? "");
    setPresetError(null);
  }

  function handleSavePreset() {
    const trimmedName = presetName.trim();
    if (!trimmedName) {
      setPresetError("请先填写方案名称。");
      return;
    }

    const nextPreset = createTaskPreset(trimmedName, toDeliverableOnlyDraft(draft));
    const nextPresets = saveTaskPreset(nextPreset);
    setSavedPresets(nextPresets);
    setSelectedPresetId(nextPreset.id);
    setPresetName(trimmedName);
    setPresetError(null);
    setPresetUpdatedNotice(false);
  }

  function handleApplyPreset() {
    if (!selectedPreset) {
      setPresetError("请先选择一个已保存方案。");
      return;
    }

    setDraft((current) =>
      toDeliverableOnlyDraft(applyTaskPreset(schema, current, selectedPreset)),
    );
    setShowAdvanced(false);
    setPresetError(null);
    setPresetUpdatedNotice(false);
  }

  function handleRenamePreset() {
    const trimmedName = presetName.trim();
    if (!selectedPresetId) {
      setPresetError("请先选择一个已保存方案。");
      return;
    }
    if (!trimmedName) {
      setPresetError("请先填写新的方案名称。");
      return;
    }

    const nextPresets = renameTaskPreset(selectedPresetId, trimmedName);
    setSavedPresets(nextPresets);
    setPresetName(trimmedName);
    setPresetError(null);
    setPresetUpdatedNotice(false);
  }

  function handleUpdatePreset() {
    const trimmedName = presetName.trim();
    if (!selectedPresetId) {
      setPresetError("请先选择一个已保存方案。");
      return;
    }
    if (!trimmedName) {
      setPresetError("请先填写方案名称。");
      return;
    }

    const nextPreset = updateTaskPreset(
      selectedPresetId,
      trimmedName,
      toDeliverableOnlyDraft(draft),
    );
    const nextPresets = saveTaskPreset(nextPreset);
    setSavedPresets(nextPresets);
    setPresetName(trimmedName);
    setPresetError(null);
    setPresetUpdatedNotice(true);
  }

  function handleDeletePreset() {
    if (!selectedPresetId) {
      setPresetError("请先选择一个已保存方案。");
      return;
    }

    const nextPresets = deleteTaskPreset(selectedPresetId);
    setSavedPresets(nextPresets);
    setSelectedPresetId("");
    setPresetName("");
    setPresetError(null);
    setPresetUpdatedNotice(false);
  }

  const submitLabel = "创建交付任务";

  return (
    <>
      <TaskConfigModal title="任务配置">
        <div className={styles.modalLayout}>
          <header className={styles.modalHeader}>
            <div>
              <p className={styles.kicker}>Task Config</p>
              <h2>任务配置</h2>
              <p className={styles.description}>
                上传文件后直接在弹窗内完成配置。关闭不会丢失草稿；只有手动清空或提交成功后才会重置。
              </p>
            </div>
            <div className={styles.headerActions}>
              <button
                className={styles.secondaryButton}
                type="button"
                onClick={() => setShowAdvanced((current) => !current)}
              >
                {showAdvanced ? "收起高级选项" : "展开高级选项"}
              </button>
              <button className={styles.ghostButton} type="button" onClick={handleClose}>
                关闭任务配置
              </button>
            </div>
          </header>

          <form className={styles.form} onSubmit={handleSubmit}>
            <section className={styles.sidebarPanel}>
              <div className={styles.summaryCard}>
                <div className={styles.summaryHeaderRow}>
                  <h3>文件摘要</h3>
                  <span>{draft.files.length} 个</span>
                </div>
                <p className={styles.summaryMeta}>
                  单次上限 {schema.uploadLimits.maxFiles} 个文件，总大小不超过{" "}
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
                  <p className={styles.emptyState}>当前还没有文件草稿。</p>
                )}

                <div className={styles.summaryActions}>
                  <label className={styles.fileButton}>
                    重新选择文件
                    <input
                      accept=".dwg"
                      aria-label="重新选择 DWG 文件"
                      className={styles.fileInput}
                      multiple
                      type="file"
                      onChange={(event) => {
                        handleReplaceFiles(Array.from(event.target.files ?? []));
                        event.currentTarget.value = "";
                      }}
                    />
                  </label>
                  <button className={styles.ghostButton} type="button" onClick={handleClearDraft}>
                    清空草稿
                  </button>
                </div>
              </div>

              <div className={styles.summaryCard}>
                <div className={styles.summaryHeaderRow}>
                  <h3>配置方案</h3>
                  <span>{savedPresets.length} 个</span>
                </div>
                <div className={styles.presetStack}>
                  <input
                    aria-label="方案名称"
                    className={styles.input}
                    placeholder="输入方案名称"
                    type="text"
                    value={presetName}
                    onChange={(event) => {
                      setPresetName(event.target.value);
                      setPresetUpdatedNotice(false);
                    }}
                  />
                  <div className={styles.presetButtonRow}>
                    <button className={styles.secondaryButton} type="button" onClick={handleSavePreset}>
                      保存为新方案
                    </button>
                    <button className={styles.secondaryButton} type="button" onClick={handleApplyPreset}>
                      应用方案
                    </button>
                    <div className={styles.presetUpdateRow}>
                      <button
                        className={styles.secondaryButton}
                        disabled={!selectedPresetId}
                        type="button"
                        onClick={handleUpdatePreset}
                      >
                        更新当前方案
                      </button>
                      {presetUpdatedNotice ? (
                        <span className={styles.presetUpdatedNotice}>已更新配置</span>
                      ) : null}
                    </div>
                  </div>
                  <select
                    aria-label="已保存方案"
                    className={styles.select}
                    value={selectedPresetId}
                    onChange={(event) => handlePresetSelectionChange(event.target.value)}
                  >
                    <option value="">选择已保存方案</option>
                    {savedPresets.map((preset) => (
                      <option key={preset.id} value={preset.id}>
                        {preset.name}
                      </option>
                    ))}
                  </select>
                  <div className={styles.presetButtonRow}>
                    <button className={styles.ghostButton} type="button" onClick={handleRenamePreset}>
                      重命名
                    </button>
                    <button className={styles.ghostButton} type="button" onClick={handleDeletePreset}>
                      删除
                    </button>
                  </div>
                  {presetError ? <p className={styles.errorText}>{presetError}</p> : null}
                </div>
              </div>

              <div className={styles.summaryCard}>
                <div className={styles.summaryHeaderRow}>
                  <h3>次级任务开关</h3>
                  <span>
                    {pendingReplaceConfig?.runDeliverable
                      ? "翻版+交付"
                      : draft.runAuditCheck
                        ? "交付+纠错"
                        : "交付"}
                  </span>
                </div>
                <div className={styles.intentNotice}>
                  {pendingReplaceConfig?.runDeliverable ? null : (
                    <button
                      aria-pressed={draft.runAuditCheck}
                      className={`${styles.intentChip} ${
                        draft.runAuditCheck ? styles.intentChipActive : ""
                      }`}
                      type="button"
                      onClick={handleAuditToggle}
                    >
                      纠错
                    </button>
                  )}
                </div>
                <div className={styles.intentHelp}>
                  {pendingReplaceConfig?.runDeliverable ? (
                    <p>
                      当前将以翻版+出图模式提交。
                      <strong>{` ${pendingReplaceConfig.sourceProjectNo} -> ${pendingReplaceConfig.targetProjectNo}`}</strong>
                      ，本页参数会整体写入 <code>deliverable_params</code>。
                    </p>
                  ) : (
                    <p>
                      当前按交付处理链路提交。
                      {draft.runAuditCheck
                        ? "已选中同时执行纠错，提交后会直接创建一个包含交付和纠错子任务的任务包。"
                        : "未选中纠错时，只会创建出图任务。"}
                    </p>
                  )}
                </div>
              </div>
            </section>

            <section className={styles.contentPanel}>
              {draft.formErrors.length > 0 ? (
                <div className={styles.formErrorPanel}>
                  {draft.formErrors.map((error) => (
                    <p key={error}>{error}</p>
                  ))}
                </div>
              ) : null}

              {primarySections.map((section) => (
                <FragmentWithUpgradeSection
                  key={`primary-${section.id}`}
                  coverRevisionField={coverRevisionField}
                  draft={draft}
                  fieldErrors={draft.fieldErrors}
                  onFieldChange={handleFieldChange}
                  onUpgradeToggle={handleUpgradeToggle}
                  section={section}
                  upgradeEnabled={upgradeEnabled}
                  upgradeSheetCodesField={upgradeSheetCodesField}
                />
              ))}

              <section className={styles.section}>
                <header className={styles.sectionHeader}>
                  <h3>打印设置</h3>
                </header>
                <div className={styles.intentNotice}>
                  {PLOT_STYLE_OPTIONS.map((option) => (
                    <button
                      key={option.key}
                      aria-pressed={draft.values.plot_style_key === option.key}
                      className={`${styles.intentChip} ${
                        draft.values.plot_style_key === option.key ? styles.intentChipActive : ""
                      }`}
                      type="button"
                      onClick={() => handleFieldChange("plot_style_key", option.key)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                <span className={styles.helperText}>
                  这里控制本次出图使用的打印样式。默认使用系统值，提交时会传入稳定的
                  {" "}
                  <code>plot_style_key</code>。
                </span>
              </section>

              {showAdvanced && advancedSections.length > 0 ? (
                <section className={styles.section}>
                  <header className={styles.sectionHeader}>
                    <h3>高级选项</h3>
                  </header>
                  <div className={styles.advancedStack}>
                    {advancedSections.map((section) => (
                      <div className={styles.advancedBlock} key={`advanced-${section.id}`}>
                        <h4>{section.title}</h4>
                        <div className={styles.fieldGrid}>
                          {section.fields
                            .filter((field) => !isCustomRenderedField(field.key))
                            .map((field) => (
                            <FieldControl
                              key={field.key}
                              error={draft.fieldErrors[field.key]?.[0]}
                              field={field}
                              onChange={(value) => handleFieldChange(field.key, value)}
                              value={draft.values[field.key] ?? ""}
                              values={draft.values}
                            />
                            ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              ) : null}
            </section>

            <footer className={styles.actions}>
              <button className={styles.primaryButton} disabled={isSubmitting} type="submit">
                {isSubmitting ? "创建中..." : submitLabel}
              </button>
            </footer>
          </form>
        </div>
      </TaskConfigModal>
    </>
  );
}

function FieldControl({
  field,
  value,
  values,
  error,
  onChange,
}: {
  field: FormField;
  value: string;
  values: Record<string, string>;
  error?: string;
  onChange: (value: string) => void;
}) {
  const required = field.required || evaluateRequiredWhen(field.requiredWhen, values);
  const inputId = useId();
  const helperText = field.description.trim();
  const placeholder = getFieldPlaceholder(field);

  return (
    <div className={styles.field}>
      <div className={styles.fieldHeader}>
        <label className={styles.fieldLabel} htmlFor={inputId}>
          <span>{field.label}</span>
          {required ? <em>必填</em> : null}
        </label>
      </div>
      {field.type === "select" || field.type === "combobox" ? (
        <ComboboxField
          field={field}
          id={inputId}
          onChange={onChange}
          placeholder={placeholder}
          value={value}
        />
      ) : (
        <input
          aria-label={field.label}
          className={styles.input}
          id={inputId}
          name={field.key}
          placeholder={placeholder}
          type={field.type === "date" ? "date" : "text"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {helperText ? <span className={styles.helperText}>{helperText}</span> : null}
      {error ? <span className={styles.errorText}>{error}</span> : null}
    </div>
  );
}

function FragmentWithUpgradeSection({
  section,
  draft,
  fieldErrors,
  onFieldChange,
  onUpgradeToggle,
  upgradeEnabled,
  coverRevisionField,
  upgradeSheetCodesField,
}: {
  section: FormSchema["sections"][number];
  draft: TaskConfigDraft;
  fieldErrors: Record<string, string[]>;
  onFieldChange: (key: string, value: string) => void;
  onUpgradeToggle: () => void;
  upgradeEnabled: boolean;
  coverRevisionField: FormField | undefined;
  upgradeSheetCodesField: FormField | undefined;
}) {
  return (
    <>
      <section className={styles.section}>
        <header className={styles.sectionHeader}>
          <h3>{section.title}</h3>
          {section.id === "project" ? (
            <div
              className={`${styles.sectionNote} ${
                draft.inference.hasConflict ? styles.sectionNoteWarning : ""
              }`}
            >
              {draft.inference.primaryProjectNo ? (
                <p>
                  已从文件名识别项目号 <strong>{draft.inference.primaryProjectNo}</strong>
                  ，已自动填入项目号，可手动修改。
                </p>
              ) : (
                <p>当前文件名未识别出项目号，提交时后端仍会继续尝试推断。</p>
              )}
              {draft.inference.hasConflict ? (
                <p>同一批文件识别到多个项目号，请以人工输入为准。</p>
              ) : null}
            </div>
          ) : null}
        </header>
        <div className={styles.fieldGrid}>
          {section.fields.map((field) => (
            <FieldControl
              key={field.key}
              error={fieldErrors[field.key]?.[0]}
              field={field}
              onChange={(value) => onFieldChange(field.key, value)}
              value={draft.values[field.key] ?? ""}
              values={draft.values}
            />
          ))}
        </div>
      </section>

      {section.id === "project" ? (
        <section className={styles.section} data-testid="upgrade-config-section">
          <header className={styles.sectionHeader}>
            <h3>升版设置</h3>
          </header>
          <div className={styles.intentNotice}>
            <button
              aria-pressed={upgradeEnabled}
              className={`${styles.intentChip} ${upgradeEnabled ? styles.intentChipActive : ""}`}
              type="button"
              onClick={onUpgradeToggle}
            >
              是否升版
            </button>
          </div>
          <span className={styles.helperText}>
            启用后可填写封面和目录版次、升版图纸编号；关闭时会隐藏输入框，但会保留已输入内容。
          </span>
          {upgradeEnabled ? (
            <div className={styles.fieldGrid}>
              {coverRevisionField ? (
                <FieldControl
                  error={fieldErrors.cover_revision?.[0]}
                  field={coverRevisionField}
                  onChange={(value) => onFieldChange("cover_revision", value)}
                  value={draft.values.cover_revision ?? ""}
                  values={draft.values}
                />
              ) : null}
              {upgradeSheetCodesField ? (
                <FieldControl
                  error={fieldErrors.upgrade_sheet_codes?.[0]}
                  field={upgradeSheetCodesField}
                  onChange={(value) => onFieldChange("upgrade_sheet_codes", value)}
                  value={draft.values.upgrade_sheet_codes ?? ""}
                  values={draft.values}
                />
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}
    </>
  );
}

function ComboboxField({
  id,
  field,
  value,
  onChange,
  placeholder,
}: {
  id: string;
  field: FormField;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const listId = useId();
  const deferredValue = useDeferredValue(value);
  const filteredOptions = (
    FULL_MENU_COMBOBOX_FIELDS.has(field.key)
      ? field.options
      : field.options.filter((option) =>
          option.toLowerCase().includes(deferredValue.trim().toLowerCase()),
        )
  ).slice(0, SCROLLABLE_FULL_OPTION_FIELDS.has(field.key) ? undefined : MAX_COMBO_OPTIONS);

  useEffect(() => {
    function handlePointerDown(event: MouseEvent) {
      if (!wrapperRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, []);

  return (
    <div className={styles.combobox} ref={wrapperRef}>
      <div className={styles.comboboxRow}>
        <input
          aria-autocomplete="list"
          aria-controls={listId}
          aria-expanded={open}
          aria-label={field.label}
          className={styles.input}
          id={id}
          name={field.key}
          placeholder={placeholder}
          role="combobox"
          type="text"
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
        />
        <button
          aria-label={`${field.label} 选项`}
          className={styles.comboToggle}
          type="button"
          onClick={() => setOpen((current) => !current)}
        >
          ▾
        </button>
      </div>

      {open && filteredOptions.length > 0 ? (
        <div
          className={`${styles.comboMenu} ${
            SCROLLABLE_FULL_OPTION_FIELDS.has(field.key) ? styles.comboMenuScrollable : ""
          }`}
          id={listId}
          role="listbox"
        >
          {filteredOptions.map((option) => (
            <button
              key={option}
              className={styles.comboOption}
              role="option"
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => {
                onChange(option);
                setOpen(false);
              }}
            >
              {option}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function filterSections(
  schema: FormSchema,
  values: Record<string, string>,
  advanced: boolean,
) {
  return schema.sections
    .map((section) => ({
      ...section,
      fields: section.fields.filter((field) => {
        if (LEGACY_UPGRADE_KEYS.has(field.key)) {
          return false;
        }

        return advanced ? isAdvancedField(field, values) : !isAdvancedField(field, values);
      }),
    }))
    .filter((section) => section.fields.length > 0);
}

function hasTaskConfigDraft(schema: FormSchema, draft: TaskConfigDraft) {
  if (draft.files.length > 0) {
    return true;
  }

  if (draft.runAuditCheck) {
    return true;
  }

  const defaultValues = getDefaultTaskValues(schema);

  return Object.entries(defaultValues).some(
    ([key, defaultValue]) => (draft.values[key] ?? "") !== defaultValue,
  );
}

function getExtension(filename: string) {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot).toLowerCase() : "";
}

function applyFilesToDraft(
  draft: TaskConfigDraft,
  files: File[],
  pendingReplaceConfig?: DeliverableWorkspaceProps["pendingReplaceConfig"],
) {
  const inference = inferProjectNumbers(files);
  const currentProjectNo = (draft.values.project_no ?? "").trim();
  const replaceTargetProjectNo = pendingReplaceConfig?.runDeliverable
    ? pendingReplaceConfig.targetProjectNo.trim()
    : "";
  const shouldAutofillProjectNo =
    !currentProjectNo ||
    currentProjectNo === draft.inference.primaryProjectNo ||
    currentProjectNo === draft.replaceConfig.targetProjectNo;
  const nextProjectNo = replaceTargetProjectNo
    ? replaceTargetProjectNo
    : inference.primaryProjectNo && shouldAutofillProjectNo
      ? inference.primaryProjectNo
      : currentProjectNo;

  return {
    ...draft,
    intent: "deliverable" as const,
    files,
    values: {
      ...draft.values,
      project_no: nextProjectNo,
      is_upgrade: draft.values.is_upgrade ?? "false",
      upgrade_sheet_codes: draft.values.upgrade_sheet_codes ?? "",
    },
    fieldErrors: {},
    formErrors: [],
    inference,
    replaceConfig: {
      sourceProjectNo:
        pendingReplaceConfig?.sourceProjectNo ??
        inference.primaryProjectNo ??
        draft.replaceConfig.sourceProjectNo,
      targetProjectNo: replaceTargetProjectNo,
    },
  };
}

function toDeliverableOnlyDraft(draft: TaskConfigDraft): TaskConfigDraft {
  return {
    ...draft,
    intent: "deliverable",
    replaceConfig: {
      sourceProjectNo: "",
      targetProjectNo: "",
    },
  };
}

function getFieldPlaceholder(field: FormField) {
  if (field.type === "select") {
    return `输入或选择${field.label}`;
  }

  if (field.type === "date") {
    return "";
  }

  return `请输入${field.label}`;
}

function buildSubmissionValues(values: Record<string, string>) {
  const sanitized = { ...values };

  delete sanitized.upgrade_start_seq;
  delete sanitized.upgrade_end_seq;
  delete sanitized.upgrade_revision;
  delete sanitized.upgrade_note_text;

  const isUpgradeEnabled = sanitized.is_upgrade === "true";
  sanitized.is_upgrade = isUpgradeEnabled ? "true" : "false";
  sanitized.cover_revision = isUpgradeEnabled ? sanitized.cover_revision ?? "" : "";
  sanitized.upgrade_sheet_codes = isUpgradeEnabled ? sanitized.upgrade_sheet_codes ?? "" : "";

  const combinedChecker = (sanitized.ied_checked_by ?? sanitized.ied_discipline_leader ?? "").trim();
  const combinedCheckerDate = (
    sanitized.ied_checked_date ??
    sanitized.ied_discipline_leader_date ??
    ""
  ).trim();
  sanitized.ied_checked_by = combinedChecker;
  sanitized.ied_discipline_leader = combinedChecker;
  sanitized.ied_checked_date = combinedCheckerDate;
  sanitized.ied_discipline_leader_date = combinedCheckerDate;

  return sanitized;
}

function findSchemaField(schema: FormSchema, key: string) {
  return schema.sections.flatMap((section) => section.fields).find((field) => field.key === key);
}

