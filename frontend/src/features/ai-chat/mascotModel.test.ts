import { describe, expect, it } from "vitest";

import {
  MASCOT_BONES,
  MASCOT_SKIN_PARTS,
  MASCOT_VIEW_BOX,
  getMascotPartsForPass,
  validateMascotModel,
} from "./mascotModel";

describe("mascotModel", () => {
  it("defines one complete articulated skeleton in one coordinate system", () => {
    expect(MASCOT_VIEW_BOX).toBe("0 0 116 145");
    expect(MASCOT_BONES.map(({ id, parentId }) => [id, parentId])).toEqual([
      ["root", null],
      ["upper-body", "root"],
      ["torso", "upper-body"],
      ["left-upper-arm", "upper-body"],
      ["left-forearm", "left-upper-arm"],
      ["left-hand", "left-forearm"],
      ["right-upper-arm", "upper-body"],
      ["right-forearm", "right-upper-arm"],
      ["right-hand", "right-forearm"],
      ["head", "upper-body"],
      ["antenna", "head"],
    ]);
    expect(validateMascotModel()).toEqual([]);
  });

  it("keeps every skin part unique and attached to a valid bone", () => {
    const boneIds = new Set(MASCOT_BONES.map((bone) => bone.id));
    const partIds = MASCOT_SKIN_PARTS.map((part) => part.id);

    expect(new Set(partIds).size).toBe(partIds.length);
    expect(MASCOT_SKIN_PARTS.every((part) => boneIds.has(part.boneId))).toBe(true);
    expect(MASCOT_SKIN_PARTS.map((part) => part.paintOrder)).toEqual(
      [...MASCOT_SKIN_PARTS]
        .sort((left, right) => left.paintOrder - right.paintOrder)
        .map((part) => part.paintOrder),
    );
  });

  it("derives complete, rear, and finger foreground passes from the same parts", () => {
    const allParts = getMascotPartsForPass("all");
    const rearParts = getMascotPartsForPass("rear");
    const frontParts = getMascotPartsForPass("front");

    expect(allParts).toEqual(MASCOT_SKIN_PARTS);
    expect(frontParts.map((part) => part.id)).toEqual([
      "left-finger-pad",
      "right-finger-pad",
    ]);
    expect(rearParts.some((part) => part.id === "left-hand-shell")).toBe(true);
    expect(rearParts.some((part) => part.id === "right-hand-shell")).toBe(true);
    expect(rearParts.some((part) => part.layer === "front")).toBe(false);
  });
});
