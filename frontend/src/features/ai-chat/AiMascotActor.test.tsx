import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AiMascotActor } from "./AiMascotActor";

function mockReducedMotion(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

function actorProps(drawerVisible = false, drawerOpen = false) {
  return {
    drawerOpen,
    drawerSize: { height: 768, width: 720 },
    drawerVisible,
    onHide: vi.fn(),
    onOpen: vi.fn(),
    onResizeKeyDown: vi.fn(),
    onResizePointerDown: vi.fn(),
  };
}

function mockActorBounds(height = 128) {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    bottom: height,
    height,
    left: 0,
    right: 102,
    top: 0,
    width: 102,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  });
}

describe("AiMascotActor", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockReducedMotion(false);
    window.localStorage.clear();
    vi.spyOn(Math, "random").mockReturnValue(0);
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 900,
      writable: true,
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("keeps one interaction actor mounted through the complete open and close sequence", () => {
    const closedProps = actorProps();
    const { rerender } = render(<AiMascotActor {...closedProps} />);
    const button = screen.getByRole("button", { name: "打开 AI 助手" });

    expect(button).toHaveAttribute("data-mascot-phase", "closed_idle");
    expect(screen.getByTestId("mascot-pass-all")).toHaveAttribute("data-active", "true");
    expect(screen.getByTestId("mascot-pass-rear")).toHaveAttribute("data-active", "false");

    rerender(<AiMascotActor {...actorProps(true, true)} />);
    expect(screen.getByRole("button", { name: "隐藏或调整 AI 助手窗口" })).toBe(button);
    expect(button).toHaveAttribute("data-mascot-phase", "opening_reach");

    act(() => vi.advanceTimersByTime(90));
    expect(button).toHaveAttribute("data-mascot-phase", "opening_ride");
    expect(screen.getByTestId("mascot-pass-all")).toHaveAttribute("data-active", "false");
    expect(screen.getByTestId("mascot-pass-rear")).toHaveAttribute("data-active", "true");
    expect(screen.getByTestId("mascot-pass-front")).toHaveAttribute("data-active", "true");

    act(() => vi.advanceTimersByTime(330));
    expect(button).toHaveAttribute("data-mascot-phase", "open_cling");

    rerender(<AiMascotActor {...actorProps(true, false)} />);
    expect(button).toHaveAttribute("data-mascot-phase", "closing_ride");

    act(() => vi.advanceTimersByTime(330));
    expect(button).toHaveAttribute("data-mascot-phase", "closing_release");
    expect(screen.getByTestId("mascot-pass-all")).toHaveAttribute("data-active", "true");

    act(() => vi.advanceTimersByTime(90));
    expect(button).toHaveAttribute("data-mascot-phase", "closed_idle");
  });

  it("feeds exactly the same pose snapshot to every render pass", () => {
    const { rerender } = render(<AiMascotActor {...actorProps()} />);
    rerender(<AiMascotActor {...actorProps(true, true)} />);
    act(() => vi.advanceTimersByTime(90));

    const rigs = Array.from(document.querySelectorAll("[data-mascot-rig]"));
    for (const boneId of ["root", "upper-body", "left-hand", "right-hand", "head"]) {
      const transforms = rigs.map((rig) =>
        rig.querySelector(`[data-bone="${boneId}"]`)?.getAttribute("transform"),
      );
      expect(new Set(transforms).size).toBe(1);
    }
  });

  it("moves directly to stable poses when reduced motion is requested", () => {
    mockReducedMotion(true);
    const { rerender } = render(<AiMascotActor {...actorProps()} />);
    const button = screen.getByRole("button", { name: "打开 AI 助手" });
    const baselineTimerCount = vi.getTimerCount();

    rerender(<AiMascotActor {...actorProps(true, true)} />);
    expect(button).toHaveAttribute("data-mascot-phase", "open_cling");
    expect(vi.getTimerCount()).toBe(baselineTimerCount);

    rerender(<AiMascotActor {...actorProps(false, false)} />);
    expect(button).toHaveAttribute("data-mascot-phase", "closed_idle");
    expect(vi.getTimerCount()).toBe(baselineTimerCount);
  });

  it("restores and persists closed vertical dragging without opening", async () => {
    vi.useRealTimers();
    const props = actorProps();
    window.localStorage.setItem("fanban.ai.mascotTop", "220");
    mockActorBounds();
    render(<AiMascotActor {...props} />);
    const button = screen.getByRole("button", { name: "打开 AI 助手" });

    fireEvent.pointerDown(button, {
      button: 0,
      clientY: 240,
      pointerId: 7,
      pointerType: "mouse",
    });
    fireEvent.pointerMove(button, {
      clientY: 330,
      pointerId: 7,
      pointerType: "mouse",
    });
    fireEvent.pointerUp(button, { clientY: 330, pointerId: 7, pointerType: "mouse" });
    fireEvent.click(button);

    expect(button).toHaveStyle({ "--ai-mascot-top": "310px" });
    expect(props.onOpen).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(window.localStorage.getItem("fanban.ai.mascotTop")).toBe("310");
    });
  });

  it("retains keyboard positioning, hover engagement, and bounded idle motion", () => {
    window.localStorage.setItem("fanban.ai.mascotTop", "220");
    mockActorBounds();
    render(<AiMascotActor {...actorProps()} />);
    const button = screen.getByRole("button", { name: "打开 AI 助手" });

    fireEvent.keyDown(button, { key: "ArrowDown" });
    expect(button).toHaveStyle({ "--ai-mascot-top": "244px" });
    fireEvent.mouseEnter(button);
    expect(button).toHaveAttribute("data-engaged", "true");
    fireEvent.mouseLeave(button);
    expect(button).toHaveAttribute("data-engaged", "false");

    expect(button).toHaveAttribute("data-idle-motion", "rest");
    act(() => vi.advanceTimersByTime(6_000));
    expect(button).toHaveAttribute("data-idle-motion", "blink");
    act(() => vi.advanceTimersByTime(900));
    expect(button).toHaveAttribute("data-idle-motion", "rest");
  });
});
