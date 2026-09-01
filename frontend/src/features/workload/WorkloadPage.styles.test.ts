// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("workload page visual accessibility", () => {
  it("uses a WCAG AA muted-text token for compact labels", () => {
    const workloadCss = readFileSync(
      resolve(process.cwd(), "src/features/workload/WorkloadPage.module.css"),
      "utf8",
    );
    const tokenMatch = workloadCss.match(/--workload-muted-text:\s*(#[0-9a-f]{6})/i);
    expect(tokenMatch, "应定义统一的小字高对比度颜色").not.toBeNull();
    if (!tokenMatch) {
      return;
    }

    expect(contrastRatio(tokenMatch[1], "#f7faff")).toBeGreaterThanOrEqual(4.5);
    ["#5b7da5", "#607996", "#687f99", "#71849a"].forEach((legacyColor) => {
      expect(workloadCss.toLowerCase()).not.toContain(legacyColor);
    });
  });
});

function contrastRatio(foreground: string, background: string) {
  const foregroundLuminance = relativeLuminance(foreground);
  const backgroundLuminance = relativeLuminance(background);
  const lighter = Math.max(foregroundLuminance, backgroundLuminance);
  const darker = Math.min(foregroundLuminance, backgroundLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

function relativeLuminance(color: string) {
  const channels = [1, 3, 5].map(
    (offset) => Number.parseInt(color.slice(offset, offset + 2), 16) / 255,
  );
  const [red, green, blue] = channels.map((channel) =>
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}
