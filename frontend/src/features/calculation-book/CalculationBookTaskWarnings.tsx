import type {
  CalculationBookOutput,
  CalculationBookWarning,
} from "../../platform/api/types";
import styles from "./CalculationBookTaskWarnings.module.css";

const DIRECTION_LABELS: Readonly<Record<string, string>> = {
  X: "水平筋",
  Y: "竖向筋",
  Z: "拉筋",
  top_x: "顶层水平向",
  top_y: "顶层竖向",
  middle_x: "中层水平向",
  middle_y: "中层竖向",
  bottom_x: "底层水平向",
  bottom_y: "底层竖向",
  z: "纵向拉筋",
  wall: "墙号",
  wall_id: "墙号",
  elevation: "楼板标高",
};

type WarningGroup = {
  key: string;
  label: string;
  warnings: CalculationBookWarning[];
};

function fieldLabel(field: string): string {
  return DIRECTION_LABELS[field] ?? field;
}

function groupLabel(warning: CalculationBookWarning): string {
  const identity = warning.identity || "未识别编号";
  if (warning.scope === "wall") {
    return `墙体 ${identity}`;
  }
  if (warning.scope === "slab") {
    return `楼板 ${identity}${identity.endsWith("m") ? "" : "m"}`;
  }
  return `配筋数据 ${identity}`;
}

function groupWarnings(warnings: readonly CalculationBookWarning[]): WarningGroup[] {
  const groups = new Map<string, WarningGroup>();
  for (const warning of warnings) {
    const key = `${warning.scope}:${warning.identity ?? ""}`;
    const current = groups.get(key);
    if (current) {
      current.warnings.push(warning);
    } else {
      groups.set(key, {
        key,
        label: groupLabel(warning),
        warnings: [warning],
      });
    }
  }
  return Array.from(groups.values());
}

function WarningEvidence({ warning }: { warning: CalculationBookWarning }) {
  if (!warning.sourceSheet || !warning.sourceRow) {
    return <span className={styles.imageEvidence}>仅图片证据</span>;
  }
  const cells = Array.from(new Set(Object.values(warning.sourceCells))).filter(Boolean);
  return (
    <div className={styles.evidence}>
      <span>{warning.sourceSheet} · 第 {warning.sourceRow} 行</span>
      {cells.length > 0 ? <span>单元格：{cells.join("、")}</span> : null}
    </div>
  );
}

export function CalculationBookTaskWarnings({
  output,
}: {
  output: CalculationBookOutput | undefined;
}) {
  if (!output || (!output.aiNormalized && output.warningCount === 0)) {
    return null;
  }

  const groups = groupWarnings(output.warnings);
  const normalized = output.aiNormalization;

  return (
    <section
      aria-label="配筋表人工补充提醒"
      className={styles.panel}
      role="region"
    >
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>配筋表处理结果</p>
          <h3 id="calculation-book-reinforcement-warning-title">
            {output.aiNormalized
              ? "AI 已规范化非标准配筋表"
              : "配筋结果包含待补充字段"}
          </h3>
          {normalized ? (
            <p>
              已处理 {normalized.sourceRowCount} 行源数据，确定内容已继续生成计算书。
            </p>
          ) : null}
        </div>
        {output.warningCount > 0 ? (
          <strong className={styles.warningCount}>需人工补充 {output.warningCount} 项</strong>
        ) : (
          <span className={styles.completeState}>无需补充</span>
        )}
      </header>

      {groups.length > 0 ? (
        <div className={styles.groups}>
          {groups.map((group) => (
            <details className={styles.group} key={group.key}>
              <summary>
                <span>{group.label}</span>
                <span>{group.warnings.length} 项</span>
              </summary>
              <div className={styles.items}>
                {group.warnings.map((warning, index) => (
                  <article className={styles.item} key={`${warning.code}-${warning.direction ?? "all"}-${index}`}>
                    <div className={styles.itemHeading}>
                      <strong>
                        {warning.direction
                          ? `方向：${fieldLabel(warning.direction)}`
                          : "多方向配筋"}
                      </strong>
                      <span>待补充</span>
                    </div>
                    <p>{warning.reason}</p>
                    {warning.blankFields.length > 0 ? (
                      <p className={styles.blankFields}>
                        留空字段：{warning.blankFields.map(fieldLabel).join("、")}
                      </p>
                    ) : null}
                    <WarningEvidence warning={warning} />
                  </article>
                ))}
              </div>
            </details>
          ))}
        </div>
      ) : null}
    </section>
  );
}
