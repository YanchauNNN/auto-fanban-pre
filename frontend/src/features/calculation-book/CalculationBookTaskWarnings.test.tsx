import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { CalculationBookOutput } from "../../platform/api/types";
import { CalculationBookTaskWarnings } from "./CalculationBookTaskWarnings";

const aiOutput: CalculationBookOutput = {
  reinforcementSource: "provided",
  figureCount: 12,
  templateType: "internal_structure",
  outputFilename: "计算书.docx",
  aiNormalized: true,
  warningCount: 3,
  warnings: [
    {
      code: "duplicate_reinforcement_rows",
      scope: "wall" as const,
      identity: "S7157",
      direction: null,
      sourceSheet: "Sheet1",
      sourceRow: 28,
      sourceCells: { wall: "A28", X: "B28", Y: "C28", Z: "D28" },
      reason: "同一墙体存在重复配筋行，相关配筋字段已留空",
      blankFields: ["X", "Y", "Z"],
    },
    {
      code: "needs_review",
      scope: "wall" as const,
      identity: "S7157",
      direction: "Y",
      sourceSheet: "Sheet1",
      sourceRow: 29,
      sourceCells: { Y: "C29" },
      reason: "竖向配筋内容无法确定，相关配筋字段已留空",
      blankFields: ["Y"],
    },
    {
      code: "needs_review",
      scope: "slab" as const,
      identity: "11.45",
      direction: "top_x",
      sourceSheet: null,
      sourceRow: null,
      sourceCells: {},
      reason: "楼板 11.45 的 top_x 向配筋信息无法确定，相关字段已留空",
      blankFields: ["top_x"],
    },
  ],
  aiNormalization: {
    skillId: "reinforcement_table_normalizer",
    model: "structured-test",
    profile: "intranet-test",
    callCount: 1,
    sourceRowCount: 40,
    normalizedWallCount: 38,
    normalizedSlabCount: 2,
    reviewWarningCount: 3,
    durationMs: 125,
    validation: "passed",
  },
  aiRebarSuggestion: null,
};

describe("CalculationBookTaskWarnings", () => {
  it("groups completed AI warnings with natural direction and evidence labels", async () => {
    const user = userEvent.setup();
    render(<CalculationBookTaskWarnings output={aiOutput} />);

    const region = screen.getByRole("region", { name: "配筋表人工补充提醒" });
    expect(region).toHaveTextContent("AI 已规范化非标准配筋表");
    expect(region).toHaveTextContent("需人工补充 3 项");
    expect(region).toHaveTextContent("已处理 40 行源数据");
    expect(screen.getByText("墙体 S7157")).toBeInTheDocument();
    expect(screen.getByText("楼板 11.45m")).toBeInTheDocument();

    const wallDisclosure = screen.getByText("墙体 S7157").closest("summary");
    expect(wallDisclosure).toHaveTextContent("2 项");
    await user.click(wallDisclosure as HTMLElement);
    expect(screen.getByText("Sheet1 · 第 28 行")).toBeInTheDocument();
    expect(screen.getByText(/单元格.*A28.*B28.*C28.*D28/)).toBeInTheDocument();
    expect(screen.getByText("留空字段：水平筋、竖向筋、拉筋")).toBeInTheDocument();
    expect(screen.getByText("方向：竖向筋")).toBeInTheDocument();

    const slabDisclosure = screen.getByText("楼板 11.45m").closest("summary");
    expect(slabDisclosure).toHaveTextContent("1 项");
    await user.click(slabDisclosure as HTMLElement);
    expect(screen.getByText("方向：顶层水平向")).toBeInTheDocument();
    expect(
      screen.getByText("楼板 11.45m 的顶层水平向配筋信息无法确定，顶层水平向已留空"),
    ).toBeInTheDocument();
    expect(screen.getByText("仅图片证据")).toBeInTheDocument();
    expect(region).not.toHaveTextContent("第 0 行");
    expect(region).not.toHaveTextContent("top_x");
  });

  it("renders nothing for a standard task without warnings", () => {
    const { container } = render(
      <CalculationBookTaskWarnings
        output={{
          ...aiOutput,
          aiNormalized: false,
          warningCount: 0,
          warnings: [],
          aiNormalization: null,
        }}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
