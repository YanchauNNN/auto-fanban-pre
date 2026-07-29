import type { UploadProjectInference } from "../../platform/api/types";

export type ReplaceBatchIdentityInference = {
  inferredProjectNos: string[];
  inferredUnitNos: string[];
  inferredFactoryCodes: string[];
  primaryProjectNo: string;
  primaryUnitNo: string;
  primaryFactoryCode: string;
  hasProjectConflict: boolean;
  hasUnitConflict: boolean;
  hasFactoryConflict: boolean;
};

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

export function inferReplaceBatchIdentity(
  files: File[],
  identityPattern: string | undefined,
): ReplaceBatchIdentityInference {
  const inferredProjectNos: string[] = [];
  const inferredUnitNos: string[] = [];
  const inferredFactoryCodes: string[] = [];
  let pattern: RegExp | null = null;

  try {
    pattern = identityPattern?.trim() ? new RegExp(identityPattern, "i") : null;
  } catch {
    pattern = null;
  }

  for (const file of files) {
    const match = pattern?.exec(file.name);
    const projectNo = match?.[1]?.trim() ?? "";
    const unitNo = match?.[2]?.trim() ?? "";
    const factoryCode = match?.[3]?.trim().toUpperCase() ?? "";
    appendUnique(inferredProjectNos, projectNo);
    appendUnique(inferredUnitNos, unitNo);
    appendUnique(inferredFactoryCodes, factoryCode);
  }

  return {
    inferredProjectNos,
    inferredUnitNos,
    inferredFactoryCodes,
    primaryProjectNo: inferredProjectNos[0] ?? "",
    primaryUnitNo: inferredUnitNos[0] ?? "",
    primaryFactoryCode: inferredFactoryCodes[0] ?? "",
    hasProjectConflict: inferredProjectNos.length > 1,
    hasUnitConflict: inferredUnitNos.length > 1,
    hasFactoryConflict: inferredFactoryCodes.length > 1,
  };
}

function appendUnique(values: string[], value: string) {
  if (value && !values.includes(value)) {
    values.push(value);
  }
}
