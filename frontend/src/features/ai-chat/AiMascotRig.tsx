import { useId, type ReactNode } from "react";

import {
  MASCOT_BONES,
  MASCOT_SKIN_PARTS,
  MASCOT_VIEW_BOX,
  getMascotPartsForPass,
  type MascotBoneId,
  type MascotRenderPass,
  type MascotSkinPartId,
} from "./mascotModel";
import {
  formatMascotBoneTransform,
  resolveMascotPose,
  type MascotPose,
  type MascotPoseName,
} from "./mascotPoses";

type AiMascotRigProps = {
  className?: string;
  pass: MascotRenderPass;
  pose: MascotPose | MascotPoseName;
};

type PaintIds = {
  bodyGradientId: string;
  shellGradientId: string;
  shadowId: string;
};

export function AiMascotRig({ className, pass, pose }: AiMascotRigProps) {
  const instanceId = useId().replace(/:/g, "");
  const paintIds: PaintIds = {
    shellGradientId: `ai-mascot-shell-${instanceId}`,
    bodyGradientId: `ai-mascot-body-${instanceId}`,
    shadowId: `ai-mascot-shadow-${instanceId}`,
  };
  const resolvedPose = typeof pose === "string" ? resolveMascotPose(pose) : pose;
  const visiblePartIds = new Set(getMascotPartsForPass(pass).map((part) => part.id));

  return (
    <svg
      aria-hidden="true"
      className={className}
      data-mascot-rig="true"
      data-render-pass={pass}
      preserveAspectRatio="xMidYMid meet"
      viewBox={MASCOT_VIEW_BOX}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id={paintIds.shellGradientId} x1="24" x2="91" y1="21" y2="88">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="0.58" stopColor="#edf7ff" />
          <stop offset="1" stopColor="#cfe7fb" />
        </linearGradient>
        <linearGradient id={paintIds.bodyGradientId} x1="36" x2="80" y1="79" y2="139">
          <stop offset="0" stopColor="#55c5f5" />
          <stop offset="0.52" stopColor="#2d91d4" />
          <stop offset="1" stopColor="#1766b0" />
        </linearGradient>
        <filter id={paintIds.shadowId} x="-35%" y="-35%" width="170%" height="190%">
          <feDropShadow
            dx="0"
            dy="4"
            floodColor="#164f86"
            floodOpacity="0.24"
            stdDeviation="3.4"
          />
        </filter>
      </defs>

      <g data-mascot-motion-root>
        {renderBone("root", resolvedPose, visiblePartIds, paintIds, pass)}
      </g>
    </svg>
  );
}

function renderBone(
  boneId: MascotBoneId,
  pose: MascotPose,
  visiblePartIds: ReadonlySet<MascotSkinPartId>,
  paintIds: PaintIds,
  pass: MascotRenderPass,
): ReactNode {
  const bone = MASCOT_BONES.find((candidate) => candidate.id === boneId);
  if (!bone) {
    return null;
  }
  const children = MASCOT_BONES.filter((candidate) => candidate.parentId === boneId);
  const parts = MASCOT_SKIN_PARTS.filter(
    (part) => part.boneId === boneId && visiblePartIds.has(part.id),
  );
  const transform = [
    `translate(${bone.origin.x} ${bone.origin.y})`,
    formatMascotBoneTransform(pose[boneId]),
  ].join(" ");
  const cssTransform = [
    `translate(${bone.origin.x}px, ${bone.origin.y}px)`,
    `translate(${pose[boneId].x}px, ${pose[boneId].y}px)`,
    `rotate(${pose[boneId].rotate}deg)`,
    `scale(${pose[boneId].scaleX}, ${pose[boneId].scaleY})`,
  ].join(" ");

  return (
    <g
      data-bone={boneId}
      filter={boneId === "root" && pass !== "front" ? `url(#${paintIds.shadowId})` : undefined}
      key={boneId}
      style={{ transform: cssTransform }}
      transform={transform}
    >
      {parts.map((part) => (
        <g data-skin-slot={part.id} key={part.id}>
          {renderSkinPart(part.id, paintIds)}
        </g>
      ))}
      {children.map((child) =>
        renderBone(child.id, pose, visiblePartIds, paintIds, pass),
      )}
    </g>
  );
}

