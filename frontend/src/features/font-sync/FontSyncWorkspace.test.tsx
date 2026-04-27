import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FontSyncWorkspace } from "./FontSyncWorkspace";
import type { ApiAdapter, FontSyncEnvironment } from "../../platform/api/types";

function createEnvironment(): FontSyncEnvironment {
  return {
    autocadReady: true,
    supported: true,
    activeProfile: "CADUserProfile",
    supportPath: "C:\\CAD\\Fonts",
    fontFileMap: "C:\\CAD\\fontmap.fmp",
    altFontFile: "simplex.shx",
    windowsFontsDir: "C:\\Windows\\Fonts",
    fontSearchRoots: ["C:\\CAD\\Fonts", "C:\\Windows\\Fonts"],
    installations: [
      {
        label: "AutoCAD 2022",
        installDir: "C:\\Program Files\\Autodesk\\AutoCAD 2022",
        acadExe: "C:\\Program Files\\Autodesk\\AutoCAD 2022\\acad.exe",
        accoreconsoleExe: "C:\\Program Files\\Autodesk\\AutoCAD 2022\\accoreconsole.exe",
        fontsDir: "C:\\Program Files\\Autodesk\\AutoCAD 2022\\Fonts",
      },
    ],
    selectedInstallation: {
      label: "AutoCAD 2022",
      installDir: "C:\\Program Files\\Autodesk\\AutoCAD 2022",
      acadExe: "C:\\Program Files\\Autodesk\\AutoCAD 2022\\acad.exe",
      accoreconsoleExe: "C:\\Program Files\\Autodesk\\AutoCAD 2022\\accoreconsole.exe",
      fontsDir: "C:\\Program Files\\Autodesk\\AutoCAD 2022\\Fonts",
    },
    errors: [],
  };
}

function createAdapter(): ApiAdapter {
  const environment = createEnvironment();
  return {
    getHealth: vi.fn(),
    getFormSchema: vi.fn(),
    preflightFonts: vi.fn(),
    createBatch: vi.fn(),
    createAuditCheck: vi.fn(),
    createAuditReplace: vi.fn(),
    listJobs: vi.fn(),
    getJobDetail: vi.fn(),
    scanFontSyncSource: vi.fn().mockResolvedValue({
      sourceId: "source-1",
      sourcePath: "C:\\temp\\source.dwg",
      bundleMode: "guaranteed",
      drawing: { filename: "source.dwg" },
      environment,
      styles: [
        {
          styleName: "STYLE-SHX",
          fontName: "simplex.shx",
          bigfontName: "",
          kind: "shx",
        },
      ],
      fontDependencies: [
        {
          dependencyId: "STYLE-SHX:font:simplex.shx",
          styleName: "STYLE-SHX",
          role: "font",
          fontName: "simplex.shx",
          kind: "shx",
          usedInBlock: false,
          absolutePathReference: false,
          resolved: true,
          resolvedPath: "C:\\CAD\\Fonts\\simplex.shx",
          copyStatus: "copied",
          bundleFontName: "simplex.shx",
        },
      ],
    }),
    exportFontSyncBundle: vi.fn(),
    scanFontSyncTarget: vi.fn().mockResolvedValue({
      environment,
      supported: true,
      autocadReady: true,
    }),
    previewFontSyncBundle: vi.fn().mockResolvedValue({
      importId: "import-1",
      bundleId: "bundle-1",
      bundleFilename: "bundle.fanfontsync",
      bundleMode: "guaranteed",
      currentEnvironment: environment,
      plannedChanges: {
        managedRoot: "C:\\managed\\bundle-1",
        managedFontsDir: "C:\\managed\\bundle-1\\fonts",
        supportPath: "C:\\CAD\\Fonts;C:\\managed\\bundle-1\\fonts",
        fontFileMap: "C:\\managed\\bundle-1\\fontmap.fmp",
        altFontFile: "simplex.shx",
      },
      diff: {
        supportPathChanged: true,
        fontFileMapChanged: true,
        altFontFileChanged: false,
      },
      manifest: {},
    }),
    applyFontSyncBundle: vi.fn().mockResolvedValue({
      importId: "import-1",
      bundleId: "bundle-1",
      bundleMode: "guaranteed",
      status: "matched",
      profileBackupPath: "C:\\backup\\target-profile.arg",
      managedRoot: "C:\\managed\\bundle-1",
      managedFontsDir: "C:\\managed\\bundle-1\\fonts",
      fontFileMap: "C:\\managed\\bundle-1\\fontmap.fmp",
      environment,
    }),
  };
}

describe("FontSyncWorkspace", () => {
  it("scans a source dwg and renders dependency summary", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();

    render(<FontSyncWorkspace adapter={adapter} />);

    await user.upload(
      screen.getByLabelText("选择源 DWG 图纸"),
      new File(["dwg"], "source.dwg", { type: "application/acad" }),
    );
    await user.click(screen.getByRole("button", { name: "开始扫描" }));

    await waitFor(() => {
      expect(adapter.scanFontSyncSource).toHaveBeenCalledTimes(1);
    });

    expect(screen.getByText("可保证复现")).toBeInTheDocument();
    expect(screen.getByText("STYLE-SHX")).toBeInTheDocument();
  });

  it("previews and applies a bundle after upload", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();

    render(<FontSyncWorkspace adapter={adapter} />);

    await user.upload(
      screen.getByLabelText("选择同步记录包"),
      new File(["bundle"], "bundle.fanfontsync", { type: "application/octet-stream" }),
    );
    await user.click(screen.getByRole("button", { name: "导入预览" }));

    await waitFor(() => {
      expect(adapter.previewFontSyncBundle).toHaveBeenCalledTimes(1);
    });

    await user.click(screen.getByRole("button", { name: "应用同步" }));

    await waitFor(() => {
      expect(adapter.applyFontSyncBundle).toHaveBeenCalledWith("import-1");
    });

    expect(screen.getByText("已对齐")).toBeInTheDocument();
  });
});
