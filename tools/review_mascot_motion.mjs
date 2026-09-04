import { readFile } from "node:fs/promises";

const usage = "Usage: node tools/review_mascot_motion.mjs <trace.json> <policy.json>\nRequires Node.js 24+. Exit codes: 0 = geometry within limits, 1 = violations, 2 = invalid input.\nA zero exit code is not visual animation acceptance.";
const args = process.argv.slice(2);

if (args.length === 1 && args[0] === "--help") {
  console.log(usage);
} else if (args.length !== 2) {
  console.error(usage);
  process.exitCode = 2;
} else {
  try {
    if (Number(process.versions.node.split(".")[0]) < 24) {
      throw new Error("Node.js 24 or newer is required for the TypeScript inspection module.");
    }
    const { reviewMotionTrace } = await import(
      "../frontend/src/features/ai-chat/motion-review/reviewMotionTrace.ts"
    );
    const trace = JSON.parse((await readFile(args[0], "utf8")).replace(/^\uFEFF/, ""));
    const policy = JSON.parse((await readFile(args[1], "utf8")).replace(/^\uFEFF/, ""));
    const report = reviewMotionTrace(trace, policy);
    console.log(JSON.stringify(report, null, 2));
    process.exitCode = report.status === "invalid" ? 2 : report.status === "violations" ? 1 : 0;
  } catch (error) {
    console.error(`Motion review failed: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 2;
  }
}
