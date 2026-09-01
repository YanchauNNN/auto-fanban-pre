// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("account workspace focus visibility", () => {
  it("uses opaque focus rings with at least 3:1 contrast on pale surfaces", () => {
    const pageCss = readFileSync(
      resolve(process.cwd(), "src/features/account/AccountPage.module.css"),
      "utf8",
    );
    const adminCss = readFileSync(
      resolve(process.cwd(), "src/features/account/AccountAdminPage.module.css"),
      "utf8",
    );
    const focusColor = "#0b5fa5";

    expect(pageCss).toContain(`outline: 3px solid ${focusColor};`);
    expect(adminCss).toContain(`outline: 3px solid ${focusColor};`);
    expect(pageCss).toMatch(/\.settlementList:focus-visible\s*\{/);
    expect(pageCss.match(/:focus-visible\s*\{[^}]*rgba\(/gs)).toBeNull();
    expect(adminCss.match(/:focus-visible\s*\{[^}]*rgba\(/gs)).toBeNull();
    expect(contrastRatio(focusColor, "#f4f8fc")).toBeGreaterThanOrEqual(3);
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
