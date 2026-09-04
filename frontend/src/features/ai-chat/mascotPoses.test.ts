import { describe, expect, it } from "vitest";

import { MASCOT_BONES } from "./mascotModel";
import {
  MASCOT_POSE_NAMES,
  formatMascotBoneTransform,
  interpolateMascotPoses,
  resolveMascotPose,
} from "./mascotPoses";

describe("mascotPoses", () => {
  it("resolves every state against the same complete bone set", () => {
    const expectedBoneIds = MASCOT_BONES.map((bone) => bone.id);

    for (const poseName of MASCOT_POSE_NAMES) {
      expect(Object.keys(resolveMascotPose(poseName))).toEqual(expectedBoneIds);
    }
  });

  it("uses mirrored transition poses and a counter-tilted cling head", () => {
    const openingReach = resolveMascotPose("opening_reach");
    const openingRide = resolveMascotPose("opening_ride");
    const openCling = resolveMascotPose("open_cling");

    expect(resolveMascotPose("closing_ride")).toEqual(openingRide);
    expect(resolveMascotPose("closing_release")).toEqual(openingReach);
    expect(openCling["upper-body"].rotate).toBe(-9);
    expect(openCling.head.rotate).toBe(4);
    expect(openCling["upper-body"].rotate + openCling.head.rotate).toBe(-5);
  });

  it("places both gripping hands on the drawer edge instead of over the face", () => {
    const openCling = resolveMascotPose("open_cling");
    const leftWrist = resolveWristPosition(openCling, "left");
    const rightWrist = resolveWristPosition(openCling, "right");

    expect(leftWrist.x).toBeCloseTo(70, 0);
    expect(leftWrist.y).toBeCloseTo(107, 0);
    expect(rightWrist.x).toBeCloseTo(70, 0);
    expect(rightWrist.y).toBeCloseTo(123, 0);
    expect(openCling.torso.x).toBeGreaterThanOrEqual(12);
  });

  it("interpolates numeric bone transforms deterministically", () => {
    const midpoint = interpolateMascotPoses("closed_idle", "open_cling", 0.5);

    expect(midpoint["upper-body"].rotate).toBe(-4.5);
    expect(midpoint.head.rotate).toBe(2);
    expect(interpolateMascotPoses("closed_idle", "open_cling", -1)).toEqual(
      resolveMascotPose("closed_idle"),
    );
    expect(interpolateMascotPoses("closed_idle", "open_cling", 2)).toEqual(
      resolveMascotPose("open_cling"),
    );
    expect(
      formatMascotBoneTransform({ x: 2, y: 3, rotate: 4, scaleX: 1.1, scaleY: 0.9 }),
    ).toBe("translate(2 3) rotate(4) scale(1.1 0.9)");
  });
});

function resolveWristPosition(
  pose: ReturnType<typeof resolveMascotPose>,
  side: "left" | "right",
) {
  const degreesToRadians = Math.PI / 180;
  const upperBodyAngle = pose["upper-body"].rotate * degreesToRadians;
  const upperArmAngle =
    upperBodyAngle + pose[`${side}-upper-arm`].rotate * degreesToRadians;
  const forearmAngle =
    upperArmAngle + pose[`${side}-forearm`].rotate * degreesToRadians;
  const shoulderX = side === "left" ? -25 : 25;
  const shoulderY = 5;
  const rotate = (x: number, y: number, angle: number) => ({
    x: x * Math.cos(angle) - y * Math.sin(angle),
    y: x * Math.sin(angle) + y * Math.cos(angle),
  });
  const shoulder = rotate(shoulderX, shoulderY, upperBodyAngle);
  const upperArm = rotate(0, 23, upperArmAngle);
  const forearm = rotate(0, 21, forearmAngle);

  return {
    x: 58 + pose["upper-body"].x + shoulder.x + upperArm.x + forearm.x,
    y: 82 + pose["upper-body"].y + shoulder.y + upperArm.y + forearm.y,
  };
}
