import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { ApiAdapter, FormSchema } from "../../platform/api/types";
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
      accept: [".zip"],
      requiredRootDirections: ["X", "Y", "Z"],
      requiredFolders: ["01", "02"],
      rootFigurePattern: "<墙号>-X|Y|Z.png",
      description: "保留目录结构",
    },
  },
} satisfies FormSchema;

const preflightResult = {
  preflightToken: "calculation-preflight-1",
  figureCount: 3,
  zeroFigureCount: 1,
  wallCount: 1,
  reinforcementWorkbook: "计算书模板文件.xlsx",
  requiresManualConfirmation: false,
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
    await user.upload(screen.getByLabelText("选择计算图片 ZIP"), archive);
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

    expect(preflightCalculationBook).toHaveBeenCalledWith(archive);
    await waitFor(() => expect(createCalculationBook).toHaveBeenCalledTimes(1));
    expect(createCalculationBook).toHaveBeenCalledWith(
      expect.objectContaining({
        template_type: "internal_structure",
        project_no: "2016",
        project_name: "浙江金七门核电厂1、2号机组",
        workshop_length: 72.5,
        preflight_token: "calculation-preflight-1",
        manual_confirmations: {},
      }),
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
      screen.getByLabelText("选择计算图片 ZIP"),
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
      screen.getByLabelText("选择计算图片 ZIP"),
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

  it("requires an explicit checkbox for every duplicate or split wall", async () => {
    const user = userEvent.setup();
    const manualPreflight = {
      ...preflightResult,
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
          suggestedSourceRow: 29,
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
      screen.getByLabelText("选择计算图片 ZIP"),
      new File(["zip"], "calculation.zip", { type: "application/zip" }),
    );
    await user.click(screen.getByRole("button", { name: "预检并核对" }));

    expect(await screen.findByRole("button", { name: "进入确认提交" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "进入确认提交" }));
    expect(await screen.findByText("S7157-1 需要人工确认")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建计算书任务" })).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: /Sheet1 · 第 28 行/ }));
    expect(screen.getByText("配筋表第 28 行")).toBeInTheDocument();
    expect(screen.getByText("1排25@200")).toBeInTheDocument();
    await user.click(screen.getByLabelText("已核对 S7157-1 的图片与配筋对应关系"));
    await user.click(screen.getByRole("button", { name: "创建计算书任务" }));

    await waitFor(() => expect(createCalculationBook).toHaveBeenCalledTimes(1));
    expect(createCalculationBook).toHaveBeenCalledWith(
      expect.objectContaining({
        manual_confirmations: { "S7157-1": 28 },
      }),
    );
  });
});
