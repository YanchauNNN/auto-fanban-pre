// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("login page hero layout", () => {
  it("keeps the main login title pinned to the top-left and on one line", () => {
    const stylesheet = readFileSync(resolve(process.cwd(), "src/app/App.module.css"), "utf8");
    const heroContentBlock = stylesheet.match(/\.loginHeroContent\s*\{[^}]+\}/)?.[0] ?? "";
    const heroTitleBlock = stylesheet.match(/\.loginHeroTitle\s*\{[^}]+\}/)?.[0] ?? "";

    expect(heroContentBlock).toContain("justify-content: flex-start");
    expect(heroTitleBlock).toContain("white-space: nowrap");
  });
});
