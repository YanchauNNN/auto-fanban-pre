import { describe, expect, it } from "vitest";

import {
  getArchiveStatusLabel,
  getSettlementStatusLabel,
  getWorkflowStatusLabel,
  getWorkloadRoleLabel,
} from "./taskGroupPresentation";

describe("task group presentation", () => {
  it("uses natural Chinese labels when backend labels are unavailable", () => {
    expect(getWorkflowStatusLabel("in_review")).toBe("审批中");
    expect(getArchiveStatusLabel("failed")).toBe("归档失败");
    expect(getSettlementStatusLabel("settled")).toBe("已结算");
    expect(getWorkloadRoleLabel("initiator")).toBe("发起人");
  });

  it("uses configured node labels for workload approval roles", () => {
    expect(
      getWorkloadRoleLabel("quality_gate", {
        nodeLabels: { quality_gate: "质量复核" },
      }),
    ).toBe("质量复核");
  });
});
