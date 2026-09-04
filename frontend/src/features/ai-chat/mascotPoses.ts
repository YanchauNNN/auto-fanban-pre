import { MASCOT_BONES, type MascotBoneId } from "./mascotModel";

export const MASCOT_POSE_NAMES = [
  "closed_idle",
  "opening_reach",
  "opening_ride",
  "open_cling",
  "closing_ride",
  "closing_release",
] as const;

export type MascotPoseName = (typeof MASCOT_POSE_NAMES)[number];

export type MascotBoneTransform = Readonly<{
  x: number;
  y: number;
  rotate: number;
  scaleX: number;
  scaleY: number;
}>;

export type MascotPose = Readonly<Record<MascotBoneId, MascotBoneTransform>>;

const REST_TRANSFORM: MascotBoneTransform = {
  x: 0,
  y: 0,
  rotate: 0,
  scaleX: 1,
  scaleY: 1,
};

function createPose(
  overrides: Partial<Record<MascotBoneId, Partial<MascotBoneTransform>>>,
): MascotPose {
  return Object.fromEntries(
    MASCOT_BONES.map((bone) => [
      bone.id,
      { ...REST_TRANSFORM, ...overrides[bone.id] },
    ]),
  ) as MascotPose;
}

const CLOSED_IDLE = createPose({
  "left-upper-arm": { rotate: 12 },
  "left-forearm": { rotate: -7 },
  "right-upper-arm": { rotate: -12 },
  "right-forearm": { rotate: 7 },
});

const OPENING_REACH = createPose({
  "upper-body": { rotate: -3 },
  "left-upper-arm": { rotate: -76 },
  "left-forearm": { rotate: 104 },
  "left-hand": { rotate: -8 },
  "right-upper-arm": { rotate: 78 },
  "right-forearm": { rotate: -26 },
  "right-hand": { rotate: 7 },
  head: { x: -7, y: -1, rotate: 2 },
});

const OPENING_RIDE = createPose({
  "upper-body": { rotate: -6 },
  torso: { x: 8, y: 2 },
  "left-upper-arm": { rotate: -98 },
  "left-forearm": { rotate: 78.5 },
  "left-hand": { rotate: 25.5 },
  "right-upper-arm": { rotate: -1.9 },
  "right-forearm": { rotate: 69.9 },
  "right-hand": { rotate: -62 },
  head: { x: -15, y: -2, rotate: 3 },
});

const OPEN_CLING = createPose({
  "upper-body": { rotate: -9 },
  torso: { x: 14, y: 4 },
  "left-upper-arm": { rotate: -82 },
  "left-forearm": { rotate: 53.1 },
  "left-hand": { rotate: 37.9 },
  "right-upper-arm": { rotate: 11.9 },
  "right-forearm": { rotate: 33.1 },
  "right-hand": { rotate: -36 },
  head: { x: -22, y: -2, rotate: 4 },
});

const MASCOT_POSES: Readonly<Record<MascotPoseName, MascotPose>> = {
  closed_idle: CLOSED_IDLE,
  opening_reach: OPENING_REACH,
  opening_ride: OPENING_RIDE,
  open_cling: OPEN_CLING,
  closing_ride: OPENING_RIDE,
  closing_release: OPENING_REACH,
};

export function resolveMascotPose(poseName: MascotPoseName) {
  return MASCOT_POSES[poseName];
}

export function interpolateMascotPoses(
  fromName: MascotPoseName,
  toName: MascotPoseName,
  progress: number,
): MascotPose {
  const from = resolveMascotPose(fromName);
  const to = resolveMascotPose(toName);
  const amount = Math.min(1, Math.max(0, progress));

  if (amount === 0) {
    return from;
  }
  if (amount === 1) {
    return to;
  }

  return Object.fromEntries(
    MASCOT_BONES.map((bone) => {
      const fromTransform = from[bone.id];
      const toTransform = to[bone.id];
      return [
        bone.id,
        {
          x: interpolateNumber(fromTransform.x, toTransform.x, amount),
          y: interpolateNumber(fromTransform.y, toTransform.y, amount),
          rotate: interpolateNumber(fromTransform.rotate, toTransform.rotate, amount),
          scaleX: interpolateNumber(fromTransform.scaleX, toTransform.scaleX, amount),
          scaleY: interpolateNumber(fromTransform.scaleY, toTransform.scaleY, amount),
        },
      ];
    }),
  ) as MascotPose;
}

export function formatMascotBoneTransform(transform: MascotBoneTransform) {
  return `translate(${transform.x} ${transform.y}) rotate(${transform.rotate}) scale(${transform.scaleX} ${transform.scaleY})`;
}

function interpolateNumber(from: number, to: number, progress: number) {
  return from + (to - from) * progress;
}
