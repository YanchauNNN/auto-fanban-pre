import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

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
  { key: "internal_code", label: "内部编号", type: "text", required: true },
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
      accept: [".zip", ".rar"],
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
      calculationFields[calculationFields.length - 1],
    ],
  },
};

const preflightResult = {
  preflightToken: "calculation-preflight-1",
  figureCount: 3,
  zeroFigureCount: 1,
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
  slabElevationCount: 0,
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
  it("keeps the required ZIP tree visible and restores focus after Escape", async () => {
    const user = userEvent.setup();
    const adapter = {
      preflightCalculationBook: vi.fn(),
      createCalculationBook: vi.fn(),
    } as unknown as ApiAdapter;
    render(<Harness adapter={adapter} />);
    const trigger = screen.getByRole("button", { name: "计算书" });
    await user.click(trigger);

    expect(screen.getByText("墙体01-X.png")).toBeInTheDocument();
    expect(screen.getByText("墙体01-Y.png")).toBeInTheDocument();
    expect(screen.getByText("墙体01-Z.png")).toBeInTheDocument();
    expect(screen.getByText("01 / 厂房标高布置图")).toBeInTheDocument();
    expect(screen.getByText("02 / 墙体有限元模型图")).toBeInTheDocument();
    const slabToggle = screen.getByRole("checkbox", { name: "包含楼板应力" });
    expect(slabToggle).not.toBeChecked();
    expect(slabToggle).toHaveAccessibleDescription(
      /共 5 组.*楼板配筋.*页面不提供手工输入/,
    );
    expect(screen.queryByLabelText("实配钢筋规格")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByLabelText("计算书模板")).toHaveFocus(),
    );

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "创建计算书" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
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
    });
  });
});
