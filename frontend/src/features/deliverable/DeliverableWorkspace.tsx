import { startTransition, useDeferredValue, useEffect, useId, useState } from "react";

import { evaluateRequiredWhen, isAdvancedField } from "../schema/schema";
import type {
  ApiAdapter,
  CreateBatchPayload,
  FormField,
  FormSchema,
} from "../../platform/api/types";
import styles from "./DeliverableWorkspace.module.css";

type DeliverableWorkspaceProps = {
  adapter: ApiAdapter;
  schema: FormSchema;
  onBatchCreated: (payload: CreateBatchPayload) => void;
};

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const NAME_ID_PATTERN = /^.+@.+$/;

export function DeliverableWorkspace({
  adapter,
  schema,
  onBatchCreated,
}: DeliverableWorkspaceProps) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [files, setFiles] = useState<File[]>([]);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    setValues(
      Object.fromEntries(
        schema.sections.flatMap((section) =>
          section.fields.map((field) => [field.key, field.defaultValue]),
        ),
      ),
    );
  }, [schema]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextFieldErrors: Record<string, string[]> = {};
    const nextFormErrors: string[] = [];

    for (const field of schema.sections.flatMap((section) => section.fields)) {
      const value = values[field.key]?.trim() ?? "";
      const required =
        field.required || evaluateRequiredWhen(field.requiredWhen, values);

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

    if (files.length === 0) {
      nextFormErrors.push("请至少上传一个 DWG 文件。");
    }

    const invalidFiles = files.filter(
      (file) => !schema.uploadLimits.allowedExts.includes(getExtension(file.name)),
    );
    if (invalidFiles.length > 0) {
      nextFormErrors.push("only .dwg files are allowed");
    }

    const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
    if (totalBytes > schema.uploadLimits.maxTotalMb * 1024 * 1024) {
      nextFormErrors.push(
        `total upload exceeds ${schema.uploadLimits.maxTotalMb} MB`,
      );
    }

    if (Object.keys(nextFieldErrors).length > 0 || nextFormErrors.length > 0) {
      setFieldErrors(nextFieldErrors);
      setFormErrors(nextFormErrors);
      return;
    }

    setFieldErrors({});
    setFormErrors([]);
    setIsSubmitting(true);

    try {
      const payload = await adapter.createBatch(values, files);
      startTransition(() => onBatchCreated(payload));
      setFiles([]);
    } catch (error) {
      const detail =
        typeof error === "object" && error && "detail" in error
          ? (error as { detail?: { upload_errors?: Record<string, string[]>; param_errors?: Record<string, string[]> } }).detail
          : undefined;
      setFieldErrors(detail?.param_errors ?? {});
      setFormErrors(Object.values(detail?.upload_errors ?? {}).flat());
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className={styles.workspacePanel}>
      <header className={styles.header}>
        <div>
          <p className={styles.kicker}>Deliverable Pipeline</p>
          <h2>交付处理任务</h2>
          <p className={styles.description}>
            使用真实 API 创建批量任务。表单规则完全跟随后端 schema。
          </p>
        </div>
        <button
          className={styles.secondaryButton}
          type="button"
          onClick={() => setShowAdvanced((current) => !current)}
        >
          {showAdvanced ? "收起高级选项" : "展开高级选项"}
        </button>
      </header>

      <form className={styles.form} onSubmit={handleSubmit}>
        <section className={styles.uploadSection}>
          <label className={styles.uploadLabel} htmlFor="dwg-upload">
            上传 DWG 文件
          </label>
          <input
            accept=".dwg"
            aria-label="上传 DWG 文件"
            id="dwg-upload"
            multiple
            type="file"
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
          />
          <p className={styles.uploadHint}>
            单次最多 {schema.uploadLimits.maxFiles} 个文件，总大小不超过{" "}
            {schema.uploadLimits.maxTotalMb} MB。
          </p>
          {files.length > 0 ? (
            <ul className={styles.fileList}>
              {files.map((file) => (
                <li key={file.name}>
                  <span>{file.name}</span>
                  <span>{Math.max(1, Math.round(file.size / 1024))} KB</span>
                </li>
              ))}
            </ul>
          ) : null}
        </section>

        {formErrors.length > 0 ? (
          <div className={styles.formErrorPanel}>
            {formErrors.map((error) => (
              <p key={error}>{error}</p>
            ))}
          </div>
        ) : null}

        {schema.sections.map((section) => {
          const visibleFields = section.fields.filter(
            (field) => showAdvanced || !isAdvancedField(field),
          );
          if (visibleFields.length === 0) {
            return null;
          }

          return (
            <section className={styles.section} key={section.id}>
              <header className={styles.sectionHeader}>
                <h3>{section.title}</h3>
              </header>
              <div className={styles.fieldGrid}>
                {visibleFields.map((field) => (
                  <FieldControl
                    key={field.key}
                    error={fieldErrors[field.key]?.[0]}
                    field={field}
                    onChange={(nextValue) =>
                      setValues((current) => ({
                        ...current,
                        [field.key]: nextValue,
                      }))
                    }
                    value={values[field.key] ?? ""}
                    values={values}
                  />
                ))}
              </div>
            </section>
          );
        })}

        <footer className={styles.actions}>
          <button className={styles.primaryButton} disabled={isSubmitting} type="submit">
            {isSubmitting ? "创建中..." : "创建交付任务"}
          </button>
        </footer>
      </form>
    </section>
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

  return (
    <label className={styles.field} htmlFor={inputId}>
      <span className={styles.fieldLabel}>
        {field.label}
        {required ? <em>必填</em> : null}
      </span>
      {field.type === "select" ? (
        <SearchableSelectField
          field={field}
          id={inputId}
          onChange={onChange}
          value={value}
        />
      ) : (
        <input
          aria-label={field.label}
          className={styles.input}
          id={inputId}
          name={field.key}
          placeholder={field.description}
          type={field.type === "date" ? "date" : "text"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      <span className={styles.helperText}>{field.description}</span>
      {error ? <span className={styles.errorText}>{error}</span> : null}
    </label>
  );
}

function SearchableSelectField({
  id,
  field,
  value,
  onChange,
}: {
  id: string;
  field: FormField;
  value: string;
  onChange: (value: string) => void;
}) {
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const filteredOptions = field.options.filter((option) =>
    option.toLowerCase().includes(deferredQuery.trim().toLowerCase()),
  );

  return (
    <div className={styles.searchableSelect}>
      <input
        aria-label={`${field.label}筛选`}
        className={styles.searchInput}
        placeholder="筛选选项"
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <select
        aria-label={field.label}
        className={styles.select}
        id={id}
        name={field.key}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">请选择</option>
        {filteredOptions.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </div>
  );
}

function getExtension(filename: string) {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot).toLowerCase() : "";
}
