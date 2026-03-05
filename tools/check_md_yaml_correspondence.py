from __future__ import annotations

import re
from pathlib import Path

import yaml


def _collect_yaml_global_fields(spec: dict) -> dict[str, dict]:
    """适配v2.0 YAML结构，返回 GlobalDocParams 字段及其规则定义"""
    if "doc_generation" in spec:
        doc = spec["doc_generation"]
        params = doc.get("params", {})
        fields: dict[str, dict] = {}
        for category in [
            "project",
            "from_titleblock",
            "cover",
            "catalog",
            "design",
            "ied",
        ]:
            if category in params:
                group = params[category]
                if isinstance(group, dict):
                    for key, rule in group.items():
                        if isinstance(rule, dict):
                            fields[key] = rule
                        else:
                            fields[key] = {}
        return fields
    # 兜底旧版路径
    if "sections" in spec and "doc_generation_spec" in spec["sections"]:
        doc = spec["sections"]["doc_generation_spec"]
        fields = doc["objects"]["GlobalDocParams"]["fields"]
        return {
            k: (v if isinstance(v, dict) else {})
            for k, v in fields.items()
        }
    raise KeyError("无法找到 doc_generation 或 sections.doc_generation_spec")


def _collect_yaml_derived_keys(spec: dict) -> set[str]:
    """适配v2.0 YAML结构"""
    if "doc_generation" in spec:
        doc = spec["doc_generation"]
        derived = doc.get("derivations", {})
        return set(derived.keys())
    # 兜底旧版路径
    if "sections" in spec and "doc_generation_spec" in spec["sections"]:
        doc = spec["sections"]["doc_generation_spec"]
        derived = doc.get("derived_rules", {})
        return set(derived.keys())
    return set()


def _collect_yaml_titleblock_keys(spec: dict) -> set[str]:
    """适配v2.0 YAML结构"""
    if "doc_generation" in spec:
        doc = spec["doc_generation"]
        # v2.0中titleblock字段在frame_meta.titleblock下
        frame_meta = doc.get("frame_meta", {})
        titleblock = frame_meta.get("titleblock", {})
        return set(titleblock.keys())
    # 兜底旧版路径
    if "sections" in spec and "doc_generation_spec" in spec["sections"]:
        doc = spec["sections"]["doc_generation_spec"]
        fields = doc["objects"]["TitleblockFields"]["fields"]
        return set(fields.keys())
    return set()


def _extract_md_globaldocparams_table_keys(md: str) -> set[str]:
    """
    Parse the Markdown table under section:
      ### 2.2 `GlobalDocParams`（用户输入，全局字段）
    and extract the first-column backticked keys only.
    """
    lines = md.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("### 2.2"):
            start = i
            break
    if start is None:
        return set()

    hdr = None
    for i in range(start, min(start + 220, len(lines))):
        if lines[i].strip().startswith("| Key |"):
            hdr = i
            break
    if hdr is None:
        return set()

    keys: set[str] = set()
    for i in range(hdr + 2, len(lines)):  # skip header + separator
        line = lines[i].rstrip()
        if not line.startswith("|"):
            break
        parts = [p.strip() for p in line.strip("|").split("|")]
        if not parts:
            continue
        col0 = parts[0]
        m = re.search(r"`([A-Za-z_][A-Za-z0-9_]*)`", col0)
        if m:
            keys.add(m.group(1))
    return keys


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    md_path = repo_root / "documents" / "参数表.md"
    yaml_path = repo_root / "documents" / "参数规范.yaml"

    md = md_path.read_text(encoding="utf-8")
    spec = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    global_fields = _collect_yaml_global_fields(spec)
    global_keys = set(global_fields.keys())
    titleblock_keys = _collect_yaml_titleblock_keys(spec)
    derived_keys = _collect_yaml_derived_keys(spec)

    md_key_like = _extract_md_globaldocparams_table_keys(md)

    yaml_all = global_keys | titleblock_keys | derived_keys

    md_only = sorted(md_key_like - yaml_all)
    # Ignore YAML deprecated fields (they may be intentionally omitted from MD)
    deprecated = set()
    if "doc_generation" in spec:
        doc = spec["doc_generation"]
        params = doc.get("params", {})
        for category in params.values():
            if isinstance(category, dict):
                for k, v in category.items():
                    if isinstance(v, dict) and v.get("deprecated") is True:
                        deprecated.add(k)
    elif "sections" in spec and "doc_generation_spec" in spec["sections"]:
        doc = spec["sections"]["doc_generation_spec"]
        gfields = doc["objects"]["GlobalDocParams"]["fields"]
        deprecated = {
            k
            for k, v in gfields.items()
            if isinstance(v, dict) and v.get("deprecated") is True
        }

    required_global_keys = {
        k
        for k, v in global_fields.items()
        if isinstance(v, dict)
        and (
            v.get("required") is True
            or ("required_when" in v and str(v.get("required_when", "")).strip() != "")
        )
    }
    optional_global_keys = global_keys - required_global_keys

    yaml_only_global_required = sorted((required_global_keys - deprecated) - md_key_like)
    yaml_only_global_optional = sorted((optional_global_keys - deprecated) - md_key_like)

    print("YAML GlobalDocParams keys:", len(global_keys))
    print("YAML TitleblockFields keys:", len(titleblock_keys))
    print("YAML derived_rules keys:", len(derived_keys))
    print("MD GlobalDocParams table keys:", len(md_key_like))
    print()

    print(
        "MD-only keys (declared in MD GlobalDocParams table but not in YAML keys):",
        len(md_only),
    )
    for k in md_only:
        print("  -", k)
    print()

    print(
        "YAML GlobalDocParams required/required_when missing in MD table (excluding deprecated):",
        len(yaml_only_global_required),
    )
    for k in yaml_only_global_required:
        print("  -", k)
    print()

    print(
        "YAML GlobalDocParams optional(required=false) missing in MD table (info):",
        len(yaml_only_global_optional),
    )
    for k in yaml_only_global_optional:
        print("  -", k)

    # Non-zero exit if there are MD-only keys (declared but not supported by YAML)
    return 1 if md_only else 0


if __name__ == "__main__":
    raise SystemExit(main())
