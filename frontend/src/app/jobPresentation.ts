import type { JobSummary, TaskKind } from "../platform/api/types";

export type JobCardModel =
  | {
      kind: "real_group";
      key: string;
      jobId: string;
      title: string;
      status: string;
      percent: number;
      stageLabel: string;
      messageLabel: string;
      findingsCount: number;
      affectedDrawingsCount: number;
      childCount: number;
      childJobs: JobSummary[];
      summary: JobSummary;
    }
  | {
      kind: "synthetic_group";
      key: string;
      jobId: string;
      title: string;
      status: string;
      percent: number;
      stageLabel: string;
      messageLabel: string;
      findingsCount: number;
      affectedDrawingsCount: number;
      childCount: number;
      childJobs: JobSummary[];
      summary: JobSummary;
    }
  | {
      kind: "single_job";
      key: string;
      jobId: string;
      title: string;
      status: string;
      percent: number;
      stageLabel: string;
      messageLabel: string;
      findingsCount: number;
      affectedDrawingsCount: number;
      childCount: 1;
      childJobs: [];
      summary: JobSummary;
    };

type PresentableJob = Pick<JobSummary, "isGroup" | "taskKind" | "stage" | "status" | "message">;

const STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  cancel_requested: "取消中",
  cancelled: "已取消",
  succeeded: "成功",
  failed: "失败",
};

const STAGE_LABELS: Record<string, string> = {
  INIT: "初始化",
  PREP_SOURCE: "准备源文件",
  DELIVERABLE_BRANCH: "执行出图子任务",
  AUDIT_BRANCH: "执行纠错子任务",
  DOCS_AND_PACKAGE: "整理文档与压缩包",
  GROUP_COMPLETE: "任务包完成",
  EXPORT_PDF_AND_DWG: "导出 DWG/PDF",
  GENERATE_DOCS: "生成目录和文档",
  PACKAGE_ZIP: "生成交付压缩包",
  AUDIT_CHECK: "执行纠错识别",
  EXPORT_REPORT: "导出纠错报告",
};

const STAGE_MESSAGES: Record<string, string> = {
  INIT: "正在初始化任务",
  PREP_SOURCE: "正在准备源文件",
  DELIVERABLE_BRANCH: "正在执行出图任务",
  AUDIT_BRANCH: "正在执行纠错任务",
  DOCS_AND_PACKAGE: "正在整理文档与压缩包",
  GROUP_COMPLETE: "任务包已完成",
  EXPORT_PDF_AND_DWG: "正在导出 DWG/PDF",
  GENERATE_DOCS: "正在生成目录和文档",
  PACKAGE_ZIP: "正在整理交付压缩包",
  AUDIT_CHECK: "正在执行纠错识别",
  EXPORT_REPORT: "正在导出纠错报告",
};

