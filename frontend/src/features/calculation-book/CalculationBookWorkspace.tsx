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
  CalculationBookConfirmationCandidate,
  CalculationBookDirectionEvidence,
  CalculationBookField,
  CalculationBookPreflightResult,
  CalculationBookSlabEvidence,
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

type Phase = "input" | "review" | "confirm";

const NUMERIC_FIELDS = new Set([
  "workshop_length",
  "workshop_width",
  "raft_slab_top_elevation",
  "roof_top_elevation",
  "factory_extreme_min_temperature",
  "factory_extreme_max_temperature",
  "site_soil_temperature",
]);

const DIRECTION_LABELS = {
  X: "水平筋",
  Y: "竖向筋",
  Z: "拉筋",
} as const;

const CONFIRMATION_REASON_LABELS: Record<string, string> = {
  duplicate_reinforcement_rows: "配筋表存在重复墙号",
  split_image_group: "图片采用 -1/-2 分组",
};

const SLAB_GROUP_ORDER = [
  "top_x",
  "top_y",
  "middle_x",
  "middle_y",
  "bottom_x",
  "bottom_y",
  "z",
] as const;

const SLAB_GROUP_LABELS: Record<string, string> = {
  top_x: "TOP-X · 上表面 X 向",
  top_y: "TOP-Y · 上表面 Y 向",
  middle_x: "MIDDLE-X · 中部 X 向",
  middle_y: "MIDDLE-Y · 中部 Y 向",
  bottom_x: "BOTTOM-X · 下表面 X 向",
  bottom_y: "BOTTOM-Y · 下表面 Y 向",
  z: "Z · Z 向",
};

const FIVE_SLAB_GROUPS = ["top_x", "top_y", "bottom_x", "bottom_y", "z"] as const;

type SlabEvidenceGroup = {
  elevation: string;
  items: CalculationBookSlabEvidence[];
  expectedCount: 5 | 7;
  hasMiddle: boolean;
  sourceRows: number[];
  issues: string[];
  complete: boolean;
};

function formatSlabKey(key: string): string {
  return key.toUpperCase().replace("_", "-");
}

function compareElevations(left: string, right: string): number {
  const leftNumber = Number(left);
  const rightNumber = Number(right);
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
    return leftNumber - rightNumber;
  }
  return left.localeCompare(right, "zh-CN", { numeric: true });
}

function buildSlabEvidenceGroups(
  slabs: readonly CalculationBookSlabEvidence[],
): SlabEvidenceGroup[] {
  const grouped = slabs.reduce((groups, item) => {
    const current = groups.get(item.elevation) ?? [];
    current.push(item);
    groups.set(item.elevation, current);
    return groups;
  }, new Map<string, CalculationBookSlabEvidence[]>());

  return Array.from(grouped, ([elevation, rawItems]) => {
    const counts = rawItems.reduce((result, item) => {
      const key = item.key.toLowerCase();
      result.set(key, (result.get(key) ?? 0) + 1);
      return result;
    }, new Map<string, number>());
    const hasMiddle = counts.has("middle_x") || counts.has("middle_y");
    const expectedCount: 5 | 7 = hasMiddle ? 7 : 5;
    const expectedKeys = hasMiddle ? SLAB_GROUP_ORDER : FIVE_SLAB_GROUPS;
    const missingKeys = expectedKeys.filter((key) => !counts.has(key));
    const duplicateKeys = Array.from(counts)
      .filter(([, count]) => count > 1)
      .map(([key]) => key);
    const unexpectedKeys = Array.from(counts.keys()).filter(
      (key) => !SLAB_GROUP_ORDER.includes(key as (typeof SLAB_GROUP_ORDER)[number]),
    );
    const sourceRows = Array.from(new Set(rawItems.map((item) => item.sourceRow))).sort(
      (left, right) => left - right,
    );
    const issues = [
      ...(missingKeys.length > 0
        ? [`缺少 ${missingKeys.map(formatSlabKey).join("、")}`]
        : []),
      ...(duplicateKeys.length > 0
        ? [`重复 ${duplicateKeys.map(formatSlabKey).join("、")}`]
        : []),
      ...(unexpectedKeys.length > 0
        ? [`存在未知组 ${unexpectedKeys.map(formatSlabKey).join("、")}`]
        : []),
      ...(sourceRows.length > 1
        ? [`同一标高来自配筋表多行：${sourceRows.join("、")}`]
        : []),
    ];
    const order = new Map<string, number>(
      SLAB_GROUP_ORDER.map((key, index) => [key, index]),
    );
    const items = [...rawItems].sort((left, right) => {
      const leftOrder = order.get(left.key.toLowerCase()) ?? Number.MAX_SAFE_INTEGER;
      const rightOrder = order.get(right.key.toLowerCase()) ?? Number.MAX_SAFE_INTEGER;
      return leftOrder - rightOrder || left.key.localeCompare(right.key);
    });
    return {
      elevation,
      items,
      expectedCount,
      hasMiddle,
      sourceRows,
      issues,
      complete: issues.length === 0 && items.length === expectedKeys.length,
    };
  }).sort((left, right) => compareElevations(left.elevation, right.elevation));
}

