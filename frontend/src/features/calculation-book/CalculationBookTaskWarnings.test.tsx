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

const aiSuggestedOutput: CalculationBookOutput = {
  reinforcementSource: "ai_suggested",
  figureCount: 177,
  templateType: "internal_structure",
  outputFilename: "AI配筋建议计算书.docx",
  aiNormalized: false,
  warningCount: 3,
  warnings: [
    {
      code: "OCR_RECOGNITION_FAILED",
      scope: "wall",
      identity: "N5012",
      direction: "X",
      sourceSheet: null,
      sourceRow: null,
      sourceCells: {},
      reason: "应力云图 SMX 识别失败，当前方向配筋建议已留空，请人工复核",
      blankFields: ["X"],
    },
    {
      code: "NO_ELIGIBLE_CANDIDATE",
      scope: "wall",
      identity: "N5013",
      direction: "Y",
      sourceSheet: null,
      sourceRow: null,
      sourceCells: {},
      reason: "后端未生成满足配筋规则的候选，当前方向已留空，请人工复核",
      blankFields: ["Y"],
    },
    {
      code: "AI_BASE_FAILURE_LIMIT",
      scope: "slab",
      identity: "11.45",
      direction: "top_x",
      sourceSheet: null,
      sourceRow: null,
      sourceCells: {},
      reason: "人工智能连续三次调用或协议失败，当前方向已留空，请人工复核",
      blankFields: ["top_x"],
    },
  ],
  aiNormalization: null,
  aiRebarSuggestion: {
    skillId: "calculation_book_rebar_adviser",
    skillVersion: "1.0.0",
    skillSha256: "abc123",
    model: "intranet-structured-model",
    callCount: 4,
    suggestedDirectionCount: 174,
    blankDirectionCount: 3,
    repairRoundCount: 2,
    validation: "passed",
  },
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

  it("summarizes image-only AI recommendations and explains every blank direction", async () => {
    const user = userEvent.setup();
    render(<CalculationBookTaskWarnings output={aiSuggestedOutput} />);

    const region = screen.getByRole("region", { name: "AI 配筋建议结果" });
    expect(region).toHaveTextContent("AI 配筋建议已生成");
    expect(region).toHaveTextContent("已生成 174 个方向");
    expect(region).toHaveTextContent("3 个方向留空待复核");
    expect(screen.getByLabelText("AI 配筋建议摘要")).toHaveTextContent("修复轮次2");
    expect(region).toHaveTextContent("intranet-structured-model");
    expect(region).toHaveTextContent("calculation_book_rebar_adviser · v1.0.0");
    expect(region).toHaveTextContent("后端校验通过");

    await user.click(screen.getByText("墙体 N5012").closest("summary") as HTMLElement);
    expect(region).toHaveTextContent("SMX 识别失败，水平筋建议已留空，请核对对应云图");
    expect(region).toHaveTextContent("仅图片证据");

    await user.click(screen.getByText("墙体 N5013").closest("summary") as HTMLElement);
    expect(region).toHaveTextContent("没有满足至少 10% 裕度的候选，竖向筋建议已留空");

    await user.click(screen.getByText("楼板 11.45m").closest("summary") as HTMLElement);
    expect(region).toHaveTextContent("AI 连续三次调用或协议校验失败，顶层水平向建议已留空");
  });

  it("shows twelve high-priority groups first and progressively reveals the rest", async () => {
    const user = userEvent.setup();
    const highPriorityWarnings = Array.from({ length: 13 }, (_, index) => ({
      code: index === 0 ? "OCR_RECOGNITION_FAILED" : "needs_review",
      scope: "wall" as const,
      identity: `高优先级-${index + 1}`,
      direction: "X",
      sourceSheet: null,
      sourceRow: null,
      sourceCells: {},
      reason: "当前方向配筋建议已留空，请人工复核",
      blankFields: ["X"],
    }));
    const ordinaryWarnings = Array.from({ length: 2 }, (_, index) => ({
      code: "workbook_only_wall",
      scope: "wall" as const,
      identity: `普通提醒-${index + 1}`,
      direction: null,
      sourceSheet: "Sheet1",
      sourceRow: index + 2,
      sourceCells: { wall: `A${index + 2}` },
      reason: "配筋表有记录，但应力图没有对应图组",
      blankFields: [],
    }));

    render(
      <CalculationBookTaskWarnings
        output={{
          ...aiSuggestedOutput,
          warningCount: 15,
          warnings: [ordinaryWarnings[0], ...highPriorityWarnings, ordinaryWarnings[1]],
        }}
      />,
    );

    expect(screen.getByText("墙体 高优先级-12")).toBeInTheDocument();
    expect(screen.queryByText("墙体 高优先级-13")).not.toBeInTheDocument();
    expect(screen.queryByText("墙体 普通提醒-1")).not.toBeInTheDocument();

    const revealButton = screen.getByRole("button", { name: "显示其余 3 组" });
    expect(revealButton).toHaveAttribute("aria-expanded", "false");
    revealButton.focus();
    await user.keyboard("{Enter}");

    expect(screen.getByText("墙体 高优先级-13")).toBeInTheDocument();
    expect(screen.getByText("墙体 普通提醒-1")).toBeInTheDocument();
    expect(screen.getByText("墙体 普通提醒-2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "收起提醒分组" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "收起提醒分组" }));
    expect(screen.queryByText("墙体 高优先级-13")).not.toBeInTheDocument();
    expect(screen.queryByText("墙体 普通提醒-1")).not.toBeInTheDocument();
  });
});