export function buildJobCardModels(items: readonly JobSummary[]): JobCardModel[] {
  const realGroups = items.filter((item) => item.isGroup);
  const realGroupIds = new Set(realGroups.map((item) => item.jobId));
  const childBuckets = new Map<string, JobSummary[]>();
  const standaloneSingles: JobSummary[] = [];

  for (const item of items) {
    if (item.isGroup) {
      continue;
    }

    if (item.groupId && realGroupIds.has(item.groupId)) {
      continue;
    }

    if (!item.batchId) {
      standaloneSingles.push(item);
      continue;
    }

    const key = `${item.batchId}::${item.sourceFilename}`;
    const bucket = childBuckets.get(key);
    if (bucket) {
      bucket.push(item);
    } else {
      childBuckets.set(key, [item]);
    }
  }

  const models: JobCardModel[] = realGroups.map((group) => ({
    kind: "real_group",
    key: `group:${group.jobId}`,
    jobId: group.jobId,
    title: group.sourceFilename,
    status: group.status,
    percent: group.percent,
    stageLabel: getStageLabel(group.stage, group),
    messageLabel: getMessageLabel(group),
    findingsCount: group.findingsCount,
    affectedDrawingsCount: group.affectedDrawingsCount,
    childCount: Math.max(group.childJobIds.length, group.children?.length ?? 0, group.runAuditCheck ? 2 : 1),
    childJobs:
      group.children && group.children.length > 0
        ? group.children
        : buildGroupChildPlaceholders(group),
    summary: group,
  }));

  for (const bucket of childBuckets.values()) {
    const sortedBucket = sortJobs(bucket);
    const hasDeliverable = sortedBucket.some((job) => job.taskKind === "deliverable");
    const hasAudit = sortedBucket.some((job) => job.taskKind === "audit_check");

    if (hasDeliverable && hasAudit) {
      const aggregate = buildSyntheticAggregate(sortedBucket);
      models.push({
        kind: "synthetic_group",
        key: `synthetic:${aggregate.batchId}:${aggregate.sourceFilename}`,
        jobId: aggregate.jobId,
        title: aggregate.sourceFilename,
        status: aggregate.status,
        percent: aggregate.percent,
        stageLabel: getStageLabel(aggregate.stage, aggregate),
        messageLabel: getMessageLabel(aggregate),
        findingsCount: aggregate.findingsCount,
        affectedDrawingsCount: aggregate.affectedDrawingsCount,
        childCount: sortedBucket.length,
        childJobs: sortedBucket,
        summary: aggregate,
      });
      continue;
    }

    for (const job of sortedBucket) {
      models.push(toSingleJobModel(job));
    }
  }

  for (const job of standaloneSingles) {
    models.push(toSingleJobModel(job));
  }

  return models.sort((left, right) => {
    const leftTime = Date.parse(left.summary.createdAt) || 0;
    const rightTime = Date.parse(right.summary.createdAt) || 0;
    return rightTime - leftTime;
  });
}

export function getStageLabel(stage: string | null, job: PresentableJob): string {
  if (stage && STAGE_LABELS[stage]) {
    return STAGE_LABELS[stage];
  }

  if (job.isGroup) {
    return job.status === "succeeded" ? "任务包完成" : "任务包处理中";
  }

  if (job.taskKind === "audit_check") {
    return job.status === "succeeded" ? "纠错完成" : "纠错处理中";
  }

  if (job.taskKind === "audit_replace") {
    return job.status === "succeeded" ? "翻版完成" : "翻版处理中";
  }

  return job.status === "succeeded" ? "出图完成" : "出图处理中";
}

export function getMessageLabel(job: PresentableJob): string {
  const message = (job.message ?? "").trim();
  if (isReadableMessage(message)) {
    return message;
  }

  if (job.stage && STAGE_MESSAGES[job.stage]) {
    return STAGE_MESSAGES[job.stage];
  }

  const statusLabel = STATUS_LABELS[job.status] ?? job.status;
  if (job.isGroup) {
    return `${statusLabel}，请查看任务包详情`;
  }
  if (job.taskKind === "audit_check") {
    return job.status === "succeeded" ? "纠错任务已完成" : "纠错任务进行中";
  }
  if (job.taskKind === "audit_replace") {
    return job.status === "succeeded" ? "翻版任务已完成" : "翻版任务进行中";
  }
  return job.status === "succeeded" ? "交付任务已完成" : "交付任务进行中";
}

export function getStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

export function getTaskKindLabel(kind: TaskKind): string {
  if (kind === "audit_check") {
    return "纠错";
  }
  if (kind === "audit_replace") {
    return "翻版";
  }
  return "交付";
}

function toSingleJobModel(job: JobSummary): JobCardModel {
  return {
    kind: "single_job",
    key: `job:${job.jobId}`,
    jobId: job.jobId,
    title: job.sourceFilename,
    status: job.status,
    percent: job.percent,
    stageLabel: getStageLabel(job.stage, job),
    messageLabel: getMessageLabel(job),
    findingsCount: job.findingsCount,
    affectedDrawingsCount: job.affectedDrawingsCount,
    childCount: 1,
    childJobs: [],
    summary: job,
  };
}

