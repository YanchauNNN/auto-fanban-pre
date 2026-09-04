import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type KeyboardEventHandler,
  type PointerEvent as ReactPointerEvent,
  type PointerEventHandler,
  type Ref,
} from "react";

import { AiMascotRig } from "./AiMascotRig";
import styles from "./AiChatDrawer.module.css";
import type { MascotPoseName } from "./mascotPoses";

const REACH_DURATION_MS = 90;
export const MASCOT_DRAWER_MOTION_MS = 420;
const RELEASE_START_MS = 330;
const MASCOT_TOP_KEY = "fanban.ai.mascotTop";
const MASCOT_EDGE_MARGIN_PX = 12;
const MASCOT_FALLBACK_HEIGHT_PX = 128;
const MASCOT_DRAG_THRESHOLD_PX = 6;
const MASCOT_KEYBOARD_STEP_PX = 24;
const MIN_IDLE_DELAY_MS = 6_000;
const IDLE_DELAY_RANGE_MS = 8_000;
const IDLE_MOTION_DURATION_MS = 900;

type IdleMotion = "rest" | "blink" | "sway" | "float" | "antenna";

const IDLE_MOTIONS: Exclude<IdleMotion, "rest">[] = [
  "blink",
  "sway",
  "float",
  "antenna",
];

type MascotDrag = {
  dragged: boolean;
  pointerId: number;
  startTop: number;
  startY: number;
};

type DrawerSize = {
  height: number;
  width: number;
};

type AiMascotActorProps = {
  buttonRef?: Ref<HTMLButtonElement>;
  drawerOpen: boolean;
  drawerSize: DrawerSize;
  drawerVisible: boolean;
  onHide: () => void;
  onOpen: () => void;
  onResizeKeyDown: KeyboardEventHandler<HTMLButtonElement>;
  onResizePointerDown: PointerEventHandler<HTMLButtonElement>;
  suppressRestoredFocusVisual?: boolean;
};

