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
  FontReplacementMap,
  FontReplacementOption,
  FontPreflightResult,
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
    sourceIslandNo: string;
    targetProjectNo: string;
    targetIslandNo: string;
    runDeliverable: boolean;
  } | null;
  onBatchCreated: (payload: CreateBatchPayload) => void;
  onNotice?: (message: string) => void;
  onClearPendingReplaceFlow?: () => void;
  onClose: () => void;
  onDraftAvailabilityChange: (available: boolean) => void;
  tutorialPreview?: {
    dialogTarget?: string;
    initialValues?: Record<string, string>;
    initialRunAuditCheck?: boolean;
  };
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
const INCLUDE_IED_PLAN_KEY = "include_ied_plan";
const MANUALLY_POSITIONED_FIELDS = new Set([INCLUDE_IED_PLAN_KEY]);
const LAST_FONT_REPLACEMENT_STORAGE_KEY = "auto-fanban.last-font-replacement";
const LAST_FONT_REPLACEMENTS_STORAGE_KEY = "auto-fanban.last-font-replacements";
const PLOT_STYLE_OPTIONS = [
  { key: "red_wider", label: "红色更宽" },
  { key: "same_width", label: "同线宽" },
  { key: "review_white", label: "交审图" },
] as const;

type FontSubmitConfig = {
  fontReplacePolicy: "none" | "replace_missing";
  fontReplacementFont?: string;
  fontReplacementFonts?: FontReplacementMap;
};

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
  tutorialPreview,
}: DeliverableWorkspaceProps) {
  const [draft, setDraft] = useState<TaskConfigDraft>(() => createTaskConfigDraft(schema));
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [isPreflighting, setIsPreflighting] = useState(false);
  const [isAwaitingSubmitPreflight, setIsAwaitingSubmitPreflight] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [fontPreflightResult, setFontPreflightResult] = useState<FontPreflightResult | null>(null);
  const [selectedReplacementFonts, setSelectedReplacementFonts] = useState<FontReplacementMap>({});
  const [fontReplacementError, setFontReplacementError] = useState<string | null>(null);
  const [savedPresets, setSavedPresets] = useState<TaskConfigPreset[]>(() => loadTaskPresets());
  const [selectedPresetId, setSelectedPresetId] = useState("");
  const [presetName, setPresetName] = useState("");
  const [presetError, setPresetError] = useState<string | null>(null);
  const [presetUpdatedNotice, setPresetUpdatedNotice] = useState(false);
  const preflightCacheRef = useRef<{ key: string; result: FontPreflightResult } | null>(null);
  const preflightPromiseRef = useRef<{
    key: string;
    requestId: number;
    promise: Promise<FontPreflightResult | null>;
  } | null>(null);
  const preflightRequestIdRef = useRef(0);
  const tutorialPreviewEnabled = Boolean(tutorialPreview);

  useEffect(() => {
    setDraft((current) => syncTaskConfigDraft(schema, current));
  }, [schema]);

  useEffect(() => {
    if (incomingFiles.length === 0) {
      return;
    }

    resetCachedFontPreflightState();
    setDraft((current) =>
      applyTutorialPreview(
        applyFilesToDraft(syncTaskConfigDraft(schema, current), incomingFiles, pendingReplaceConfig),
        tutorialPreview,
      ),
    );

    if (!tutorialPreviewEnabled) {
      void primeFontPreflight(incomingFiles);
    }
  }, [incomingFiles, pendingReplaceConfig, schema, tutorialPreview]);

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
  const iedPlanField = useMemo(
    () => findSchemaField(schema, "include_ied_plan"),
    [schema],
  );
  const upgradeEnabled = draft.values.is_upgrade === "true";
  const selectedPreset = useMemo(
    () => savedPresets.find((preset) => preset.id === selectedPresetId) ?? null,
    [savedPresets, selectedPresetId],
  );
  const missingFontFiles = useMemo(
    () =>
      (fontPreflightResult?.files ?? []).filter(
        (file) => normalizeFontPreflightStatus(file.status) === "missing_fonts",
      ),
    [fontPreflightResult],
  );
  const missingFontKinds = useMemo(
    () => collectMissingFontKinds(missingFontFiles),
    [missingFontFiles],
  );
  const displayedReplacementOptionsByKind = useMemo(
    () => buildDisplayedReplacementOptionsByKind(fontPreflightResult),
    [fontPreflightResult],
  );

  useEffect(() => {
    onDraftAvailabilityChange(hasTaskConfigDraft(schema, draft));
  }, [draft, onDraftAvailabilityChange, schema]);

  if (!isOpen) {
    return null;
  }

  function resetFontPreflightState() {
    setFontPreflightResult(null);
    setSelectedReplacementFonts({});
    setFontReplacementError(null);
  }

  function resetCachedFontPreflightState() {
    preflightRequestIdRef.current += 1;
    preflightCacheRef.current = null;
    preflightPromiseRef.current = null;
    setIsPreflighting(false);
    setIsAwaitingSubmitPreflight(false);
    resetFontPreflightState();
  }

  function setValidationErrors(
    detail?: {
      upload_errors?: Record<string, string[]>;
      param_errors?: Record<string, string[]>;
    },
    extraFormErrors: string[] = [],
  ) {
    setDraft((current) => ({
      ...current,
      fieldErrors: detail?.param_errors ?? {},
      formErrors: [...Object.values(detail?.upload_errors ?? {}).flat(), ...extraFormErrors],
    }));
  }

  function extractValidationDetail(error: unknown) {
    if (typeof error !== "object" || !error || !("detail" in error)) {
      return undefined;
    }

    return (error as {
      detail?: {
        upload_errors?: Record<string, string[]>;
        param_errors?: Record<string, string[]>;
      };
    }).detail;
  }

  async function submitDeliverable(fontConfig: FontSubmitConfig) {
    setIsSubmitting(true);
    setFontReplacementError(null);

    const submissionValues = buildSubmissionValues(schema, draft.values, fontConfig);

    try {
      const payload = pendingReplaceConfig?.runDeliverable
        ? await adapter.createAuditReplace({
            sourceProjectNo: pendingReplaceConfig.sourceProjectNo,
            sourceIslandNo: pendingReplaceConfig.sourceIslandNo,
            targetProjectNo: pendingReplaceConfig.targetProjectNo,
            targetIslandNo: pendingReplaceConfig.targetIslandNo,
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
      if (fontConfig.fontReplacePolicy === "replace_missing") {
        saveLastReplacementFonts(
          fontConfig.fontReplacementFonts ??
            normalizeReplacementSelectionMap({
              shx: fontConfig.fontReplacementFont ?? "",
            }),
        );
      }

      setDraft(createTaskConfigDraft(schema));
      setShowAdvanced(false);
      resetFontPreflightState();
      onClearPendingReplaceFlow?.();
      startTransition(() => onBatchCreated(payload));
      onClose();
    } catch (error) {
      const detail = extractValidationDetail(error);
      const fontErrors = [
        ...(detail?.param_errors?.font_replace_policy ?? []),
        ...(detail?.param_errors?.font_replacement_font ?? []),
        ...(detail?.param_errors?.font_replacement_fonts ?? []),
      ];

      if (fontErrors.length > 0) {
        setFontReplacementError(fontErrors.join("；"));
      }

      setValidationErrors(detail);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (tutorialPreviewEnabled || isSubmitting || isAwaitingSubmitPreflight) {
      return;
    }

    const nextFieldErrors: Record<string, string[]> = {};
    const nextFormErrors: string[] = [];

    for (const field of schema.sections.flatMap((section) => section.fields)) {
      if (shouldSkipFieldValidation(field, draft.values)) {
        continue;
      }

      const value = draft.values[field.key]?.trim() ?? "";
      const required = isFieldRequired(field, draft.values);

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
    resetFontPreflightState();
    setIsAwaitingSubmitPreflight(true);
    try {
      const preflight = await ensureFontPreflight(draft.files);
      if (!preflight) {
        return;
      }

      const failedFiles = preflight.files.filter(
        (file) => normalizeFontPreflightStatus(file.status) === "failed",
      );
      if (failedFiles.length > 0) {
        showFontPreflightFailures(failedFiles);
        return;
      }

      const missingFiles = preflight.files.filter(
        (file) => normalizeFontPreflightStatus(file.status) === "missing_fonts",
      );
      if (missingFiles.length > 0) {
        openFontReplacementConfirmation(preflight, missingFiles);
        return;
      }

      await submitDeliverable({ fontReplacePolicy: "none" });
    } finally {
      setIsAwaitingSubmitPreflight(false);
    }
  }

  async function handleConfirmFontReplacement() {
    if (isSubmitting) {
      return;
    }

    const selectedFonts = pickSelectedReplacementFonts(
      missingFontKinds,
      selectedReplacementFonts,
      displayedReplacementOptionsByKind,
    );
    const missingSelections = missingFontKinds.filter((kind) => !selectedFonts[kind]);

    if (missingSelections.length > 0) {
      setFontReplacementError(
        missingSelections.length === 1
          ? `请先选择${getFontReplacementKindLabel(missingSelections[0] ?? "")}替代字体。`
          : `请先选择以下类型的替代字体：${missingSelections
              .map((kind) => getFontReplacementKindLabel(kind))
              .join("、")}。`,
      );
      return;
    }

    await submitDeliverable({
      fontReplacePolicy: "replace_missing",
      fontReplacementFonts: selectedFonts,
    });
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
    resetCachedFontPreflightState();
    setDraft((current) =>
      applyFilesToDraft(syncTaskConfigDraft(schema, current), files, pendingReplaceConfig),
    );
    if (!tutorialPreviewEnabled) {
      void primeFontPreflight(files);
    }
  }

  function handleClearDraft() {
    setPresetUpdatedNotice(false);
    resetCachedFontPreflightState();
    setDraft(createTaskConfigDraft(schema));
    setShowAdvanced(false);
    setPresetError(null);
    onClearPendingReplaceFlow?.();
    onClose();
  }

  function handleClose() {
    setPresetError(null);
    resetFontPreflightState();
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
      <TaskConfigModal
        title="任务配置"
        dialogClassName={tutorialPreviewEnabled ? styles.tutorialPreviewDialog : undefined}
        dialogDataAttributes={
          tutorialPreview?.dialogTarget
            ? { "data-tutorial-target": tutorialPreview.dialogTarget }
            : undefined
        }
      >
        <div
          className={`${styles.modalLayout} ${
            tutorialPreviewEnabled ? styles.modalLayoutPassive : ""
          }`}
        >
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
                      {pendingReplaceConfig.sourceIslandNo ? (
                        <strong>{`（来源${formatSourceIslandLabel(pendingReplaceConfig.sourceProjectNo, pendingReplaceConfig.sourceIslandNo)}）`}</strong>
                      ) : null}
                      {pendingReplaceConfig.targetIslandNo ? (
                        <strong>{`（${pendingReplaceConfig.targetIslandNo}号岛）`}</strong>
                      ) : null}
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
                  iedPlanField={iedPlanField}
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
              <button
                className={styles.primaryButton}
                disabled={isSubmitting || isAwaitingSubmitPreflight}
                type="submit"
              >
                {isSubmitting ? "创建中..." : isPreflighting ? "正在执行字体搜索..." : submitLabel}
              </button>
            </footer>
          </form>
        </div>
      </TaskConfigModal>

      {fontPreflightResult ? (
        <TaskConfigModal title="缺失字体处理">
          <div className={styles.fontModalBody}>
            <header className={styles.modalHeader}>
              <div>
                <p className={styles.kicker}>Font Preflight</p>
                <h2>缺失字体处理</h2>
                <p className={styles.description}>
                  检测到当前批次存在缺失字体。请按缺失字体类型选择替代字体，确认后再继续正式提交。
                </p>
              </div>
            </header>

            <section className={styles.section}>
              <header className={styles.sectionHeader}>
                <h3>缺失字体文件</h3>
              </header>
              <div className={styles.fontFileList}>
                {missingFontFiles.map((file) => (
                  <article className={styles.fontFileCard} key={file.filename}>
                    <div className={styles.summaryHeaderRow}>
                      <h3>{file.filename}</h3>
                      <span>{`${file.missingStyleCount} 处缺失`}</span>
                    </div>
                    {file.missingFonts.length > 0 ? (
                      <div className={styles.fontMissingList}>
                        {file.missingFonts.map((font) => (
                          <div
                            className={styles.fontMissingItem}
                            key={`${file.filename}-${font.styleName}-${font.fontName}`}
                          >
                            <strong>{font.styleName}</strong>
                            <span>{`字体：${font.fontName || "-"}`}</span>
                            <span>{`大字体：${font.bigfontName || "-"}`}</span>
                            <span>{`类型：${font.kind}`}</span>
                            <span>{`是否在块中使用：${font.usedInBlock ? "是" : "否"}`}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className={styles.emptyState}>当前文件未返回具体缺失字体条目。</p>
                    )}
                  </article>
                ))}
              </div>
            </section>

            <section className={styles.section}>
              <header className={styles.sectionHeader}>
                <h3>替代策略</h3>
              </header>
              <div className={styles.advancedStack}>
                {missingFontKinds.map((kind) => {
                  const options = displayedReplacementOptionsByKind[kind] ?? [];
                  const selectedValue = selectedReplacementFonts[kind] ?? "";
                  const selectedOption =
                    options.find((option) => option.value === selectedValue) ?? options[0] ?? null;
                  const rawOptions = resolveRawReplacementOptionsForKind(fontPreflightResult, kind);
                  const fieldLabel =
                    missingFontKinds.length === 1
                      ? "替代字体"
                      : `${getFontReplacementKindLabel(kind)} 替代字体`;

                  return (
                    <div className={styles.field} key={kind}>
                      <label
                        className={styles.fieldLabel}
                        htmlFor={`font-replacement-select-${kind}`}
                      >
                        <span>{fieldLabel}</span>
                        <em>必填</em>
                      </label>
                      <select
                        aria-label={fieldLabel}
                        className={styles.select}
                        id={`font-replacement-select-${kind}`}
                        value={selectedValue}
                        onChange={(event) => {
                          setSelectedReplacementFonts((current) => ({
                            ...current,
                            [kind]: event.target.value,
                          }));
                          setFontReplacementError(null);
                        }}
                      >
                        <option value="">请选择替代字体</option>
                        {options.map((option) => (
                          <option key={`${kind}-${option.value}`} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <span className={styles.helperText}>
                        {`${getFontReplacementKindLabel(kind)} 缺失会绑定当前类型的候选列表，前端不会把不同类型混用。`}
                      </span>
                      {rawOptions.length > 0 && options.length !== rawOptions.length ? (
                        <span className={styles.helperText}>
                          当前已优先收敛为 AutoCAD Fonts 目录候选，已隐藏其他 TrueType 回退项。
                        </span>
                      ) : null}
                      {selectedOption ? (
                        <div className={styles.fontReplacementPreview}>
                          <strong>{`当前候选：${selectedOption.label}`}</strong>
                          <span>{`来源：${getFontReplacementSourceLabel(selectedOption.source)}`}</span>
                          <span>{`类型：${getFontReplacementKindLabel(selectedOption.kind)}`}</span>
                        </div>
                      ) : null}
                    </div>
                  );
                })}
                {fontReplacementError ? (
                  <span className={styles.errorText}>{fontReplacementError}</span>
                ) : null}
              </div>

              <ul className={styles.fontNoticeList}>
                <li>只会修改任务工作副本。</li>
                <li>不会修改原始上传文件。</li>
                <li>替代只作用于检测到缺失的字体样式。</li>
                <li>同一批次文件会按字体类型分别使用当前选中的替代字体。</li>
                <li>对 SHX / 大字体缺失，候选会优先来自 AutoCAD Fonts 目录。</li>
              </ul>
            </section>

            <footer className={styles.actions}>
              <button
                className={styles.ghostButton}
                type="button"
                onClick={resetFontPreflightState}
              >
                取消
              </button>
              <button
                className={styles.primaryButton}
                disabled={isSubmitting}
                type="button"
                onClick={handleConfirmFontReplacement}
              >
                {isSubmitting ? "提交中..." : "继续提交"}
              </button>
            </footer>
          </div>
        </TaskConfigModal>
      ) : null}
    </>
  );

  function showFontPreflightFailures(failedFiles: FontPreflightResult["files"]) {
    setDraft((current) => ({
      ...current,
      fieldErrors: {},
      formErrors: buildFontPreflightFailureMessages(failedFiles),
    }));
  }

  function openFontReplacementConfirmation(
    preflight: FontPreflightResult,
    missingFiles: FontPreflightResult["files"],
  ) {
    const replacementOptionsByKind = buildDisplayedReplacementOptionsByKind(preflight);
    const unavailableKinds = collectMissingFontKinds(missingFiles).filter(
      (kind) => (replacementOptionsByKind[kind] ?? []).length === 0,
    );
    if (unavailableKinds.length > 0) {
      setDraft((current) => ({
        ...current,
        fieldErrors: {},
        formErrors: [
          `检测到缺失字体，但当前工作站没有可用替代字体：${unavailableKinds
            .map((kind) => getFontReplacementKindLabel(kind))
            .join("、")}。`,
        ],
      }));
      return;
    }

    setFontPreflightResult(preflight);
    setSelectedReplacementFonts(
      resolveInitialReplacementFonts(
        missingFiles,
        replacementOptionsByKind,
        preflight.defaultReplacementFonts ?? {},
        preflight.defaultReplacementFont ?? null,
        loadLastReplacementFonts(),
        loadLastReplacementFont(),
      ),
    );
    setFontReplacementError(null);
  }

  async function ensureFontPreflight(files: File[]) {
    const nextKey = buildFilePreflightCacheKey(files);
    if (preflightCacheRef.current?.key === nextKey) {
      return preflightCacheRef.current.result;
    }

    if (preflightPromiseRef.current?.key === nextKey) {
      return preflightPromiseRef.current.promise;
    }

    return runFontPreflight(files);
  }

  async function primeFontPreflight(files: File[]) {
    const preflight = await runFontPreflight(files);
    if (!preflight) {
      return;
    }

    const failedFiles = preflight.files.filter(
      (file) => normalizeFontPreflightStatus(file.status) === "failed",
    );
    if (failedFiles.length > 0) {
      showFontPreflightFailures(failedFiles);
    }
  }

  async function runFontPreflight(files: File[]) {
    const requestId = preflightRequestIdRef.current + 1;
    const nextKey = buildFilePreflightCacheKey(files);
    preflightRequestIdRef.current = requestId;
    setIsPreflighting(true);
    setFontReplacementError(null);
    const promise = (async () => {
      try {
        const preflight = await adapter.preflightFonts(files);
        if (preflightRequestIdRef.current !== requestId) {
          return null;
        }

        preflightCacheRef.current = {
          key: nextKey,
          result: preflight,
        };
        return preflight;
      } catch (error) {
        if (preflightRequestIdRef.current !== requestId) {
          return null;
        }

        preflightCacheRef.current = null;
        setValidationErrors(extractValidationDetail(error), ["字体预检失败，请稍后重试。"]);
        return null;
      } finally {
        if (preflightRequestIdRef.current === requestId) {
          setIsPreflighting(false);
        }
        if (preflightPromiseRef.current?.requestId === requestId) {
          preflightPromiseRef.current = null;
        }
      }
    })();

    preflightPromiseRef.current = {
      key: nextKey,
      requestId,
      promise,
    };

    return promise;
  }
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
  const required = isFieldRequired(field, values);
  const inputId = useId();
  const helperText = field.description.trim();
  const placeholder = getFieldPlaceholder(field);

  if (field.type === "checkbox") {
    return (
      <div className={styles.field}>
        <label className={styles.checkboxField} htmlFor={inputId}>
          <input
            aria-label={field.label}
            checked={value === "true"}
            className={styles.checkboxInput}
            id={inputId}
            name={field.key}
            type="checkbox"
            onChange={(event) => onChange(event.target.checked ? "true" : "false")}
          />
          <span className={styles.checkboxLabelText}>{field.label}</span>
          {required ? <em className={styles.checkboxRequired}>必填</em> : null}
        </label>
        {helperText ? <span className={styles.helperText}>{helperText}</span> : null}
        {error ? <span className={styles.errorText}>{error}</span> : null}
      </div>
    );
  }

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
  iedPlanField,
  onFieldChange,
  onUpgradeToggle,
  upgradeEnabled,
  coverRevisionField,
  upgradeSheetCodesField,
}: {
  section: FormSchema["sections"][number];
  draft: TaskConfigDraft;
  fieldErrors: Record<string, string[]>;
  iedPlanField: FormField | undefined;
  onFieldChange: (key: string, value: string) => void;
  onUpgradeToggle: () => void;
  upgradeEnabled: boolean;
  coverRevisionField: FormField | undefined;
  upgradeSheetCodesField: FormField | undefined;
}) {
  const showIedPlanToggle = section.id === "ied" && iedPlanField;

  return (
    <>
      <section className={styles.section}>
        <header className={styles.sectionHeader}>
          <div className={styles.sectionHeaderTop}>
            <h3>{section.title}</h3>
            {showIedPlanToggle ? (
              <SectionHeaderCheckbox
                checked={(draft.values[iedPlanField.key] ?? iedPlanField.defaultValue) === "true"}
                field={iedPlanField}
                onChange={(value) => onFieldChange(iedPlanField.key, value)}
              />
            ) : null}
          </div>
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

function SectionHeaderCheckbox({
  field,
  checked,
  onChange,
}: {
  field: FormField;
  checked: boolean;
  onChange: (value: string) => void;
}) {
  const inputId = useId();

  return (
    <label className={styles.sectionHeaderCheckbox} htmlFor={inputId}>
      <input
        aria-label={field.label}
        checked={checked}
        className={styles.sectionHeaderCheckboxInput}
        id={inputId}
        name={field.key}
        type="checkbox"
        onChange={(event) => onChange(event.target.checked ? "true" : "false")}
      />
      <span>{field.label}</span>
    </label>
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

        if (MANUALLY_POSITIONED_FIELDS.has(field.key)) {
          return false;
        }

        return advanced ? isAdvancedField(field, values) : !isAdvancedField(field, values);
      }),
    }))
    .filter((section) => section.fields.length > 0);
}

function isFieldRequired(field: FormField, values: Record<string, string>) {
  if (shouldSkipFieldValidation(field, values)) {
    return false;
  }

  return field.required || evaluateRequiredWhen(field.requiredWhen, values);
}

function shouldSkipFieldValidation(field: FormField, values: Record<string, string>) {
  return isIedParameterField(field.key) && values[INCLUDE_IED_PLAN_KEY] === "false";
}

function isIedParameterField(fieldKey: string) {
  return fieldKey.startsWith("ied_");
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
      sourceIslandNo: pendingReplaceConfig?.sourceIslandNo ?? draft.replaceConfig.sourceIslandNo,
      targetProjectNo: replaceTargetProjectNo,
      targetIslandNo: pendingReplaceConfig?.targetIslandNo ?? draft.replaceConfig.targetIslandNo,
    },
  };
}

function applyTutorialPreview(
  draft: TaskConfigDraft,
  tutorialPreview: DeliverableWorkspaceProps["tutorialPreview"],
) {
  if (!tutorialPreview) {
    return draft;
  }

  return {
    ...draft,
    runAuditCheck: tutorialPreview.initialRunAuditCheck ?? draft.runAuditCheck,
    values: {
      ...draft.values,
      ...tutorialPreview.initialValues,
    },
    fieldErrors: {},
    formErrors: [],
  };
}

function toDeliverableOnlyDraft(draft: TaskConfigDraft): TaskConfigDraft {
  return {
    ...draft,
    intent: "deliverable",
    replaceConfig: {
      sourceProjectNo: "",
      sourceIslandNo: "",
      targetProjectNo: "",
      targetIslandNo: "",
    },
  };
}

function getFieldPlaceholder(field: FormField) {
  if (field.type === "select") {
    return `输入或选择${field.label}`;
  }

  if (field.type === "date" || field.type === "checkbox") {
    return "";
  }

  return `请输入${field.label}`;
}

function formatSourceIslandLabel(sourceProjectNo: string, sourceIslandNo: string) {
  const normalizedProjectNo = sourceProjectNo.trim();
  const normalizedIslandNo = sourceIslandNo.trim();
  if (!normalizedIslandNo) {
    return "";
  }
  return normalizedProjectNo === "2016"
    ? `${normalizedIslandNo}号机组`
    : `${normalizedIslandNo}号岛`;
}

function normalizeFontPreflightStatus(status: string) {
  return status.trim().toLowerCase();
}

function buildFontPreflightFailureMessages(files: FontPreflightResult["files"]) {
  return files.flatMap((file) =>
    file.errors.length > 0 ? file.errors : [`${file.filename}：字体预检失败`],
  );
}

function buildFilePreflightCacheKey(files: File[]) {
  return files
    .map((file) => `${file.name}:${file.size}:${file.lastModified}`)
    .sort()
    .join("|");
}

function filterPreferredReplacementOptions(options: FontReplacementOption[]) {
  const autocadOptions = options.filter(
    (option) => option.source.trim().toLowerCase() === "autocad_fonts",
  );
  if (autocadOptions.length > 0) {
    return autocadOptions;
  }
  return options;
}

function collectMissingFontKinds(files: FontPreflightResult["files"]) {
  const seen = new Set<string>();
  const kinds: string[] = [];
  for (const file of files) {
    for (const font of file.missingFonts) {
      const kind = font.kind.trim().toLowerCase();
      if (!kind || seen.has(kind)) {
        continue;
      }
      seen.add(kind);
      kinds.push(kind);
    }
  }
  return kinds;
}

function buildDisplayedReplacementOptionsByKind(
  result: FontPreflightResult | null,
): Record<string, FontReplacementOption[]> {
  if (!result) {
    return {};
  }

  const replacementOptionsByKind = result.replacementOptionsByKind ?? {};
  const source =
    Object.keys(replacementOptionsByKind).length > 0
      ? replacementOptionsByKind
      : groupReplacementOptionsByKind(result.replacementOptions ?? []);

  return Object.fromEntries(
    Object.entries(source).map(([kind, options]) => [kind, filterPreferredReplacementOptions(options)]),
  );
}

function groupReplacementOptionsByKind(
  options: FontPreflightResult["replacementOptions"],
): Record<string, FontReplacementOption[]> {
  const grouped = new Map<string, FontReplacementOption[]>();
  for (const option of options) {
    const kind = option.kind.trim().toLowerCase() || "unknown";
    grouped.set(kind, [...(grouped.get(kind) ?? []), option]);
  }
  return Object.fromEntries(grouped.entries());
}

function resolveRawReplacementOptionsForKind(
  result: FontPreflightResult,
  kind: string,
) {
  if (result.replacementOptionsByKind?.[kind]?.length) {
    return result.replacementOptionsByKind[kind] ?? [];
  }
  return result.replacementOptions.filter(
    (option) => option.kind.trim().toLowerCase() === kind.trim().toLowerCase(),
  );
}

function resolveInitialReplacementFont(
  options: FontReplacementOption[],
  explicitDefaultValue: string,
  rememberedValue: string,
) {
  const trimmedDefaultValue = explicitDefaultValue.trim();
  if (trimmedDefaultValue && options.some((option) => option.value === trimmedDefaultValue)) {
    return trimmedDefaultValue;
  }

  const trimmedRememberedValue = rememberedValue.trim();
  if (
    trimmedRememberedValue &&
    options.some((option) => option.value === trimmedRememberedValue)
  ) {
    return trimmedRememberedValue;
  }

  if (options.length === 1) {
    return options[0]?.value ?? "";
  }

  return "";
}

function resolveInitialReplacementFonts(
  missingFiles: FontPreflightResult["files"],
  optionsByKind: Record<string, FontReplacementOption[]>,
  defaultReplacementFonts: FontReplacementMap,
  defaultReplacementFont: string | null,
  rememberedValues: FontReplacementMap,
  rememberedValue: string,
) {
  const kinds = collectMissingFontKinds(missingFiles);
  const initialValues: FontReplacementMap = {};

  for (const kind of kinds) {
    const options = optionsByKind[kind] ?? [];
    const fallbackDefaultValue =
      kinds.length === 1 ? (defaultReplacementFont?.trim() ?? "") : "";
    const resolved = resolveInitialReplacementFont(
      options,
      defaultReplacementFonts[kind] ?? fallbackDefaultValue,
      rememberedValues[kind] ?? (kinds.length === 1 ? rememberedValue : ""),
    );
    if (resolved) {
      initialValues[kind] = resolved;
    }
  }

  return initialValues;
}

function getFontReplacementKindLabel(kind: string) {
  switch (kind.trim().toLowerCase()) {
    case "shx":
      return "SHX";
    case "bigfont":
      return "大字体";
    case "ttf":
      return "TrueType";
    default:
      return kind || "未知";
  }
}

function getFontReplacementSourceLabel(source: string) {
  switch (source.trim().toLowerCase()) {
    case "autocad_fonts":
      return "AutoCAD Fonts 目录";
    case "windows_fonts":
      return "Windows 字体库";
    default:
      return source || "后端预检";
  }
}

function loadLastReplacementFont() {
  if (typeof window === "undefined") {
    return "";
  }

  return window.localStorage.getItem(LAST_FONT_REPLACEMENT_STORAGE_KEY)?.trim() ?? "";
}

function loadLastReplacementFonts(): FontReplacementMap {
  if (typeof window === "undefined") {
    return {};
  }

  const raw = window.localStorage.getItem(LAST_FONT_REPLACEMENTS_STORAGE_KEY);
  if (!raw) {
    return {};
  }

  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return normalizeReplacementSelectionMap(parsed);
  } catch {
    return {};
  }
}

function saveLastReplacementFont(value: string) {
  saveLastReplacementFonts(normalizeReplacementSelectionMap({ shx: value }));
}

function saveLastReplacementFonts(values: FontReplacementMap) {
  if (typeof window === "undefined") {
    return;
  }

  const normalizedValues = normalizeReplacementSelectionMap(values);
  if (Object.keys(normalizedValues).length === 0) {
    window.localStorage.removeItem(LAST_FONT_REPLACEMENTS_STORAGE_KEY);
    window.localStorage.removeItem(LAST_FONT_REPLACEMENT_STORAGE_KEY);
    return;
  }

  window.localStorage.setItem(
    LAST_FONT_REPLACEMENTS_STORAGE_KEY,
    JSON.stringify(normalizedValues),
  );
  const legacyValue = normalizedValues.shx ?? Object.values(normalizedValues)[0] ?? "";
  if (legacyValue) {
    window.localStorage.setItem(LAST_FONT_REPLACEMENT_STORAGE_KEY, legacyValue);
  }
}

function normalizeReplacementSelectionMap(values: Record<string, unknown> | FontReplacementMap) {
  return Object.fromEntries(
    Object.entries(values)
      .map(([kind, value]) => [kind.trim().toLowerCase(), String(value ?? "").trim()])
      .filter(([kind, value]) => kind && value),
  );
}

function pickSelectedReplacementFonts(
  kinds: string[],
  selectedValues: FontReplacementMap,
  optionsByKind: Record<string, FontReplacementOption[]>,
) {
  const normalizedSelections = normalizeReplacementSelectionMap(selectedValues);
  return Object.fromEntries(
    kinds.flatMap((kind) => {
      const selectedValue = normalizedSelections[kind] ?? "";
      const options = optionsByKind[kind] ?? [];
      return options.some((option) => option.value === selectedValue)
        ? ([[kind, selectedValue]] as const)
        : [];
    }),
  );
}

function buildSubmissionValues(
  schema: FormSchema,
  values: Record<string, string>,
  fontConfig: FontSubmitConfig = { fontReplacePolicy: "none" },
) {
  const sanitized: Record<string, unknown> = { ...values };
  const checkboxFieldKeys = new Set(
    schema.sections.flatMap((section) =>
      section.fields
        .filter((field) => field.type === "checkbox")
        .map((field) => field.key),
    ),
  );

  for (const fieldKey of checkboxFieldKeys) {
    sanitized[fieldKey] = sanitized[fieldKey] === "true";
  }

  delete sanitized.upgrade_start_seq;
  delete sanitized.upgrade_end_seq;
  delete sanitized.upgrade_revision;
  delete sanitized.upgrade_note_text;

  const isUpgradeEnabled = sanitized.is_upgrade === "true";
  sanitized.is_upgrade = isUpgradeEnabled ? "true" : "false";
  sanitized.cover_revision = isUpgradeEnabled ? sanitized.cover_revision ?? "" : "";
  sanitized.upgrade_sheet_codes = isUpgradeEnabled ? sanitized.upgrade_sheet_codes ?? "" : "";
  sanitized.font_replace_policy = fontConfig.fontReplacePolicy;
  if (fontConfig.fontReplacePolicy === "replace_missing") {
    const replacementFonts = normalizeReplacementSelectionMap(
      fontConfig.fontReplacementFonts ?? {},
    );
    if (Object.keys(replacementFonts).length > 0) {
      sanitized.font_replacement_fonts = replacementFonts;
    } else {
      delete sanitized.font_replacement_fonts;
    }

    if (Object.keys(replacementFonts).length === 1) {
      sanitized.font_replacement_font = Object.values(replacementFonts)[0] ?? "";
    } else if (fontConfig.fontReplacementFont) {
      sanitized.font_replacement_font = fontConfig.fontReplacementFont;
    } else {
      delete sanitized.font_replacement_font;
    }
  } else {
    delete sanitized.font_replacement_fonts;
    delete sanitized.font_replacement_font;
  }

  return sanitized;
}

function findSchemaField(schema: FormSchema, key: string) {
  return schema.sections.flatMap((section) => section.fields).find((field) => field.key === key);
}