function buildSyntheticAggregate(children: readonly JobSummary[]): JobSummary {
  const representative = pickRepresentativeJob(children);
  const status = aggregateStatus(children);
  const stage = deriveSyntheticStage(children, status);
  const percent = aggregatePercent(children);
  const findingsCount = children.reduce((sum, child) => sum + child.findingsCount, 0);
  const affectedDrawingsCount = children.reduce(
    (sum, child) => sum + child.affectedDrawingsCount,
    0,
  );

  return {
    ...representative,
    status,
    stage,
    percent,
    message: "",
    findingsCount,
    affectedDrawingsCount,
    childJobIds: children.map((child) => child.jobId),
    sourceFilenames: Array.from(new Set(children.map((child) => child.sourceFilename))),
    children: [...children],
  };
}

function deriveSyntheticStage(children: readonly JobSummary[], status: string) {
  if (status === "succeeded") {
    return "GROUP_COMPLETE";
  }

  const runningChild = children.find((child) => child.status === "running");
  if (runningChild?.taskKind === "audit_check") {
    return "AUDIT_BRANCH";
  }
  if (runningChild?.taskKind === "deliverable") {
    return "DELIVERABLE_BRANCH";
  }

  const queuedChild = children.find((child) => child.status === "queued");
  if (queuedChild?.taskKind === "audit_check") {
    return "AUDIT_BRANCH";
  }
  if (queuedChild?.taskKind === "deliverable") {
    return "DELIVERABLE_BRANCH";
  }

  if (status === "failed") {
    return pickRepresentativeJob(children, status).stage;
  }

  return "PREP_SOURCE";
}

function pickRepresentativeJob(children: readonly JobSummary[], preferredStatus?: string) {
  const matchingStatus = preferredStatus
    ? children.find((child) => child.status === preferredStatus)
    : null;
  if (matchingStatus) {
    return matchingStatus;
  }

  return (
    children.find((child) => child.status === "running") ??
    children.find((child) => child.status === "queued") ??
    children.find((child) => child.status === "failed") ??
    children.find((child) => child.taskKind === "deliverable") ??
    children[0]
  );
}

function aggregateStatus(children: readonly JobSummary[]) {
  if (children.some((child) => child.status === "running")) {
    return "running";
  }
  if (children.some((child) => child.status === "queued" || child.status === "cancel_requested")) {
    return "queued";
  }
  if (children.some((child) => child.status === "failed")) {
    return "failed";
  }
  if (children.every((child) => child.status === "cancelled")) {
    return "cancelled";
  }
  return "succeeded";
}

function aggregatePercent(children: readonly JobSummary[]) {
  if (children.length === 0) {
    return 0;
  }
  const total = children.reduce((sum, child) => sum + child.percent, 0);
  return Math.round(total / children.length);
}

function sortJobs(items: readonly JobSummary[]) {
  return [...items].sort((left, right) => {
    if ((left.taskKind === "deliverable") !== (right.taskKind === "deliverable")) {
      return left.taskKind === "deliverable" ? -1 : 1;
    }
    const leftTime = Date.parse(left.createdAt) || 0;
    const rightTime = Date.parse(right.createdAt) || 0;
    return rightTime - leftTime;
  });
}

function buildGroupChildPlaceholders(job: JobSummary): JobSummary[] {
  const placeholderKinds: TaskKind[] = job.runAuditCheck
    ? ["deliverable", "audit_check"]
    : ["deliverable"];
  const jobIds =
    job.childJobIds.length > 0
      ? job.childJobIds
      : placeholderKinds.map((kind) => `${job.jobId}-${kind}`);

  return jobIds.map((childJobId, index) => {
    const taskKind: TaskKind = placeholderKinds[index] ?? "deliverable";
    return {
      ...job,
      jobId: childJobId,
      isGroup: false,
      groupId: job.jobId,
      taskKind,
      taskRole: taskKind === "deliverable" ? "deliverable_main" : "audit_check",
      runAuditCheck: false,
      childJobIds: [],
      children: undefined,
    };
  });
}

function isReadableMessage(message: string) {
  if (!message) {
    return false;
  }
  if (/^[\u003F\uFF1F]+$/u.test(message) || message.includes("????")) {
    return false;
  }
  if (/[\uFFFD]/u.test(message)) {
    return false;
  }

  return /[\u4e00-\u9fff]/.test(message);
}
