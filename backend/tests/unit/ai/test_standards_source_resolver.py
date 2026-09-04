from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


def _write_pdf(path: Path, body: bytes = b"fixture") -> str:
    payload = b"%PDF-1.7\n" + body
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_resolver_prefers_primary_and_falls_back_per_file(tmp_path: Path) -> None:
    from src.ai.standards_source_resolver import StandardsSourceResolver

    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"
    local_hash = _write_pdf(primary / "group" / "local.pdf", b"local")
    remote_hash = _write_pdf(fallback / "group" / "remote.pdf", b"remote")
    resolver = StandardsSourceResolver(
        primary_root=primary,
        fallback_roots=[fallback],
        per_file_fallback=True,
    )

    local = resolver.resolve("group/local.pdf", expected_sha256=local_hash)
    remote = resolver.resolve("group/remote.pdf", expected_sha256=remote_hash)

    assert local.path == (primary / "group" / "local.pdf").resolve()
    assert local.root_kind == "primary"
    assert local.fallback_used is False
    assert remote.path == (fallback / "group" / "remote.pdf").resolve()
    assert remote.root_kind == "fallback"
    assert remote.fallback_used is True


def test_resolver_rejects_paths_outside_configured_roots(tmp_path: Path) -> None:
    from src.ai.standards_source_resolver import (
        StandardsSourceInvalid,
        StandardsSourceResolver,
    )

    resolver = StandardsSourceResolver(primary_root=tmp_path / "primary")

    with pytest.raises(StandardsSourceInvalid, match="relative"):
        resolver.resolve("../outside.pdf")
    with pytest.raises(StandardsSourceInvalid, match="relative"):
        resolver.resolve(str((tmp_path / "outside.pdf").resolve()))


def test_resolver_rejects_invalid_pdf_and_hash_mismatch(tmp_path: Path) -> None:
    from src.ai.standards_source_resolver import (
        StandardsSourceInvalid,
        StandardsSourceResolver,
    )

    root = tmp_path / "primary"
    invalid = root / "invalid.pdf"
    invalid.parent.mkdir(parents=True)
    invalid.write_bytes(b"not a pdf")
    _write_pdf(root / "mismatch.pdf")
    resolver = StandardsSourceResolver(primary_root=root, verify_sha256=True)

    with pytest.raises(StandardsSourceInvalid, match="signature"):
        resolver.resolve("invalid.pdf")
    with pytest.raises(StandardsSourceInvalid, match="SHA256"):
        resolver.resolve("mismatch.pdf", expected_sha256="0" * 64)


def test_resolver_reports_all_attempts_when_source_is_missing(tmp_path: Path) -> None:
    from src.ai.standards_source_resolver import (
        StandardsSourceNotFound,
        StandardsSourceResolver,
    )

    resolver = StandardsSourceResolver(
        primary_root=tmp_path / "primary",
        fallback_roots=[tmp_path / "fallback"],
    )

    with pytest.raises(StandardsSourceNotFound) as exc_info:
        resolver.resolve("missing.pdf")

    assert "primary" in str(exc_info.value)
    assert "fallback" in str(exc_info.value)
