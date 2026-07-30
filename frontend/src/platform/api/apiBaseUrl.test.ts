import { describe, expect, it } from "vitest";

import { resolveApiBaseUrl } from "./apiBaseUrl";

describe("resolveApiBaseUrl", () => {
  it("prefers VITE_API_BASE_URL when it is configured", () => {
    expect(
      resolveApiBaseUrl({
        DEV: true,
        VITE_API_BASE_URL: "http://192.168.1.10:9000/",
      }),
    ).toBe("http://192.168.1.10:9000");
  });

  it("uses same-origin requests in development when no override is provided", () => {
    expect(
      resolveApiBaseUrl({
        DEV: true,
      }),
    ).toBe("");
  });

  it("uses same-origin requests in production when no override is provided", () => {
    expect(
      resolveApiBaseUrl({
        DEV: false,
      }),
    ).toBe("");
  });
});
