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
  buildRecommendedProjectNos,
  evaluateRequiredWhen,
  isAdvancedField,
} from "../schema/schema";
import type {
  ApiAdapter,
  CreateBatchPayload,
  FormField,
  FormSchema,
  TaskConfigDraft,
  TaskConfigPreset,
  TaskIntent,
} from "../../platform/api/types";
import {
  applyTaskPreset,
  createTaskPreset,
  deleteTaskPreset,
  loadTaskPresets,
  renameTaskPreset,
  saveTaskPreset,
} from "./taskPresets";
import { createTaskConfigDraft, getDefaultTaskValues, syncTaskConfigDraft } from "./taskDraft";
import { inferProjectNumbers } from "./uploadInference";
import { ReplaceTaskModal } from "./ReplaceTaskModal";
import { TaskConfigModal } from "./TaskConfigModal";
import styles from "./DeliverableWorkspace.module.css";

type DeliverableWorkspaceProps = {
  adapter: ApiAdapter;
  schema: FormSchema;
  isOpen: boolean;
  incomingFiles: File[];
  onBatchCreated: (payload: CreateBatchPayload) => void;
  onClose: () => void;
  onDraftAvailabilityChange: (available: boolean) => void;
};

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const NAME_ID_PATTERN = /^.+@.+$/;
const MAX_COMBO_OPTIONS = 10;

