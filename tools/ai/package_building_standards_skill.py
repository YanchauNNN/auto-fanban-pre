from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile


SKILL_DIR_NAME = "building-structure-standards"
AUDIT_REPORT_NAME = "建筑结构总图规范语料获取审计表.xlsx"


def build_package(
    *,
    skill_root: Path,
    output_zip: Path,
    audit_workbook: Path,
    validation_set: Path,
) -> dict[str, Any]:
    skill_root = skill_root.resolve()
    output_zip = output_zip.resolve()
    if skill_root.name != SKILL_DIR_NAME:
        raise ValueError(f"skill root must be named {SKILL_DIR_NAME}")
    if not audit_workbook.is_file():
        raise FileNotFoundError(audit_workbook)
    if not validation_set.is_file():
        raise FileNotFoundError(validation_set)

    report_dir = skill_root / "assets" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(audit_workbook, report_dir / AUDIT_REPORT_NAME)
    references = skill_root / "references"
    references.mkdir(parents=True, exist_ok=True)
    shutil.copy2(validation_set, references / "validation_set.yaml")

    validation = _load_json(
        skill_root / "assets" / "data" / "validation_report.json"
    )
    if int(validation.get("failed_count", 1)) != 0:
        raise ValueError("validation report contains failures")
    parse_report = _load_json(
        skill_root / "assets" / "data" / "parse_report.json"
    )
    source_manifest = _load_json(
        skill_root / "assets" / "data" / "source_manifest.json"
    )
    audit_catalog = _load_json(
        skill_root / "assets" / "data" / "audit_catalog.json"
    )
    if not isinstance(audit_catalog, list):
        raise ValueError("audit catalog must be a JSON array")

    manifest_path = skill_root / "assets" / "data" / "manifest.json"
    manifest_hash_path = skill_root / "assets" / "data" / "manifest.sha256"
    for generated in (manifest_path, manifest_hash_path):
        if generated.exists():
            generated.unlink()
    files = [
        {
            "path": path.relative_to(skill_root).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(skill_root.rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix.lower() != ".pyc"
    ]
    manifest = {
        "schema_version": 1,
        "skill_id": "building_structure_standards",
        "skill_directory": SKILL_DIR_NAME,
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "package_scope": "私有内部离线检索",
        "authorization_notice": (
            "仅收录官方社会公开或已明确授权用于内部离线检索的全文；"
            "审计目录中无授权全文的条目不进入正文索引。"
        ),
        "confidentiality": "内部；受控 JT/CP 语料如后续加入应实施最小权限",
        "audit": {
            "record_count": len(audit_catalog),
            "major_counts": dict(
                sorted(
                    Counter(
                        str(item.get("major") or "") for item in audit_catalog
                    ).items()
                )
            ),
            "source_type_counts": dict(
                sorted(
                    Counter(
                        str(item.get("source_type") or "")
                        for item in audit_catalog
                    ).items()
                )
            ),
        },
        "corpus": parse_report,
        "validation": {
            key: validation.get(key)
            for key in (
                "case_count",
                "passed_count",
                "failed_count",
                "pass_rate",
                "categories",
                "database_sha256",
                "catalog_sha256",
                "cases_sha256",
            )
        },
        "source_manifest_sha256": _sha256(
            skill_root / "assets" / "data" / "source_manifest.json"
        ),
        "authorized_source_count": len(source_manifest.get("sources", [])),
        "files": files,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest_sha256 = _sha256(manifest_path)
    manifest_hash_path.write_text(
        f"{manifest_sha256}  manifest.json\n",
        encoding="ascii",
    )

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    if output_zip.exists():
        output_zip.unlink()
    prefix = f"private/{SKILL_DIR_NAME}"
    with ZipFile(output_zip, "w", compression=ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(skill_root.rglob("*")):
            if (
                not path.is_file()
                or "__pycache__" in path.parts
                or path.suffix.lower() == ".pyc"
            ):
                continue
            relative = path.relative_to(skill_root).as_posix()
            bundle.write(path, f"{prefix}/{relative}")
        bundle.writestr(
            "private/INSTALL-ZH-CN.txt",
            (
                "建筑结构总图规范离线 Skill\n"
                "1. 将 building-structure-standards 目录安装到 "
                "storage/ai/skills/。\n"
                "2. 核对 assets/data/manifest.sha256 和 manifest.json 中的文件哈希。\n"
                "3. 运行 python scripts/validate_skill.py，要求全部通过。\n"
                "4. 本地检索可断网；网页自然语言回答仍取决于配置的模型服务。\n"
                "5. 禁止向未授权对象再分发包内规范全文。\n"
            ),
        )
    return {
        "output_zip": str(output_zip),
        "zip_size": output_zip.stat().st_size,
        "zip_sha256": _sha256(output_zip),
        "manifest_sha256": manifest_sha256,
        "file_count": len(files),
        "validation": manifest["validation"],
        "audit": manifest["audit"],
        "corpus": manifest["corpus"],
    }


def _load_json(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Package the private offline building standards skill."
    )
    parser.add_argument("--skill-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-workbook", type=Path, required=True)
    parser.add_argument("--validation-set", type=Path, required=True)
    args = parser.parse_args(argv)
    result = build_package(
        skill_root=args.skill_root,
        output_zip=args.output,
        audit_workbook=args.audit_workbook,
        validation_set=args.validation_set,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
