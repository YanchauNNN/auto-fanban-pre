import type { TaskGroupSummary } from "../platform/api/types";

export type TaskGroupCardModel = {
  key: string;
  groupId: string;
  title: string;
  searchText: string;
  status: string;
  createdAt: string;
  creatorLabel: string;
  officeLabel: string;
  workflowLabel: string;
  currentNodeLabel: string;
  archiveLabel: string;
  effectiveWorkloadLabel: string;
  canViewDetail: boolean;
  canSubmit: boolean;
  canApprove: boolean;
  summary: TaskGroupSummary;
};

const WORKFLOW_STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  submitted: "已提交",
  in_review: "审批中",
  three_review_approved: "三审通过",
  archiving: "归档中",
  archived: "已归档",
  archive_failed: "归档失败",
  cancelled: "已取消",
};

const ARCHIVE_STATUS_LABELS: Record<string, string> = {
  pending: "待归档",
  running: "归档中",
  succeeded: "已归档",
  failed: "归档失败",
};

const NODE_LABELS: Record<string, string> = {
  one_review: "一审",
  two_review: "二审",
  three_review: "三审",
};

export function buildTaskGroupCardModels(items: readonly TaskGroupSummary[]): TaskGroupCardModel[] {
  return [...items]
    .map((item) => {
      const title = item.sourceFilenames[0] ?? item.groupId;
      return {
        key: item.groupId,
        groupId: item.groupId,
        title,
        searchText: [title, ...item.sourceFilenames].join(" ").toLowerCase(),
        status: item.status,
        createdAt: item.createdAt,
        creatorLabel: item.creatorName ?? item.ownerSnapshot?.creatorName ?? "未知创建者",
        officeLabel: item.creatorOffice ?? item.ownerSnapshot?.creatorOffice ?? "未记录科室",
        workflowLabel: getWorkflowStatusLabel(item.workflowStatus),
        currentNodeLabel: getCurrentNodeLabel(item.currentNodeKey),
        archiveLabel: getArchiveStatusLabel(item.archiveStatus),
        effectiveWorkloadLabel: formatEffectiveWorkload(item.effectiveWorkload),
        canViewDetail: item.canViewDetail,
        canSubmit: item.canSubmit,
        canApprove: item.canApprove,
        summary: item,
      };
    })
    .sort((left, right) => {
      const leftTime = Date.parse(left.createdAt) || 0;
      const rightTime = Date.parse(right.createdAt) || 0;
      return rightTime - leftTime;
    });
}

export function getWorkflowStatusLabel(status: string) {
  return WORKFLOW_STATUS_LABELS[status] ?? status;
}

export function getArchiveStatusLabel(status: string) {
  return ARCHIVE_STATUS_LABELS[status] ?? status;
}

export function getCurrentNodeLabel(nodeKey: string | null) {
  if (!nodeKey) {
    return "未进入审批";
  }
  return NODE_LABELS[nodeKey] ?? nodeKey;
}

function formatEffectiveWorkload(value: number) {
  return value.toFixed(2);
}
