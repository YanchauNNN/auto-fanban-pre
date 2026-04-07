import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { JobDetail } from "../../platform/api/types";
import { AuditCheckSummaryModal } from "./AuditCheckSummaryModal";
import styles from "./AuditCheckSummaryModal.module.css";

const job: JobDetail = {
  jobId: "audit-job-1",
  batchId: "batch-audit-1",
  groupId: null,
  isGroup: false,
  sourceFilename: "19076RS-JGS01.dwg",
  sourceFilenames: ["19076RS-JGS01.dwg"],
  taskKind: "audit_check",
  taskRole: "audit_check",
  jobMode: "audit_check",
  projectNo: "1907",
  status: "succeeded",
  stage: "EXPORT_REPORT",
  percent: 100,
  message: "",
  createdAt: "2026-04-07T10:00:00+08:00",
  finishedAt: "2026-04-07T10:05:00+08:00",
  startedAt: "2026-04-07T10:00:10+08:00",
  currentFile: null,
  runAuditCheck: true,
  childJobIds: [],
  findingsCount: 12,
  affectedDrawingsCount: 4,
  artifacts: {
    packageAvailable: false,
    iedAvailable: false,
    reportAvailable: true,
    replacedDwgAvailable: false,
    reportDownloadUrl: "/api/jobs/audit-job-1/download/report",
  },
  retryAvailable: false,
  sharedRunId: null,
  flags: [],
  errors: [],
  topWrongTexts: ["核岛安装施工图"],
  topInternalCodes: ["19076RS-JGS01-001"],
};

describe("AuditCheckSummaryModal", () => {
  it("uses a dedicated summary dialog size class", () => {
    render(<AuditCheckSummaryModal job={job} onClose={vi.fn()} />);

    expect(screen.getByRole("dialog", { name: "纠错结果摘要" })).toHaveClass(
      styles.summaryDialog,
    );
  });
});