export function DeliverableWorkspace({
  adapter,
  schema,
  isOpen,
  incomingFiles,
  onBatchCreated,
  onClose,
  onDraftAvailabilityChange,
}: DeliverableWorkspaceProps) {
  const [draft, setDraft] = useState<TaskConfigDraft>(() => createTaskConfigDraft(schema));
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [replaceModalOpen, setReplaceModalOpen] = useState(false);
  const [replaceConfigError, setReplaceConfigError] = useState<string | null>(null);
  const [savedPresets, setSavedPresets] = useState<TaskConfigPreset[]>(() => loadTaskPresets());
  const [selectedPresetId, setSelectedPresetId] = useState("");
  const [presetName, setPresetName] = useState("");
  const [presetError, setPresetError] = useState<string | null>(null);

  useEffect(() => {
    setDraft((current) => syncTaskConfigDraft(schema, current));
  }, [schema]);

  useEffect(() => {
    if (incomingFiles.length === 0) {
      return;
    }

    setDraft((current) => applyFilesToDraft(syncTaskConfigDraft(schema, current), incomingFiles));
    setReplaceModalOpen(false);
    setReplaceConfigError(null);
  }, [incomingFiles, schema]);

  const primarySections = useMemo(
    () => filterSections(schema, draft.values, false),
    [draft.values, schema],
  );
  const advancedSections = useMemo(
    () => filterSections(schema, draft.values, true),
    [draft.values, schema],
  );
  const projectNoOptions = useMemo(() => getProjectNoOptions(schema), [schema]);
  const recommendedProjectNos = useMemo(
    () => buildRecommendedProjectNos(draft.inference.inferredProjectNos, projectNoOptions),
    [draft.inference.inferredProjectNos, projectNoOptions],
  );
  const selectedPreset = useMemo(
    () => savedPresets.find((preset) => preset.id === selectedPresetId) ?? null,
    [savedPresets, selectedPresetId],
  );

  useEffect(() => {
    onDraftAvailabilityChange(hasTaskConfigDraft(schema, draft));
  }, [draft, onDraftAvailabilityChange, schema]);

  if (!isOpen) {
    return null;
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (draft.intent !== "deliverable") {
      setDraft((current) => ({
        ...current,
        formErrors: [getIntentUnavailableMessage(current.intent)],
      }));
      return;
    }

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

    try {
      const payload = await adapter.createBatch(draft.values, draft.files);
      setDraft(createTaskConfigDraft(schema));
      setShowAdvanced(false);
      setReplaceModalOpen(false);
      setReplaceConfigError(null);
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

  function handleReplaceFiles(files: File[]) {
    if (files.length === 0) {
      return;
    }

    setDraft((current) => applyFilesToDraft(syncTaskConfigDraft(schema, current), files));
    setReplaceModalOpen(false);
    setReplaceConfigError(null);
  }

  function handleClearDraft() {
    setDraft(createTaskConfigDraft(schema));
    setShowAdvanced(false);
    setReplaceModalOpen(false);
    setReplaceConfigError(null);
    setPresetError(null);
    onClose();
  }

  function handleClose() {
    setReplaceModalOpen(false);
    setReplaceConfigError(null);
    setPresetError(null);
    onClose();
  }

  function handleIntentChange(intent: TaskIntent) {
    const nextIntent = draft.intent === intent ? "deliverable" : intent;

    setDraft((current) => ({
      ...current,
      intent: nextIntent,
      fieldErrors: {},
      formErrors: [],
      replaceConfig:
        nextIntent === "audit_replace"
          ? {
              sourceProjectNo:
                current.replaceConfig.sourceProjectNo || current.inference.primaryProjectNo,
              targetProjectNo: current.replaceConfig.targetProjectNo,
            }
          : {
              sourceProjectNo: current.inference.primaryProjectNo,
              targetProjectNo: "",
            },
    }));

    setReplaceConfigError(null);
    setReplaceModalOpen(nextIntent === "audit_replace");
  }

  function handleReplaceConfigChange(
    field: "sourceProjectNo" | "targetProjectNo",
    value: string,
  ) {
    setDraft((current) => ({
      ...current,
      replaceConfig: {
        ...current.replaceConfig,
        [field]: value,
      },
    }));
    setReplaceConfigError(null);
  }

  function handleReplaceConfigConfirm() {
    const nextError = validateReplaceConfig(
      draft.replaceConfig.sourceProjectNo,
      draft.replaceConfig.targetProjectNo,
    );
    if (nextError) {
      setReplaceConfigError(nextError);
      return;
    }

    setReplaceConfigError(null);
    setReplaceModalOpen(false);
  }

  function handlePresetSelectionChange(nextId: string) {
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

    const nextPreset = createTaskPreset(trimmedName, draft, selectedPreset?.id);
    const nextPresets = saveTaskPreset(nextPreset);
    setSavedPresets(nextPresets);
    setSelectedPresetId(nextPreset.id);
    setPresetName(trimmedName);
    setPresetError(null);
  }

  function handleApplyPreset() {
    if (!selectedPreset) {
      setPresetError("请先选择一个已保存方案。");
      return;
    }

    setDraft((current) => applyTaskPreset(schema, current, selectedPreset));
    setShowAdvanced(false);
    setPresetError(null);
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
  }

  const submitLabel = draft.intent === "deliverable" ? "创建交付任务" : "创建任务";

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
                    onChange={(event) => setPresetName(event.target.value)}
                  />
                  <div className={styles.presetButtonRow}>
                    <button className={styles.secondaryButton} type="button" onClick={handleSavePreset}>
                      保存方案
                    </button>
                    <button className={styles.secondaryButton} type="button" onClick={handleApplyPreset}>
                      应用方案
                    </button>
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
                  <span>{draft.intent === "deliverable" ? "交付" : "翻版"}</span>
                </div>
                <div className={styles.intentNotice}>
                  <button
                    aria-pressed={draft.intent === "audit_replace"}
                    className={`${styles.intentChip} ${
                      draft.intent === "audit_replace" ? styles.intentChipActive : ""
                    }`}
                    type="button"
                    onClick={() => handleIntentChange("audit_replace")}
                  >
                    翻版
                  </button>
                </div>
                <div className={styles.intentHelp}>
                  {draft.intent === "deliverable" ? (
                    <p>当前按交付处理链路提交；纠错已经独立到首页主入口，这里只保留翻版结构。</p>
                  ) : (
                    <div className={styles.replaceSummary}>
                      <p>
                        {draft.replaceConfig.sourceProjectNo || draft.replaceConfig.targetProjectNo
                          ? `原始项目号 ${draft.replaceConfig.sourceProjectNo || "未填写"} → 目标项目号 ${
                              draft.replaceConfig.targetProjectNo || "未填写"
                            }`
                          : "尚未填写翻版项目号，请先完成翻版配置。"}
                      </p>
                      <div className={styles.recommendations}>
                        <button
                          className={styles.recommendationChip}
                          type="button"
                          onClick={() => setReplaceModalOpen(true)}
                        >
                          编辑翻版配置
                        </button>
                        {recommendedProjectNos.map((projectNo) => (
                          <button
                            key={`replace-source-${projectNo}`}
                            className={styles.recommendationChip}
                            type="button"
                            onClick={() =>
                              handleReplaceConfigChange("sourceProjectNo", projectNo)
                            }
                          >
                            {projectNo}
                          </button>
                        ))}
                      </div>
                    </div>
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
                <section className={styles.section} key={`primary-${section.id}`}>
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
                        error={draft.fieldErrors[field.key]?.[0]}
                        field={field}
                        onChange={(value) => handleFieldChange(field.key, value)}
                        value={draft.values[field.key] ?? ""}
                        values={draft.values}
                      />
                    ))}
                  </div>
                </section>
              ))}

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
                          {section.fields.map((field) => (
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

      {replaceModalOpen ? (
        <ReplaceTaskModal
          error={replaceConfigError}
          recommendedProjectNos={recommendedProjectNos}
          sourceProjectNo={draft.replaceConfig.sourceProjectNo}
          targetProjectNo={draft.replaceConfig.targetProjectNo}
          onChange={handleReplaceConfigChange}
          onClose={() => {
            setReplaceModalOpen(false);
            setReplaceConfigError(null);
          }}
          onConfirm={handleReplaceConfigConfirm}
        />
      ) : null}
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
  const filteredOptions = field.options
    .filter((option) =>
      option.toLowerCase().includes(deferredValue.trim().toLowerCase()),
    )
    .slice(0, MAX_COMBO_OPTIONS);

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
        <div className={styles.comboMenu} id={listId} role="listbox">
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
      fields: section.fields.filter((field) =>
        advanced ? isAdvancedField(field, values) : !isAdvancedField(field, values),
      ),
    }))
    .filter((section) => section.fields.length > 0);
}

