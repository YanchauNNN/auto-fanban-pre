import { describe, expect, it } from "vitest";

import {
  reviewMotionTrace,
  type MotionReviewPolicy,
  type MotionTrace,
} from "./reviewMotionTrace";

function policy(): MotionReviewPolicy {
  return {
    sampleGapMs: 25,
    minimumDurationMs: 40,
    viewportMarginPx: 0,
    connectionGapPx: 1,
    contactErrorPx: 2,
    boneLengthRelativeError: 0.02,
    speedPxPerSecond: 1_000,
    accelerationPxPerSecondSquared: 20_000,
    trackedLandmarks: ["shoulder", "elbow", "wrist", "torso_socket"],
    requiredPhases: ["cling"],
    bones: [{ id: "upper_arm", from: "shoulder", to: "elbow", length: 20 }],
    connections: [{ id: "shoulder_socket", from: "torso_socket", to: "shoulder" }],
    contacts: [{ id: "left_grip", landmark: "wrist", phases: ["cling"], offset: { x: 0, y: 50 } }],
  };
}

function trace(): MotionTrace {
  return {
    schemaVersion: 1,
    source: "synthetic",
    viewport: { width: 400, height: 300 },
    frames: [0, 20, 40].map((timeMs) => ({
      timeMs,
      phase: "cling",
      actorScale: 1,
      drawer: { left: 200, top: 20, width: 200, height: 280 },
      landmarks: {
        shoulder: { x: 170, y: 50 },
        torso_socket: { x: 170, y: 50 },
        elbow: { x: 170, y: 70 },
        wrist: { x: 200, y: 70 },
      },
    })),
  };
}

describe("reviewMotionTrace", () => {
  it("never treats geometric checks or synthetic frames as visual acceptance", () => {
    const report = reviewMotionTrace(trace(), policy());
    expect(report.status).toBe("within-geometric-limits");
    expect(report.visualReviewRequired).toBe(true);
    expect(report.source).toBe("synthetic");
    expect(report.issues).toEqual([]);
  });

  it("measures contacts against the independently moving drawer", () => {
    const moving = trace();
    moving.frames[1].drawer.left += 12;
    const report = reviewMotionTrace(moving, policy());
    expect(report.status).toBe("violations");
    expect(report.issues).toContainEqual(expect.objectContaining({ code: "contact-drift", frame: 1, subject: "left_grip", measured: 12 }));
  });

  it("checks intermediate frames even when both endpoints are correct", () => {
    const moving = trace();
    moving.frames[1].landmarks.wrist.x += 8;
    expect(reviewMotionTrace(moving, policy()).issues).toContainEqual(expect.objectContaining({ code: "contact-drift", frame: 1 }));
  });

  it("uses actor scale for bone lengths and contact offsets", () => {
    const scaled = trace();
    for (const frame of scaled.frames) {
      frame.actorScale = 2;
      frame.landmarks.elbow.y = 90;
      frame.landmarks.wrist.y = 120;
    }
    expect(reviewMotionTrace(scaled, policy()).issues).toEqual([]);
  });

  it("detects detached shoulder sockets and stretched bones", () => {
    const moving = trace();
    moving.frames[1].landmarks.torso_socket.x += 14;
    moving.frames[1].landmarks.elbow.y += 5;
    const report = reviewMotionTrace(moving, policy());
    expect(report.issues).toContainEqual(expect.objectContaining({ code: "connection-gap", frame: 1, measured: 14 }));
    expect(report.issues).toContainEqual(expect.objectContaining({ code: "bone-length", frame: 1, measured: 0.25 }));
  });

  it("reports excessive speed and sudden velocity changes", () => {
    const moving = trace();
    moving.frames[1].landmarks.wrist.x += 30;
    const codes = reviewMotionTrace(moving, policy()).issues.map((issue) => issue.code);
    expect(codes).toContain("speed");
    expect(codes).toContain("acceleration");
  });

  it("reports tracked landmarks outside the viewport", () => {
    const moving = trace();
    moving.frames[1].landmarks.wrist.x = -3;
    expect(reviewMotionTrace(moving, policy()).issues).toContainEqual(expect.objectContaining({ code: "viewport", frame: 1, subject: "wrist" }));
  });

  it("requires all authored phases instead of accepting a short stable excerpt", () => {
    const rules = policy();
    rules.requiredPhases.push("pull");
    expect(reviewMotionTrace(trace(), rules).status).toBe("invalid");
    expect(reviewMotionTrace(trace(), rules).issues).toContainEqual(expect.objectContaining({ code: "missing-phase", subject: "pull" }));
  });

  it.each([
    ["empty capture", (value: MotionTrace) => { value.frames = []; }],
    ["single frame", (value: MotionTrace) => { value.frames.length = 1; }],
    ["missing landmark", (value: MotionTrace) => { delete value.frames[1].landmarks.wrist; }],
    ["non-finite point", (value: MotionTrace) => { value.frames[1].landmarks.wrist.x = NaN; }],
    ["zero scale", (value: MotionTrace) => { value.frames[1].actorScale = 0; }],
    ["non-monotonic time", (value: MotionTrace) => { value.frames[1].timeMs = 0; }],
    ["missing frame", (value: MotionTrace) => { value.frames[2].timeMs = 100; }],
    ["too short", (value: MotionTrace) => { value.frames[2].timeMs = 30; }],
  ])("fails closed for %s", (_name, modify) => {
    const value = trace();
    modify(value);
    expect(reviewMotionTrace(value, policy()).status).toBe("invalid");
  });

  it.each([null, {}, { schemaVersion: 1, frames: [null] }])("rejects malformed JSON without throwing", (value) => {
    expect(reviewMotionTrace(value, policy()).status).toBe("invalid");
  });

  it("rejects policies that disable meaningful checks", () => {
    expect(reviewMotionTrace(trace(), {}).status).toBe("invalid");
    const rules = policy();
    rules.contactErrorPx = NaN;
    expect(reviewMotionTrace(trace(), rules).status).toBe("invalid");
    expect(reviewMotionTrace(trace(), { ...policy(), trackedLandmarks: [] }).status).toBe("invalid");
  });

  it("rejects non-finite derived measurements instead of silently accepting them", () => {
    const rules = policy();
    rules.bones[0].length = 0.5;
    const value = trace();
    for (const frame of value.frames) {
      frame.actorScale = Number.MIN_VALUE;
      frame.landmarks.elbow = { ...frame.landmarks.shoulder };
      frame.landmarks.wrist = { x: frame.drawer.left, y: frame.drawer.top };
    }
    const report = reviewMotionTrace(value, rules);
    expect(report.status).toBe("invalid");
    expect(report.issues).toContainEqual(expect.objectContaining({
      code: "non-finite-measurement", subject: "upper_arm", frame: 0,
    }));
  });

  it("only requires grip contact in the declared phases", () => {
    const moving = trace();
    moving.frames[0].phase = "reach";
    moving.frames[0].landmarks.wrist.x -= 10;
    const report = reviewMotionTrace(moving, policy());
    expect(report.issues.filter((issue) => issue.code === "contact-drift")).toEqual([]);
  });
});
