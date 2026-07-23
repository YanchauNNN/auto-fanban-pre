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
    const adapter = { createCalculationBook: vi.fn() } as unknown as ApiAdapter;
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
    const createCalculationBook = vi.fn().mockResolvedValue({
      batchId: "batch-calc",
      jobs: [],
    });
    const onBatchCreated = vi.fn();
    const adapter = { createCalculationBook } as unknown as ApiAdapter;
    render(
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
    await user.click(screen.getByRole("button", { name: "创建计算书任务" }));

    await waitFor(() => expect(createCalculationBook).toHaveBeenCalledTimes(1));
    expect(createCalculationBook).toHaveBeenCalledWith(
      expect.objectContaining({
        template_type: "internal_structure",
        project_no: "2016",
        project_name: "浙江金七门核电厂1、2号机组",
        workshop_length: 72.5,
      }),
      archive,
    );
    expect(onBatchCreated).toHaveBeenCalledWith({ batchId: "batch-calc", jobs: [] });
  });

  it("announces validation errors and focuses the first required field", async () => {
    const user = userEvent.setup();
    const adapter = { createCalculationBook: vi.fn() } as unknown as ApiAdapter;
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

    await user.click(screen.getByRole("button", { name: "创建计算书任务" }));

    expect(screen.getByRole("alert")).toHaveTextContent("请修正 15 个参数");
    await waitFor(() =>
      expect(screen.getByLabelText("计算书模板")).toHaveFocus(),
    );
    expect(screen.getByLabelText("计算书模板")).toHaveAttribute("aria-required", "true");
    expect(adapter.createCalculationBook).not.toHaveBeenCalled();
  });

  it("locks close, cancel, and Escape while the create request is pending", async () => {
    const user = userEvent.setup();
    let resolveRequest: ((value: { batchId: string; jobs: [] }) => void) | undefined;
    const createCalculationBook = vi.fn(
      () =>
        new Promise<{ batchId: string; jobs: [] }>((resolve) => {
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
        adapter={{ createCalculationBook } as unknown as ApiAdapter}
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
    await user.click(screen.getByRole("button", { name: "创建计算书任务" }));

    expect(screen.getByRole("button", { name: "关闭创建计算书" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "取消" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();

    resolveRequest?.({ batchId: "batch-calc", jobs: [] });
    await waitFor(() => expect(onBatchCreated).toHaveBeenCalled());
  });
});
