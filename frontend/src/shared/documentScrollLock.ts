let bodyLockCount = 0;
let previousBodyOverflow: string | null = null;

export function lockBodyScroll() {
  if (typeof document === "undefined") {
    return () => {};
  }

  if (bodyLockCount === 0) {
    previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }

  bodyLockCount += 1;
  let released = false;

  return () => {
    if (released || typeof document === "undefined") {
      return;
    }

    released = true;
    bodyLockCount = Math.max(0, bodyLockCount - 1);

    if (bodyLockCount === 0) {
      document.body.style.overflow = previousBodyOverflow ?? "";
      previousBodyOverflow = null;
    }
  };
}
