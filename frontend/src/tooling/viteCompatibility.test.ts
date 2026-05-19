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
    const previewSource = readFileSync(resolve(process.cwd(), "src/app/PreviewPdfModal.tsx"), "utf8");

    expect(configSource).toContain("find: /^pdfjs-dist$/");
    expect(configSource).toContain('replacement: "pdfjs-dist/legacy/build/pdf.mjs"');
    expect(previewSource).toContain('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url');
    expect(previewSource).toContain('pdfjs.GlobalWorkerOptions.workerSrc = `${pdfPreviewWorkerUrl}?react-pdf-compat=5.4.296`');
  });

  it("keeps oversized pdf preview pages horizontally scrollable from a top control", () => {
    const appCssSource = readFileSync(resolve(process.cwd(), "src/app/App.module.css"), "utf8");
    const viewerControlsBlock =
      appCssSource.match(/\.previewViewerControls \{[\s\S]*?\n\}/)?.[0] ?? "";
    const previewPagesBlock = appCssSource.match(/\.previewPages \{[\s\S]*?\n\}/)?.[0] ?? "";

    expect(viewerControlsBlock).toContain("position: sticky;");
    expect(previewPagesBlock).toContain("overflow-x: hidden;");
    expect(appCssSource).toContain("width: max-content;");
  });
});
