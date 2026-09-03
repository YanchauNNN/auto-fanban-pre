from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class StandardsSourceError(RuntimeError):
    pass


class StandardsSourceNotFound(StandardsSourceError, FileNotFoundError):
    pass


class StandardsSourceInvalid(StandardsSourceError, ValueError):
    pass


@dataclass(frozen=True)
class ResolvedStandardSource:
    path: Path
    root: Path
    root_kind: str
    root_index: int
    relative_path: str
    fallback_used: bool
    sha256: str | None = None


class StandardsSourceResolver:
    def __init__(
        self,
        *,
        primary_root: Path,
        fallback_roots: Sequence[Path] = (),
        per_file_fallback: bool = True,
        verify_sha256: bool = False,
    ) -> None:
        self.primary_root = _absolute_path(primary_root)
        self.fallback_roots = tuple(_absolute_path(path) for path in fallback_roots)
        self.per_file_fallback = bool(per_file_fallback)
        self.verify_sha256 = bool(verify_sha256)

    @property
    def roots(self) -> tuple[Path, ...]:
        if not self.per_file_fallback:
            return (self.primary_root,)
        return (self.primary_root, *self.fallback_roots)

    def resolve(
        self,
        relative_path: str,
        *,
        expected_sha256: str = "",
    ) -> ResolvedStandardSource:
        normalized = _validate_relative_pdf_path(relative_path)
        attempts: list[str] = []
        invalid_attempts: list[str] = []

        for index, root in enumerate(self.roots):
            kind = "primary" if index == 0 else "fallback"
            candidate = _safe_child(root, normalized)
            if not candidate.is_file():
                attempts.append(f"{kind}[{index}]: missing")
                continue
            try:
                with candidate.open("rb") as handle:
                    signature = handle.read(5)
            except OSError as exc:
                invalid_attempts.append(f"{kind}[{index}]: unreadable ({exc})")
                continue
            if signature != b"%PDF-":
                invalid_attempts.append(f"{kind}[{index}]: invalid PDF signature")
                continue

            actual_sha256: str | None = None
            if self.verify_sha256 and expected_sha256:
                actual_sha256 = _sha256(candidate)
                if actual_sha256.casefold() != expected_sha256.casefold():
                    invalid_attempts.append(f"{kind}[{index}]: SHA256 mismatch")
                    continue
            return ResolvedStandardSource(
                path=candidate,
                root=root,
                root_kind=kind,
                root_index=index,
                relative_path=normalized.as_posix(),
                fallback_used=index > 0,
                sha256=actual_sha256,
            )

        details = "; ".join([*attempts, *invalid_attempts]) or "no roots configured"
        if invalid_attempts:
            raise StandardsSourceInvalid(
                f"standard source is invalid for relative path {relative_path!r}: {details}"
            )
        raise StandardsSourceNotFound(
            f"standard source was not found for relative path {relative_path!r}: {details}"
        )


def _validate_relative_pdf_path(relative_path: str) -> Path:
    value = str(relative_path or "").strip().replace("\\", "/")
    path = Path(value)
    if not value or path.is_absolute() or value.startswith("//") or ".." in path.parts:
        raise StandardsSourceInvalid("standard source path must be a safe relative path")
    if path.suffix.casefold() != ".pdf":
        raise StandardsSourceInvalid("standard source path must reference a PDF")
    return path


def _absolute_path(path: Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _safe_child(root: Path, relative_path: Path) -> Path:
    candidate = (root / relative_path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise StandardsSourceInvalid("standard source path escapes the configured root") from exc
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
