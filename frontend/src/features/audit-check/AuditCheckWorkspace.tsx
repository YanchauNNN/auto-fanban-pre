import { startTransition, useDeferredValue, useEffect, useId, useMemo, useRef, useState } from "react";

import type { ApiAdapter, CreateBatchPayload, FormSchema } from "../../platform/api/types";
import { TaskConfigModal } from "../deliverable/TaskConfigModal";
import styles from "./AuditCheckWorkspace.module.css";

type AuditCheckWorkspaceProps = {
  adapter: ApiAdapter;
  schema: FormSchema;
  isOpen: boolean;
  onBatchCreated: (payload: CreateBatchPayload) => void;
  onClose: () => void;
  onDraftAvailabilityChange: (available: boolean) => void;
};

type AuditCheckDraft = {
  projectNo: string;
  files: File[];
  fieldErrors: Record<string, string[]>;
  formErrors: string[];
};

const MAX_COMBO_OPTIONS = 10;

export function AuditCheckWorkspace({
  adapter,
  schema,
  isOpen,
  onBatchCreated,
  onClose,
  onDraftAvailabilityChange,
}: AuditCheckWorkspaceProps) {
  const [draft, setDraft] = useState<AuditCheckDraft>(createAuditDraft());
  const [isSubmitting, setIsSubmitting] = useState(false);
  const projectOptions = useMemo(
    () => (schema.auditReplaceProjectOptions ?? []).filter((option) => option.trim().length > 0),
    [schema.auditReplaceProjectOptions],
  );

  useEffect(() => {
    onDraftAvailabilityChange(Boolean(draft.projectNo.trim()) || draft.files.length > 0);
  }, [draft.files.length, draft.projectNo, onDraftAvailabilityChange]);

  if (!isOpen) {
    return null;
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextFieldErrors: Record<string, string[]> = {};
    const nextFormErrors: string[] = [];

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

    if (nextFormErrors.length > 0 || Object.keys(nextFieldErrors).length > 0) {
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
      const payload = await adapter.createAuditCheck(draft.projectNo.trim(), draft.files);
      setDraft(createAuditDraft());
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

  function handleProjectNoChange(value: string) {
    setDraft((current) => ({
      ...current,
      projectNo: value,
      fieldErrors: {
        ...current.fieldErrors,
        project_no: [],
      },
    }));
  }

  function handleFilesReplace(files: File[]) {
    if (files.length === 0) {
      return;
    }
    setDraft((current) => ({
      ...current,
      files,
      formErrors: [],
    }));
  }

  function handleClearDraft() {
    setDraft(createAuditDraft());
    onClose();
  }

  return (
    <TaskConfigModal title="纠错配置">
      <div className={styles.layout}>
        <header className={styles.header}>
          <div>
            <p className={styles.kicker}>Audit Check</p>
            <h2>纠错配置</h2>
            <p className={styles.description}>
              这一轮只接真实纠错链路。表单只保留项目号和 DWG 文件，关闭后保留草稿，再次打开可继续提交。
            </p>
          </div>
          <div className={styles.headerActions}>
            <button className={styles.ghostButton} type="button" onClick={onClose}>
              关闭纠错配置
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
                <p className={styles.emptyState}>当前还没有纠错文件草稿。</p>
              )}
              <div className={styles.summaryActions}>
                <label className={styles.fileButton}>
                  选择纠错 DWG
                  <input
                    accept=".dwg"
                    aria-label="选择纠错 DWG 文件"
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
              <h3>纠错参数</h3>

              {draft.formErrors.length > 0 ? (
                <div className={styles.formErrorPanel}>
                  {draft.formErrors.map((error) => (
                    <p key={error}>{error}</p>
                  ))}
                </div>
              ) : null}

              <div className={styles.fieldStack}>
                <div className={styles.field}>
                  <div className={styles.fieldHeader}>
                    <label className={styles.fieldLabel} htmlFor="audit-project-no">
                      <span>项目号</span>
                    </label>
                  </div>

                  <ProjectNoCombobox
                    options={projectOptions}
                    value={draft.projectNo}
                    onChange={handleProjectNoChange}
                  />

                  <span className={styles.helperText}>
                    可留空，届时将依赖文件名推断；联调时仍建议显式选择项目号。
                  </span>

                  {draft.fieldErrors.project_no?.[0] ? (
                    <span className={styles.errorText}>{draft.fieldErrors.project_no[0]}</span>
                  ) : null}
                </div>

                <div className={styles.field}>
                  <span className={styles.hintStrong}>推荐项目号</span>
                  <div className={styles.recommendations}>
                    {projectOptions.map((option) => (
                      <button
                        key={option}
                        className={styles.recommendationChip}
                        type="button"
                        onClick={() => handleProjectNoChange(option)}
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
              {isSubmitting ? "创建中..." : "创建纠错任务"}
            </button>
          </footer>
        </form>
      </div>
    </TaskConfigModal>
  );
}

function ProjectNoCombobox({
  value,
  options,
  onChange,
}: {
  value: string;
  options: readonly string[];
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const listId = useId();
  const deferredValue = useDeferredValue(value);
  const filteredOptions = options
    .filter((option) => option.toLowerCase().includes(deferredValue.trim().toLowerCase()))
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
          aria-label="项目号"
          className={styles.input}
          id="audit-project-no"
          placeholder="输入或选择项目号"
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
          aria-label="项目号选项"
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

function createAuditDraft(): AuditCheckDraft {
  return {
    projectNo: "",
    files: [],
    fieldErrors: {},
    formErrors: [],
  };
}

function getExtension(filename: string) {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot).toLowerCase() : "";
}
