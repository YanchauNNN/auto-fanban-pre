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

export type TaskGroupPresentationLabels = {
  workflowStatusLabels?: Record<string, string>;
  archiveStatusLabels?: Record<string, string>;
  nodeLabels?: Record<string, string>;
  emptyCurrentNodeLabel?: string;
};

export function buildTaskGroupCardModels(
  items: readonly TaskGroupSummary[],
  labels: TaskGroupPresentationLabels = {},
): TaskGroupCardModel[] {
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
        workflowLabel: getWorkflowStatusLabel(item.workflowStatus, labels),
        currentNodeLabel: getCurrentNodeLabel(item.currentNodeKey, labels),
        archiveLabel: getArchiveStatusLabel(item.archiveStatus, labels),
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

export function getWorkflowStatusLabel(status: string, labels: TaskGroupPresentationLabels = {}) {
  return labels.workflowStatusLabels?.[status] ?? status;
}

export function getArchiveStatusLabel(status: string, labels: TaskGroupPresentationLabels = {}) {
  return labels.archiveStatusLabels?.[status] ?? status;
}

export function getCurrentNodeLabel(nodeKey: string | null, labels: TaskGroupPresentationLabels = {}) {
  if (!nodeKey) {
    return labels.emptyCurrentNodeLabel ?? "";
  }
  return labels.nodeLabels?.[nodeKey] ?? nodeKey;
}

function formatEffectiveWorkload(value: number) {
  return value.toFixed(2);
}