function prefersReducedMotion() {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function isSplitPassPhase(phase: MascotPoseName) {
  return ["opening_ride", "open_cling", "closing_ride"].includes(phase);
}

export function AiMascotActor({
  buttonRef,
  drawerOpen,
  drawerSize,
  drawerVisible,
  onHide,
  onOpen,
  onResizeKeyDown,
  onResizePointerDown,
  suppressRestoredFocusVisual = false,
}: AiMascotActorProps) {
  const [reducedMotion] = useState(prefersReducedMotion);
  const [hovered, setHovered] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [idleMotion, setIdleMotion] = useState<IdleMotion>("rest");
  const [suppressFocusVisual, setSuppressFocusVisual] = useState(
    suppressRestoredFocusVisual,
  );
  const [top, setTop] = useState(loadMascotTop);
  const [phase, setPhase] = useState<MascotPoseName>(() =>
    drawerOpen ? "open_cling" : "closed_idle",
  );
  const initialRenderRef = useRef(true);
  const timersRef = useRef<number[]>([]);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const topRef = useRef(top);
  const dragRef = useRef<MascotDrag | null>(null);
  const suppressClickRef = useRef(false);
  const suppressClickTimerRef = useRef<number | null>(null);
  const splitPass = isSplitPassPhase(phase);
  const engaged = hovered && !drawerVisible && !suppressFocusVisual;
  const buttonLabel = drawerVisible
    ? "隐藏或调整 AI 助手窗口"
    : "打开 AI 助手";
  const sharedStyle = {
    "--ai-drawer-height": `${drawerSize.height}px`,
    "--ai-drawer-width": `${drawerSize.width}px`,
    "--ai-mascot-top": `${top}px`,
  } as CSSProperties;
  topRef.current = top;

  const clampToViewport = useCallback((candidate: number) => {
    const triggerHeight =
      triggerRef.current?.getBoundingClientRect().height || MASCOT_FALLBACK_HEIGHT_PX;
    return clampMascotTop(candidate, window.innerHeight, triggerHeight);
  }, []);

  const setButtonRef = useCallback(
    (node: HTMLButtonElement | null) => {
      triggerRef.current = node;
      assignRef(buttonRef, node);
    },
    [buttonRef],
  );

  useEffect(() => {
    if (suppressRestoredFocusVisual) {
      setSuppressFocusVisual(true);
    }
  }, [suppressRestoredFocusVisual]);

  useEffect(() => {
    const keepMascotInViewport = () => {
      const current = topRef.current;
      const next = clampToViewport(current);
      if (next !== current) {
        topRef.current = next;
        setTop(next);
      }
    };
    keepMascotInViewport();
    window.addEventListener("resize", keepMascotInViewport);
    return () => window.removeEventListener("resize", keepMascotInViewport);
  }, [clampToViewport]);

  useEffect(() => {
    try {
      window.localStorage.setItem(MASCOT_TOP_KEY, String(Math.round(top)));
    } catch {
      // Browser storage restrictions should not disable the actor.
    }
  }, [top]);

  useEffect(() => {
    let timerId: ReturnType<typeof setTimeout> | undefined;

    if (reducedMotion || drawerVisible || engaged) {
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
  }, [drawerVisible, engaged, reducedMotion]);

  useEffect(() => {
    if (initialRenderRef.current) {
      initialRenderRef.current = false;
      return undefined;
    }

    for (const timerId of timersRef.current) {
      window.clearTimeout(timerId);
    }
    timersRef.current = [];

    if (reducedMotion) {
      setPhase(drawerOpen ? "open_cling" : "closed_idle");
      return undefined;
    }

    if (drawerOpen) {
      setPhase("opening_reach");
      timersRef.current = [
        window.setTimeout(() => setPhase("opening_ride"), REACH_DURATION_MS),
        window.setTimeout(() => setPhase("open_cling"), MASCOT_DRAWER_MOTION_MS),
      ];
    } else if (drawerVisible) {
      setPhase("closing_ride");
      timersRef.current = [
        window.setTimeout(() => setPhase("closing_release"), RELEASE_START_MS),
        window.setTimeout(() => setPhase("closed_idle"), MASCOT_DRAWER_MOTION_MS),
      ];
    } else {
      setPhase("closed_idle");
    }

    return () => {
      for (const timerId of timersRef.current) {
        window.clearTimeout(timerId);
      }
      timersRef.current = [];
    };
  }, [drawerOpen, drawerVisible, reducedMotion]);

  useEffect(
    () => () => {
      if (suppressClickTimerRef.current !== null) {
        window.clearTimeout(suppressClickTimerRef.current);
      }
    },
    [],
  );

  function handleClosedPointerDown(event: ReactPointerEvent<HTMLButtonElement>) {
    if (event.pointerType === "mouse" && event.button !== 0) {
      return;
    }
    if (suppressClickTimerRef.current !== null) {
      window.clearTimeout(suppressClickTimerRef.current);
      suppressClickTimerRef.current = null;
    }
    suppressClickRef.current = false;
    dragRef.current = {
      dragged: false,
      pointerId: event.pointerId,
      startTop: topRef.current,
      startY: event.clientY,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function handleClosedPointerMove(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    const deltaY = event.clientY - drag.startY;
    if (!drag.dragged && Math.abs(deltaY) < MASCOT_DRAG_THRESHOLD_PX) {
      return;
    }
    drag.dragged = true;
    suppressClickRef.current = true;
    setDragging(true);
    setTop(clampToViewport(drag.startTop + deltaY));
    event.preventDefault();
  }

  function finishClosedPointerInteraction(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    dragRef.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture?.(event.pointerId);
    }
    if (drag.dragged) {
      suppressClickTimerRef.current = window.setTimeout(() => {
        suppressClickRef.current = false;
        suppressClickTimerRef.current = null;
      });
    }
  }

  function handleClick() {
    if (!drawerVisible && suppressClickRef.current) {
      suppressClickRef.current = false;
      if (suppressClickTimerRef.current !== null) {
        window.clearTimeout(suppressClickTimerRef.current);
        suppressClickTimerRef.current = null;
      }
      return;
    }
    if (drawerVisible) {
      onHide();
    } else {
      onOpen();
    }
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLButtonElement>) {
    setSuppressFocusVisual(false);
    if (drawerVisible) {
      onResizeKeyDown(event);
      return;
    }
    const step = event.shiftKey ? MASCOT_KEYBOARD_STEP_PX * 2 : MASCOT_KEYBOARD_STEP_PX;
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      const direction = event.key === "ArrowUp" ? -1 : 1;
      setTop((current) => clampToViewport(current + direction * step));
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      setTop(clampToViewport(event.key === "Home" ? MASCOT_EDGE_MARGIN_PX : Infinity));
    }
  }

  return (
    <>
      <span
        aria-hidden="true"
        className={`${styles.mascotActorLayer} ${styles.mascotActorAll}`}
        data-active={String(!splitPass)}
        data-engaged={String(engaged)}
        data-mascot-phase={phase}
        data-idle-motion={idleMotion}
        data-testid="mascot-pass-all"
        style={sharedStyle}
      >
        <AiMascotRig className={styles.mascotActorSvg} pass="all" pose={phase} />
      </span>
      <span
        aria-hidden="true"
        className={`${styles.mascotActorLayer} ${styles.mascotActorRear}`}
        data-active={String(splitPass)}
        data-engaged={String(engaged)}
        data-mascot-phase={phase}
        data-idle-motion={idleMotion}
        data-testid="mascot-pass-rear"
        style={sharedStyle}
      >
        <AiMascotRig className={styles.mascotActorSvg} pass="rear" pose={phase} />
      </span>
      <span
        aria-hidden="true"
        className={`${styles.mascotActorLayer} ${styles.mascotActorFront}`}
        data-active={String(splitPass)}
        data-engaged={String(engaged)}
        data-mascot-phase={phase}
        data-idle-motion={idleMotion}
        data-testid="mascot-pass-front"
        style={sharedStyle}
      >
        <AiMascotRig className={styles.mascotActorSvg} pass="front" pose={phase} />
      </span>
      <button
        aria-label={buttonLabel}
        className={styles.mascotActorButton}
        data-dragging={String(dragging)}
        data-engaged={String(engaged)}
        data-idle-motion={idleMotion}
        data-mascot-phase={phase}
        data-suppress-focus-visual={String(suppressFocusVisual)}
        ref={setButtonRef}
        style={sharedStyle}
        type="button"
        onBlur={() => setSuppressFocusVisual(false)}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onPointerCancel={
          drawerVisible ? undefined : finishClosedPointerInteraction
        }
        onPointerDown={
          drawerVisible ? onResizePointerDown : handleClosedPointerDown
        }
        onPointerMove={drawerVisible ? undefined : handleClosedPointerMove}
        onPointerUp={drawerVisible ? undefined : finishClosedPointerInteraction}
      >
        <span aria-hidden="true" className={styles.mascotActorBubble}>
          {drawerVisible ? "点我隐藏窗口" : "点我进入AI功能"}
        </span>
      </button>
    </>
  );
}

function loadMascotTop() {
  if (typeof window === "undefined") {
    return 0;
  }
  const defaultTop = Math.min(window.innerHeight * 0.48, 520);
  try {
    const stored = Number(window.localStorage.getItem(MASCOT_TOP_KEY));
    if (Number.isFinite(stored) && window.localStorage.getItem(MASCOT_TOP_KEY) !== null) {
      return stored;
    }
  } catch {
    // Browser storage restrictions should not disable the actor.
  }
  return defaultTop;
}

function clampMascotTop(candidate: number, viewportHeight: number, triggerHeight: number) {
  const maximumTop = Math.max(
    MASCOT_EDGE_MARGIN_PX,
    viewportHeight - triggerHeight - MASCOT_EDGE_MARGIN_PX,
  );
  return Math.min(Math.max(candidate, MASCOT_EDGE_MARGIN_PX), maximumTop);
}

function assignRef<T>(ref: Ref<T> | undefined, value: T | null) {
  if (typeof ref === "function") {
    ref(value);
  } else if (ref) {
    (ref as { current: T | null }).current = value;
  }
}
