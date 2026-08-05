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
  return DIRECTION_LABELS[field] ?? "相关配筋";
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

function warningMessage(warning: CalculationBookWarning): string {
  if (warning.code === "duplicate_reinforcement_rows") {
    return "同一墙体存在重复配筋行，相关配筋字段已留空";
  }
  if (warning.code === "split_image_group") {
    return "墙体存在 -1/-2 应力图组，配筋对应关系需人工补充，相关配筋字段已留空";
  }
  if (warning.code === "image_only_wall") {
    return "应力图中存在该墙体，但配筋表没有对应数据，相关配筋字段已留空";
  }
  if (warning.code === "workbook_only_wall") {
    return "配筋表中存在该墙体，但应力图中没有对应图组，未生成对应图片段落";
  }
  if (warning.code === "image_only_slab") {
    return "应力图中存在该楼板标高，但配筋表没有对应数据，相关配筋字段已留空";
  }
  if (warning.code === "workbook_only_slab") {
    return "配筋表中存在该楼板标高，但应力图中没有对应图组，未生成对应图片段落";
  }

  const direction = warning.direction
    ? fieldLabel(warning.direction)
    : "相关方向";
  if (warning.code === "OCR_RECOGNITION_FAILED") {
    return `SMX 识别失败，${direction}建议已留空，请核对对应云图`;
  }
  if (warning.code === "NO_ELIGIBLE_CANDIDATE") {
    return `没有满足至少 10% 裕度的候选，${direction}建议已留空`;
  }
  if (warning.code === "AI_NEEDS_REVIEW") {
    return `AI 未能形成确定建议，${direction}已留空，请人工复核`;
  }
  if (warning.code === "AI_BASE_FAILURE_LIMIT") {
    return `AI 连续三次调用或协议校验失败，${direction}建议已留空`;
  }
  if (warning.code === "UNKNOWN_IMAGE_NAME") {
    return "云图文件名无法匹配墙体或楼板，未生成该图片的配筋建议";
  }

  const reinforcementDirection = warning.direction
    ? `${fieldLabel(warning.direction)}配筋`
    : "部分配筋";
  const blankResult = warning.blankFields.length > 0
    ? `${warning.blankFields.map(fieldLabel).join("、")}已留空`
    : "相关字段已留空";
  return `${groupLabel(warning)} 的${reinforcementDirection}信息无法确定，${blankResult}`;
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
  if (
    !output
    || (!output.aiNormalized && !output.aiRebarSuggestion && output.warningCount === 0)
  ) {
    return null;
  }

  const groups = groupWarnings(output.warnings);
  const normalized = output.aiNormalization;
  const suggested = output.aiRebarSuggestion;
  const isSuggested = output.reinforcementSource === "ai_suggested" || Boolean(suggested);
  const validationLabel = suggested?.validation === "passed"
    ? "通过"
    : suggested?.validation || "未记录";

  return (
    <section
      aria-label={isSuggested ? "AI 配筋建议结果" : "配筋表人工补充提醒"}
      className={styles.panel}
      role="region"
    >
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>
            {isSuggested ? "云图配筋建议结果" : "配筋表处理结果"}
          </p>
          <h3 id="calculation-book-reinforcement-warning-title">
            {isSuggested
              ? "AI 配筋建议已生成"
              : output.aiNormalized
              ? "AI 已规范化非标准配筋表"
              : "配筋结果包含待补充字段"}
          </h3>
          {suggested ? (
            <p>
              已生成 {suggested.suggestedDirectionCount} 个方向，
              {suggested.blankDirectionCount} 个方向留空待复核。
            </p>
          ) : normalized ? (
            <p>
              已处理 {normalized.sourceRowCount} 行源数据，确定内容已继续生成计算书。
            </p>
          ) : null}
        </div>
        {output.warningCount > 0 ? (
          <strong className={styles.warningCount}>
            {isSuggested ? "需人工复核" : "需人工补充"} {output.warningCount} 项
          </strong>
        ) : (
          <span className={styles.completeState}>无需补充</span>
        )}
      </header>

      {suggested ? (
        <div aria-label="AI 配筋建议摘要" className={styles.suggestionSummary}>
          <div className={styles.suggestionMetrics}>
            <span><small>建议方向</small><strong>{suggested.suggestedDirectionCount}</strong></span>
            <span><small>留空方向</small><strong>{suggested.blankDirectionCount}</strong></span>
            <span><small>模型调用</small><strong>{suggested.callCount}</strong></span>
            <span><small>修复轮次</small><strong>{suggested.repairRoundCount}</strong></span>
          </div>
          <div className={styles.suggestionMeta}>
            <span><small>内部模型</small><strong>{suggested.model || "未记录"}</strong></span>
            <span title={suggested.skillSha256 || undefined}>
              <small>Skill</small>
              <strong>
                {suggested.skillId || "未记录"}
                {suggested.skillVersion ? ` · v${suggested.skillVersion}` : ""}
              </strong>
            </span>
            <span><small>后端校验</small><strong>{validationLabel}</strong></span>
          </div>
        </div>
      ) : null}

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
                    <p>{warningMessage(warning)}</p>
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
