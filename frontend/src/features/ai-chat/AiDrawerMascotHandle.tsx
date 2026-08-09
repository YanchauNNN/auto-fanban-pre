import {
  useState,
  type KeyboardEventHandler,
  type PointerEventHandler,
} from "react";

import styles from "./AiChatDrawer.module.css";

type AiDrawerMascotHandleProps = {
  onHide: () => void;
  onResizeKeyDown: KeyboardEventHandler<HTMLButtonElement>;
  onResizePointerDown: PointerEventHandler<HTMLButtonElement>;
};

export function AiDrawerMascotHandle({
  onHide,
  onResizeKeyDown,
  onResizePointerDown,
}: AiDrawerMascotHandleProps) {
  const [hovered, setHovered] = useState(false);
  const [pressed, setPressed] = useState(false);
  const interaction = pressed ? "pressed" : hovered ? "hover" : "rest";

  return (
    <button
      aria-label="隐藏或调整 AI 助手窗口"
      className={styles.drawerMascotHandle}
      data-interaction={interaction}
      type="button"
      onClick={onHide}
      onKeyDown={onResizeKeyDown}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onPointerCancel={() => setPressed(false)}
      onPointerDown={(event) => {
        setPressed(true);
        event.currentTarget.setPointerCapture?.(event.pointerId);
        onResizePointerDown(event);
      }}
      onPointerUp={(event) => {
        setPressed(false);
        if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
          event.currentTarget.releasePointerCapture?.(event.pointerId);
        }
      }}
    >
      <span aria-hidden="true" className={styles.drawerMascotBubble}>
        {pressed ? "按住我拖动，调整窗口大小" : "点我隐藏窗口"}
      </span>
      <svg
        aria-hidden="true"
        className={styles.drawerMascotSvg}
        viewBox="0 0 112 82"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <linearGradient id="ai-drawer-mascot-shell" x1="24" x2="88" y1="10" y2="72">
            <stop offset="0" stopColor="#ffffff" />
            <stop offset="1" stopColor="#dceeff" />
          </linearGradient>
          <filter id="ai-drawer-mascot-shadow" x="-30%" y="-35%" width="160%" height="190%">
            <feDropShadow
              dx="0"
              dy="3"
              floodColor="#164f86"
              floodOpacity="0.2"
              stdDeviation="3"
            />
          </filter>
        </defs>

        <g className={styles.drawerMascotCharacter} filter="url(#ai-drawer-mascot-shadow)">
          <g className={styles.drawerMascotAntenna}>
            <path d="M56 17V8" fill="none" stroke="#246fae" strokeLinecap="round" strokeWidth="3.5" />
            <circle cx="56" cy="5" fill="#62d9ff" r="4.5" />
            <circle cx="54.5" cy="3.7" fill="#e6fbff" r="1.5" />
          </g>

          <g className={styles.drawerMascotHead}>
            <rect
              fill="url(#ai-drawer-mascot-shell)"
              height="55"
              rx="25"
              stroke="#1c639e"
              strokeWidth="3"
              width="70"
              x="21"
              y="17"
            />
            <path
              d="M28 43c2-13 12-20 28-20s26 7 28 20v9c-2 10-12 15-28 15S30 62 28 52z"
              fill="#124f89"
            />
            <path
              d="M33 41c4-8 12-13 23-13s19 4 23 11"
              fill="none"
              opacity="0.3"
              stroke="#65d5ff"
              strokeLinecap="round"
              strokeWidth="3"
            />
            <g className={styles.drawerMascotEyes} fill="#9eeeff">
              <ellipse cx="44" cy="47" rx="3.8" ry="5.3" />
              <ellipse cx="68" cy="47" rx="3.8" ry="5.3" />
            </g>
            <path d="M50 57c4 3 8 3 12 0" fill="none" stroke="#9eeeff" strokeLinecap="round" strokeWidth="2.4" />
            <circle cx="33" cy="56" fill="#ff9fba" opacity="0.78" r="2.8" />
            <circle cx="79" cy="56" fill="#ff9fba" opacity="0.78" r="2.8" />
          </g>

          <g className={styles.drawerMascotHands}>
            <path d="M8 70h96" fill="none" stroke="#1b5b93" strokeLinecap="round" strokeWidth="3" />
            <circle cx="25" cy="70" fill="#eef8ff" stroke="#1a5a94" strokeWidth="3" r="8" />
            <circle cx="87" cy="70" fill="#eef8ff" stroke="#1a5a94" strokeWidth="3" r="8" />
            <path d="M20 68v7M25 67v8M30 68v7M82 68v7M87 67v8M92 68v7" fill="none" stroke="#58a8df" strokeLinecap="round" strokeWidth="1.8" />
          </g>
        </g>
      </svg>
    </button>
  );
}