function hasTaskConfigDraft(schema: FormSchema, draft: TaskConfigDraft) {
  if (draft.files.length > 0) {
    return true;
  }

  if (draft.intent !== "deliverable") {
    return true;
  }

  if (draft.replaceConfig.sourceProjectNo || draft.replaceConfig.targetProjectNo) {
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

function getProjectNoOptions(schema: FormSchema) {
  const fieldOptions =
    schema.sections
    .flatMap((section) => section.fields)
    .find((field) => field.key === "project_no")?.options ?? [];

  const merged = new Set<string>();
  for (const projectNo of [
    ...(schema.auditReplaceProjectOptions ?? []),
    ...fieldOptions,
  ]) {
    const normalized = projectNo.trim();
    if (!normalized) {
      continue;
    }
    merged.add(normalized);
  }

  return Array.from(merged);
}

function applyFilesToDraft(draft: TaskConfigDraft, files: File[]) {
  const inference = inferProjectNumbers(files);
  const currentProjectNo = draft.values.project_no.trim();
  const shouldAutofillProjectNo =
    !currentProjectNo || currentProjectNo === draft.inference.primaryProjectNo;
  const nextProjectNo =
    inference.primaryProjectNo && shouldAutofillProjectNo
      ? inference.primaryProjectNo
      : currentProjectNo;

  return {
    ...draft,
    intent: "deliverable" as const,
    files,
    values: {
      ...draft.values,
      project_no: nextProjectNo,
    },
    fieldErrors: {},
    formErrors: [],
    inference,
    replaceConfig: {
      sourceProjectNo: inference.primaryProjectNo || draft.replaceConfig.sourceProjectNo,
      targetProjectNo: "",
    },
  };
}

function getIntentUnavailableMessage(intent: TaskIntent) {
  if (intent === "audit_replace") {
    return "翻版接口未开放，当前无法提交。";
  }

  return "";
}

function validateReplaceConfig(sourceProjectNo: string, targetProjectNo: string) {
  const source = sourceProjectNo.trim();
  const target = targetProjectNo.trim();

  if (!source) {
    return "请填写原始项目号。";
  }

  if (!target) {
    return "请填写目标项目号。";
  }

  if (source === target) {
    return "原始项目号和目标项目号不能相同。";
  }

  return null;
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
