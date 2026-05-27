from __future__ import annotations

import yaml

from src.archive.identity import build_archive_identity
from src.models import GlobalDocParams


def test_archive_identity_uses_yaml_level_pattern_and_mechanism_fallbacks(tmp_path, monkeypatch) -> None:
    business_spec = tmp_path / "documents" / "参数规范.yaml"
    business_spec.parent.mkdir(parents=True, exist_ok=True)
    business_spec.write_text(
        yaml.safe_dump(
            {
                "schema_version": "2.0",
                "management_features": {
                    "archive": {
                        "level_pattern": "{revision}/{engineering_no}/{subitem_no}/{album_internal_code}",
                    }
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    mechanism_spec = tmp_path / "documents" / "参数规范-3.yaml"
    mechanism_spec.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "backend_mechanism": {
                    "archive_defaults": {
                        "engineering_no": "ENG_UNKNOWN",
                        "subitem_no": "SUB_UNKNOWN",
                        "album_internal_code": "ALBUM_UNKNOWN",
                        "revision": "Z",
                    }
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FANBAN_SPEC_PATH", str(business_spec))
    monkeypatch.setenv("FANBAN_MECHANISM_SPEC_PATH", str(mechanism_spec))

    identity = build_archive_identity(
        GlobalDocParams(project_no="2016", engineering_no="", subitem_no="", revision=""),
        album_internal_code="",
        document_revision="",
    )

    assert identity.relative_parts == ("Z", "ENG_UNKNOWN", "SUB_UNKNOWN", "ALBUM_UNKNOWN")