function formatFileSize(bytes: number): string {
  if (bytes >= 1024 ** 3) {
    return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  }
  if (bytes >= 1024 ** 2) {
    return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  }
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

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
  const [phase, setPhase] = useState<Phase>("input");
  const [preflight, setPreflight] = useState<CalculationBookPreflightResult | null>(null);
  const [selectedRows, setSelectedRows] = useState<Record<string, number>>({});
  const [confirmedWalls, setConfirmedWalls] = useState<Record<string, boolean>>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [formErrors, setFormErrors] = useState<string[]>([]);
  const [busyAction, setBusyAction] = useState<"preflight" | "submit" | null>(null);
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const initialFocusRef = useRef<HTMLSelectElement>(null);
  const errorSummaryRef = useRef<HTMLDivElement>(null);
  const reviewHeadingRef = useRef<HTMLHeadingElement>(null);
  const wasOpenRef = useRef(false);

  useEffect(() => {
    if (isOpen && !wasOpenRef.current) {
      setValues(initialValues);
      setArchive(null);
      setPhase("input");
      setPreflight(null);
      setSelectedRows({});
      setConfirmedWalls({});
      setFieldErrors({});
      setFormErrors([]);
      setBusyAction(null);
    }
    wasOpenRef.current = isOpen;
  }, [initialValues, isOpen]);

  useLayoutEffect(() => {
    if (!isOpen) {
      return;
    }
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    initialFocusRef.current?.focus({ preventScroll: true });
    return () => {
      previousFocus?.focus();
    };
  }, [isOpen]);

  if (!isOpen || !calculationSchema) {
    return null;
  }

  const activeSchema = calculationSchema;
  const slabField = calculationSchema.fields.find(
    (field) => field.key === "include_slab_stress",
  );
  const projectFields = calculationSchema.fields.filter(
    (field) => !NUMERIC_FIELDS.has(field.key) && field.key !== "include_slab_stress",
  );
  const workshopFields = calculationSchema.fields.filter((field) => NUMERIC_FIELDS.has(field.key));
  const fieldErrorCount = Object.values(fieldErrors).filter((messages) => messages.length > 0).length;
  const hasValidationErrors = fieldErrorCount > 0 || formErrors.length > 0;
  const allRequiredWallsConfirmed =
    preflight?.confirmations.every((item) => confirmedWalls[item.wallId]) ?? true;
  const slabEvidenceGroups = buildSlabEvidenceGroups(preflight?.slabs ?? []);
  const slabEvidenceIssues =
    preflight && values.include_slab_stress === "true"
      ? slabEvidenceGroups.length > 0
        ? slabEvidenceGroups.flatMap((group) =>
            group.issues.map((issue) => `${group.elevation}m：${issue}`),
          )
        : ["已勾选楼板应力，但预检结果未返回楼板云图证据"]
      : [];
  const slabEvidenceComplete = slabEvidenceIssues.length === 0;
  const busy = busyAction !== null;

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
    if (field.key === "include_slab_stress" && preflight) {
      resetPreflight();
    }
  }

  function resetPreflight() {
    setPhase("input");
    setPreflight(null);
    setSelectedRows({});
    setConfirmedWalls({});
  }

  function handleArchive(file: File | null) {
    setArchive(file);
    setFormErrors([]);
    resetPreflight();
  }

  function requestClose() {
    if (!busy) {
      onClose();
    }
  }

  function focusFirstValidationError(
    nextFieldErrors: Record<string, string[]>,
    nextFormErrors: string[],
  ) {
    window.requestAnimationFrame(() => {
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

  function validateInput() {
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
    setFieldErrors(nextFieldErrors);
    setFormErrors(nextFormErrors);
    if (Object.keys(nextFieldErrors).length > 0 || nextFormErrors.length > 0) {
      focusFirstValidationError(nextFieldErrors, nextFormErrors);
      return false;
    }
    return true;
  }

  function buildParams(): SubmissionParams {
    return Object.fromEntries(
      activeSchema.fields.map((field) => {
        const raw = String(values[field.key] ?? "").trim();
        return [
          field.key,
          field.type === "number"
            ? Number(raw)
            : field.type === "checkbox"
              ? raw === "true"
              : raw,
        ];
      }),
    );
  }

  function applyApiError(error: unknown, fallback: string) {
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
        : [fallback];
    const nextApiFieldErrors = detail?.param_errors ?? {};
    if (Object.keys(nextApiFieldErrors).length > 0) {
      setPhase("input");
    }
    setFieldErrors(nextApiFieldErrors);
    setFormErrors(nextApiFormErrors);
    focusFirstValidationError(nextApiFieldErrors, nextApiFormErrors);
  }

  async function handlePreflight() {
    if (busy || !validateInput()) {
      return;
    }
    setBusyAction("preflight");
    setFieldErrors({});
    setFormErrors([]);
    try {
      if (!adapter.preflightCalculationBook) {
        throw new Error("当前后台不支持计算书预检。");
      }
      const result = await adapter.preflightCalculationBook(
        archive as File,
        {
          includeSlabStress:
            String(values.include_slab_stress ?? "false") === "true",
        },
      );
      setPreflight(result);
      setSelectedRows(
        Object.fromEntries(
          result.confirmations.map((item) => [item.wallId, item.suggestedSourceRow]),
        ),
      );
      setConfirmedWalls({});
      setPhase("review");
      window.requestAnimationFrame(() => reviewHeadingRef.current?.focus());
    } catch (error) {
      applyApiError(error, "计算书预检失败，请根据提示修正 ZIP 后重试。");
    } finally {
      setBusyAction(null);
    }
  }

  async function handleCreate() {
    if (
      busy ||
      !preflight ||
      !archive ||
      !allRequiredWallsConfirmed ||
      !slabEvidenceComplete
    ) {
      return;
    }
    setBusyAction("submit");
    setFieldErrors({});
    setFormErrors([]);
    try {
      if (!adapter.createCalculationBook) {
        throw new Error("当前后台不支持计算书任务。");
      }
      const params: SubmissionParams = {
        ...buildParams(),
        preflight_token: preflight.preflightToken,
        manual_confirmations: Object.fromEntries(
          preflight.confirmations.map((item) => [
            item.wallId,
            selectedRows[item.wallId] ?? item.suggestedSourceRow,
          ]),
        ),
      };
      const payload = await adapter.createCalculationBook(params);
      startTransition(() => onBatchCreated(payload));
      onClose();
    } catch (error) {
      applyApiError(error, "计算书任务创建失败，请检查确认项后重试。");
    } finally {
      setBusyAction(null);
    }
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (phase === "input") {
      if (!validateInput()) {
        return;
      }
      if (preflight) {
        setPhase("review");
        window.requestAnimationFrame(() => reviewHeadingRef.current?.focus());
      } else {
        void handlePreflight();
      }
    } else if (phase === "review") {
      if (!slabEvidenceComplete) {
        return;
      }
      setPhase("confirm");
      window.requestAnimationFrame(() => reviewHeadingRef.current?.focus());
    } else {
      void handleCreate();
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
            <p>上传、核验、人工确认后再进入后台任务队列。</p>
          </div>
          <button
            aria-label="关闭创建计算书"
            className={styles.closeButton}
            disabled={busy}
            type="button"
            onClick={requestClose}
          >
            关闭
          </button>
        </header>

        <form noValidate onSubmit={handleSubmit}>
          <nav className={styles.steps} aria-label="计算书创建步骤">
            <span
              aria-current={phase === "input" ? "step" : undefined}
              data-state={phase === "input" ? "current" : "completed"}
            >
              01 文件与参数
            </span>
            <span
              aria-current={phase === "review" ? "step" : undefined}
              data-state={phase === "input" ? "pending" : phase === "review" ? "current" : "completed"}
            >
              02 规范化核验
            </span>
            <span
              aria-current={phase === "confirm" ? "step" : undefined}
              data-state={phase === "confirm" ? "current" : "pending"}
            >
              03 确认提交
            </span>
          </nav>

          {busy ? (
            <div
              className={styles.progress}
              role="progressbar"
              aria-valuetext={busyAction === "preflight" ? "正在预检计算书文件" : "正在创建计算书任务"}
            >
              <span />
              {busyAction === "preflight" ? "正在读取图例与配筋表…" : "正在提交任务…"}
            </div>
          ) : null}

          {phase === "input" ? (
            <div className={styles.content}>
              <aside className={styles.archivePanel}>
                <div className={styles.stepBadge}>01 · 任务文件</div>
                <h3>ZIP 结构检查</h3>
                <p className={styles.helper}>{calculationSchema.archive.description}</p>
                <div className={styles.tree} aria-label="ZIP 必需结构">
                  <div className={styles.treeRoot}>计算图片.zip</div>
                  <div><span>├─</span> 墙体01-X.png</div>
                  <div><span>├─</span> 墙体01-Y.png</div>
                  <div><span>├─</span> 墙体01-Z.png</div>
                  <div><span>├─</span> 计算书模板文件.xlsx</div>
                  <div><span>├─</span> 01 / 厂房标高布置图</div>
                  <div><span>└─</span> 02 / 墙体有限元模型图</div>
                </div>
                {slabField ? (
                  <label className={styles.slabToggle}>
                    <input
                      aria-describedby="calculation-book-slab-toggle-help"
                      aria-labelledby="calculation-book-slab-toggle-label"
                      checked={values[slabField.key] === "true"}
                      type="checkbox"
                      onChange={(event) =>
                        updateValue(
                          slabField,
                          String(event.currentTarget.checked),
                        )}
                    />
                    <span>
                      <strong id="calculation-book-slab-toggle-label">{slabField.label}</strong>
                      <small id="calculation-book-slab-toggle-help">
                        勾选后，每个标高识别 TOP-X、TOP-Y、BOTTOM-X、BOTTOM-Y、Z，共 5 组；
                        同时包含 MIDDLE-X 和 MIDDLE-Y 时为 7 组。楼板实配钢筋仅从 Excel
                        的“楼板配筋”工作表读取，页面不提供手工输入。
                      </small>
                    </span>
                  </label>
                ) : null}
                <label className={styles.uploadBox}>
                  <span>{archive ? archive.name : "选择 ZIP 文件"}</span>
                  <small>{archive ? formatFileSize(archive.size) : "仅支持单个 .zip 文件"}</small>
                  <input
                    accept={calculationSchema.archive.accept.join(",")}
                    aria-label="选择计算图片 ZIP"
                    type="file"
                    onChange={(event) => handleArchive(event.currentTarget.files?.[0] ?? null)}
                  />
                </label>
                <div className={styles.validationList} aria-live="polite">
                  <span data-ready={archive ? "true" : "false"}>单个 ZIP</span>
                  <span>根目录 X / Y / Z 图片</span>
                  <span>根目录墙体配筋表</span>
                  <span>01 与 02 子目录</span>
                </div>
              </aside>

              <section className={styles.formPanel}>
                <div className={styles.stepBadge}>02 · 参数</div>
                {hasValidationErrors ? (
                  <ErrorPanel
                    panelRef={errorSummaryRef}
                    fieldErrorCount={fieldErrorCount}
                    formErrors={formErrors}
                  />
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
          ) : preflight ? (
            <ReviewPanel
              headingRef={reviewHeadingRef}
              phase={phase}
              preflight={preflight}
              selectedRows={selectedRows}
              confirmedWalls={confirmedWalls}
              onSelectRow={(wallId, row) => {
                setSelectedRows((current) => ({ ...current, [wallId]: row }));
                setConfirmedWalls((current) => ({ ...current, [wallId]: false }));
              }}
              onConfirm={(wallId, checked) =>
                setConfirmedWalls((current) => ({ ...current, [wallId]: checked }))
              }
              slabEvidenceGroups={slabEvidenceGroups}
              slabEvidenceIssues={slabEvidenceIssues}
            />
          ) : null}

          {phase !== "input" && hasValidationErrors ? (
            <div className={styles.reviewErrors}>
              <ErrorPanel
                panelRef={errorSummaryRef}
                fieldErrorCount={fieldErrorCount}
                formErrors={formErrors}
              />
            </div>
          ) : null}

          <footer className={styles.footer}>
            <div aria-live="polite">
              <strong>
                {busyAction === "preflight"
                  ? "正在核验文件…"
                  : busyAction === "submit"
                    ? "正在创建任务…"
                      : phase === "input"
                      ? "先预检，再创建任务"
                      : phase === "review"
                        ? slabEvidenceComplete
                          ? "核验完成，进入确认提交"
                          : "楼板证据不完整，不能提交"
                        : allRequiredWallsConfirmed
                        ? "核验完成，可以创建任务"
                        : "请完成所有人工确认"}
              </strong>
              <span>
                {phase === "input"
                  ? "预检会读取图例、规范化配筋并检查图片对应关系。"
                  : phase === "review"
                    ? "确认识别证据无误后，再检查人工映射与最终摘要。"
                    : "ZIP 已由预检暂存，创建时不会重复上传；完成后可下载 DOCX。"}
              </span>
            </div>
            <div className={styles.footerActions}>
              {phase !== "input" ? (
                <button
                  className={styles.secondaryButton}
                  disabled={busy}
                  type="button"
                  onClick={() => setPhase(phase === "confirm" ? "review" : "input")}
                >
                  {phase === "confirm" ? "返回核验" : "返回修改"}
                </button>
              ) : null}
              <button
                className={styles.secondaryButton}
                disabled={busy}
                type="button"
                onClick={requestClose}
              >
                取消
              </button>
              <button
                className={styles.primaryButton}
                disabled={
                  busy ||
                  (phase !== "input" && !slabEvidenceComplete) ||
                  (phase === "confirm" && !allRequiredWallsConfirmed)
                }
                type="submit"
              >
                {busyAction === "preflight"
                  ? "正在预检…"
                  : busyAction === "submit"
                    ? "正在创建…"
                    : phase === "input"
                      ? preflight ? "继续核对" : "预检并核对"
                      : phase === "review"
                        ? "进入确认提交"
                        : "创建计算书任务"}
              </button>
            </div>
          </footer>
        </form>
      </div>
    </TaskConfigModal>
  );
}

function ReviewPanel({
  phase,
  preflight,
  selectedRows,
  confirmedWalls,
  onSelectRow,
  onConfirm,
  slabEvidenceGroups,
  slabEvidenceIssues,
  headingRef,
}: {
  phase: Exclude<Phase, "input">;
  preflight: CalculationBookPreflightResult;
  selectedRows: Record<string, number>;
  confirmedWalls: Record<string, boolean>;
  onSelectRow: (wallId: string, row: number) => void;
  onConfirm: (wallId: string, checked: boolean) => void;
  slabEvidenceGroups: SlabEvidenceGroup[];
  slabEvidenceIssues: string[];
  headingRef: RefObject<HTMLHeadingElement>;
}) {
  return (
    <section className={styles.reviewPanel}>
      <div className={styles.reviewHeader}>
        <div>
          <p className={styles.stepBadge}>02 · 规范化核验</p>
          <h3 ref={headingRef} tabIndex={-1}>
            {phase === "review" ? "文件与配筋对应结果" : "最终确认与提交"}
          </h3>
          <p>
            {phase === "review"
              ? "所有数值均保留图片和 Excel 单元格证据，请先核对识别结果。"
              : `本次采用配筋表：${preflight.reinforcementWorkbook}。确认人工映射后才允许创建任务。`}
          </p>
        </div>
        <div className={styles.summaryCards}>
          <span aria-label={`共 ${preflight.wallCount} 面墙`}>
            <strong>{preflight.wallCount}</strong><small>面墙</small>
          </span>
          <span aria-label={`共 ${preflight.figureCount} 张云图`}>
            <strong>{preflight.figureCount}</strong><small>云图</small>
          </span>
          <span aria-label={`共 ${preflight.zeroFigureCount} 张 Z 向零值图`}>
            <strong>{preflight.zeroFigureCount}</strong><small>Z 向零值</small>
          </span>
          {preflight.slabFigureCount > 0 ? (
            <>
              <span aria-label={`共 ${preflight.slabElevationCount} 个楼板标高`}>
                <strong>{preflight.slabElevationCount}</strong><small>楼板标高</small>
              </span>
              <span aria-label={`共 ${preflight.slabFigureCount} 张楼板云图`}>
                <strong>{preflight.slabFigureCount}</strong><small>楼板云图</small>
              </span>
            </>
          ) : null}
        </div>
      </div>

      {preflight.warnings.map((warning) => (
        <div className={styles.warningPanel} key={warning.code} role="status">
          <strong>
            {warning.code === "slab_ignored_by_choice"
              ? "压缩包包含楼板云图，本次未勾选楼板应力，已跳过"
              : "以下根目录图片未按墙号-X/Y/Z规则进入计算"}
          </strong>
          <p>{warning.filenames.join("、")}</p>
        </div>
      ))}

      {phase === "confirm" && preflight.confirmations.length > 0 ? (
        <div className={styles.confirmationSection}>
          <div>
            <p className={styles.stepBadge}>03 · 人工确认</p>
            <h3>重复配筋行与分组图片</h3>
          </div>
          {preflight.confirmations.map((item) => (
            <article className={styles.confirmationCard} key={item.wallId}>
              <header>
                <div>
                  <h4>{item.wallId} 需要人工确认</h4>
                  <p>
                    {item.reasons.map((reason) => CONFIRMATION_REASON_LABELS[reason] ?? reason).join("；")}
                  </p>
                </div>
                <span>建议第 {item.suggestedSourceRow} 行</span>
              </header>
              <fieldset>
                <legend>选择与该图片组对应的配筋表行</legend>
                {item.candidates.map((candidate) => (
                  <CandidateOption
                    candidate={candidate}
                    checked={(selectedRows[item.wallId] ?? item.suggestedSourceRow) === candidate.sourceRow}
                    key={candidate.sourceRow}
                    name={`confirmation-${item.wallId}`}
                    onChange={() => onSelectRow(item.wallId, candidate.sourceRow)}
                  />
                ))}
              </fieldset>
              <label className={styles.confirmCheckbox}>
                <input
                  checked={Boolean(confirmedWalls[item.wallId])}
                  type="checkbox"
                  onChange={(event) => onConfirm(item.wallId, event.currentTarget.checked)}
                />
                <span>已核对 {item.wallId} 的图片与配筋对应关系</span>
              </label>
            </article>
          ))}
        </div>
      ) : phase === "confirm" ? (
        <div className={styles.successPanel}>未发现重复配筋行或 -1/-2 图片组，无需额外人工映射。</div>
      ) : null}

      {slabEvidenceIssues.length > 0 ? (
        <div className={styles.slabEvidenceError} role="alert">
          <strong>楼板云图证据不完整，已阻止进入提交</strong>
          {slabEvidenceIssues.map((issue) => <p key={issue}>{issue}</p>)}
        </div>
      ) : null}

      {slabEvidenceGroups.length > 0 ? (
        <div className={styles.evidenceSection}>
          <div>
            <h3>逐标高楼板识别证据</h3>
            <p>
              这里只核对图片、Excel 单元格和精确公式结果；实配钢筋不在页面重复录入。
            </p>
          </div>
          {slabEvidenceGroups.map((group, groupIndex) => (
            <details
              className={styles.wallEvidence}
              key={`slab-${group.elevation}`}
              open={groupIndex === 0}
            >
              <summary>
                <strong>{group.elevation}m 楼板</strong>
                <span>
                  <b data-complete={group.complete ? "true" : "false"}>
                    {group.items.length}/{group.expectedCount}{" "}
                    {group.complete ? "完整" : "异常"}
                    {group.hasMiddle ? " · 含 MIDDLE" : ""}
                  </b>
                  {" · "}
                  配筋表第 {group.sourceRows.join("、")} 行
                </span>
              </summary>
              <div className={styles.slabDirectionGrid}>
                {group.items.map((item) => (
                  <SlabEvidenceCard
                    evidence={item}
                    key={`${item.elevation}-${item.key}`}
                  />
                ))}
              </div>
            </details>
          ))}
        </div>
      ) : null}

      <div className={styles.evidenceSection}>
        <div>
          <h3>逐墙识别证据</h3>
          <p>展开墙号可核对图例范围、原始写法、成品表写法，以及按精确公式计算后的实配面积显示值。</p>
        </div>
        {preflight.walls.map((wall) => {
          const confirmation = preflight.confirmations.find(
            (item) => item.wallId === wall.wallId,
          );
          const selectedRow =
            selectedRows[wall.wallId] ?? confirmation?.suggestedSourceRow ?? wall.suggestedSourceRow;
          const selectedCandidate = confirmation?.candidates.find(
            (candidate) => candidate.sourceRow === selectedRow,
          );
          return (
            <details
              className={styles.wallEvidence}
              open={phase === "confirm" && confirmation ? true : undefined}
              key={`${phase}-${wall.wallId}`}
            >
              <summary>
                <strong>{wall.wallId}</strong>
                <span>配筋表第 {selectedRow} 行</span>
              </summary>
              <div className={styles.directionGrid}>
                {(["X", "Y", "Z"] as const).map((direction) => (
                  <DirectionEvidence
                    direction={direction}
                    evidence={{
                      ...wall.directions[direction],
                      ...selectedCandidate?.directions[direction],
                    }}
                    key={direction}
                  />
                ))}
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}

function SlabEvidenceCard({
  evidence,
}: {
  evidence: CalculationBookSlabEvidence;
}) {
  return (
    <article className={styles.directionCard}>
      <header>
        <h4>{SLAB_GROUP_LABELS[evidence.key] ?? evidence.key}</h4>
        <span>{evidence.sourceCell}</span>
      </header>
      <p>{evidence.imageFilename}</p>
      <dl>
        <div>
          <dt>计算范围</dt>
          <dd>
            {evidence.isZeroResult
              ? "无 SMX，计算值按 0 处理"
              : `${evidence.smn} → ${evidence.smx} mm²/m`}
          </dd>
        </div>
        <div>
          <dt>Excel 写法</dt>
          <dd>{evidence.originalText}</dd>
        </div>
        <div>
          <dt>规范写法</dt>
          <dd>{evidence.canonicalSpecification}</dd>
        </div>
        <div>
          <dt>计算书用语</dt>
          <dd>{evidence.narrativeSpecification}</dd>
        </div>
        <div>
          <dt>实配面积</dt>
          <dd>{evidence.actualArea} mm²/m</dd>
        </div>
      </dl>
    </article>
  );
}

function CandidateOption({
  candidate,
  name,
  checked,
  onChange,
}: {
  candidate: CalculationBookConfirmationCandidate;
  name: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <label className={styles.candidateOption}>
      <input checked={checked} name={name} type="radio" onChange={onChange} />
      <span>
        <strong>{candidate.sourceSheet} · 第 {candidate.sourceRow} 行</strong>
        <small>
          {(["X", "Y", "Z"] as const)
            .map((direction) => {
              const evidence = candidate.directions[direction];
              const unit = direction === "Z" ? "mm²/m²" : "mm²/m";
              return (
                `${direction}: ${evidence.originalText} → ` +
                `${evidence.canonicalSpecification}（${evidence.actualArea} ${unit}）`
              );
            })
            .join(" · ")}
        </small>
      </span>
    </label>
  );
}

function DirectionEvidence({
  direction,
  evidence,
}: {
  direction: "X" | "Y" | "Z";
  evidence: CalculationBookDirectionEvidence;
}) {
  return (
    <article className={styles.directionCard}>
      <header>
        <strong>{direction} · {DIRECTION_LABELS[direction]}</strong>
        <span>{evidence.sourceCell}</span>
      </header>
      <p>{evidence.imageFilename}</p>
      <dl>
        <div>
          <dt>计算范围</dt>
          <dd>
            {evidence.isZeroResult
              ? "Z 向无 SMX，计算值按 0 处理"
              : `${evidence.smn} → ${evidence.smx} mm²/m`}
          </dd>
        </div>
        <div>
          <dt>原始写法</dt>
          <dd>{evidence.originalText}</dd>
        </div>
        <div>
          <dt>成品表写法</dt>
          <dd>{evidence.canonicalSpecification}</dd>
        </div>
        <div>
          <dt>计算书用语</dt>
          <dd>{evidence.narrativeSpecification}</dd>
        </div>
        <div>
          <dt>实配面积</dt>
          <dd>
            {evidence.actualArea} {direction === "Z" ? "mm²/m²" : "mm²/m"}
          </dd>
        </div>
      </dl>
    </article>
  );
}

const ErrorPanel = ({
  fieldErrorCount,
  formErrors,
  panelRef,
}: {
  fieldErrorCount: number;
  formErrors: string[];
  panelRef: RefObject<HTMLDivElement>;
}) => (
  <div ref={panelRef} className={styles.errorPanel} role="alert" tabIndex={-1}>
    {fieldErrorCount > 0 ? (
      <strong>请修正 {fieldErrorCount} 个参数，已定位到第一个错误字段。</strong>
    ) : null}
    {formErrors.map((message) => <p key={message}>{message}</p>)}
  </div>
);

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
