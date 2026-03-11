import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DeliverableWorkspace } from "./DeliverableWorkspace";
import type { ApiAdapter } from "../../platform/api/types";

const schema = {
  schemaVersion: "frontend-form@1",
  uploadLimits: {
    maxFiles: 50,
    allowedExts: [".dwg"],
    maxTotalMb: 2048,
  },
  sections: [
    {
      id: "project",
      title: "任务与项目",
      fields: [
        {
          key: "project_no",
          label: "项目号",
          type: "select",
          required: false,
          requiredWhen: null,
          defaultValue: "",
          description: "项目号",
          options: ["2016", "1818"],
        },
      ],
    },
    {
      id: "cover",
      title: "图册与封面",
      fields: [
        {
          key: "album_title_cn",
          label: "图册名称（中文）",
          type: "text",
          required: true,
          requiredWhen: null,
          defaultValue: "",
          description: "图册名称",
          options: [],
        },
      ],
    },
  ],
} as const;

describe("DeliverableWorkspace", () => {
  it("maps 422 param errors into field and form level messages", async () => {
    const user = userEvent.setup();
    const adapter: ApiAdapter = {
      getHealth: vi.fn(),
      getFormSchema: vi.fn(),
      listJobs: vi.fn(),
      getJobDetail: vi.fn(),
      createBatch: vi.fn().mockRejectedValue({
        status: 422,
        detail: {
          upload_errors: {
            files: ["only .dwg files are allowed"],
          },
          param_errors: {
            album_title_cn: ["required"],
          },
        },
      }),
    };
    const onBatchCreated = vi.fn();

    render(
      <DeliverableWorkspace
        adapter={adapter}
        schema={schema}
        onBatchCreated={onBatchCreated}
      />,
    );

    const fileInput = screen.getByLabelText("上传 DWG 文件");
    await user.upload(
      fileInput,
      new File(["dwg"], "A01.dwg", { type: "application/acad" }),
    );
    await user.type(screen.getByLabelText("图册名称（中文）"), "示例图册");
    await user.click(screen.getByRole("button", { name: "创建交付任务" }));

    await waitFor(() => {
      expect(screen.getByText("only .dwg files are allowed")).toBeInTheDocument();
      expect(screen.getByText("required")).toBeInTheDocument();
    });
    expect(onBatchCreated).not.toHaveBeenCalled();
  });
});
