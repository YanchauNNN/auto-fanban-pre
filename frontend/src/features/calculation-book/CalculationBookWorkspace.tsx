import {
  startTransition,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";

import type {
  ApiAdapter,
  CalculationBookField,
  CreateBatchPayload,
  FormSchema,
  SubmissionParams,
} from "../../platform/api/types";
import { TaskConfigModal } from "../../shared/ui/TaskConfigModal";
import styles from "./CalculationBookWorkspace.module.css";

type Props = {
  adapter: ApiAdapter;
  schema: FormSchema;
  isOpen: boolean;
  onBatchCreated: (payload: CreateBatchPayload) => void;
  onClose: () => void;
};

const NUMERIC_FIELDS = new Set([
  "workshop_length",
  "workshop_width",
  "raft_slab_top_elevation",
  "roof_top_elevation",
  "factory_extreme_min_temperature",
  "factory_extreme_max_temperature",
  "site_soil_temperature",
]);

export function CalculationBookWorkspace({
  adapter,
  schema,
  isOpen,
  onBatchCreated,
  onClose,
}: Props) {
  const calculationSchema = schema.calculationBook;
  const initialValues = useMemo(
    () =>
      Object.fromEntries(
        (calculationSchema?.fields ?? []).map((field) => [
          field.key,
          field.defaultValue ?? "",
        ]),
      ),
    [calculationSchema],
  );
  const [values, setValues] = useState<Record<string, string>>(initialValues);
  const [archive, setArchive] = useState<File | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const initialFocusRef = useRef<HTMLSelectElement>(null);
  const errorSummaryRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setValues(initialValues);
  }, [initialValues]);

  useLayoutEffect(() => {
    if (!isOpen) {
      return;
    }
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    initialFocusRef.current?.focus();
    return () => {
      previousFocus?.focus();
    };
  }, [isOpen]);

  if (!isOpen || !calculationSchema) {
    return null;
  }

  const activeSchema = calculationSchema;
  const projectFields = calculationSchema.fields.filter((field) => !NUMERIC_FIELDS.has(field.key));
  const workshopFields = calculationSchema.fields.filter((field) => NUMERIC_FIELDS.has(field.key));
  const fieldErrorCount = Object.values(fieldErrors).filter((messages) => messages.length > 0).length;
  const hasValidationErrors = fieldErrorCount > 0 || formErrors.length > 0;

  function updateValue(field: CalculationBookField, nextValue: string) {
    setValues((current) => {
      const next = { ...current, [field.key]: nextValue };
      if (field.key === "project_no") {
        next.project_name =
          calculationSchema?.projectOptions.find((option) => option.value === nextValue)?.label ?? "";
      }
      return next;
    });
    setFieldErrors((current) => ({ ...current, [field.key]: [] }));
  }

  function handleArchive(file: File | null) {
    setArchive(file);
    setFormErrors([]);
  }

  function requestClose() {
    if (!submitting) {
      onClose();
    }
  }

  function focusFirstValidationError(
    nextFieldErrors: Record<string, string[]>,
    nextFormErrors: string[],
  ) {
    window.requestAnimationFrame(() => {
      const firstInvalidField = activeSchema.fields.find(
        (field) => nextFieldErrors[field.key]?.length,
      );
      if (firstInvalidField) {
        document.getElementById(`calculation-book-${firstInvalidField.key}`)?.focus();
        return;
      }
      if (nextFormErrors.length > 0) {
        errorSummaryRef.current?.focus();
      }
    });
  }

  function trapFocus(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab" || !surfaceRef.current) {
      return;
    }
    const focusable = Array.from(
      surfaceRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((element) => element.offsetParent !== null || element === document.activeElement);
    if (focusable.length === 0) {
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) {
      return;
    }
    const nextFieldErrors: Record<string, string[]> = {};
    for (const field of activeSchema.fields) {
      if (field.required && !String(values[field.key] ?? "").trim()) {
        nextFieldErrors[field.key] = [`请填写${field.label}`];
      }
    }
    const nextFormErrors: string[] = [];
    if (!archive) {
      nextFormErrors.push("请选择计算图片 ZIP。");
    } else if (!archive.name.toLowerCase().endsWith(".zip")) {
      nextFormErrors.push("计算图片必须使用 .zip 格式。");
    }
    if (Object.keys(nextFieldErrors).length > 0 || nextFormErrors.length > 0) {
      setFieldErrors(nextFieldErrors);
      setFormErrors(nextFormErrors);
      focusFirstValidationError(nextFieldErrors, nextFormErrors);
      return;
    }

    const params: SubmissionParams = Object.fromEntries(
      activeSchema.fields.map((field) => {
        const raw = String(values[field.key] ?? "").trim();
        return [field.key, field.type === "number" ? Number(raw) : raw];
      }),
    );
    setSubmitting(true);
    setFieldErrors({});
    setFormErrors([]);
    try {
      if (!adapter.createCalculationBook) {
        throw new Error("当前后台不支持计算书任务。");
      }
      const payload = await adapter.createCalculationBook(params, archive as File);
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
      const nextApiFormErrors =
        Object.values(detail?.upload_errors ?? {}).flat().length > 0
          ? Object.values(detail?.upload_errors ?? {}).flat()
          : ["计算书任务创建失败，请检查输入后重试。"];
      const nextApiFieldErrors = detail?.param_errors ?? {};
      setFieldErrors(nextApiFieldErrors);
      setFormErrors(nextApiFormErrors);
      focusFirstValidationError(nextApiFieldErrors, nextApiFormErrors);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <TaskConfigModal
      dialogClassName={styles.dialog}
      title="创建计算书"
      onRequestClose={requestClose}
    >
      <div ref={surfaceRef} className={styles.surface} onKeyDown={trapFocus}>
        <header className={styles.header}>
          <div>
            <p className={styles.kicker}>Calculation Book</p>
            <h2>创建计算书</h2>
            <p>填写工程与厂房参数，上传保持原目录结构的计算图片 ZIP。</p>
          </div>
          <button
            aria-label="关闭创建计算书"
            className={styles.closeButton}
            disabled={submitting}
            type="button"
            onClick={requestClose}
          >
            关闭
          </button>
        </header>

        <form noValidate onSubmit={handleSubmit}>
          <div className={styles.content}>
            <aside className={styles.archivePanel}>
              <div className={styles.stepBadge}>01 · 计算图片</div>
              <h3>ZIP 结构检查</h3>
              <p className={styles.helper}>{calculationSchema.archive.description}</p>
              <div className={styles.tree} aria-label="ZIP 必需结构">
                <div className={styles.treeRoot}>计算图片.zip</div>
                <div><span>├─</span> 墙体01-X.png</div>
                <div><span>├─</span> 墙体01-Y.png</div>
                <div><span>├─</span> 墙体01-Z.png</div>
                <div><span>├─</span> 01 / 厂房标高布置图</div>
                <div><span>└─</span> 02 / 墙体有限元模型图</div>
              </div>
              <label className={styles.uploadBox}>
                <span>{archive ? archive.name : "选择 ZIP 文件"}</span>
                <small>{archive ? `${Math.max(1, Math.round(archive.size / 1024))} KB` : "仅支持单个 .zip 文件"}</small>
                <input
                  accept={calculationSchema.archive.accept.join(",")}
                  aria-label="选择计算图片 ZIP"
                  type="file"
                  onChange={(event) => handleArchive(event.currentTarget.files?.[0] ?? null)}
                />
              </label>
              <div className={styles.validationList} aria-live="polite">
                <span data-ready={archive ? "true" : "false"}>单个 ZIP</span>
                <span>根目录 X / Y / Z（提交后校验）</span>
                <span>01 与 02 子目录（提交后校验）</span>
              </div>
            </aside>

            <section className={styles.formPanel}>
              <div className={styles.stepBadge}>02 · 参数</div>
              {hasValidationErrors ? (
                <div
                  ref={errorSummaryRef}
                  className={styles.errorPanel}
                  role="alert"
                  tabIndex={-1}
                >
                  {fieldErrorCount > 0 ? (
                    <strong>请修正 {fieldErrorCount} 个参数，已定位到第一个错误字段。</strong>
                  ) : null}
                  {formErrors.map((message) => <p key={message}>{message}</p>)}
                </div>
              ) : null}
              <FieldGroup
                fields={projectFields}
                initialFocusRef={initialFocusRef}
                projectOptions={calculationSchema.projectOptions}
                templateOptions={calculationSchema.templates}
                values={values}
                errors={fieldErrors}
                onChange={updateValue}
                title="工程基本信息"
              />
              <FieldGroup
                fields={workshopFields}
                projectOptions={calculationSchema.projectOptions}
                templateOptions={calculationSchema.templates}
                values={values}
                errors={fieldErrors}
                onChange={updateValue}
                title="厂房与温度参数"
              />
            </section>
          </div>

          <footer className={styles.footer}>
            <div aria-live="polite">
              <strong>{submitting ? "正在创建任务…" : "任务将进入后台队列"}</strong>
              <span>生成完成后可在任务详情下载 DOCX。</span>
            </div>
            <div className={styles.footerActions}>
              <button
                className={styles.secondaryButton}
                disabled={submitting}
                type="button"
                onClick={requestClose}
              >
                取消
              </button>
              <button className={styles.primaryButton} disabled={submitting} type="submit">
                {submitting ? "正在创建…" : "创建计算书任务"}
              </button>
            </div>
          </footer>
        </form>
      </div>
    </TaskConfigModal>
  );
}

