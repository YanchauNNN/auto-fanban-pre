from __future__ import annotations

from src.cad.drawing_understanding import (
    answer_package_question,
    classify_text_semantics,
    derive_project_unit_from_internal_codes,
    summarize_element_package,
)


def test_classify_text_semantics_labels_common_drawing_tokens() -> None:
    elements = [
        {"text": "20161NH-JGS03-009", "source": "msp:TEXT"},
        {"text": "墙N2001(一)模板图", "source": "msp:MTEXT"},
        {"text": "1/100", "source": "msp:TEXT"},
        {"text": "第 2 张 共 3 张", "source": "msp:TEXT"},
        {"text": "F", "source": "msp:virtual:TEXT"},
    ]

    tagged = classify_text_semantics(elements)

    assert tagged[0]["semantic_tags"] == ["internal_code", "project_no", "unit_no"]
    assert tagged[1]["semantic_tags"] == ["drawing_title_candidate", "wall_mark"]
    assert tagged[2]["semantic_tags"] == ["scale"]
    assert tagged[3]["semantic_tags"] == ["page_marker"]
    assert tagged[4]["semantic_tags"] == ["grid_or_revision_marker"]


def test_summarize_element_package_counts_frames_layers_and_semantics() -> None:
    package = {
        "drawings": [
            {
                "source_file": "sample-a.dwg",
                "status": "ok",
                "frames": [{"frame_id": "f1"}, {"frame_id": "f2"}],
                "layers": [{"name": "图框", "count": 3}],
                "text_elements": [
                    {"semantic_tags": ["internal_code", "project_no"]},
                    {"semantic_tags": ["drawing_title_candidate"]},
                ],
            },
            {
                "source_file": "sample-b.dwg",
                "status": "failed",
                "frames": [],
                "layers": [{"name": "wall", "count": 5}],
                "text_elements": [],
            },
        ]
    }

    summary = summarize_element_package(package)

    assert summary["drawing_count"] == 2
    assert summary["ok_count"] == 1
    assert summary["failed_count"] == 1
    assert summary["frame_count"] == 2
    assert summary["top_layers"] == [{"name": "wall", "count": 5}, {"name": "图框", "count": 3}]
    assert summary["semantic_tag_counts"] == {
        "drawing_title_candidate": 1,
        "internal_code": 1,
        "project_no": 1,
    }


def test_answer_package_question_returns_grounded_counts_and_titles() -> None:
    package = {
        "summary": {"drawing_count": 1, "frame_count": 2},
        "drawings": [
            {
                "source_file": "sample.dwg",
                "frames": [
                    {
                        "titleblock": {
                            "internal_code": "20161NH-JGS03-009",
                            "title_cn": "核辅助厂房墙模板图",
                        }
                    },
                    {
                        "titleblock": {
                            "internal_code": "20161NH-JGS03-010",
                            "title_cn": "核辅助厂房梁配筋图",
                        }
                    },
                ],
            }
        ],
    }

    count_answer = answer_package_question(package, "这个元素包里有多少图框？")
    title_answer = answer_package_question(package, "有哪些图纸标题？")

    assert count_answer["answer"] == "共 1 张输入图纸，识别到 2 个图框。"
    assert title_answer["answer"] == (
        "识别到 2 个标题：20161NH-JGS03-009：核辅助厂房墙模板图；"
        "20161NH-JGS03-010：核辅助厂房梁配筋图。"
    )


def test_derive_project_unit_from_internal_codes_uses_majority_prefix() -> None:
    frames = [
        {"titleblock": {"internal_code": "18185NR-JGS50-001"}},
        {"titleblock": {"internal_code": "18185NR-JGS50-002"}},
        {"titleblock": {"internal_code": "20161NH-JGS03-001"}},
        {"titleblock": {"internal_code": ""}},
    ]

    assert derive_project_unit_from_internal_codes(frames) == {
        "project_no": "1818",
        "unit_no": "5",
        "evidence_count": 2,
    }
