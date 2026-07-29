import { describe, expect, it } from "vitest";

import { inferProjectNumbers, inferReplaceBatchIdentity } from "./uploadInference";

describe("inferProjectNumbers", () => {
  it("extracts project numbers from the first four digits of each filename", () => {
    const inference = inferProjectNumbers([
      new File(["dwg"], "2016-A01.dwg", { type: "application/acad" }),
      new File(["dwg"], "2016-B01.dwg", { type: "application/acad" }),
    ]);

    expect(inference).toEqual({
      inferredProjectNos: ["2016"],
      inferredUnitNos: [],
      primaryProjectNo: "2016",
      primaryUnitNo: "",
      hasConflict: false,
      hasUnitConflict: false,
    });
  });

  it("warns when the selected files imply multiple project numbers", () => {
    const inference = inferProjectNumbers([
      new File(["dwg"], "2016-A01.dwg", { type: "application/acad" }),
      new File(["dwg"], "1818-B01.dwg", { type: "application/acad" }),
    ]);

    expect(inference.inferredProjectNos).toEqual(["2016", "1818"]);
    expect(inference.primaryProjectNo).toBe("2016");
    expect(inference.hasConflict).toBe(true);
  });

  it("extracts unit numbers from project code filenames", () => {
    const inference = inferProjectNumbers([
      new File(["dwg"], "20261NS-JGS01.dwg", { type: "application/acad" }),
      new File(["dwg"], "20261RS-JGS65.dwg", { type: "application/acad" }),
      new File(["dwg"], "20261RB-SBS01.dwg", { type: "application/acad" }),
    ]);

    expect(inference.inferredProjectNos).toEqual(["2026"]);
    expect(inference.inferredUnitNos).toEqual(["1"]);
    expect(inference.primaryUnitNo).toBe("1");
    expect(inference.hasUnitConflict).toBe(false);
  });

  it("extracts a shared replace identity from album codes anywhere in filenames", () => {
    const inference = inferReplaceBatchIdentity(
      [
        new File(["dwg"], "出图版--20261PC-JGS01-A.dwg", { type: "application/acad" }),
        new File(["dwg"], "20261PC-JGS02-B.dwg", { type: "application/acad" }),
      ],
      String.raw`(\d{4})([0-9])([A-Z0-9]{2,4})-?[A-Z]{3}\d{2}`,
    );

    expect(inference).toMatchObject({
      inferredProjectNos: ["2026"],
      inferredUnitNos: ["1"],
      inferredFactoryCodes: ["PC"],
      primaryProjectNo: "2026",
      primaryUnitNo: "1",
      primaryFactoryCode: "PC",
      hasProjectConflict: false,
      hasUnitConflict: false,
      hasFactoryConflict: false,
    });
  });

  it("detects mixed source projects and factory codes in one replace batch", () => {
    const inference = inferReplaceBatchIdentity(
      [
        new File(["dwg"], "20161RC-JGS01-A.dwg", { type: "application/acad" }),
        new File(["dwg"], "18185RB-JGS02-A.dwg", { type: "application/acad" }),
      ],
      String.raw`(\d{4})([0-9])([A-Z0-9]{2,4})-?[A-Z]{3}\d{2}`,
    );

    expect(inference.hasProjectConflict).toBe(true);
    expect(inference.hasUnitConflict).toBe(true);
    expect(inference.hasFactoryConflict).toBe(true);
  });
});
