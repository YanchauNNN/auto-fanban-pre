// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("AI chat drawer layout", () => {
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
