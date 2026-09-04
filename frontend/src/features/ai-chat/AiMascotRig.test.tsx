import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MASCOT_BONES, MASCOT_SKIN_PARTS, MASCOT_VIEW_BOX } from "./mascotModel";
import { AiMascotRig } from "./AiMascotRig";

describe("AiMascotRig", () => {
  it("renders every pass from the same viewBox, skeleton, and pose", () => {
    const { container } = render(
      <>
        <AiMascotRig pass="all" pose="open_cling" />
        <AiMascotRig pass="rear" pose="open_cling" />
        <AiMascotRig pass="front" pose="open_cling" />
      </>,
    );
    const rigs = Array.from(container.querySelectorAll("[data-mascot-rig]"));

    expect(rigs).toHaveLength(3);
    for (const rig of rigs) {
      expect(rig).toHaveAttribute("viewBox", MASCOT_VIEW_BOX);
      expect(rig.querySelectorAll("[data-bone]")).toHaveLength(MASCOT_BONES.length);
      expect(rig).not.toHaveAttribute("data-mascot-variant");
    }

    for (const bone of MASCOT_BONES) {
      const transforms = rigs.map((rig) =>
        rig.querySelector(`[data-bone="${bone.id}"]`)?.getAttribute("transform"),
      );
      const transitionStyles = rigs.map((rig) =>
        rig.querySelector(`[data-bone="${bone.id}"]`)?.getAttribute("style"),
      );
      expect(new Set(transforms).size).toBe(1);
      expect(new Set(transitionStyles).size).toBe(1);
      expect(transitionStyles[0]).toContain("transform:");
    }
  });

  it("filters canonical skin parts without defining a second grip illustration", () => {
    const { container } = render(
      <>
        <AiMascotRig pass="all" pose="closed_idle" />
        <AiMascotRig pass="rear" pose="closed_idle" />
        <AiMascotRig pass="front" pose="closed_idle" />
      </>,
    );
    const all = container.querySelector('[data-render-pass="all"]');
    const rear = container.querySelector('[data-render-pass="rear"]');
    const front = container.querySelector('[data-render-pass="front"]');
    const partIds = (root: Element | null) =>
      Array.from(root?.querySelectorAll("[data-skin-part]") ?? []).map((part) =>
        part.getAttribute("data-skin-part"),
      );

    expect(partIds(all)).toEqual(MASCOT_SKIN_PARTS.map((part) => part.id));
    expect(partIds(rear)).toEqual(
      MASCOT_SKIN_PARTS.filter((part) => part.layer === "rear").map((part) => part.id),
    );
    expect(partIds(front)).toEqual(["left-finger-pad", "right-finger-pad"]);
  });

  it("keeps the arm bones above the torso and the head above the shoulders", () => {
    const { container } = render(<AiMascotRig pass="all" pose="closed_idle" />);
    const torso = container.querySelector('[data-bone="torso"]');
    const leftArm = container.querySelector('[data-bone="left-upper-arm"]');
    const rightArm = container.querySelector('[data-bone="right-upper-arm"]');
    const head = container.querySelector('[data-bone="head"]');

    expect(torso && leftArm ? torso.compareDocumentPosition(leftArm) : 0).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(leftArm && rightArm ? leftArm.compareDocumentPosition(rightArm) : 0).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(rightArm && head ? rightArm.compareDocumentPosition(head) : 0).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it("isolates ambient motion from the root bone transform", () => {
    const { container } = render(<AiMascotRig pass="all" pose="closed_idle" />);
    const motionRoot = container.querySelector("[data-mascot-motion-root]");
    const rootBone = container.querySelector('[data-bone="root"]');

    expect(motionRoot).not.toBeNull();
    expect(motionRoot?.firstElementChild).toBe(rootBone);
    expect(rootBone?.getAttribute("style")).toContain("translate(58px, 82px)");
  });
});
