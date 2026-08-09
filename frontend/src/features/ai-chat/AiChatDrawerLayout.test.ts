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

  it("uses one desktop mascot at the drawer top-left for hide and resize", () => {
    const css = readFileSync(
      resolve(process.cwd(), "src/features/ai-chat/AiChatDrawer.module.css"),
      "utf8",
    );
    const drawerSource = readFileSync(
      resolve(process.cwd(), "src/features/ai-chat/AiChatDrawer.tsx"),
      "utf8",
    );
    const handleRule = css.match(/\.drawerMascotHandle\s*\{[\s\S]*?\n\}/)?.[0] ?? "";
    const bubbleRule = css.match(/\.drawerMascotBubble\s*\{[\s\S]*?\n\}/)?.[0] ?? "";
    const headerRule = css.match(/\.header\s*\{[\s\S]*?\n\}/)?.[0] ?? "";

    expect(handleRule).toContain("position: absolute;");
    expect(handleRule).toContain("top: 0.18rem;");
    expect(handleRule).toContain("left: 0.45rem;");
    expect(bubbleRule).toContain("top: calc(100% + 0.12rem);");
    expect(bubbleRule).toContain("left: 0.25rem;");
    expect(headerRule).toContain("padding: 1rem 1rem 0.75rem 6.35rem;");
    expect(drawerSource).toContain("<AiDrawerMascotHandle");
    expect(drawerSource).not.toContain("className={styles.resizeHandle}");
    expect(drawerSource).not.toContain('aria-label="关闭 AI 助手"');
  });
});
