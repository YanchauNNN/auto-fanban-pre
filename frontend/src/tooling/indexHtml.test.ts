// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("index html shell assets", () => {
  it("declares a favicon so browsers do not fall back to a missing /favicon.ico request", () => {
    const htmlSource = readFileSync(resolve(process.cwd(), "index.html"), "utf8");

    expect(htmlSource).toContain('rel="icon"');
  });
});