function renderSkinPart(partId: MascotSkinPartId, paintIds: PaintIds): ReactNode {
  const marker = { "data-skin-part": partId } as const;
  const bodyFill = `url(#${paintIds.bodyGradientId})`;
  const shellFill = `url(#${paintIds.shellGradientId})`;

  switch (partId) {
    case "torso-shell":
      return (
        <path
          {...marker}
          d="M-25 2C-20-5 20-5 25 2L28 39C29 51 19 58 0 58S-29 51-28 39Z"
          fill={bodyFill}
          stroke="#155a96"
          strokeLinejoin="round"
          strokeWidth="3"
        />
      );
    case "torso-highlight":
      return (
        <path
          {...marker}
          d="M-19 7C-10 2 10 2 19 7"
          fill="none"
          opacity="0.52"
          stroke="#a8eeff"
          strokeLinecap="round"
          strokeWidth="2.2"
        />
      );
    case "torso-panel":
      return (
        <rect
          {...marker}
          fill="#edf9ff"
          height="24"
          rx="10"
          stroke="#b9def3"
          strokeWidth="1.6"
          width="28"
          x="-14"
          y="14"
        />
      );
    case "torso-indicator":
      return <circle {...marker} cx="0" cy="20" fill="#55d7ff" r="3.2" />;
    case "torso-detail":
      return (
        <g {...marker} fill="none" stroke="#155a96" strokeLinecap="round">
          <path d="M-6.5 29h13" stroke="#258bcf" strokeWidth="3" />
          <path d="M-16 55v3M16 55v3" strokeWidth="5" />
        </g>
      );
    case "left-upper-arm-shell":
    case "right-upper-arm-shell":
      return (
        <g {...marker}>
          <circle data-joint={partId.startsWith("left") ? "left-shoulder" : "right-shoulder"} cx="0" cy="0" fill="#247fbe" r="8.4" stroke="#155a96" strokeWidth="2.6" />
          <path
            d="M-7.2-4.5C-8 6-7.2 17-5.6 25.5C-3 29.2 3 29.2 5.6 25.5C7.2 17 8 6 7.2-4.5Z"
            fill={bodyFill}
            stroke="#155a96"
            strokeLinejoin="round"
            strokeWidth="2.6"
          />
          <path d="M-3-1C-3 8-2.6 14-1.8 19" fill="none" opacity="0.48" stroke="#a3eaff" strokeLinecap="round" strokeWidth="1.6" />
        </g>
      );
    case "left-forearm-shell":
    case "right-forearm-shell":
      return (
        <g {...marker}>
          <circle data-joint={partId.startsWith("left") ? "left-elbow" : "right-elbow"} cx="0" cy="0" fill="#3da7df" r="7.6" stroke="#155a96" strokeWidth="2.4" />
          <path
            d="M-6.4-4C-7 5.5-6.3 15-4.7 22.5C-2.4 26 2.4 26 4.7 22.5C6.3 15 7 5.5 6.4-4Z"
            fill={bodyFill}
            stroke="#155a96"
            strokeLinejoin="round"
            strokeWidth="2.4"
          />
        </g>
      );
    case "left-hand-shell":
    case "right-hand-shell":
      return (
        <circle
          {...marker}
          cx="0"
          cy="0"
          data-joint={partId.startsWith("left") ? "left-wrist" : "right-wrist"}
          fill={shellFill}
          r="8.6"
          stroke="#155a96"
          strokeWidth="2.5"
        />
      );
    case "left-finger-pad":
    case "right-finger-pad":
      return (
        <g {...marker}>
          <path
            d="M-5.8-4.8C-2.8-7.2 2.5-7.1 5.7-4.1C7.5-2.2 7.3 2.7 5 4.9C2 7-2.9 6.6-5.7 3.7Z"
            fill="#f8fdff"
            stroke="#155a96"
            strokeLinejoin="round"
            strokeWidth="1.8"
          />
          <path d="M-2.5-3v5.3M1-3.5v5.7M4-2.4v4.3" fill="none" stroke="#63b8e8" strokeLinecap="round" strokeWidth="1.35" />
        </g>
      );
    case "head-left-ear":
      return <circle {...marker} cx="-39" cy="-27" fill="#2c8ecb" r="7.2" stroke="#155a96" strokeWidth="2.4" />;
    case "head-right-ear":
      return <circle {...marker} cx="39" cy="-27" fill="#2c8ecb" r="7.2" stroke="#155a96" strokeWidth="2.4" />;
    case "head-shell":
      return (
        <rect
          {...marker}
          fill={shellFill}
          height="64"
          rx="29"
          stroke="#155a96"
          strokeWidth="3"
          width="76"
          x="-38"
          y="-58"
        />
      );
    case "face-screen":
      return <path {...marker} d="M-30-29C-29-45-17-52 0-52S29-45 30-29v10C28-7 17-1 0-1s-28-6-30-18Z" fill="#124f82" />;
    case "face-screen-highlight":
      return <path {...marker} d="M-24-31C-20-42-11-47 1-47c11 0 20 4 24 13" fill="none" opacity="0.3" stroke="#68dfff" strokeLinecap="round" strokeWidth="3" />;
    case "face-eyes":
      return (
        <g {...marker} data-expression-part="eyes" fill="#a5f1ff">
          <ellipse cx="-12.5" cy="-25" rx="4" ry="5.7" />
          <ellipse cx="12.5" cy="-25" rx="4" ry="5.7" />
        </g>
      );
    case "face-smile":
      return <path {...marker} d="M-6-13C-2-9 2-9 6-13" fill="none" stroke="#a5f1ff" strokeLinecap="round" strokeWidth="2.6" />;
    case "face-cheeks":
      return (
        <g {...marker} fill="#ff9fba" opacity="0.82">
          <circle cx="-25" cy="-14" r="3" />
          <circle cx="25" cy="-14" r="3" />
        </g>
      );
    case "head-shell-highlight":
      return <path {...marker} d="M-31-40C-23-51-11-54 1-54" fill="none" opacity="0.9" stroke="#fff" strokeLinecap="round" strokeWidth="3.8" />;
    case "antenna-stem":
      return <path {...marker} d="M0-57V-68" fill="none" stroke="#246fae" strokeLinecap="round" strokeWidth="3.8" />;
    case "antenna-light":
      return <circle {...marker} data-expression-part="antenna-light" cx="0" cy="-72" fill="#5bdcff" r="5.6" />;
    case "antenna-highlight":
      return <circle {...marker} cx="-1.8" cy="-73.8" fill="#e8fcff" r="1.8" />;
  }
}
