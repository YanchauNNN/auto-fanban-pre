type PromiseWithResolvers = <T>() => {
  promise: Promise<T>;
  resolve: (value: T | PromiseLike<T>) => void;
  reject: (reason?: unknown) => void;
};

type PromiseWithResolversConstructor = PromiseConstructor & {
  withResolvers?: PromiseWithResolvers;
};

export function ensurePromiseWithResolvers() {
  const promiseConstructor = Promise as PromiseWithResolversConstructor;
  const promiseWithResolvers = promiseConstructor.withResolvers;

  if (typeof promiseWithResolvers === "function") {
    return;
  }

  promiseConstructor.withResolvers = function withResolvers<T>() {
    let resolve!: (value: T | PromiseLike<T>) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((innerResolve, innerReject) => {
      resolve = innerResolve;
      reject = innerReject;
    });

    return {
      promise,
      resolve,
      reject,
    };
  };
}
