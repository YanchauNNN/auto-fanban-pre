import { afterEach, describe, expect, it } from "vitest";

import { lockBodyScroll } from "./documentScrollLock";

describe("lockBodyScroll", () => {
  afterEach(() => {
    document.body.style.overflow = "";
    document.documentElement.style.overflow = "";
  });

  it("locks both body and document element scrolling until the last release", () => {
    document.body.style.overflow = "auto";
    document.documentElement.style.overflow = "scroll";

    const releaseFirst = lockBodyScroll();
    const releaseSecond = lockBodyScroll();

    expect(document.body.style.overflow).toBe("hidden");
    expect(document.documentElement.style.overflow).toBe("hidden");

    releaseFirst();

    expect(document.body.style.overflow).toBe("hidden");
    expect(document.documentElement.style.overflow).toBe("hidden");

    releaseSecond();

    expect(document.body.style.overflow).toBe("auto");
    expect(document.documentElement.style.overflow).toBe("scroll");
  });
});
