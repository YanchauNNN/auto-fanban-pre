import { describe, expect, it } from "vitest";

import { inferProjectNumbers } from "./uploadInference";

describe("inferProjectNumbers", () => {
  it("extracts project numbers from the first four digits of each filename", () => {
    const inference = inferProjectNumbers([
      new File(["dwg"], "2016-A01.dwg", { type: "application/acad" }),
      new File(["dwg"], "2016-B01.dwg", { type: "application/acad" }),
    ]);

    expect(inference).toEqual({
      inferredProjectNos: ["2016"],
      primaryProjectNo: "2016",
      hasConflict: false,
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
});
