import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ApiAdapter,
  CalculationBookSlabEvidence,
  FormSchema,
} from "../../platform/api/types";
import { CalculationBookWorkspace } from "./CalculationBookWorkspace";

const calculationFields = [
  { key: "template_type", label: "计算书模板", type: "select", required: true },
  { key: "project_no", label: "项目代号", type: "select", required: true },
  { key: "project_name", label: "项目名称", type: "text", required: true },
  {
    key: "internal_code",
    label: "内部编号",
    type: "text",
    required: true,
    placeholder: "例如：20161NH-JGS01",
  },
  { key: "version", label: "版本", type: "text", required: true, defaultValue: "A" },
  { key: "subproject_code", label: "子项代号或系统号", type: "select", required: true, options: ["RX"] },
  { key: "subproject_name", label: "子项或系统名称", type: "select", required: true, options: ["内部结构"] },
  { key: "design_phase", label: "设计阶段", type: "select", required: true, options: ["施工图设计"] },
  { key: "document_name", label: "文件名称", type: "text", required: true },
  { key: "workshop_length", label: "厂房外轮廓长度", type: "number", required: true, unit: "m" },
  { key: "workshop_width", label: "厂房外轮廓宽度", type: "number", required: true, unit: "m" },
  { key: "raft_slab_top_elevation", label: "筏板顶标高", type: "number", required: true, unit: "m" },
  { key: "roof_top_elevation", label: "屋面顶标高", type: "number", required: true, unit: "m" },
  { key: "factory_extreme_min_temperature", label: "历史最低温度", type: "number", required: true, unit: "℃" },
  { key: "factory_extreme_max_temperature", label: "历史最高温度", type: "number", required: true, unit: "℃" },
  { key: "site_soil_temperature", label: "场地土温", type: "number", required: true, unit: "℃" },
  {
    key: "reinforcement_source",
    label: "配筋来源",
    type: "select",
    required: false,
    defaultValue: "provided",
    options: ["provided", "ai_suggested"],
  },
  {
    key: "include_slab_stress",
    label: "包含楼板应力",
    type: "checkbox",
    required: false,
    defaultValue: "false",
  },
] as const;

const schema = {
  schemaVersion: "frontend-form@1",
  uploadLimits: { maxFiles: 50, allowedExts: [".dwg"], maxTotalMb: 2048 },
  sections: [],
  calculationBook: {
    templates: [{ value: "internal_structure", label: "内部结构计算书" }],
    projectOptions: [{ value: "2016", label: "浙江金七门核电厂1、2号机组" }],
    fields: calculationFields,
    archive: {
      accept: [".zip", ".rar", ".7z"],
      requiredRootDirections: ["X", "Y", "Z"],
      requiredFolders: ["01", "02"],
      rootFigurePattern: "<墙号>-X|Y|Z.png",
      description: "保留目录结构",
    },
  },
} satisfies FormSchema;

const minimalSlabSchema: FormSchema = {
  ...schema,
  calculationBook: {
    ...schema.calculationBook,
    fields: [
      calculationFields[0],
      calculationFields[calculationFields.length - 2],
      calculationFields[calculationFields.length - 1],
    ],
  },
};

const presetSchema: FormSchema = {
  ...schema,
  calculationBook: {
    ...schema.calculationBook,
    projectOptions: [
      ...schema.calculationBook.projectOptions,
      { value: "2026", label: "金七门核电厂扩建工程" },
    ],
    fields: [
      calculationFields[0],
      calculationFields[1],
      calculationFields[2],
      calculationFields[3],
      calculationFields[calculationFields.length - 2],
      calculationFields[calculationFields.length - 1],
    ],
  },
};

const preflightResult = {
  preflightToken: "calculation-preflight-1",
  reinforcementSource: "provided" as const,
  requiresAiRecommendation: false,
  figureCount: 3,
  wallDirectionFigureCount: 3,
  zeroFigureCount: 1,
  zZeroOrMissingSmxCount: 1,
  wallCount: 1,
  reinforcementSourceRowCount: 1,
  reinforcementNormalizedRowCount: 1,
  reinforcementIssueRowCount: 0,
  reinforcementUniqueWallCount: 1,
  normalizationTriggered: true,
  normalizationSkillId: "reinforcement_table_normalizer",
  requiresAiNormalization: false,
  aiReinforcementExpectedSourceRowCount: null,
  aiConfirmationMessage: null,
  formatInspection: {
    wallSheet: "Sheet1",
    slabSheet: "楼板配筋",
    reasons: [],
  },
  imageWallGroupCount: 1,
  imageUniqueWallCount: 1,
  matchedUniqueWallCount: 1,
  imageOnlyWallIds: [],
  workbookOnlyWallIds: [],
  requiresWallCountConfirmation: false,
  normalizationIssues: [],
  reinforcementWorkbook: "计算书模板文件.xlsx",
  requiresManualConfirmation: false,
  slabFigureCount: 0,
  slabZeroFigureCount: 0,
  slabElevationCount: 0,
  slabActualGroupCount: 0,
  requiresOcrReview: false,
  ignoredRootImages: [],
  reviewItems: [],
  slabs: [],
  confirmations: [],
  warnings: [],
  walls: [
    {
      wallId: "N5012",
      baseWallId: "N5012",
      groupIndex: null,
      suggestedSourceRow: 2,
      directions: {
        X: {
          imageFilename: "N5012-X.JPEG",
          smn: 0,
          smx: 2504,
          legendValues: [0, 278, 556, 835, 1113, 1391, 1669, 1948, 2226, 2504],
          isZeroResult: false,
          sourceCell: "B2",
          originalText: "1D32间距200",
          canonicalSpecification: "1D32间距200",
          narrativeSpecification: "1排32@200",
          actualArea: 4021.2,
        },
        Y: {
          imageFilename: "N5012-Y.JPEG",
          smn: 0,
          smx: 2208,
          legendValues: [0, 245, 491, 736, 981, 1227, 1472, 1717, 1963, 2208],
          isZeroResult: false,
          sourceCell: "C2",
          originalText: "1D28间距200",
          canonicalSpecification: "1D28间距200",
          narrativeSpecification: "1排28@200",
          actualArea: 3078.8,
        },
        Z: {
          imageFilename: "N5012-Z.JPEG",
          smn: 0,
          smx: 0,
          legendValues: [],
          isZeroResult: true,
          sourceCell: "D2",
          originalText: "1A14间距400*400#",
          canonicalSpecification: "1C14间距400*400",
          narrativeSpecification: "1排14@400x400",
          actualArea: 962.1,
        },
      },
    },
  ],
} as const;

function aiWallEvidence(wallId: string, needsReview = false) {
  const source = preflightResult.walls[0];
  return {
    ...source,
    wallId,
    baseWallId: wallId,
    suggestedSourceRow: null,
    directions: {
      X: {
        ...source.directions.X,
        imageFilename: `${wallId}-X.JPEG`,
        smx: needsReview ? null : source.directions.X.smx,
        sourceCell: "",
        originalText: "",
        canonicalSpecification: "",
        narrativeSpecification: "",
        actualArea: null,
      },
      Y: {
        ...source.directions.Y,
        imageFilename: `${wallId}-Y.JPEG`,
        sourceCell: "",
        originalText: "",
        canonicalSpecification: "",
        narrativeSpecification: "",
        actualArea: null,
      },
      Z: {
        ...source.directions.Z,
        imageFilename: `${wallId}-Z.JPEG`,
        sourceCell: "",
        originalText: "",
        canonicalSpecification: "",
        narrativeSpecification: "",
        actualArea: null,
      },
    },
  };
}

