import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DeliverableWorkspace } from "./DeliverableWorkspace";
import type { ApiAdapter, FormSchema } from "../../platform/api/types";
import { normalizeFormSchema } from "../schema/schema";

const schema: FormSchema = normalizeFormSchema({
  schema_version: "frontend-form@1",
  upload_limits: {
    max_files: 50,
    allowed_exts: [".dwg"],
    max_total_mb: 2048,
  },
  deliverable: {
    sections: [
      {
        id: "project",
        title: "project",
        fields: [
          {
            key: "project_no",
            label: "project_no",
            type: "text",
            required: false,
            required_when: null,
            source: "frontend",
            default: "",
            format: null,
            desc: "",
            options: [],
          },
          {
            key: "cover_variant",
            label: "cover_variant",
            type: "select",
            required: true,
            required_when: null,
            source: "frontend",
            default: "通用",
            format: null,
            desc: "封面模板选择",
            options: ["通用"],
          },
        ],
      },
      {
        id: "cover",
        title: "cover",
        fields: [
          {
            key: "album_title_cn",
            label: "album_title_cn",
            type: "text",
            required: true,
            required_when: null,
            source: "frontend",
            default: "",
            format: null,
            desc: "图册名称（中文）",
            options: [],
          },
        ],
      },
      {
        id: "ied",
        title: "ied",
        fields: [
          {
            key: "ied_checked_by",
            label: "ied_checked_by",
            type: "text",
            required: true,
            required_when: null,
            source: "frontend",
            default: "",
            format: "姓名@ID",
            desc: "校核者(BB列)",
            options: [],
          },
          {
            key: "ied_checked_date",
            label: "ied_checked_date",
            type: "text",
            required: true,
            required_when: null,
            source: "frontend",
            default: "",
            format: "YYYY-MM-DD",
            desc: "校核日期(BC列)",
            options: [],
          },
          {
            key: "ied_discipline_leader",
            label: "ied_discipline_leader",
            type: "text",
            required: true,
            required_when: null,
            source: "frontend",
            default: "",
            format: "姓名@ID",
            desc: "工种负责人(BD列)",
            options: [],
          },
          {
            key: "ied_discipline_leader_date",
            label: "ied_discipline_leader_date",
            type: "text",
            required: true,
            required_when: null,
            source: "frontend",
            default: "",
            format: "YYYY-MM-DD",
            desc: "工种负责人审核日期(BE列)",
            options: [],
          },
        ],
      },
    ],
  },
  audit_replace: {
    project_options: [],
  },
});

function createAdapter(): ApiAdapter {
  return {
    ping: vi.fn(),
    getHealth: vi.fn(),
    getFormSchema: vi.fn(),
    preflightFonts: vi.fn().mockResolvedValue({
      files: [
        {
          filename: "A01.dwg",
          status: "ok",
          missingFonts: [],
          detectedStyleCount: 12,
          missingStyleCount: 0,
          fontReplacementApplied: false,
          replacementFont: null,
          replacedStyleCount: 0,
          errors: [],
        },
      ],
      replacementOptions: [],
      requiresConfirmation: false,
    }),
    createAuditCheck: vi.fn(),
    createAuditReplace: vi.fn(),
    rememberAuditReplaceFactoryCodes: vi.fn().mockResolvedValue({ factoryCodes: [] }),
    createSplitOnlyBatch: vi.fn(),
    listJobs: vi.fn(),
    getJobsActivity: vi.fn(),
    getJobDetail: vi.fn(),
    createBatch: vi.fn().mockResolvedValue({
      batchId: "batch-1",
      jobs: [],
    }),
  };
}

describe("DeliverableWorkspace independent IED checker fields", () => {
  it("renders checker and discipline leader inputs separately and submits their distinct values", async () => {
    const user = userEvent.setup();
    const adapter = createAdapter();

    render(
      <DeliverableWorkspace
        adapter={adapter}
        incomingFiles={[new File(["dwg"], "A01.dwg", { type: "application/acad" })]}
        isOpen
        onBatchCreated={vi.fn()}
        onClose={vi.fn()}
        onDraftAvailabilityChange={vi.fn()}
        schema={schema}
      />,
    );

    await user.type(screen.getByLabelText("图册名称（中文）"), "示例图册");
    await user.type(screen.getByLabelText("校核者"), "王任超@wangrca");
    await user.type(screen.getByLabelText("工种负责人"), "孟志勇@mengzy");

    const checkedDateInput = screen.getByLabelText("校核日期");
    await user.clear(checkedDateInput);
    await user.type(checkedDateInput, "2026-03-22");

    const disciplineLeaderDateInput = screen.getByLabelText("工种负责人审核日期");
    await user.clear(disciplineLeaderDateInput);
    await user.type(disciplineLeaderDateInput, "2026-03-24");

    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    await waitFor(() => {
      expect(adapter.createBatch).toHaveBeenCalledWith(
        expect.objectContaining({
          ied_checked_by: "王任超@wangrca",
          ied_checked_date: "2026-03-22",
          ied_discipline_leader: "孟志勇@mengzy",
          ied_discipline_leader_date: "2026-03-24",
        }),
        expect.any(Array),
        false,
      );
    });
  });
});
