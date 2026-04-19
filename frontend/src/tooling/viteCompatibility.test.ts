// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

describe("vite browser compatibility", () => {
  it("ships a compatibility build for non-Chrome browsers and older Chromium shells", () => {
    const configSource = readFileSync(resolve(process.cwd(), "vite.config.ts"), "utf8");

    expect(configSource).toContain('@vitejs/plugin-legacy');
    expect(configSource).toContain("legacy({");
    expect(configSource).toContain('targets: ["defaults", "not IE 11"]');
    expect(configSource).toContain('cssTarget: "chrome61"');
  });

  it("forces pdf preview runtime to use pdfjs legacy build", () => {
    const configSource = readFileSync(resolve(process.cwd(), "vite.config.ts"), "utf8");
    const appSource = readFileSync(resolve(process.cwd(), "src/app/App.tsx"), "utf8");

    expect(configSource).toContain("find: /^pdfjs-dist$/");
    expect(configSource).toContain('replacement: "pdfjs-dist/legacy/build/pdf.mjs"');
    expect(appSource).toContain('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url');
    expect(appSource).toContain("pdfjs.GlobalWorkerOptions.workerSrc = pdfPreviewWorkerUrl");
  });
});
