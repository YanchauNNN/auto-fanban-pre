export const MASCOT_VIEW_BOX = "0 0 116 145" as const;

export type MascotBoneId =
  | "root"
  | "upper-body"
  | "torso"
  | "left-upper-arm"
  | "left-forearm"
  | "left-hand"
  | "right-upper-arm"
  | "right-forearm"
  | "right-hand"
  | "head"
  | "antenna";

export type MascotRenderPass = "all" | "rear" | "front";
export type MascotSkinLayer = Exclude<MascotRenderPass, "all">;

export type MascotBoneDefinition = {
  id: MascotBoneId;
  parentId: MascotBoneId | null;
  origin: Readonly<{ x: number; y: number }>;
};

export const MASCOT_BONES: readonly MascotBoneDefinition[] = [
  { id: "root", parentId: null, origin: { x: 58, y: 82 } },
  { id: "upper-body", parentId: "root", origin: { x: 0, y: 0 } },
  { id: "torso", parentId: "upper-body", origin: { x: 0, y: 0 } },
  { id: "left-upper-arm", parentId: "upper-body", origin: { x: -25, y: 5 } },
  { id: "left-forearm", parentId: "left-upper-arm", origin: { x: 0, y: 23 } },
  { id: "left-hand", parentId: "left-forearm", origin: { x: 0, y: 21 } },
  { id: "right-upper-arm", parentId: "upper-body", origin: { x: 25, y: 5 } },
  { id: "right-forearm", parentId: "right-upper-arm", origin: { x: 0, y: 23 } },
  { id: "right-hand", parentId: "right-forearm", origin: { x: 0, y: 21 } },
  { id: "head", parentId: "upper-body", origin: { x: 0, y: 0 } },
  { id: "antenna", parentId: "head", origin: { x: 0, y: 0 } },
];

export type MascotSkinPartId =
  | "torso-shell"
  | "torso-highlight"
  | "torso-panel"
  | "torso-indicator"
  | "torso-detail"
  | "left-upper-arm-shell"
  | "left-forearm-shell"
  | "left-hand-shell"
  | "left-finger-pad"
  | "right-upper-arm-shell"
  | "right-forearm-shell"
  | "right-hand-shell"
  | "right-finger-pad"
  | "head-left-ear"
  | "head-right-ear"
  | "head-shell"
  | "face-screen"
  | "face-screen-highlight"
  | "face-eyes"
  | "face-smile"
  | "face-cheeks"
  | "head-shell-highlight"
  | "antenna-stem"
  | "antenna-light"
  | "antenna-highlight";

export type MascotSkinPart = {
  id: MascotSkinPartId;
  boneId: MascotBoneId;
  layer: MascotSkinLayer;
  paintOrder: number;
};

export const MASCOT_SKIN_PARTS: readonly MascotSkinPart[] = [
  { id: "torso-shell", boneId: "torso", layer: "rear", paintOrder: 10 },
  { id: "torso-highlight", boneId: "torso", layer: "rear", paintOrder: 11 },
  { id: "torso-panel", boneId: "torso", layer: "rear", paintOrder: 12 },
  { id: "torso-indicator", boneId: "torso", layer: "rear", paintOrder: 13 },
  { id: "torso-detail", boneId: "torso", layer: "rear", paintOrder: 14 },
  {
    id: "left-upper-arm-shell",
    boneId: "left-upper-arm",
    layer: "rear",
    paintOrder: 20,
  },
  {
    id: "left-forearm-shell",
    boneId: "left-forearm",
    layer: "rear",
    paintOrder: 21,
  },
  { id: "left-hand-shell", boneId: "left-hand", layer: "rear", paintOrder: 22 },
  { id: "left-finger-pad", boneId: "left-hand", layer: "front", paintOrder: 23 },
  {
    id: "right-upper-arm-shell",
    boneId: "right-upper-arm",
    layer: "rear",
    paintOrder: 30,
  },
  {
    id: "right-forearm-shell",
    boneId: "right-forearm",
    layer: "rear",
    paintOrder: 31,
  },
  { id: "right-hand-shell", boneId: "right-hand", layer: "rear", paintOrder: 32 },
  { id: "right-finger-pad", boneId: "right-hand", layer: "front", paintOrder: 33 },
  { id: "head-left-ear", boneId: "head", layer: "rear", paintOrder: 40 },
  { id: "head-right-ear", boneId: "head", layer: "rear", paintOrder: 41 },
  { id: "head-shell", boneId: "head", layer: "rear", paintOrder: 42 },
  { id: "face-screen", boneId: "head", layer: "rear", paintOrder: 43 },
  { id: "face-screen-highlight", boneId: "head", layer: "rear", paintOrder: 44 },
  { id: "face-eyes", boneId: "head", layer: "rear", paintOrder: 45 },
  { id: "face-smile", boneId: "head", layer: "rear", paintOrder: 46 },
  { id: "face-cheeks", boneId: "head", layer: "rear", paintOrder: 47 },
  { id: "head-shell-highlight", boneId: "head", layer: "rear", paintOrder: 48 },
  { id: "antenna-stem", boneId: "antenna", layer: "rear", paintOrder: 50 },
  { id: "antenna-light", boneId: "antenna", layer: "rear", paintOrder: 51 },
  { id: "antenna-highlight", boneId: "antenna", layer: "rear", paintOrder: 52 },
];

export function getMascotPartsForPass(pass: MascotRenderPass) {
  if (pass === "all") {
    return MASCOT_SKIN_PARTS;
  }
  return MASCOT_SKIN_PARTS.filter((part) => part.layer === pass);
}

export function validateMascotModel() {
  const errors: string[] = [];
  const boneIds = new Set<MascotBoneId>();
  const partIds = new Set<MascotSkinPartId>();

  for (const bone of MASCOT_BONES) {
    if (boneIds.has(bone.id)) {
      errors.push(`duplicate bone: ${bone.id}`);
    }
    if (bone.parentId !== null && !boneIds.has(bone.parentId)) {
      errors.push(`invalid parent for ${bone.id}: ${bone.parentId}`);
    }
    boneIds.add(bone.id);
  }

  for (const part of MASCOT_SKIN_PARTS) {
    if (partIds.has(part.id)) {
      errors.push(`duplicate part: ${part.id}`);
    }
    if (!boneIds.has(part.boneId)) {
      errors.push(`invalid bone for ${part.id}: ${part.boneId}`);
    }
    partIds.add(part.id);
  }

  return errors;
}
