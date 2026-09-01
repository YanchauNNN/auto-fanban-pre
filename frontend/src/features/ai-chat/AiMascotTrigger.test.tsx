import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AiMascotTrigger } from "./AiMascotTrigger";

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

describe("AiMascotTrigger", () => {
  beforeEach(() => {
    mockReducedMotion(false);
    vi.spyOn(Math, "random").mockReturnValue(0);
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("opens the AI drawer and forwards the focus-restoration ref", () => {
    const onOpen = vi.fn();
    const buttonRef = createRef<HTMLButtonElement>();
    render(<AiMascotTrigger buttonRef={buttonRef} onOpen={onOpen} />);

    const trigger = screen.getByRole("button", { name: "打开 AI 助手" });
    expect(buttonRef.current).toBe(trigger);
    fireEvent.click(trigger);

    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("shows the desktop invitation state on hover and keyboard focus", () => {
    render(<AiMascotTrigger onOpen={() => undefined} />);
    const trigger = screen.getByRole("button", { name: "打开 AI 助手" });
    const bubble = screen.getByText("点我进入AI功能");

    expect(trigger).toHaveAttribute("data-engaged", "false");
    expect(bubble).toHaveAttribute("aria-hidden", "true");

    fireEvent.mouseEnter(trigger);
    expect(trigger).toHaveAttribute("data-engaged", "true");

    fireEvent.mouseLeave(trigger);
    expect(trigger).toHaveAttribute("data-engaged", "false");

    fireEvent.focus(trigger);
    expect(trigger).toHaveAttribute("data-engaged", "true");

    fireEvent.blur(trigger);
    expect(trigger).toHaveAttribute("data-engaged", "false");
  });

  it("runs one bounded idle motion and clears scheduled timers on unmount", () => {
    vi.useFakeTimers();
    const { unmount } = render(<AiMascotTrigger onOpen={() => undefined} />);
    const trigger = screen.getByRole("button", { name: "打开 AI 助手" });

    expect(trigger).toHaveAttribute("data-idle-motion", "rest");
    expect(vi.getTimerCount()).toBe(1);

    act(() => vi.advanceTimersByTime(6_000));
    expect(trigger).toHaveAttribute("data-idle-motion", "blink");

    act(() => vi.advanceTimersByTime(900));
    expect(trigger).toHaveAttribute("data-idle-motion", "rest");
    expect(vi.getTimerCount()).toBe(1);

    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not schedule idle animation when reduced motion is requested", () => {
    vi.useFakeTimers();
    mockReducedMotion(true);
    render(<AiMascotTrigger onOpen={() => undefined} />);

    expect(screen.getByRole("button", { name: "打开 AI 助手" })).toHaveAttribute(
      "data-idle-motion",
      "rest",
    );
    expect(vi.getTimerCount()).toBe(0);
  });
});