function FieldGroup({
  fields,
  values,
  errors,
  templateOptions,
  projectOptions,
  initialFocusRef,
  title,
  onChange,
}: {
  fields: readonly CalculationBookField[];
  values: Record<string, string>;
  errors: Record<string, string[]>;
  templateOptions: readonly { value: string; label: string }[];
  projectOptions: readonly { value: string; label: string }[];
  initialFocusRef?: RefObject<HTMLSelectElement>;
  title: string;
  onChange: (field: CalculationBookField, value: string) => void;
}) {
  return (
    <fieldset className={styles.fieldset}>
      <legend>{title}</legend>
      <div className={styles.fieldGrid}>
        {fields.map((field) => {
          const fieldId = `calculation-book-${field.key}`;
          const errorId = `${fieldId}-error`;
          const options =
            field.key === "template_type"
              ? templateOptions
              : field.key === "project_no"
                ? projectOptions
                : (field.options ?? []).map((value) => ({ value, label: value }));
          const readOnly = field.key === "project_name";
          return (
            <div className={`${styles.field} ${field.key === "document_name" ? styles.fieldWide : ""}`} key={field.key}>
              <label htmlFor={fieldId}>
                <span>
                  {field.label}
                  {field.required ? <em>必填</em> : null}
                </span>
                {field.unit ? <small>{field.unit}</small> : null}
              </label>
              {field.type === "select" ? (
                <select
                  ref={field.key === "template_type" ? initialFocusRef : undefined}
                  aria-label={field.label}
                  aria-describedby={errors[field.key]?.length ? errorId : undefined}
                  aria-invalid={errors[field.key]?.length ? "true" : undefined}
                  aria-required={field.required}
                  id={fieldId}
                  required={field.required}
                  value={values[field.key] ?? ""}
                  onChange={(event) => onChange(field, event.currentTarget.value)}
                >
                  <option value="">请选择</option>
                  {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              ) : (
                <input
                  aria-label={field.label}
                  aria-describedby={errors[field.key]?.length ? errorId : undefined}
                  aria-invalid={errors[field.key]?.length ? "true" : undefined}
                  aria-required={field.required}
                  id={fieldId}
                  placeholder={field.placeholder}
                  readOnly={readOnly}
                  required={field.required}
                  step={field.type === "number" ? "any" : undefined}
                  type={field.type === "number" ? "number" : "text"}
                  value={values[field.key] ?? ""}
                  onChange={(event) => onChange(field, event.currentTarget.value)}
                />
              )}
              {errors[field.key]?.length ? (
                <span className={styles.fieldError} id={errorId}>
                  {errors[field.key].join("；")}
                </span>
              ) : null}
            </div>
          );
        })}
      </div>
    </fieldset>
  );
}
