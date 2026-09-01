import { useEffect, useState, type Ref } from "react";

import styles from "./AiChatDrawer.module.css";

type IdleMotion = "rest" | "blink" | "tilt" | "float" | "antenna";

const IDLE_MOTIONS: Exclude<IdleMotion, "rest">[] = [
  "blink",
  "tilt",
  "float",
  "antenna",
];
const MIN_IDLE_DELAY_MS = 6_000;
const IDLE_DELAY_RANGE_MS = 8_000;
const IDLE_MOTION_DURATION_MS = 900;

type AiMascotTriggerProps = {
  onOpen: () => void;
  buttonRef?: Ref<HTMLButtonElement>;
};

function prefersReducedMotion() {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function AiMascotTrigger({ onOpen, buttonRef }: AiMascotTriggerProps) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [idleMotion, setIdleMotion] = useState<IdleMotion>("rest");
  const [reducedMotion] = useState(prefersReducedMotion);
  const engaged = hovered || focused;

  useEffect(() => {
    let timerId: ReturnType<typeof setTimeout> | undefined;

    if (reducedMotion || engaged) {
      setIdleMotion("rest");
      return undefined;
    }

    const scheduleNextMotion = () => {
      const delay = MIN_IDLE_DELAY_MS + Math.random() * IDLE_DELAY_RANGE_MS;
      timerId = setTimeout(() => {
        const motionIndex = Math.floor(Math.random() * IDLE_MOTIONS.length);
        setIdleMotion(IDLE_MOTIONS[motionIndex] ?? "blink");
        timerId = setTimeout(() => {
          setIdleMotion("rest");
          scheduleNextMotion();
        }, IDLE_MOTION_DURATION_MS);
      }, delay);
    };

    scheduleNextMotion();
    return () => {
      if (timerId !== undefined) {
        clearTimeout(timerId);
      }
    };
  }, [engaged, reducedMotion]);

  return (
    <button
      aria-label="打开 AI 助手"
      className={styles.mascotTrigger}
      data-engaged={String(engaged)}
      data-idle-motion={idleMotion}
      ref={buttonRef}
      type="button"
      onBlur={() => setFocused(false)}
      onClick={onOpen}
      onFocus={() => setFocused(true)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <span aria-hidden="true" className={styles.speechBubble}>
        点我进入AI功能
      </span>
      <span aria-hidden="true" className={styles.mascotStage}>
        <svg
          className={styles.mascotSvg}
          viewBox="0 0 108 140"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <linearGradient id="ai-mascot-shell" x1="18" x2="87" y1="18" y2="118">
              <stop offset="0" stopColor="#ffffff" />
              <stop offset="1" stopColor="#dceeff" />
            </linearGradient>
            <linearGradient id="ai-mascot-blue" x1="25" x2="82" y1="32" y2="112">
              <stop offset="0" stopColor="#54b8ff" />
              <stop offset="1" stopColor="#1261b8" />
            </linearGradient>
            <filter id="ai-mascot-shadow" x="-30%" y="-30%" width="160%" height="180%">
              <feDropShadow dx="0" dy="5" floodColor="#164f86" floodOpacity="0.23" stdDeviation="4" />
            </filter>
          </defs>

          <g className={styles.mascotRobot} filter="url(#ai-mascot-shadow)">
            <g className={styles.mascotAntenna}>
              <path d="M55 27V15" fill="none" stroke="#246fae" strokeLinecap="round" strokeWidth="4" />
              <circle className={styles.mascotAntennaLight} cx="55" cy="10" fill="#62d9ff" r="6" />
              <circle cx="53" cy="8" fill="#dff9ff" r="2" />
            </g>

            <g className={styles.mascotHead}>
              <rect x="19" y="26" width="73" height="62" rx="28" fill="url(#ai-mascot-shell)" stroke="#1c639e" strokeWidth="3" />
              <path d="M27 56c1-14 12-23 28-23s27 9 29 23v9c-1 11-12 17-29 17S28 76 27 65z" fill="#124f89" />
              <path d="M31 55c2-10 11-17 24-17 12 0 21 6 24 15" fill="none" opacity="0.28" stroke="#65d5ff" strokeLinecap="round" strokeWidth="3" />
              <g className={styles.mascotEyes} fill="#9eeeff">
                <ellipse cx="43" cy="59" rx="4" ry="6" />
                <ellipse cx="68" cy="59" rx="4" ry="6" />
              </g>
              <path d="M49 70c4 3 9 3 13 0" fill="none" stroke="#9eeeff" strokeLinecap="round" strokeWidth="2.5" />
              <circle cx="29" cy="69" fill="#ff9fba" opacity="0.78" r="3" />
              <circle cx="81" cy="69" fill="#ff9fba" opacity="0.78" r="3" />
              <path d="M24 46c6-10 16-16 29-17" fill="none" opacity="0.88" stroke="#fff" strokeLinecap="round" strokeWidth="4" />
            </g>

            <g className={styles.mascotBody}>
              <path d="M32 85c5-6 41-6 46 0l5 34c1 9-8 14-28 14s-29-5-28-14z" fill="url(#ai-mascot-blue)" stroke="#14558f" strokeWidth="3" />
              <rect x="42" y="94" width="27" height="22" rx="10" fill="#eaf7ff" opacity="0.96" />
              <path d="M49 105h13" fill="none" stroke="#2689ce" strokeLinecap="round" strokeWidth="3" />
              <circle cx="55.5" cy="99" fill="#63d8ff" r="3" />
            </g>

            <g className={styles.mascotGripArm}>
              <path d="M80 91c10 2 13 9 12 18" fill="none" stroke="#1c609b" strokeLinecap="round" strokeWidth="10" />
              <path d="M91 105h12" fill="none" stroke="#e7f5ff" strokeLinecap="round" strokeWidth="9" />
              <path d="M101 100v13" fill="none" stroke="#1a5a94" strokeLinecap="round" strokeWidth="3" />
            </g>

            <g className={styles.mascotWaveArm}>
              <path d="M30 91c-10 3-12 12-10 20" fill="none" stroke="#1c609b" strokeLinecap="round" strokeWidth="10" />
              <circle cx="20" cy="112" fill="#e7f5ff" stroke="#1a5a94" strokeWidth="3" r="7" />
              <path d="M16 108l-3-6M20 106l-1-7M24 108l2-6" fill="none" stroke="#1a5a94" strokeLinecap="round" strokeWidth="2" />
            </g>
          </g>
          <path className={styles.mascotEdgeHint} d="M103 25v102" fill="none" stroke="#1b5b93" strokeLinecap="round" strokeWidth="4" />
        </svg>
      </span>
    </button>
  );
}
