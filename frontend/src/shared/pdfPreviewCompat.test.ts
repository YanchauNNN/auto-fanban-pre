import { describe, expect, it } from "vitest";

import { ensurePromiseWithResolvers } from "./pdfPreviewCompat";

type PromiseWithResolversConstructor = PromiseConstructor & {
  withResolvers?: <T>() => {
    promise: Promise<T>;
    resolve: (value: T | PromiseLike<T>) => void;
    reject: (reason?: unknown) => void;
  };
};

describe("pdf preview compatibility", () => {
  it("polyfills Promise.withResolvers when the runtime does not provide it", async () => {
    const promiseConstructor = Promise as PromiseWithResolversConstructor;
    const original = promiseConstructor.withResolvers;

    try {
      delete promiseConstructor.withResolvers;

      ensurePromiseWithResolvers();

      expect(typeof promiseConstructor.withResolvers).toBe("function");
      const capability = promiseConstructor.withResolvers!<number>();
      capability.resolve(7);
      await expect(capability.promise).resolves.toBe(7);
    } finally {
      if (original) {
        promiseConstructor.withResolvers = original;
      } else {
        delete promiseConstructor.withResolvers;
      }
    }
  });
});
