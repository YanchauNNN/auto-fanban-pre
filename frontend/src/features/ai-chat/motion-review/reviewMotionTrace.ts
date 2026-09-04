import type {
  MotionReviewPolicy,
  MotionTrace,
  MotionFrame,
  Point,
} from "./motionTrace";

export type { MotionReviewPolicy, MotionTrace } from "./motionTrace";

type IssueCode = "invalid-policy" | "invalid-trace" | "sample-gap" | "sample-order"
  | "short-capture" | "missing-phase" | "contact-drift" | "connection-gap"
  | "bone-length" | "speed" | "acceleration" | "viewport" | "non-finite-measurement";

export type MotionIssue = {
  code: IssueCode;
  frame?: number;
  timeMs?: number;
  subject?: string;
  measured?: number;
  limit?: number;
};

export type MotionReviewReport = {
  status: "invalid" | "violations" | "within-geometric-limits";
  source: "browser-capture" | "synthetic" | "unknown";
  visualReviewRequired: true;
  frameCount: number;
  durationMs: number;
  issues: MotionIssue[];
};

const distance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);

function velocity(from: MotionFrame, to: MotionFrame, landmark: string): Point {
  const seconds = (to.timeMs - from.timeMs) / 1000;
  return {
    x: (to.landmarks[landmark].x - from.landmarks[landmark].x) / seconds,
    y: (to.landmarks[landmark].y - from.landmarks[landmark].y) / seconds,
  };
}

