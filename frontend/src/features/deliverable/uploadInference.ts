import type { UploadProjectInference } from "../../platform/api/types";

export function inferProjectNumbers(files: File[]): UploadProjectInference {
  const inferredProjectNos: string[] = [];
  const inferredUnitNos: string[] = [];

  for (const file of files) {
    const projectMatch = file.name.match(/^(\d{4})/);
    if (!projectMatch) {
      continue;
    }

    const projectNo = projectMatch[1];
    if (!inferredProjectNos.includes(projectNo)) {
      inferredProjectNos.push(projectNo);
    }
    const unitMatch = file.name.match(
      new RegExp(`^${projectNo}([0-9])(?=[A-Z0-9]{2,4}-[A-Z]{3}\\d{2})`),
    );
    if (unitMatch?.[1] && !inferredUnitNos.includes(unitMatch[1])) {
      inferredUnitNos.push(unitMatch[1]);
    }
  }

  return {
    inferredProjectNos,
    inferredUnitNos,
    primaryProjectNo: inferredProjectNos[0] ?? "",
    primaryUnitNo: inferredUnitNos[0] ?? "",
    hasConflict: inferredProjectNos.length > 1,
    hasUnitConflict: inferredUnitNos.length > 1,
  };
}
