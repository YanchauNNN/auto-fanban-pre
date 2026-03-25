import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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
});