const aiPreflightResult = {
  ...preflightResult,
  preflightToken: "calculation-ai-preflight-1",
  reinforcementSource: "ai_suggested" as const,
  requiresAiRecommendation: true,
  figureCount: 177,
  wallDirectionFigureCount: 177,
  zeroFigureCount: 2,
  zZeroOrMissingSmxCount: 3,
  wallCount: 59,
  reinforcementSourceRowCount: 0,
  reinforcementNormalizedRowCount: 0,
  reinforcementIssueRowCount: 0,
  reinforcementUniqueWallCount: 0,
  normalizationTriggered: false,
  normalizationSkillId: null,
  formatInspection: { wallSheet: null, slabSheet: null, reasons: [] },
  imageWallGroupCount: 59,
  imageUniqueWallCount: 59,
  matchedUniqueWallCount: 0,
  reinforcementWorkbook: null,
  requiresOcrReview: true,
  reviewItems: [
    {
      code: "split_image_group",
      scope: "wall",
      identity: "N5012-1",
      direction: "X",
      imageFilename: "N5012-1-X.png",
      reason: "-1/-2 图片组需要人工确认",
    },
  ],
  walls: [
    aiWallEvidence("N5012"),
    aiWallEvidence("N5013"),
    aiWallEvidence("N5014", true),
  ],
} as const;

const slabGroupMetadata = {
  top_x: { position: "TOP", direction: "X", sourceCell: "B2" },
  top_y: { position: "TOP", direction: "Y", sourceCell: "C2" },
  middle_x: { position: "MIDDLE", direction: "X", sourceCell: "D2" },
  middle_y: { position: "MIDDLE", direction: "Y", sourceCell: "E2" },
  bottom_x: { position: "BOTTOM", direction: "X", sourceCell: "F2" },
  bottom_y: { position: "BOTTOM", direction: "Y", sourceCell: "G2" },
  z: { position: null, direction: "Z", sourceCell: "H2" },
} as const;

function slabEvidence(
  key: keyof typeof slabGroupMetadata,
  elevation = "11.45",
): CalculationBookSlabEvidence {
  const metadata = slabGroupMetadata[key];
  return {
    elevation,
    key,
    position: metadata.position,
    direction: metadata.direction,
    imageFilename: `${elevation}-${key.toUpperCase().replace("_", "-")}.png`,
    smn: 0,
    smx: key === "z" ? 0 : 4888,
    legendValues: key === "z" ? [] : [0, 543, 1086, 1629, 2172, 2715, 3259, 3802, 4345, 4888],
    isZeroResult: key === "z",
    sourceRow: 2,
    sourceCell: metadata.sourceCell,
    originalText: key === "z" ? "1C14间距400*400" : "1D36@200",
    canonicalSpecification: key === "z" ? "1C14间距400*400" : "1D36间距200",
    narrativeSpecification: key === "z" ? "1排14@400x400" : "1排36@200",
    actualArea: key === "z" ? 961.6 : 5089.4,
  };
}

function Harness({ adapter }: { adapter: ApiAdapter }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>计算书</button>
      <CalculationBookWorkspace
        adapter={adapter}
        isOpen={open}
        schema={schema}
        onBatchCreated={() => undefined}
        onClose={() => setOpen(false)}
      />
    </>
  );
}

