// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("AI chat drawer layout", () => {
  it("anchors the desktop mascot to the right edge with an inward speech bubble", () => {
    const css = readFileSync(
      resolve(process.cwd(), "src/features/ai-chat/AiChatDrawer.module.css"),
      "utf8",
    );
    const triggerRule = css.match(/\.mascotTrigger\s*\{[\s\S]*?\n\}/)?.[0] ?? "";
    const bubbleRule = css.match(/\.speechBubble\s*\{[\s\S]*?\n\}/)?.[0] ?? "";

    expect(triggerRule).toContain("position: fixed;");
    const stageRule = css.match(/\.mascotStage\s*\{[\s\S]*?\n\}/)?.[0] ?? "";

    expect(triggerRule).toContain("right: 1rem;");
    expect(triggerRule).toContain("width: 6rem;");
    expect(triggerRule).toContain("height: 7.75rem;");
    expect(stageRule).toContain("pointer-events: none;");
    expect(stageRule).toContain("transform: translateX(0.875rem);");
    expect(bubbleRule).toContain("right: calc(100% + 0.35rem);");
    expect(css).not.toContain("writing-mode: vertical-rl;");
  });

  it("keeps assistant markdown messages wide enough for tables and code", () => {
    const css = readFileSync(
      resolve(process.cwd(), "src/features/ai-chat/AiChatDrawer.module.css"),
      "utf8",
    );
    const assistantMessageRule =
      css.match(/\.assistantMessage\s*\{[\s\S]*?\n\}/)?.[0] ?? "";

    expect(assistantMessageRule).toContain("width: 86%;");
  });
});
