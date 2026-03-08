import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";

vi.mock("../platform/api/useApiAdapter", () => ({
  useApiAdapter: () => ({
    getHealth: vi.fn().mockResolvedValue({
      status: "ok",
      ready: true,
      storageWritable: true,
      workerAlive: true,
      queueDepth: 1,
      autocadReady: true,
      officeReady: true,
      serverTime: "2026-03-08T10:20:30+08:00",
    }),
    getFormSchema: vi.fn().mockResolvedValue({
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
              required: true,
              requiredWhen: null,
              defaultValue: "",
              description: "项目号",
              options: ["2016", "1818"],
            },
          ],
        },
      ],
    }),
    createBatch: vi.fn(),
    listJobs: vi.fn().mockResolvedValue({
      total: 0,
      items: [],
    }),
    getJobDetail: vi.fn(),
  }),
}));

describe("App", () => {
  it("renders three task cards and marks unavailable tasks", async () => {
    render(<App />);

    expect(await screen.findByRole("button", { name: "交付处理" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "纠错" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "翻版" })).toBeDisabled();
    expect(screen.getAllByText("接口未开放")).toHaveLength(2);
  });

  it("switches deliverable workspace panel into focus", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "交付处理" }));

    expect(screen.getByRole("heading", { name: "交付处理任务" })).toBeInTheDocument();
  });
});
