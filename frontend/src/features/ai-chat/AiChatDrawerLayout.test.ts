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
    const layerRule = css.match(/\.mascotActorLayer\s*\{[\s\S]*?\n\}/)?.[0] ?? "";
    const buttonRule = css.match(/\.mascotActorButton\s*\{[\s\S]*?\n\}/)?.[0] ?? "";
    const bubbleRule = css.match(/\.mascotActorBubble\s*\{[\s\S]*?\n\}/)?.[0] ?? "";

    expect(layerRule).toContain("position: fixed;");
    expect(layerRule).toContain("top: var(--ai-mascot-top);");
    expect(layerRule).toContain("right: 0.6rem;");
    expect(layerRule).toContain("pointer-events: none;");
    expect(buttonRule).toContain("position: fixed;");
    expect(buttonRule).toContain("touch-action: none;");
    expect(bubbleRule).toContain("right: calc(100% + 0.35rem);");
    expect(css).toContain('[data-mascot-phase="opening_ride"]');
    expect(css).toContain("right: calc(var(--ai-drawer-width) - 2.7rem);");
    expect(css).toContain("transition: transform 330ms");
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

  it("uses the real drawer panel to occlude the mascot between its rear rig and gripping fingers", () => {
    const css = readFileSync(
      resolve(process.cwd(), "src/features/ai-chat/AiChatDrawer.module.css"),
      "utf8",
    );
    const drawerSource = readFileSync(
      resolve(process.cwd(), "src/features/ai-chat/AiChatDrawer.tsx"),
      "utf8",
    );
    const actorSource = readFileSync(
      resolve(process.cwd(), "src/features/ai-chat/AiMascotActor.tsx"),
      "utf8",
    );
    const drawerRule = css.match(/\.drawer\s*\{[\s\S]*?\n\}/)?.[0] ?? "";
    const panelRule = css.match(/\.drawerPanel\s*\{[\s\S]*?\n\}/)?.[0] ?? "";
    const rearRule = css.match(/\.mascotActorRear\s*\{[\s\S]*?\n\}/)?.[0] ?? "";
    const frontRule = css.match(/\.mascotActorFront\s*\{[\s\S]*?\n\}/)?.[0] ?? "";
    const buttonRule = css.match(/\.mascotActorButton\s*\{[\s\S]*?\n\}/)?.[0] ?? "";
    const headerRule = css.match(/\.header\s*\{[\s\S]*?\n\}/)?.[0] ?? "";

    expect(rearRule).toContain("z-index: 37;");
    expect(drawerRule).toContain("z-index: 38;");
    expect(frontRule).toContain("z-index: 39;");
    expect(buttonRule).toContain("z-index: 40;");
    expect(drawerRule).toContain("overflow: visible;");
    expect(panelRule).toContain("position: relative;");
    expect(panelRule).toContain("overflow: hidden;");
    expect(panelRule).toContain("height: 100%;");
    expect(headerRule).toContain("padding:");
    expect(drawerSource).toContain("<AiMascotActor");
    expect(drawerSource).toContain("<div className={styles.drawerPanel}>");
    expect(actorSource).toContain('pass="rear"');
    expect(actorSource).toContain('pass="front"');
    expect(drawerSource).not.toContain("className={styles.resizeHandle}");
    expect(drawerSource).not.toContain('aria-label="关闭 AI 助手"');
  });

  it("keeps the persisted vertical position active on mobile", () => {
    const css = readFileSync(
      resolve(process.cwd(), "src/features/ai-chat/AiChatDrawer.module.css"),
      "utf8",
    );
    const mobileBlock = css.match(/@media \(max-width: 720px\)[\s\S]*?\n\}/)?.[0] ?? "";
    const mobileLayerRule =
      mobileBlock.match(/\.mascotActorLayer\s*\{[\s\S]*?\n\s*\}/)?.[0] ?? "";
    const mobileOpenRule =
      mobileBlock.match(/\[data-mascot-phase="open_cling"\][\s\S]*?\n\s*\}/)?.[0] ?? "";
    const mobileHeaderRule = mobileBlock.match(/\.header\s*\{[\s\S]*?\n\s*\}/)?.[0] ?? "";

    expect(mobileLayerRule).toContain(".mascotActorLayer {");
    expect(mobileLayerRule).not.toContain("top: auto;");
    expect(mobileLayerRule).toContain("width: 5rem;");
    expect(mobileLayerRule).toContain("height: 6.25rem;");
    expect(mobileOpenRule).toContain("right: calc(100vw - 5.45rem);");
    expect(mobileHeaderRule).toContain("padding-left:");
  });
});
