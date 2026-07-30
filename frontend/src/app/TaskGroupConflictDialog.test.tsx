import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TaskGroupConflictDialog } from "./TaskGroupConflictDialog";

describe("TaskGroupConflictDialog", () => {
  it("renders archive conflict copy and confirms overwrite submission", async () => {
    const onClose = vi.fn();
    const onConfirm = vi.fn();
    const user = userEvent.setup();

    render(
      <TaskGroupConflictDialog kind="archive" onClose={onClose} onConfirm={onConfirm} />,
    );

    expect(screen.getByRole("dialog", { name: "归档冲突确认" })).toBeInTheDocument();
    expect(screen.getByText("归档目标已存在，是否覆盖归档后继续提交？")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "继续提交" }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("renders duplicate conflict copy and supports canceling", async () => {
    const onClose = vi.fn();
    const onConfirm = vi.fn();
    const user = userEvent.setup();

    render(
      <TaskGroupConflictDialog kind="duplicate" onClose={onClose} onConfirm={onConfirm} />,
    );

    expect(screen.getByRole("dialog", { name: "重复流程确认" })).toBeInTheDocument();
    expect(screen.getByText("已有同图册流程在执行中，是否取消旧流程并重新提交？")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "取消" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
