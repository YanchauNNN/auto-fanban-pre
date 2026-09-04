// @vitest-environment node
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, unlinkSync, rmdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

const command = resolve(process.cwd(), "../tools/review_mascot_motion.mjs");
const files: string[] = [];
const directories: string[] = [];

function temporary(content: string) {
  const directory = mkdtempSync(join(tmpdir(), "fanban-motion-review-"));
  directories.push(directory);
  const path = join(directory, "input.json");
  files.push(path);
  writeFileSync(path, content, "utf8");
  return path;
}

afterEach(() => {
  files.splice(0).forEach((file) => unlinkSync(file));
  directories.splice(0).forEach((directory) => rmdirSync(directory));
});

describe("motion review CLI", () => {
  it("explains arguments without loading a server or business session", () => {
    const result = spawnSync(process.execPath, [command, "--help"], { encoding: "utf8" });
    expect(result.status).toBe(0);
    expect(result.stdout).toContain("<trace.json> <policy.json>");
  });

  it("returns a nonzero status for invalid data without overwriting the input", () => {
    const path = temporary("{}");
    const result = spawnSync(process.execPath, [command, path, path], { encoding: "utf8" });
    expect(result.status).toBe(2);
    expect(JSON.parse(result.stdout).status).toBe("invalid");
    expect(readFileSync(path, "utf8")).toBe("{}");
  });

  it("reports malformed JSON as a failure", () => {
    const path = temporary("{broken");
    const result = spawnSync(process.execPath, [command, path, path], { encoding: "utf8" });
    expect(result.status).toBe(2);
    expect(result.stderr).toContain("Motion review failed:");
  });

  it.each([
    [0, 0, "within-geometric-limits"],
    [10, 1, "violations"],
  ])("evaluates a complete JSON trace with grip offset %s", (drift, exitCode, status) => {
    const trace = temporary(JSON.stringify({
      schemaVersion: 1,
      source: "synthetic",
      viewport: { width: 400, height: 300 },
      frames: [0, 20, 40].map((timeMs) => ({
        timeMs, phase: "cling", actorScale: 1,
        drawer: { left: 200 + drift, top: 20, width: 180, height: 280 },
        landmarks: { socket: { x: 180, y: 70 }, shoulder: { x: 180, y: 70 }, wrist: { x: 200, y: 70 } },
      })),
    }));
    const policy = temporary(JSON.stringify({
      sampleGapMs: 25, minimumDurationMs: 40, viewportMarginPx: 0,
      connectionGapPx: 1, contactErrorPx: 2, boneLengthRelativeError: 0.02,
      speedPxPerSecond: 1000, accelerationPxPerSecondSquared: 20000,
      trackedLandmarks: ["socket", "shoulder", "wrist"], requiredPhases: ["cling"],
      bones: [{ id: "arm", from: "shoulder", to: "wrist", length: 20 }],
      connections: [{ id: "shoulder_socket", from: "socket", to: "shoulder" }],
      contacts: [{ id: "grip", landmark: "wrist", phases: ["cling"], offset: { x: 0, y: 50 } }],
    }));
    const result = spawnSync(process.execPath, [command, trace, policy], { encoding: "utf8" });
    expect(result.status).toBe(exitCode);
    const report = JSON.parse(result.stdout);
    expect(report.status).toBe(status);
    expect(report.source).toBe("synthetic");
    expect(report.visualReviewRequired).toBe(true);
  });
});
