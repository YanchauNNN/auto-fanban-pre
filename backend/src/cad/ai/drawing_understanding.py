from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

INTERNAL_CODE_RE = re.compile(
    r"\b(?P<project_no>\d{4})(?P<unit_no>[1-9])?[A-Z]{2,4}-[A-Z]{2,5}\d{2}-\d{3}\b"
)
EXTERNAL_CODE_RE = re.compile(r"\b[A-Z0-9]{19}\b")
PROJECT_NO_RE = re.compile(r"\b(?:1818|1907|1915|1916|2016|2026|2035|1418)\b")
SCALE_RE = re.compile(r"(?:^|[^\d])(?:1\s*[:/]\s*\d{1,5}|\d{1,5}\s*[:/]\s*1)(?:$|[^\d])")
WALL_MARK_RE = re.compile(r"(?:墙|WALL)?[A-Z]?\d{3,5}(?:[A-Z])?")
SINGLE_GRID_RE = re.compile(r"^[A-Z]$|^\d{1,2}$")

TITLE_KEYWORDS = (
    "图",
    "平面",
    "剖面",
    "模板",
    "配筋",
    "布置",
    "详图",
    "索引",
    "节点",
)


def classify_text_semantics(elements: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for element in elements:
        item = dict(element)
        text = _normalize_text(item.get("text"))
        item["semantic_tags"] = _classify_text(text)
        tagged.append(item)
    return tagged


def summarize_element_package(package: Mapping[str, Any]) -> dict[str, Any]:
    drawings = [item for item in package.get("drawings", []) if isinstance(item, Mapping)]
    layer_counts: Counter[str] = Counter()
    semantic_counts: Counter[str] = Counter()
    frame_count = 0
    ok_count = 0
    failed_count = 0

    for drawing in drawings:
        status = str(drawing.get("status") or "").lower()
        if status == "ok":
            ok_count += 1
        elif status == "failed":
            failed_count += 1

        frames = drawing.get("frames", [])
        if isinstance(frames, list):
            frame_count += len(frames)

        for layer in drawing.get("layers", []):
            if not isinstance(layer, Mapping):
                continue
            name = str(layer.get("name") or "").strip()
            count = _to_int(layer.get("count"))
            if name and count > 0:
                layer_counts[name] += count

        for text_element in drawing.get("text_elements", []):
            if not isinstance(text_element, Mapping):
                continue
            for tag in text_element.get("semantic_tags", []):
                semantic_counts[str(tag)] += 1

    return {
        "drawing_count": len(drawings),
        "ok_count": ok_count,
        "failed_count": failed_count,
        "frame_count": frame_count,
        "top_layers": [
            {"name": name, "count": count}
            for name, count in sorted(layer_counts.items(), key=lambda item: (-item[1], item[0]))[:20]
        ],
        "semantic_tag_counts": dict(sorted(semantic_counts.items())),
    }


def answer_package_question(package: Mapping[str, Any], question: str) -> dict[str, Any]:
    normalized_question = _normalize_text(question)
    summary = package.get("summary") if isinstance(package.get("summary"), Mapping) else {}

    if "多少" in normalized_question and "图框" in normalized_question:
        drawing_count = _to_int(summary.get("drawing_count"))
        frame_count = _to_int(summary.get("frame_count"))
        if not drawing_count or not frame_count:
            derived = summarize_element_package(package)
            drawing_count = _to_int(derived.get("drawing_count"))
            frame_count = _to_int(derived.get("frame_count"))
        return {
            "answer": f"共 {drawing_count} 张输入图纸，识别到 {frame_count} 个图框。",
            "evidence": [{"summary": {"drawing_count": drawing_count, "frame_count": frame_count}}],
        }

    if "标题" in normalized_question or "图纸名称" in normalized_question:
        titles = _collect_titles(package)
        if not titles:
            return {"answer": "当前元素包没有识别到图纸标题。", "evidence": []}
        rendered = "；".join(
            f"{item['internal_code']}：{item['title']}" if item["internal_code"] else item["title"]
            for item in titles
        )
        return {
            "answer": f"识别到 {len(titles)} 个标题：{rendered}。",
            "evidence": titles,
        }

    return {
        "answer": "当前本地问答雏形只支持图框数量和图纸标题查询。",
        "evidence": [],
    }


def derive_project_unit_from_internal_codes(frames: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    prefixes: Counter[tuple[str, str]] = Counter()
    for frame in frames:
        titleblock = frame.get("titleblock")
        if not isinstance(titleblock, Mapping):
            continue
        internal_code = _strip_spaces(str(titleblock.get("internal_code") or "")).upper()
        match = INTERNAL_CODE_RE.search(internal_code)
        if match is None:
            continue
        unit_no = match.group("unit_no") or ""
        prefixes[(match.group("project_no"), unit_no)] += 1

    if not prefixes:
        return {"project_no": None, "unit_no": None, "evidence_count": 0}

    (project_no, unit_no), count = max(
        prefixes.items(),
        key=lambda item: (item[1], item[0][0], item[0][1]),
    )
    return {"project_no": project_no, "unit_no": unit_no or None, "evidence_count": count}


def _classify_text(text: str) -> list[str]:
    tags: list[str] = []
    compact = _strip_spaces(text).upper()

    if INTERNAL_CODE_RE.search(compact):
        tags.extend(["internal_code", "project_no"])
        match = INTERNAL_CODE_RE.search(compact)
        if match and match.group("unit_no"):
            tags.append("unit_no")
    elif PROJECT_NO_RE.search(compact):
        tags.append("project_no")

    if EXTERNAL_CODE_RE.search(compact):
        tags.append("external_code")

    if any(keyword in text for keyword in TITLE_KEYWORDS) and len(compact) >= 4:
        tags.append("drawing_title_candidate")

    if WALL_MARK_RE.search(compact) and ("墙" in text or "WALL" in compact):
        tags.append("wall_mark")

    if SCALE_RE.search(compact) or "比例" in text:
        tags.append("scale")

    if _looks_like_page_marker(text, compact):
        tags.append("page_marker")

    if not tags and SINGLE_GRID_RE.fullmatch(compact):
        tags.append("grid_or_revision_marker")

    return _dedupe(tags)


def _collect_titles(package: Mapping[str, Any]) -> list[dict[str, str]]:
    titles: list[dict[str, str]] = []
    for drawing in package.get("drawings", []):
        if not isinstance(drawing, Mapping):
            continue
        for frame in drawing.get("frames", []):
            if not isinstance(frame, Mapping):
                continue
            titleblock = frame.get("titleblock")
            if not isinstance(titleblock, Mapping):
                continue
            title = str(titleblock.get("title_cn") or titleblock.get("title_en") or "").strip()
            if not title:
                continue
            titles.append(
                {
                    "source_file": str(drawing.get("source_file") or ""),
                    "internal_code": str(titleblock.get("internal_code") or "").strip(),
                    "title": title,
                }
            )
    return titles


def _looks_like_page_marker(text: str, compact: str) -> bool:
    if ("第" in text and "张" in text) or ("共" in text and "张" in text):
        return True
    return "PAGE" in compact and ("OF" in compact or "/" in compact)


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _strip_spaces(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _to_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