describe("CalculationBookWorkspace", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("downloads the standard reinforcement template without submitting or advancing the task", async () => {
    const user = userEvent.setup();
    const downloadArtifact = vi.fn().mockResolvedValue(undefined);
    const preflightCalculationBook = vi.fn();
    const onBatchCreated = vi.fn();
    const onClose = vi.fn();
    render(
      <CalculationBookWorkspace
        adapter={{ downloadArtifact, preflightCalculationBook } as unknown as ApiAdapter}
        isOpen
        schema={schema}
        onBatchCreated={onBatchCreated}
        onClose={onClose}
      />,
    );

    const downloadButton = screen.getByRole("button", { name: "下载标准配筋模板" });
    expect(downloadButton).not.toHaveAttribute("aria-describedby");
    await user.click(downloadButton);

    await waitFor(() => {
      expect(downloadArtifact).toHaveBeenCalledWith(
        "/api/jobs/calculation-books/reinforcement-template",
        "标准配筋模板.xlsx",
      );
    });
    expect(preflightCalculationBook).not.toHaveBeenCalled();
    expect(onBatchCreated).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText("01 文件与参数")).toHaveAttribute("aria-current", "step");
  });

  it("prevents duplicate template downloads while pending and announces success", async () => {
    const user = userEvent.setup();
    let resolveDownload!: () => void;
    const downloadArtifact = vi.fn(
      () => new Promise<void>((resolve) => {
        resolveDownload = resolve;
      }),
    );
    const preflightCalculationBook = vi.fn();
    const createCalculationBook = vi.fn();
    const onBatchCreated = vi.fn();
    render(
      <CalculationBookWorkspace
        adapter={{
          createCalculationBook,
          downloadArtifact,
          preflightCalculationBook,
        } as unknown as ApiAdapter}
        isOpen
        schema={schema}
        onBatchCreated={onBatchCreated}
        onClose={() => undefined}
      />,
    );

    const downloadButton = screen.getByRole("button", { name: "下载标准配筋模板" });
    await user.click(downloadButton);

    await waitFor(() => expect(downloadButton).toBeDisabled());
    expect(downloadButton).toHaveAttribute("aria-busy", "true");
    const loadingStatus = screen.getByRole("status");
    expect(loadingStatus).toHaveTextContent("正在下载…");
    expect(loadingStatus).toHaveAttribute(
      "id",
      "calculation-book-template-download-feedback",
    );
    expect(downloadButton).toHaveAttribute("aria-describedby", loadingStatus.id);
    expect(screen.getByRole("button", { name: "关闭创建计算书" })).toBeEnabled();
    expect(screen.getByLabelText("计算书模板")).toBeEnabled();
    expect(screen.getByText("01 文件与参数")).toHaveAttribute("aria-current", "step");
    expect(preflightCalculationBook).not.toHaveBeenCalled();
    expect(createCalculationBook).not.toHaveBeenCalled();
    expect(onBatchCreated).not.toHaveBeenCalled();
    await user.click(downloadButton);
    expect(downloadArtifact).toHaveBeenCalledTimes(1);

    resolveDownload();
    const successStatus = await screen.findByRole("status");
    expect(successStatus).toHaveTextContent("已开始下载");
    expect(downloadButton).toHaveAttribute("aria-describedby", successStatus.id);
    expect(downloadButton).toBeEnabled();
  });

  it("announces template download failures and allows retrying", async () => {
    const user = userEvent.setup();
    const downloadArtifact = vi.fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(undefined);
    render(
      <CalculationBookWorkspace
        adapter={{ downloadArtifact } as unknown as ApiAdapter}
        isOpen
        schema={schema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );

    const downloadButton = screen.getByRole("button", { name: "下载标准配筋模板" });
    await user.click(downloadButton);
    const failureAlert = await screen.findByRole("alert");
    expect(failureAlert).toHaveTextContent("下载失败，请重试");
    expect(failureAlert).toHaveAttribute(
      "id",
      "calculation-book-template-download-feedback",
    );
    expect(downloadButton).toHaveAttribute("aria-describedby", failureAlert.id);
    expect(downloadButton).toBeEnabled();

    await user.click(downloadButton);
    expect(await screen.findByRole("status")).toHaveTextContent("已开始下载");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(downloadArtifact).toHaveBeenCalledTimes(2);
  });

  it("starts the template download from the keyboard", async () => {
    const user = userEvent.setup();
    const downloadArtifact = vi.fn().mockResolvedValue(undefined);
    render(
      <CalculationBookWorkspace
        adapter={{ downloadArtifact } as unknown as ApiAdapter}
        isOpen
        schema={schema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );

    const downloadButton = screen.getByRole("button", { name: "下载标准配筋模板" });
    downloadButton.focus();
    await user.keyboard("{Enter}");

    await waitFor(() => expect(downloadArtifact).toHaveBeenCalledTimes(1));
  });

  it("clears template download feedback when the workspace is reopened", async () => {
    const user = userEvent.setup();
    const downloadArtifact = vi.fn().mockResolvedValue(undefined);
    render(<Harness adapter={{ downloadArtifact } as unknown as ApiAdapter} />);

    await user.click(screen.getByRole("button", { name: "计算书" }));
    await user.click(screen.getByRole("button", { name: "下载标准配筋模板" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已开始下载");

    await user.click(screen.getByRole("button", { name: "关闭创建计算书" }));
    await user.click(screen.getByRole("button", { name: "计算书" }));

    expect(screen.queryByText("已开始下载")).not.toBeInTheDocument();
  });

  it.each(["resolve", "reject"] as const)(
    "ignores a pending template download %s after the workspace closes",
    async (outcome) => {
      const user = userEvent.setup();
      let settleDownload!: () => void;
      const downloadPromise = new Promise<void>((resolve, reject) => {
        settleDownload = () => {
          if (outcome === "resolve") {
            resolve();
          } else {
            reject(new Error("offline"));
          }
        };
      });
      const downloadArtifact = vi.fn(() => downloadPromise);
      const calculationBookGetter = vi.fn(() => schema.calculationBook);
      const trackedSchema = {
        ...schema,
        get calculationBook() {
          return calculationBookGetter();
        },
      } as FormSchema;
      const adapter = { downloadArtifact } as unknown as ApiAdapter;
      const workspace = (open: boolean) => (
        <CalculationBookWorkspace
          adapter={adapter}
          isOpen={open}
          schema={trackedSchema}
          onBatchCreated={() => undefined}
          onClose={() => undefined}
        />
      );
      const { rerender } = render(workspace(true));

      await user.click(screen.getByRole("button", { name: "下载标准配筋模板" }));
      await waitFor(() => {
        expect(screen.getByRole("button", { name: "下载标准配筋模板" })).toBeDisabled();
      });
      rerender(workspace(false));
      calculationBookGetter.mockClear();

      await act(async () => {
        settleDownload();
        await downloadPromise.catch(() => undefined);
        await Promise.resolve();
      });

      expect(calculationBookGetter).not.toHaveBeenCalled();
      rerender(workspace(true));
      expect(screen.queryByText("已开始下载")).not.toBeInTheDocument();
      expect(screen.queryByText("下载失败，请重试")).not.toBeInTheDocument();
    },
  );

  it("creates, updates, renames, and deletes a calculation book preset with live feedback", async () => {
    const user = userEvent.setup();
    render(
      <CalculationBookWorkspace
        adapter={{} as ApiAdapter}
        isOpen
        schema={presetSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );

    expect(screen.getByLabelText("计算书方案名称")).toBeInTheDocument();
    expect(screen.getByLabelText("已保存计算书方案")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "保存为新方案" }));
    expect(screen.getByRole("alert")).toHaveTextContent("请先填写计算书方案名称");
    await user.click(screen.getByRole("button", { name: "应用方案" }));
    expect(screen.getByRole("alert")).toHaveTextContent("请先选择一个已保存计算书方案");

    await user.type(screen.getByLabelText("内部编号"), "preset-v1");
    await user.type(screen.getByLabelText("计算书方案名称"), "常用参数");
    await user.click(screen.getByRole("button", { name: "保存为新方案" }));
    expect(screen.getByRole("status")).toHaveTextContent("已保存计算书方案");
    expect(screen.getByRole("option", { name: "常用参数" })).toBeInTheDocument();

    await user.clear(screen.getByLabelText("内部编号"));
    await user.type(screen.getByLabelText("内部编号"), "preset-v2");
    await user.click(screen.getByRole("button", { name: "更新当前方案" }));
    expect(screen.getByRole("status")).toHaveTextContent("已更新计算书方案");

    await user.clear(screen.getByLabelText("计算书方案名称"));
    await user.type(screen.getByLabelText("计算书方案名称"), "结构专业常用参数");
    await user.click(screen.getByRole("button", { name: "重命名" }));
    expect(screen.getByRole("status")).toHaveTextContent("已重命名计算书方案");
    expect(screen.getByRole("option", { name: "结构专业常用参数" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "删除" }));
    expect(screen.getByRole("status")).toHaveTextContent("已删除计算书方案");
    expect(screen.queryByRole("option", { name: "结构专业常用参数" })).not.toBeInTheDocument();
  });

  it("applies parameters without replacing the archive and invalidates prior preflight state", async () => {
    const user = userEvent.setup();
    const preflightCalculationBook = vi.fn().mockResolvedValue(preflightResult);
    render(
      <CalculationBookWorkspace
        adapter={{ preflightCalculationBook } as unknown as ApiAdapter}
        isOpen
        schema={presetSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );

    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    await user.selectOptions(screen.getByLabelText("项目代号"), "2016");
    await user.type(screen.getByLabelText("内部编号"), "saved-code");
    await user.click(screen.getByRole("checkbox", { name: "包含楼板应力" }));
    await user.click(screen.getByRole("checkbox", { name: "无实配钢筋" }));
    await user.type(screen.getByLabelText("计算书方案名称"), "含楼板方案");
    await user.click(screen.getByRole("button", { name: "保存为新方案" }));

    await user.selectOptions(screen.getByLabelText("项目代号"), "2026");
    await user.clear(screen.getByLabelText("内部编号"));
    await user.type(screen.getByLabelText("内部编号"), "current-code");
    await user.click(screen.getByRole("checkbox", { name: "包含楼板应力" }));
    await user.click(screen.getByRole("checkbox", { name: "无实配钢筋" }));
    const archive = new File(["zip"], "business-package.zip", { type: "application/zip" });
    await user.upload(screen.getByLabelText("选择计算图片压缩包"), archive);
    await user.click(screen.getByRole("button", { name: "预检并核对" }));
    expect(await screen.findByLabelText("共 1 面墙")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "返回修改" }));

    await user.clear(screen.getByLabelText("内部编号"));
    await user.click(screen.getByRole("button", { name: "继续核对" }));
    expect(screen.getByText("请填写内部编号")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "应用方案" }));

    expect(screen.getByRole("status")).toHaveTextContent("已应用计算书方案");
    expect(screen.getByText("business-package.zip")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "包含楼板应力" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "无实配钢筋" })).toBeChecked();
    expect(screen.getByLabelText("项目代号")).toHaveValue("2016");
    expect(screen.getByLabelText("项目名称")).toHaveValue("浙江金七门核电厂1、2号机组");
    expect(screen.getByLabelText("内部编号")).toHaveValue("saved-code");
    expect(screen.queryByText("请填写内部编号")).not.toBeInTheDocument();
    expect(screen.getByText("先预检，再创建任务")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "预检并核对" }));
    await waitFor(() => expect(preflightCalculationBook).toHaveBeenCalledTimes(2));
    expect(preflightCalculationBook).toHaveBeenLastCalledWith(archive, {
      includeSlabStress: true,
      reinforcementSource: "ai_suggested",
    });
  });

  it("announces browser storage failures instead of losing preset actions silently", async () => {
    const user = userEvent.setup();
    render(
      <CalculationBookWorkspace
        adapter={{} as ApiAdapter}
        isOpen
        schema={presetSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );
    await user.type(screen.getByLabelText("计算书方案名称"), "无法保存的方案");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota exceeded", "QuotaExceededError");
    });

    await user.click(screen.getByRole("button", { name: "保存为新方案" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "保存计算书预设失败，请检查浏览器本地存储后重试",
    );
  });

  it("locks every preset control while preflight is pending", async () => {
    const user = userEvent.setup();
    let resolvePreflight: ((result: typeof preflightResult) => void) | undefined;
    const preflightCalculationBook = vi.fn(
      () => new Promise<typeof preflightResult>((resolve) => {
        resolvePreflight = resolve;
      }),
    );
    render(
      <CalculationBookWorkspace
        adapter={{ preflightCalculationBook } as unknown as ApiAdapter}
        isOpen
        schema={presetSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );
    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    await user.selectOptions(screen.getByLabelText("项目代号"), "2016");
    await user.type(screen.getByLabelText("内部编号"), "saved-code");
    await user.type(screen.getByLabelText("计算书方案名称"), "预检锁定方案");
    await user.click(screen.getByRole("button", { name: "保存为新方案" }));
    await user.clear(screen.getByLabelText("内部编号"));
    await user.type(screen.getByLabelText("内部编号"), "current-code");
    await user.upload(
      screen.getByLabelText("选择计算图片压缩包"),
      new File(["zip"], "pending.zip", { type: "application/zip" }),
    );

    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    expect(screen.getByLabelText("计算书方案名称")).toBeDisabled();
    expect(screen.getByLabelText("已保存计算书方案")).toBeDisabled();
    for (const name of ["保存为新方案", "应用方案", "更新当前方案", "重命名", "删除"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    await user.click(screen.getByRole("button", { name: "应用方案" }));
    expect(screen.getByLabelText("内部编号")).toHaveValue("current-code");

    resolvePreflight?.(preflightResult);
    await waitFor(() => expect(screen.getByLabelText("共 1 面墙")).toBeInTheDocument());
  });

  it("orders the compact task rail and keeps archive guidance collapsed until requested", async () => {
    const user = userEvent.setup();
    const adapter = {
      preflightCalculationBook: vi.fn(),
      createCalculationBook: vi.fn(),
    } as unknown as ApiAdapter;
    render(<Harness adapter={adapter} />);
    const trigger = screen.getByRole("button", { name: "计算书" });
    await user.click(trigger);
    await waitFor(() =>
      expect(screen.getByLabelText("计算书模板")).toHaveFocus(),
    );

    const uploadInput = screen.getByLabelText("选择计算图片压缩包");
    const uploadBox = uploadInput.closest("label");
    expect(uploadBox).not.toBeNull();
    expect(within(uploadBox as HTMLElement).getByText("上传压缩包")).toBeInTheDocument();
    expect(uploadInput).toHaveAttribute("accept", ".zip,.rar,.7z");
    expect(within(uploadBox as HTMLElement).getByText("单个 .zip、.rar 或 .7z 文件")).toBeInTheDocument();
    expect(screen.getByLabelText("内部编号")).toHaveAttribute(
      "placeholder",
      "例如：20161NH-JGS01",
    );
    const slabToggle = screen.getByRole("checkbox", { name: "包含楼板应力" });
    const slabBox = slabToggle.closest("label");
    const presetPanel = screen.getByRole("heading", { name: "参数预设" }).closest("section");
    const archiveHelp = screen.getByText("压缩包结构要求").closest("details");
    expect(slabBox).not.toBeNull();
    expect(presetPanel).not.toBeNull();
    expect(archiveHelp).not.toBeNull();
    expect((uploadBox as Node).compareDocumentPosition(slabBox as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect((slabBox as Node).compareDocumentPosition(presetPanel as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect((presetPanel as Node).compareDocumentPosition(archiveHelp as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(archiveHelp).not.toHaveAttribute("open");
    expect(slabToggle).not.toBeChecked();
    expect(slabToggle).toHaveAccessibleDescription(
      /自动识别 5 组.*MIDDLE-X.*自动识别 7 组.*楼板配筋仅从 Excel 读取.*页面不手工输入/,
    );
    await user.click(screen.getByText("压缩包结构要求"));
    expect(archiveHelp).toHaveAttribute("open");
    expect(screen.getByText("计算图片.zip / .rar / .7z")).toBeInTheDocument();
    expect(screen.getByText("单个 ZIP / RAR / 7Z")).toBeInTheDocument();
    expect(screen.getByText("墙体01-X.png")).toBeInTheDocument();
    expect(screen.getByText("墙体01-Y.png")).toBeInTheDocument();
    expect(screen.getByText("墙体01-Z.png")).toBeInTheDocument();
    expect(screen.getByText("01 / 厂房标高布置图")).toBeInTheDocument();
    expect(screen.getByText("02 / 墙体有限元模型图")).toBeInTheDocument();
    await user.upload(
      uploadInput,
      new File(["7z"], "business-package.7z", { type: "application/x-7z-compressed" }),
    );
    expect(within(uploadBox as HTMLElement).getByText("business-package.7z")).toBeInTheDocument();
    expect(screen.queryByLabelText("实配钢筋规格")).not.toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "创建计算书" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("runs the image-only AI flow from one explicit compact mode switch", async () => {
    const user = userEvent.setup();
    const preflightCalculationBook = vi.fn().mockResolvedValue(aiPreflightResult);
    const createCalculationBook = vi.fn().mockResolvedValue({
      batchId: "batch-ai-rebar",
      jobs: [],
    });
    render(
      <CalculationBookWorkspace
        adapter={{
          preflightCalculationBook,
          createCalculationBook,
        } as unknown as ApiAdapter}
        isOpen
        schema={minimalSlabSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );

    const aiMode = screen.getByRole("checkbox", { name: "无实配钢筋" });
    const slabMode = screen.getByRole("checkbox", { name: "包含楼板应力" });
    expect(aiMode).not.toBeChecked();
    expect(screen.queryByRole("combobox", { name: "配筋来源" })).not.toBeInTheDocument();
    expect(aiMode).toHaveAccessibleDescription(/压缩包需包含唯一的 Excel 配筋表/);
    expect((aiMode.closest("label") as Node).compareDocumentPosition(
      slabMode.closest("label") as Node,
    ) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    await user.click(aiMode);
    expect(aiMode).toBeChecked();
    expect(aiMode).toHaveAccessibleDescription(/压缩包不得包含 Excel/);
    expect(slabMode).toHaveAccessibleDescription(/楼板配筋建议同样由云图 SMX 生成/);

    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    const archive = new File(["rar"], "images-only.rar", {
      type: "application/vnd.rar",
    });
    await user.upload(screen.getByLabelText("选择计算图片压缩包"), archive);
    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    expect(preflightCalculationBook).toHaveBeenCalledWith(archive, {
      includeSlabStress: false,
      reinforcementSource: "ai_suggested",
    });
    expect(await screen.findByText("云图核验结果")).toBeInTheDocument();
    expect(screen.getByText("02 云图核验")).toHaveAttribute("aria-current", "step");
    expect(screen.getByLabelText("共 59 个墙体图组")).toBeInTheDocument();
    expect(screen.getByLabelText("共 177 张墙体方向图")).toBeInTheDocument();
    expect(screen.getByLabelText("共 3 张 Z 向零值或无 SMX 图")).toBeInTheDocument();
    expect(screen.getByText("N5012-1 · X")).toBeInTheDocument();
    expect(screen.getByText("-1/-2 图片组需要人工确认")).toBeInTheDocument();
    expect(screen.queryByText("配筋表与图片匹配")).not.toBeInTheDocument();
    expect(screen.queryByText(/Excel 单元格证据/)).not.toBeInTheDocument();
    expect(screen.queryByText(/程序将启动人工智能/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "进入确认提交" }));
    await user.click(screen.getByRole("button", { name: "创建计算书任务" }));
    await waitFor(() => expect(createCalculationBook).toHaveBeenCalledTimes(1));
    expect(createCalculationBook).toHaveBeenCalledWith(expect.objectContaining({
      reinforcement_source: "ai_suggested",
      include_slab_stress: false,
      preflight_token: "calculation-ai-preflight-1",
    }));
    expect(createCalculationBook.mock.calls[0]?.[0]).not.toHaveProperty(
      "confirm_ai_normalization",
    );
  });

  it("compacts AI wall evidence and folds the confirmed wall set", async () => {
    const user = userEvent.setup();
    const aiSlabs = (["top_x", "top_y", "bottom_x", "bottom_y", "z"] as const)
      .map((key) => ({
        ...slabEvidence(key),
        sourceRow: null,
        sourceCell: "",
        actualArea: null,
      }));
    const preflightCalculationBook = vi.fn().mockResolvedValue({
      ...aiPreflightResult,
      slabFigureCount: aiSlabs.length,
      slabElevationCount: 1,
      slabActualGroupCount: aiSlabs.length,
      slabs: aiSlabs,
    });
    render(
      <CalculationBookWorkspace
        adapter={{ preflightCalculationBook } as unknown as ApiAdapter}
        isOpen
        schema={minimalSlabSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );

    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    await user.click(screen.getByRole("checkbox", { name: "无实配钢筋" }));
    await user.click(screen.getByRole("checkbox", { name: "包含楼板应力" }));
    await user.upload(
      screen.getByLabelText("选择计算图片压缩包"),
      new File(["rar"], "images-only.rar", { type: "application/vnd.rar" }),
    );
    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    expect(await screen.findByText("云图核验结果")).toBeInTheDocument();
    expect(screen.getAllByText("等待任务生成 AI 建议")).toHaveLength(1);
    const reviewWallSummary = screen.getByText("N5012").closest("summary");
    expect(reviewWallSummary).not.toBeNull();
    expect(reviewWallSummary).toHaveTextContent("3/3 方向完整");
    await user.click(reviewWallSummary as HTMLElement);
    const reviewWall = reviewWallSummary?.closest("details");
    expect(reviewWall).not.toBeNull();
    expect(within(reviewWall as HTMLElement).getByText("X · 水平筋")).toBeInTheDocument();
    expect(within(reviewWall as HTMLElement).getByText("Y · 竖向筋")).toBeInTheDocument();
    expect(within(reviewWall as HTMLElement).getByText("Z · 拉筋")).toBeInTheDocument();
    expect(screen.getByText("N5014").closest("summary")).toHaveTextContent("需复核");

    await user.click(screen.getByRole("button", { name: "进入确认提交" }));

    expect(screen.getByText("03 · 确认提交")).toBeInTheDocument();
    const confirmedSummary = screen.getByText("已核验逐墙证据（59 组）").closest("summary");
    const confirmedEvidence = confirmedSummary?.closest("details");
    expect(confirmedEvidence).not.toBeNull();
    expect(confirmedEvidence).not.toHaveAttribute("open");
    const manualReviewHeading = screen.getByRole("heading", { name: "需人工复核" });
    expect(confirmedEvidence).not.toContainElement(manualReviewHeading);

    await user.click(confirmedSummary as HTMLElement);
    const confirmedWallSummary = within(confirmedEvidence as HTMLElement)
      .getByText("N5013")
      .closest("summary");
    expect(confirmedWallSummary).not.toBeNull();
    await user.click(confirmedWallSummary as HTMLElement);
    const confirmedWall = confirmedWallSummary?.closest("details");
    expect(within(confirmedWall as HTMLElement).getByText("X · 水平筋")).toBeInTheDocument();
    expect(within(confirmedWall as HTMLElement).getByText("Y · 竖向筋")).toBeInTheDocument();
    expect(within(confirmedWall as HTMLElement).getByText("Z · 拉筋")).toBeInTheDocument();
  });

  it("keeps provided reinforcement source rows in each wall summary", async () => {
    const user = userEvent.setup();
    const preflightCalculationBook = vi.fn().mockResolvedValue(preflightResult);
    render(
      <CalculationBookWorkspace
        adapter={{ preflightCalculationBook } as unknown as ApiAdapter}
        isOpen
        schema={minimalSlabSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );

    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    await user.upload(
      screen.getByLabelText("选择计算图片压缩包"),
      new File(["zip"], "with-reinforcement.zip", { type: "application/zip" }),
    );
    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    const wallSummary = (await screen.findByText("N5012")).closest("summary");
    expect(wallSummary).not.toBeNull();
    expect(wallSummary).toHaveTextContent("配筋表第 2 行");
    expect(screen.queryByText("已核验逐墙证据（1 组）")).not.toBeInTheDocument();
  });

  it("invalidates an existing preflight whenever either mode switch changes", async () => {
    const user = userEvent.setup();
    const preflightCalculationBook = vi.fn().mockResolvedValue(aiPreflightResult);
    render(
      <CalculationBookWorkspace
        adapter={{ preflightCalculationBook } as unknown as ApiAdapter}
        isOpen
        schema={minimalSlabSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );
    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    await user.click(screen.getByRole("checkbox", { name: "无实配钢筋" }));
    await user.upload(
      screen.getByLabelText("选择计算图片压缩包"),
      new File(["rar"], "images-only.rar"),
    );
    await user.click(screen.getByRole("button", { name: "预检并核对" }));
    expect(await screen.findByText("云图核验结果")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "返回修改" }));
    expect(screen.getByRole("button", { name: "继续核对" })).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "包含楼板应力" }));
    expect(screen.getByRole("button", { name: "预检并核对" })).toBeInTheDocument();
  });

  it("submits normalized parameters and one ZIP without duplicate submission", async () => {
    const user = userEvent.setup();
    const preflightCalculationBook = vi.fn().mockResolvedValue(preflightResult);
    const createCalculationBook = vi.fn().mockResolvedValue({
      batchId: "batch-calc",
      jobs: [],
    });
    const onBatchCreated = vi.fn();
    const adapter = {
      preflightCalculationBook,
      createCalculationBook,
    } as unknown as ApiAdapter;
    const { rerender } = render(
      <CalculationBookWorkspace
        adapter={adapter}
        isOpen
        schema={schema}
        onBatchCreated={onBatchCreated}
        onClose={() => undefined}
      />,
    );

    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    await user.selectOptions(screen.getByLabelText("项目代号"), "2016");
    await user.type(screen.getByLabelText("内部编号"), "20160RX-JGS01-001");
    await user.selectOptions(screen.getByLabelText("子项代号或系统号"), "RX");
    await user.selectOptions(screen.getByLabelText("子项或系统名称"), "内部结构");
    await user.selectOptions(screen.getByLabelText("设计阶段"), "施工图设计");
    await user.type(screen.getByLabelText("文件名称"), "0.000m~15.000m配筋计算书");
    for (const [label, value] of [
      ["厂房外轮廓长度", "72.5"],
      ["厂房外轮廓宽度", "48"],
      ["筏板顶标高", "-8.5"],
      ["屋面顶标高", "31.2"],
      ["历史最低温度", "-18"],
      ["历史最高温度", "39"],
      ["场地土温", "15"],
    ]) {
      await user.type(screen.getByLabelText(label), value);
    }
    const archive = new File(["zip"], "calculation.zip", { type: "application/zip" });
    await user.upload(screen.getByLabelText("选择计算图片压缩包"), archive);
    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    expect(await screen.findByLabelText("共 1 面墙")).toBeInTheDocument();
    expect(screen.getByText("1C14间距400*400")).toBeInTheDocument();
    expect(screen.getByText("Z 向无 SMX，计算值按 0 处理")).toBeInTheDocument();
    rerender(
      <CalculationBookWorkspace
        adapter={adapter}
        isOpen
        schema={{
          ...schema,
          calculationBook: { ...schema.calculationBook! },
        }}
        onBatchCreated={onBatchCreated}
        onClose={() => undefined}
      />,
    );
    await user.click(screen.getByRole("button", { name: "进入确认提交" }));
    await user.click(screen.getByRole("button", { name: "创建计算书任务" }));

    expect(preflightCalculationBook).toHaveBeenCalledWith(archive, {
      includeSlabStress: false,
      reinforcementSource: "provided",
    });
    await waitFor(() => expect(createCalculationBook).toHaveBeenCalledTimes(1));
    expect(createCalculationBook).toHaveBeenCalledWith(
      expect.objectContaining({
        template_type: "internal_structure",
        project_no: "2016",
        project_name: "浙江金七门核电厂1、2号机组",
        workshop_length: 72.5,
        include_slab_stress: false,
        preflight_token: "calculation-preflight-1",
      }),
    );
    expect(createCalculationBook.mock.calls[0]?.[0]).not.toHaveProperty(
      "manual_confirmations",
    );
    expect(createCalculationBook.mock.calls[0]?.[0]).not.toHaveProperty(
      "confirm_ai_normalization",
    );
    expect(onBatchCreated).toHaveBeenCalledWith({ batchId: "batch-calc", jobs: [] });
  });

  it("announces validation errors and focuses the first required field", async () => {
    const user = userEvent.setup();
    const adapter = {
      preflightCalculationBook: vi.fn(),
      createCalculationBook: vi.fn(),
    } as unknown as ApiAdapter;
    render(
      <CalculationBookWorkspace
        adapter={adapter}
        isOpen
        schema={schema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );
    await user.upload(
      screen.getByLabelText("选择计算图片压缩包"),
      new File(["zip"], "calculation.zip", { type: "application/zip" }),
    );

    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    expect(screen.getByRole("alert")).toHaveTextContent("请修正 15 个参数");
    await waitFor(() =>
      expect(screen.getByLabelText("计算书模板")).toHaveFocus(),
    );
    expect(screen.getByLabelText("计算书模板")).toHaveAttribute("aria-required", "true");
    expect(adapter.preflightCalculationBook).not.toHaveBeenCalled();
  });

  it("locks close, cancel, and Escape while preflight is pending", async () => {
    const user = userEvent.setup();
    let resolveRequest: ((value: typeof preflightResult) => void) | undefined;
    const preflightCalculationBook = vi.fn(
      () =>
        new Promise<typeof preflightResult>((resolve) => {
          resolveRequest = resolve;
        }),
    );
    const onClose = vi.fn();
    const onBatchCreated = vi.fn();
    const minimalSchema: FormSchema = {
      ...schema,
      calculationBook: {
        ...schema.calculationBook!,
        fields: [calculationFields[0]],
      },
    };
    render(
      <CalculationBookWorkspace
        adapter={{
          preflightCalculationBook,
          createCalculationBook: vi.fn(),
        } as unknown as ApiAdapter}
        isOpen
        schema={minimalSchema}
        onBatchCreated={onBatchCreated}
        onClose={onClose}
      />,
    );
    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    await user.upload(
      screen.getByLabelText("选择计算图片压缩包"),
      new File(["zip"], "calculation.zip", { type: "application/zip" }),
    );
    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    expect(screen.getByRole("button", { name: "关闭创建计算书" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "取消" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();

    resolveRequest?.(preflightResult);
    await waitFor(() => expect(screen.getByLabelText("共 1 面墙")).toBeInTheDocument());
    expect(onBatchCreated).not.toHaveBeenCalled();
  });

  it("does not ask for create-time confirmation for duplicate rows or split image groups", async () => {
    const user = userEvent.setup();
    const manualPreflight = {
      ...preflightResult,
      warnings: [
        { code: "duplicate_reinforcement_rows", filenames: [] },
        { code: "split_image_group", filenames: [] },
      ],
      requiresManualConfirmation: true,
      confirmations: [
        {
          wallId: "S7157-1",
          baseWallId: "S7157",
          reasons: ["duplicate_reinforcement_rows", "split_image_group"],
          suggestedSourceRow: 29,
          candidates: [
            {
              sourceRow: 28,
              sourceSheet: "Sheet1",
              directions: {
                ...preflightResult.walls[0].directions,
                Y: {
                  ...preflightResult.walls[0].directions.Y,
                  sourceCell: "C28",
                  originalText: "1D25间距200",
                  canonicalSpecification: "1D25间距200",
                  narrativeSpecification: "1排25@200",
                  actualArea: 2454.4,
                },
              },
            },
            {
              sourceRow: 29,
              sourceSheet: "Sheet1",
              directions: preflightResult.walls[0].directions,
            },
          ],
        },
      ],
      walls: [
        {
          ...preflightResult.walls[0],
          wallId: "S7157-1",
          baseWallId: "S7157",
          groupIndex: 1,
          suggestedSourceRow: null,
          directions: {
            X: {
              ...preflightResult.walls[0].directions.X,
              sourceCell: "",
              actualArea: null,
            },
            Y: {
              ...preflightResult.walls[0].directions.Y,
              sourceCell: "",
              actualArea: null,
            },
            Z: {
              ...preflightResult.walls[0].directions.Z,
              sourceCell: "",
              actualArea: null,
            },
          },
        },
      ],
    };
    const createCalculationBook = vi.fn().mockResolvedValue({
      batchId: "batch-calc",
      jobs: [],
    });
    const adapter = {
      preflightCalculationBook: vi.fn().mockResolvedValue(manualPreflight),
      createCalculationBook,
    } as unknown as ApiAdapter;
    const minimalSchema: FormSchema = {
      ...schema,
      calculationBook: {
        ...schema.calculationBook!,
        fields: [calculationFields[0]],
      },
    };
    render(
      <CalculationBookWorkspace
        adapter={adapter}
        isOpen
        schema={minimalSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );
    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    await user.upload(
      screen.getByLabelText("选择计算图片压缩包"),
      new File(["zip"], "calculation.zip", { type: "application/zip" }),
    );
    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    expect(await screen.findByRole("button", { name: "进入确认提交" })).toBeInTheDocument();
    expect(
      screen.queryAllByText("以下根目录图片未按墙号-X/Y/Z规则进入计算"),
    ).toHaveLength(0);
    const wallEvidence = screen.getByText("S7157-1").closest("details");
    expect(wallEvidence).not.toBeNull();
    expect(within(wallEvidence as HTMLElement).getByText("无对应配筋行")).toBeInTheDocument();
    const xHeading = within(wallEvidence as HTMLElement).getByText("X · 水平筋");
    expect(xHeading.closest("header")?.querySelector("span")).toBeNull();
    for (const label of within(wallEvidence as HTMLElement).getAllByText("实配面积")) {
      expect(label.closest("div")?.querySelector("dd")).toHaveTextContent("待补充");
    }
    expect(wallEvidence).not.toHaveTextContent("配筋表第  行");
    expect(wallEvidence).not.toHaveTextContent("待补充 mm²/m");
    await user.click(screen.getByRole("button", { name: "进入确认提交" }));
    expect(screen.queryByText("S7157-1 需要人工确认")).not.toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建计算书任务" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "创建计算书任务" }));

    await waitFor(() => expect(createCalculationBook).toHaveBeenCalledTimes(1));
    expect(createCalculationBook.mock.calls[0]?.[0]).not.toHaveProperty(
      "manual_confirmations",
    );
  });

  it("starts an AI task only after the nonstandard workbook confirmation", async () => {
    const user = userEvent.setup();
    const preflightCalculationBook = vi.fn().mockResolvedValue({
      ...preflightResult,
      preflightToken: "ai-preflight-token",
      figureCount: 174,
      wallCount: 0,
      reinforcementSourceRowCount: 0,
      reinforcementNormalizedRowCount: 0,
      reinforcementIssueRowCount: 1,
      reinforcementUniqueWallCount: 0,
      normalizationTriggered: false,
      normalizationSkillId: null,
      imageWallGroupCount: 58,
      imageUniqueWallCount: 58,
      matchedUniqueWallCount: 0,
      slabFigureCount: 35,
      slabElevationCount: 5,
      slabs: [],
      walls: [],
      confirmations: [],
      normalizationIssues: [
        {
          sourceSheet: "墙体配筋结果",
          sourceRow: 8,
          sourceCells: { wall: "A8", X: "B8", Y: "C8", Z: "D8" },
          originalValues: { wall: "N5008", X: "", Y: "双层@二百", Z: "" },
          originalWallText: "N5008",
          wallId: "N5008",
          error: "竖向配筋格式无法确定",
        },
      ],
      requiresAiNormalization: true,
      aiReinforcementExpectedSourceRowCount: 315,
      aiConfirmationMessage: "您上传的墙体配筋表非标准格式，程序将启动人工智能。",
      formatInspection: {
        wallSheet: "墙体配筋结果",
        slabSheet: "楼板配筋",
        reasons: [
          {
            scope: "wall",
            code: "wall_layout_nonstandard",
            sheet: "墙体配筋结果",
            message: "不是标准四列墙体配筋模板",
          },
        ],
      },
    });
    const createCalculationBook = vi.fn().mockResolvedValue({
      batchId: "batch-ai",
      jobs: [],
    });
    render(
      <CalculationBookWorkspace
        adapter={{
          preflightCalculationBook,
          createCalculationBook,
        } as unknown as ApiAdapter}
        isOpen
        schema={minimalSlabSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );

    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    await user.click(screen.getByRole("checkbox", { name: "包含楼板应力" }));
    const archive = new File(["rar"], "nonstandard-calculation.rar", {
      type: "application/vnd.rar",
    });
    await user.upload(screen.getByLabelText("选择计算图片压缩包"), archive);
    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    expect(
      await screen.findByText("您上传的墙体配筋表非标准格式，程序将启动人工智能。"),
    ).toBeInTheDocument();
    expect(screen.getByText("03 确认提交")).toHaveAttribute("aria-current", "step");
    expect(screen.getByText("03 · AI 规范化确认")).toBeInTheDocument();
    expect(screen.getByText("预计需规范化 315 行源数据")).toBeInTheDocument();
    expect(screen.queryByLabelText("共 0 面墙")).not.toBeInTheDocument();
    expect(screen.queryByText("0规范化行")).not.toBeInTheDocument();
    expect(screen.queryByText("待修正行")).not.toBeInTheDocument();
    expect(screen.queryByText("竖向配筋格式无法确定")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("实配钢筋规格")).not.toBeInTheDocument();
    expect(createCalculationBook).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "返回修改" }));
    expect(screen.getByLabelText("选择计算图片压缩包")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "继续 AI 确认" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "继续 AI 确认" }));
    expect(
      await screen.findByText("您上传的墙体配筋表非标准格式，程序将启动人工智能。"),
    ).toBeInTheDocument();
    expect(createCalculationBook).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "确认并开始任务" }));

    await waitFor(() => expect(createCalculationBook).toHaveBeenCalledTimes(1));
    expect(createCalculationBook).toHaveBeenCalledWith(
      expect.objectContaining({
        preflight_token: "ai-preflight-token",
        include_slab_stress: true,
        confirm_ai_normalization: true,
      }),
    );
    expect(createCalculationBook.mock.calls[0]?.[0]).not.toHaveProperty(
      "confirm_wall_count_mismatch",
    );
    expect(createCalculationBook.mock.calls[0]?.[0]).not.toHaveProperty(
      "manual_confirmations",
    );
  });

  it("accepts RAR and keeps wall-count mismatches nonblocking", async () => {
    const user = userEvent.setup();
    const mismatchPreflight = {
      ...preflightResult,
      figureCount: 174,
      wallCount: 54,
      reinforcementSourceRowCount: 315,
      reinforcementNormalizedRowCount: 315,
      reinforcementIssueRowCount: 0,
      reinforcementUniqueWallCount: 314,
      imageWallGroupCount: 59,
      imageUniqueWallCount: 58,
      matchedUniqueWallCount: 54,
      imageOnlyWallIds: ["N5003A", "N5003B", "N5022", "NDTJ1"],
      workbookOnlyWallIds: ["N0001", "N0002"],
      requiresWallCountConfirmation: true,
      requiresManualConfirmation: true,
    };
    const preflightCalculationBook = vi.fn().mockResolvedValue(mismatchPreflight);
    const createCalculationBook = vi.fn().mockResolvedValue({
      batchId: "batch-calc",
      jobs: [],
    });
    const minimalSchema: FormSchema = {
      ...schema,
      calculationBook: {
        ...schema.calculationBook!,
        fields: [calculationFields[0]],
      },
    };
    render(
      <CalculationBookWorkspace
        adapter={{
          preflightCalculationBook,
          createCalculationBook,
        } as unknown as ApiAdapter}
        isOpen
        schema={minimalSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );
    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    const archive = new File(["rar"], "calculation.rar", {
      type: "application/vnd.rar",
    });
    await user.upload(screen.getByLabelText("选择计算图片压缩包"), archive);
    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    expect(await screen.findByText("配筋表与图片匹配")).toBeInTheDocument();
    expect(screen.getByLabelText("配筋源行 315")).toBeInTheDocument();
    expect(screen.getByLabelText("规范化行 315")).toBeInTheDocument();
    expect(screen.getByLabelText("配筋表唯一墙号 314")).toBeInTheDocument();
    expect(screen.getByLabelText("图片墙组 59")).toBeInTheDocument();
    expect(screen.getByLabelText("已匹配墙号 54")).toBeInTheDocument();
    expect(screen.queryByLabelText("实配钢筋规格")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "进入确认提交" }));
    expect(
      screen.queryByRole("region", { name: "墙体数量存在差异，需要确认" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建计算书任务" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "创建计算书任务" }));

    await waitFor(() => expect(createCalculationBook).toHaveBeenCalledTimes(1));
    expect(createCalculationBook.mock.calls[0]?.[0]).not.toHaveProperty(
      "confirm_wall_count_mismatch",
    );
  });

  it("preflights and displays optional slab evidence without asking for rebar inputs", async () => {
    const user = userEvent.setup();
    const slabPreflight = {
      ...preflightResult,
      slabFigureCount: 5,
      slabElevationCount: 1,
      slabs: [
        slabEvidence("z"),
        slabEvidence("bottom_y"),
        slabEvidence("top_y"),
        slabEvidence("bottom_x"),
        slabEvidence("top_x"),
      ].map((evidence) => ({
        ...evidence,
        sourceRow: null,
        sourceCell: "",
        actualArea: null,
      })),
    };
    const preflightCalculationBook = vi.fn().mockResolvedValue(slabPreflight);
    const createCalculationBook = vi.fn().mockResolvedValue({
      batchId: "batch-calc",
      jobs: [],
    });
    render(
      <CalculationBookWorkspace
        adapter={{
          preflightCalculationBook,
          createCalculationBook,
        } as unknown as ApiAdapter}
        isOpen
        schema={minimalSlabSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );
    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    await user.click(screen.getByRole("checkbox", { name: "包含楼板应力" }));
    const archive = new File(["zip"], "calculation.zip", { type: "application/zip" });
    await user.upload(screen.getByLabelText("选择计算图片压缩包"), archive);
    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    expect(await screen.findByLabelText("共 5 张楼板云图")).toBeInTheDocument();
    expect(screen.getByText("11.45m 楼板")).toBeInTheDocument();
    expect(screen.getByText("5/5 完整")).toBeInTheDocument();
    expect(screen.getByText("11.45m 楼板").closest("summary")).toHaveTextContent("无对应配筋行");
    const orderedGroups = screen.getAllByRole("heading", { level: 4 }).map((node) => node.textContent);
    expect(orderedGroups).toEqual([
      "TOP-X · 上表面 X 向",
      "TOP-Y · 上表面 Y 向",
      "BOTTOM-X · 下表面 X 向",
      "BOTTOM-Y · 下表面 Y 向",
      "Z · Z 向",
    ]);
    expect(screen.getAllByText("1D36间距200")).toHaveLength(4);
    const topSlabCard = screen
      .getByRole("heading", { level: 4, name: "TOP-X · 上表面 X 向" })
      .closest("article");
    expect(topSlabCard).not.toBeNull();
    expect(topSlabCard?.querySelector("header span")).toBeNull();
    const actualAreaLabel = within(topSlabCard as HTMLElement).getByText("实配面积");
    expect(actualAreaLabel.closest("div")?.querySelector("dd")).toHaveTextContent("待补充");
    expect(topSlabCard).not.toHaveTextContent("待补充 mm²/m");
    expect(screen.queryByLabelText("实配钢筋规格")).not.toBeInTheDocument();
    expect(preflightCalculationBook).toHaveBeenCalledWith(archive, {
      includeSlabStress: true,
      reinforcementSource: "provided",
    });

    await user.click(screen.getByRole("button", { name: "进入确认提交" }));
    await user.click(screen.getByRole("button", { name: "创建计算书任务" }));
    await waitFor(() => expect(createCalculationBook).toHaveBeenCalledTimes(1));
    expect(createCalculationBook).toHaveBeenCalledWith(
      expect.objectContaining({ include_slab_stress: true }),
    );
  });

  it("sorts elevations and expands paired MIDDLE groups into a complete seven-group set", async () => {
    const user = userEvent.setup();
    const slabs = [
      ...(["z", "middle_y", "bottom_y", "top_x", "middle_x", "bottom_x", "top_y"] as const)
        .map((key) => slabEvidence(key, "15.95")),
      ...(["z", "bottom_y", "top_y", "bottom_x", "top_x"] as const)
        .map((key) => slabEvidence(key, "11.45")),
    ];
    const preflightCalculationBook = vi.fn().mockResolvedValue({
      ...preflightResult,
      slabFigureCount: slabs.length,
      slabElevationCount: 2,
      slabs,
    });
    render(
      <CalculationBookWorkspace
        adapter={{ preflightCalculationBook } as unknown as ApiAdapter}
        isOpen
        schema={minimalSlabSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );
    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    await user.click(screen.getByRole("checkbox", { name: "包含楼板应力" }));
    await user.upload(
      screen.getByLabelText("选择计算图片压缩包"),
      new File(["zip"], "calculation.zip", { type: "application/zip" }),
    );
    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    const elevationLabels = await screen.findAllByText(/m 楼板$/);
    expect(elevationLabels.map((node) => node.textContent)).toEqual([
      "11.45m 楼板",
      "15.95m 楼板",
    ]);
    expect(screen.getByText("7/7 完整 · 含 MIDDLE")).toBeInTheDocument();
  });

  it("blocks confirmation when slab evidence is missing a required group", async () => {
    const user = userEvent.setup();
    const preflightCalculationBook = vi.fn().mockResolvedValue({
      ...preflightResult,
      slabFigureCount: 4,
      slabElevationCount: 1,
      slabs: [
        slabEvidence("top_x"),
        slabEvidence("top_y"),
        slabEvidence("bottom_x"),
        slabEvidence("z"),
      ],
    });
    render(
      <CalculationBookWorkspace
        adapter={{ preflightCalculationBook } as unknown as ApiAdapter}
        isOpen
        schema={minimalSlabSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );
    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    await user.click(screen.getByRole("checkbox", { name: "包含楼板应力" }));
    await user.upload(
      screen.getByLabelText("选择计算图片压缩包"),
      new File(["zip"], "calculation.zip", { type: "application/zip" }),
    );
    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("缺少 BOTTOM-Y");
    expect(screen.getByRole("button", { name: "进入确认提交" })).toBeDisabled();
  });

  it("does not ask the user to repair a row before the task can leave it blank", async () => {
    const user = userEvent.setup();
    const createCalculationBook = vi.fn().mockResolvedValue({
      batchId: "batch-partial",
      jobs: [],
    });
    const preflightCalculationBook = vi.fn().mockResolvedValue({
      ...preflightResult,
      reinforcementSourceRowCount: 2,
      reinforcementNormalizedRowCount: 1,
      reinforcementIssueRowCount: 1,
      normalizationIssues: [
        {
          sourceSheet: "墙体配筋",
          sourceRow: 3,
          sourceCells: { wall: "A3", X: "B3", Y: "C3", Z: "D3" },
          originalValues: {
            wall: "N5002",
            X: "1D22间距200",
            Y: "直径22双层@二百",
            Z: "1C8间距400*400",
          },
          originalWallText: "N5002",
          wallId: "N5002",
          error: "竖向配筋格式无法确定",
        },
      ],
    });
    render(
      <CalculationBookWorkspace
        adapter={{
          preflightCalculationBook,
          createCalculationBook,
        } as unknown as ApiAdapter}
        isOpen
        schema={minimalSlabSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );
    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    await user.upload(
      screen.getByLabelText("选择计算图片压缩包"),
      new File(["zip"], "calculation.zip", { type: "application/zip" }),
    );
    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    expect(await screen.findByText("配筋表与图片匹配")).toBeInTheDocument();
    expect(screen.queryByText("竖向配筋格式无法确定")).not.toBeInTheDocument();
    expect(screen.queryByText("查看待修正行")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "进入确认提交" }));
    expect(screen.getByRole("button", { name: "创建计算书任务" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "创建计算书任务" }));
    await waitFor(() => expect(createCalculationBook).toHaveBeenCalledTimes(1));
  });

  it("blocks submission when normalization audit counts are not conserved", async () => {
    const user = userEvent.setup();
    const preflightCalculationBook = vi.fn().mockResolvedValue({
      ...preflightResult,
      reinforcementSourceRowCount: 40,
      reinforcementNormalizedRowCount: 38,
      reinforcementIssueRowCount: 0,
      normalizationIssues: [],
    });
    render(
      <CalculationBookWorkspace
        adapter={{ preflightCalculationBook } as unknown as ApiAdapter}
        isOpen
        schema={minimalSlabSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );
    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    await user.upload(
      screen.getByLabelText("选择计算图片压缩包"),
      new File(["zip"], "calculation.zip", { type: "application/zip" }),
    );
    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("规范化审计数据不守恒");
    expect(screen.getByRole("button", { name: "进入确认提交" })).toBeDisabled();
  });

  it("invalidates a prior preflight when the slab option changes", async () => {
    const user = userEvent.setup();
    const preflightCalculationBook = vi.fn().mockResolvedValue(preflightResult);
    const minimalSchema: FormSchema = {
      ...schema,
      calculationBook: {
        ...schema.calculationBook!,
        fields: [
          calculationFields[0],
          calculationFields[calculationFields.length - 1],
        ],
      },
    };
    render(
      <CalculationBookWorkspace
        adapter={{
          preflightCalculationBook,
          createCalculationBook: vi.fn(),
        } as unknown as ApiAdapter}
        isOpen
        schema={minimalSchema}
        onBatchCreated={() => undefined}
        onClose={() => undefined}
      />,
    );
    await user.selectOptions(screen.getByLabelText("计算书模板"), "internal_structure");
    const archive = new File(["zip"], "calculation.zip", { type: "application/zip" });
    await user.upload(screen.getByLabelText("选择计算图片压缩包"), archive);
    await user.click(screen.getByRole("button", { name: "预检并核对" }));
    await screen.findByRole("button", { name: "进入确认提交" });
    await user.click(screen.getByRole("button", { name: "返回修改" }));
    await user.click(screen.getByRole("checkbox", { name: "包含楼板应力" }));

    expect(screen.getByRole("button", { name: "预检并核对" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "预检并核对" }));
    await waitFor(() => expect(preflightCalculationBook).toHaveBeenCalledTimes(2));
    expect(preflightCalculationBook).toHaveBeenLastCalledWith(archive, {
      includeSlabStress: true,
      reinforcementSource: "provided",
    });
  });
});
