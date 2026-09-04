import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { UpdateLogDialog } from "./UpdateLogDialog";

describe("UpdateLogDialog", () => {
  it("renders the complete project update log without version navigation", () => {
    render(<UpdateLogDialog onClose={vi.fn()} />);

    expect(screen.getByRole("dialog", { name: "更新日志" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "项目更新日志" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /2026\.01\.04\.1/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /2026\.09\.01\.6/ })).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("focuses the close button and closes with Escape", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(<UpdateLogDialog onClose={onClose} />);

    expect(screen.getByRole("button", { name: "关闭更新日志" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