export function reviewMotionTrace(input: unknown, rules: unknown): MotionReviewReport {
  const report: MotionReviewReport = {
    status: "invalid",
    source: "unknown",
    visualReviewRequired: true,
    frameCount: 0,
    durationMs: 0,
    issues: [],
  };
  if (!isMotionReviewPolicy(rules)) {
    report.issues.push({ code: "invalid-policy" });
    return report;
  }
  if (!isMotionTrace(input, rules.trackedLandmarks)) {
    report.issues.push({ code: "invalid-trace" });
    return report;
  }
  const { frames, viewport } = input;
  report.source = input.source;
  report.frameCount = frames.length;
  report.durationMs = frames[frames.length - 1].timeMs - frames[0].timeMs;

  for (let index = 1; index < frames.length; index++) {
    const gap = frames[index].timeMs - frames[index - 1].timeMs;
    if (gap <= 0 || gap > rules.sampleGapMs) {
      report.issues.push({
        code: gap <= 0 ? "sample-order" : "sample-gap",
        frame: index,
        timeMs: frames[index].timeMs,
        measured: gap,
        limit: rules.sampleGapMs,
      });
    }
  }
  if (report.durationMs < rules.minimumDurationMs) {
    report.issues.push({ code: "short-capture", measured: report.durationMs, limit: rules.minimumDurationMs });
  }
  const capturedPhases = new Set(frames.map((frame) => frame.phase));
  for (const phase of rules.requiredPhases) {
    if (!capturedPhases.has(phase)) {
      report.issues.push({ code: "missing-phase", subject: phase });
    }
  }
  // Sparse, incomplete or unordered samples cannot establish continuous motion.
  if (report.issues.length > 0) {
    return report;
  }

  frames.forEach((frame, index) => {
    const check = (code: IssueCode, subject: string, measured: number, limit: number) => {
      if (!Number.isFinite(measured)) {
        report.issues.push({ code: "non-finite-measurement", frame: index, timeMs: frame.timeMs, subject });
        return;
      }
      if (measured > limit) {
        report.issues.push({ code, frame: index, timeMs: frame.timeMs, subject, measured, limit });
      }
    };
    for (const connection of rules.connections) {
      check("connection-gap", connection.id,
        distance(frame.landmarks[connection.from], frame.landmarks[connection.to]), rules.connectionGapPx);
    }
    for (const bone of rules.bones) {
      const expected = bone.length * frame.actorScale;
      const measured = distance(frame.landmarks[bone.from], frame.landmarks[bone.to]);
      check("bone-length", bone.id, Math.abs(measured / expected - 1), rules.boneLengthRelativeError);
    }
    for (const contact of rules.contacts) {
      if (!contact.phases.includes(frame.phase)) {
        continue;
      }
      const target = {
        x: frame.drawer.left + contact.offset.x * frame.actorScale,
        y: frame.drawer.top + contact.offset.y * frame.actorScale,
      };
      check("contact-drift", contact.id, distance(frame.landmarks[contact.landmark], target), rules.contactErrorPx);
    }
    for (const landmark of rules.trackedLandmarks) {
      const position = frame.landmarks[landmark];
      const outside = Math.max(
        rules.viewportMarginPx - position.x,
        rules.viewportMarginPx - position.y,
        position.x - (viewport.width - rules.viewportMarginPx),
        position.y - (viewport.height - rules.viewportMarginPx),
      );
      check("viewport", landmark, outside, 0);
      if (index === 0) {
        continue;
      }
      const currentVelocity = velocity(frames[index - 1], frame, landmark);
      check("speed", landmark, Math.hypot(currentVelocity.x, currentVelocity.y), rules.speedPxPerSecond);
      if (index > 1) {
        const previousVelocity = velocity(frames[index - 2], frames[index - 1], landmark);
        // Segment velocities are located at interval midpoints, including uneven sampling.
        const midpointSeconds = (frame.timeMs - frames[index - 2].timeMs) / 2000;
        check("acceleration", landmark, distance(currentVelocity, previousVelocity) / midpointSeconds,
          rules.accelerationPxPerSecondSquared);
      }
    }
  });
  if (report.issues.some((issue) => issue.code === "non-finite-measurement")) {
    return report;
  }
  report.status = report.issues.length === 0 ? "within-geometric-limits" : "violations";
  return report;
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function positive(value: unknown): value is number {
  return finite(value) && value > 0;
}

function named(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function point(value: unknown): value is Point {
  return record(value) && finite(value.x) && finite(value.y);
}

function names(value: unknown): value is string[] {
  return Array.isArray(value) && value.length > 0 && value.every(named)
    && new Set(value).size === value.length;
}

function namedRecords(value: unknown): value is Record<string, unknown>[] {
  return Array.isArray(value) && value.length > 0
    && value.every((entry) => record(entry) && named(entry.id))
    && new Set(value.map((entry) => entry.id)).size === value.length;
}

function isMotionReviewPolicy(value: unknown): value is MotionReviewPolicy {
  if (!record(value) || !names(value.trackedLandmarks) || !names(value.requiredPhases)) {
    return false;
  }
  const positiveKeys = ["sampleGapMs", "minimumDurationMs", "speedPxPerSecond", "accelerationPxPerSecondSquared"];
  const nonNegativeKeys = ["viewportMarginPx", "connectionGapPx", "contactErrorPx", "boneLengthRelativeError"];
  if (!positiveKeys.every((key) => positive(value[key]))
    || !nonNegativeKeys.every((key) => finite(value[key]) && (value[key] as number) >= 0)) {
    return false;
  }
  const tracked = new Set(value.trackedLandmarks);
  const phases = new Set(value.requiredPhases);
  const linked = (entry: Record<string, unknown>) =>
    named(entry.from) && named(entry.to) && entry.from !== entry.to
    && tracked.has(entry.from) && tracked.has(entry.to);
  return namedRecords(value.bones) && value.bones.every((bone) => linked(bone) && positive(bone.length))
    && namedRecords(value.connections) && value.connections.every(linked)
    && namedRecords(value.contacts) && value.contacts.every((contact) =>
      named(contact.landmark) && tracked.has(contact.landmark) && point(contact.offset)
      && names(contact.phases) && contact.phases.every((phase) => phases.has(phase)));
}

function isMotionTrace(value: unknown, requiredLandmarks: string[]): value is MotionTrace {
  if (!record(value) || value.schemaVersion !== 1
    || (value.source !== "browser-capture" && value.source !== "synthetic")
    || !record(value.viewport) || !positive(value.viewport.width) || !positive(value.viewport.height)
    || !Array.isArray(value.frames) || value.frames.length < 3) {
    return false;
  }
  return value.frames.every((frame) => {
    if (!record(frame) || !finite(frame.timeMs) || frame.timeMs < 0
      || !named(frame.phase) || !positive(frame.actorScale) || !record(frame.drawer)
      || !finite(frame.drawer.left) || !finite(frame.drawer.top)
      || !positive(frame.drawer.width) || !positive(frame.drawer.height)
      || !record(frame.landmarks)) {
      return false;
    }
    const landmarks = frame.landmarks;
    return requiredLandmarks.every((name) =>
      Object.prototype.hasOwnProperty.call(landmarks, name) && point(landmarks[name]));
  });
}
