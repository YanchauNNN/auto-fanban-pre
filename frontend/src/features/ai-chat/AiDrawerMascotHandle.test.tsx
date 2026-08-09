import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AiDrawerMascotHandle } from "./AiDrawerMascotHandle";

function renderHandle() {
  const onHide = vi.fn();
  const onResizeKeyDown = vi.fn();
  const onResizePointerDown = vi.fn();
  render(
    <AiDrawerMascotHandle
      onHide={onHide}
      onResizeKeyDown={onResizeKeyDown}
      onResizePointerDown={onResizePointerDown}
    />,
  );
  return { onHide, onResizeKeyDown, onResizePointerDown };
}

describe("AiDrawerMascotHandle", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("shows hide guidance on hover and resize guidance while pressed", () => {
    renderHandle();
    const handle = screen.getByRole("button", { name: "隐藏或调整 AI 助手窗口" });

    expect(handle).toHaveAttribute("data-interaction", "rest");
    fireEvent.mouseEnter(handle);
    expect(handle).toHaveAttribute("data-interaction", "hover");
    expect(screen.getByText("点我隐藏窗口")).toBeInTheDocument();

    fireEvent.pointerDown(handle, { clientX: 100, clientY: 100, pointerId: 1 });
    expect(handle).toHaveAttribute("data-interaction", "pressed");
    expect(screen.getByText("按住我拖动，调整窗口大小")).toBeInTheDocument();

    fireEvent.pointerUp(handle, { pointerId: 1 });
    expect(handle).toHaveAttribute("data-interaction", "hover");
  });

  it("keeps the hide guidance available to keyboard users", () => {
    renderHandle();
    const handle = screen.getByRole("button", { name: "隐藏或调整 AI 助手窗口" });

    expect(handle).toBeEnabled();
    expect(screen.getByText("点我隐藏窗口")).toBeInTheDocument();
  });

  it("forwards click, pointer, and keyboard actions to the drawer", () => {
    const { onHide, onResizeKeyDown, onResizePointerDown } = renderHandle();
    const handle = screen.getByRole("button", { name: "隐藏或调整 AI 助手窗口" });

    fireEvent.pointerDown(handle, { clientX: 100, clientY: 100, pointerId: 2 });
    expect(onResizePointerDown).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(onResizeKeyDown).toHaveBeenCalledTimes(1);

    fireEvent.click(handle);
    expect(onHide).toHaveBeenCalledTimes(1);
  });

  it("leaves the pressed state when the pointer is cancelled", () => {
    renderHandle();
    const handle = screen.getByRole("button", { name: "隐藏或调整 AI 助手窗口" });

    fireEvent.pointerDown(handle, { pointerId: 3 });
    expect(handle).toHaveAttribute("data-interaction", "pressed");

    fireEvent.pointerCancel(handle, { pointerId: 3 });
    expect(handle).toHaveAttribute("data-interaction", "rest");
  });
});
