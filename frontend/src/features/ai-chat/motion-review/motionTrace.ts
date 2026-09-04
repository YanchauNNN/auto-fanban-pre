export type Point = { x: number; y: number };

export type MotionFrame = {
  timeMs: number;
  phase: string;
  actorScale: number;
  drawer: { left: number; top: number; width: number; height: number };
  landmarks: Record<string, Point>;
};

export type MotionTrace = {
  schemaVersion: 1;
  source: "browser-capture" | "synthetic";
  viewport: { width: number; height: number };
  frames: MotionFrame[];
};

type Connection = { id: string; from: string; to: string };

export type MotionReviewPolicy = {
  sampleGapMs: number;
  minimumDurationMs: number;
  viewportMarginPx: number;
  connectionGapPx: number;
  contactErrorPx: number;
  boneLengthRelativeError: number;
  speedPxPerSecond: number;
  accelerationPxPerSecondSquared: number;
  trackedLandmarks: string[];
  requiredPhases: string[];
  bones: (Connection & { length: number })[];
  connections: Connection[];
  contacts: { id: string; landmark: string; phases: string[]; offset: Point }[];
};
