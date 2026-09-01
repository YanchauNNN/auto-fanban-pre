import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { TaskConfigModal } from "./TaskConfigModal";

function ModalHarness({
  showPrimary,
  showSecondary,
}: {
  showPrimary: boolean;
  showSecondary: boolean;
}) {
  return (
    <>
      {showPrimary ? (
        <TaskConfigModal title="主弹窗">
          <div>primary</div>
        </TaskConfigModal>
      ) : null}
      {showSecondary ? (
        <TaskConfigModal title="次弹窗">
          <div>secondary</div>
        </TaskConfigModal>
      ) : null}
    </>
  );
}

describe("TaskConfigModal", () => {
  it("keeps document scrolling locked while another modal is still open", () => {
    const { rerender } = render(<ModalHarness showPrimary showSecondary />);

    expect(screen.getByRole("dialog", { name: "主弹窗" })).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "次弹窗" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    rerender(<ModalHarness showPrimary={false} showSecondary />);

    expect(screen.queryByRole("dialog", { name: "主弹窗" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "次弹窗" })).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");
  });

  it("restores document scrolling after all nested modals close", () => {
    const { rerender } = render(<ModalHarness showPrimary showSecondary />);

    expect(document.body.style.overflow).toBe("hidden");

    rerender(<ModalHarness showPrimary={false} showSecondary={false} />);

    expect(screen.queryByRole("dialog", { name: "主弹窗" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "次弹窗" })).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe("");
  });

  it("calls the close handler for only the topmost modal when Escape is pressed", async () => {
    const onPrimaryClose = vi.fn();
    const onSecondaryClose = vi.fn();
    const user = userEvent.setup();

    render(
      <>
        <TaskConfigModal title="主弹窗" onRequestClose={onPrimaryClose}>
          <div>primary</div>
        </TaskConfigModal>
        <TaskConfigModal title="次弹窗" onRequestClose={onSecondaryClose}>
          <div>secondary</div>
        </TaskConfigModal>
      </>,
    );

    await user.keyboard("{Escape}");

    expect(onSecondaryClose).toHaveBeenCalledTimes(1);
    expect(onPrimaryClose).not.toHaveBeenCalled();
  });

  it("moves focus into the dialog, traps Tab, and restores the opener", async () => {
    const user = userEvent.setup();

    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            打开参数
          </button>
          {open ? (
            <TaskConfigModal title="参数弹窗" onRequestClose={() => setOpen(false)}>
              <button type="button">第一项</button>
              <button type="button">最后一项</button>
            </TaskConfigModal>
          ) : null}
        </>
      );
    }

    render(<Harness />);
    const opener = screen.getByRole("button", { name: "打开参数" });
    await user.click(opener);

    const first = screen.getByRole("button", { name: "第一项" });
    const last = screen.getByRole("button", { name: "最后一项" });
    expect(first).toHaveFocus();

    last.focus();
    await user.tab();
    expect(first).toHaveFocus();

    await user.tab({ shift: true });
    expect(last).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "参数弹窗" })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });
});
