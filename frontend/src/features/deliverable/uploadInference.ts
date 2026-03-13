import type { UploadProjectInference } from "../../platform/api/types";

export function inferProjectNumbers(files: File[]): UploadProjectInference {
  const inferredProjectNos: string[] = [];

  for (const file of files) {
    const match = file.name.match(/^(\d{4})/);
    if (!match) {
      continue;
    }

    const projectNo = match[1];
    if (!inferredProjectNos.includes(projectNo)) {
      inferredProjectNos.push(projectNo);
    }
  }

  return {
    inferredProjectNos,
    primaryProjectNo: inferredProjectNos[0] ?? "",
    hasConflict: inferredProjectNos.length > 1,
  };
}
