from __future__ import annotations

import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from src.ai.chat_client import (
    ChatClientTimeout,
    ChatCompletionResult,
)
from src.ai.rebar_suggestion_task import (
    RebarSuggestionTask,
    RebarSuggestionTaskLimits,
)
from src.ai.reinforcement_task_normalizer import (
    ReinforcementTaskNormalizer,
    ReinforcementTaskNormalizerLimits,
)
from src.calculation_book.executor import (
    CalculationBookJobExecutor,
    ReinforcementNormalizerMetadata,
)
from src.calculation_book.ocr import StressLegendReading
from src.calculation_book.processor import (
    CalculationBookAssets,
    CalculationBookProcessor,
)

from .test_calculation_book_ai_normalization import (
    FakeStructuredGateway,
    TestClient,
    _build_archive,
    _configure_api_env,
    _params,
    _poll_job,
    _write_image,
)


class FakeRebarSuggestionGateway:
    """A deterministic fake model behind the real structured Skill adapter."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.item_call_counts: Counter[str] = Counter()

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatCompletionResult:
        assert tools is None
        system_payload = json.loads(str(messages[0]["content"]))
        user_payload = json.loads(str(messages[1]["content"]))
        request = user_payload["request"]
        items = request["items"]
        assert len(items) == 1
        item = items[0]
        item_id = str(item["item_id"])
        self.item_call_counts[item_id] += 1
        call_index = self.item_call_counts[item_id]
        self.calls.append(
            {
                "item_id": item_id,
                "call_index": call_index,
                "repair_context": item.get("repair_context"),
                "candidate_ids": [
                    candidate["candidate_id"]
                    for candidate in item["candidates"]
                ],
                "skill_id": system_payload["skill_bundle"]["skill_id"],
            }
        )

        if item_id.endswith(":Z"):
            raise ChatClientTimeout("deterministic integration timeout")

        candidates = item["candidates"]
        selected = (
            candidates[-1]
            if item_id.endswith(":X") and call_index == 1
            else candidates[0]
        )
        return ChatCompletionResult(
            content=json.dumps(
                {
                    "schema_version": "smx-rebar-1",
                    "items": [
                        {
                            "item_id": item_id,
                            "status": "selected",
                            "selected_candidate_id": selected[
                                "candidate_id"
                            ],
                            "reason": "deterministic integration selection",
                            "review_reasons": [],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            raw_model="fake-rebar-suggestion-gateway",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )


def _nonzero_reading(_direction: str) -> StressLegendReading:
    return StressLegendReading(
        smn=0,
        smx=800,
        legend_values=tuple(800 * index / 9 for index in range(10)),
    )


def _build_ai_archive(tmp_path: Path) -> Path:
    source = tmp_path / "ai-suggestion-source"
    for name in (
        "N5012-X.png",
        "N5012-Y.png",
        "N5012-Z.png",
        "01/layout.png",
        "02/model.png",
    ):
        _write_image(source / name)
    archive_path = tmp_path / "ai-suggestion.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())
    return archive_path


def _preflight(
    client: TestClient,
    archive: Path,
    *,
    reinforcement_source: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/jobs/calculation-books/preflight",
        data={
            "include_slab_stress": "false",
            "reinforcement_source": reinforcement_source,
        },
        files={
            "archive": (
                archive.name,
                archive.read_bytes(),
                "application/zip",
            )
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_and_wait(
    client: TestClient,
    *,
    preflight: dict[str, Any],
    reinforcement_source: str,
    confirm_ai_normalization: bool = False,
) -> tuple[str, dict[str, Any]]:
    response = client.post(
        "/api/jobs/calculation-books",
        data={
            "params_json": json.dumps(
                {
                    **_params(include_slab_stress=False),
                    "preflight_token": preflight["preflight_token"],
                    "reinforcement_source": reinforcement_source,
                    "confirm_ai_normalization": confirm_ai_normalization,
                },
                ensure_ascii=False,
            )
        },
    )
    assert response.status_code == 201, response.text
    job_id = response.json()["jobs"][0]["job_id"]
    detail = _poll_job(client, job_id)
    assert detail["status"] == "succeeded", detail
    return job_id, detail


def test_formal_modes_ai_targeted_repair_and_local_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "FANBAN_CALCULATION_BOOK__AI_SUGGESTION__BATCH_SIZE",
        "1",
    )
    repo_root = _configure_api_env(monkeypatch, tmp_path)
    normalizer_gateway = FakeStructuredGateway(
        {
            "schema_version": "hybrid-1",
            "source_row_count": 1,
            "patch_rows": [
                {
                    "kind": "wall",
                    "status": "needs_review",
                    "wall_id": "N5012",
                    "X": None,
                    "Y": "1D28间距200",
                    "Z": "1C14间距400*400",
                    "reason": "水平筋写法无法确定",
                    "blank_fields": ["X"],
                    "source_sheet": "墙体配筋",
                    "source_row": 2,
                    "source_cells": {
                        "wall": "A2",
                        "X": "B2",
                        "Y": "C2",
                        "Z": "D2",
                    },
                }
            ],
            "review_sources": [],
        }
    )
    normalizer = ReinforcementTaskNormalizer(
        client=normalizer_gateway,
        skill_root=(
            repo_root / "tools" / "ai" / "reinforcement-table-normalizer"
        ),
        limits=ReinforcementTaskNormalizerLimits(
            max_non_empty_cells=100,
            max_snapshot_chars=100_000,
            max_skill_chars=100_000,
        ),
    )
    rebar_gateway = FakeRebarSuggestionGateway()
    rebar_task = RebarSuggestionTask(
        client=rebar_gateway,
        model="fake-structured-rebar",
        skill_root=(
            repo_root / "tools" / "ai" / "recommend-rebar-from-smx"
        ),
        skill_version="1.0.0",
        limits=RebarSuggestionTaskLimits(),
    )
    processor = CalculationBookProcessor(
        assets=CalculationBookAssets(
            template_root=(
                repo_root / "documents_bin" / "calculation_book"
            ),
        ),
        ocr_recognizer=lambda _path, direction: _nonzero_reading(direction),
    )
    executor = CalculationBookJobExecutor(
        processor=processor,
        normalizer=normalizer,
        normalizer_metadata=ReinforcementNormalizerMetadata(
            model="fake-structured-normalizer",
            profile="integration",
        ),
        rebar_suggestion_invoker=rebar_task,
    )

    import API.app.runtime as runtime_module
    from API.app.main import create_app
    from API.app.runtime import PipelineJobProcessor

    monkeypatch.setattr(
        runtime_module,
        "recognize_stress_legend",
        lambda _path, *, direction, **_kwargs: _nonzero_reading(direction),
    )
    app = create_app(
        job_processor=PipelineJobProcessor(
            calculation_book_executor_factory=lambda: executor,
        )
    )
    standard = _build_archive(
        tmp_path,
        standard=True,
        include_slab_figures=False,
    )
    nonstandard = _build_archive(
        tmp_path,
        standard=False,
        include_slab_figures=False,
    )
    ai_archive = _build_ai_archive(tmp_path)

    with TestClient(app) as client:
        standard_preflight = _preflight(
            client,
            standard,
            reinforcement_source="provided",
        )
        assert standard_preflight["requires_ai_normalization"] is False
        _, standard_detail = _create_and_wait(
            client,
            preflight=standard_preflight,
            reinforcement_source="provided",
        )
        assert standard_detail["calculation_book_output"]["ai_normalized"] is False
        assert normalizer_gateway.calls == []
        assert rebar_gateway.calls == []

        nonstandard_preflight = _preflight(
            client,
            nonstandard,
            reinforcement_source="provided",
        )
        assert nonstandard_preflight["requires_ai_normalization"] is True
        _, nonstandard_detail = _create_and_wait(
            client,
            preflight=nonstandard_preflight,
            reinforcement_source="provided",
            confirm_ai_normalization=True,
        )
        assert nonstandard_detail["calculation_book_output"]["ai_normalized"] is True
        assert len(normalizer_gateway.calls) == 1
        assert rebar_gateway.calls == []

        ai_preflight = _preflight(
            client,
            ai_archive,
            reinforcement_source="ai_suggested",
        )
        assert ai_preflight["requires_ai_recommendation"] is True
        assert ai_preflight["reinforcement_workbook"] is None
        assert ai_preflight["image_wall_group_count"] == 1
        assert ai_preflight["wall_direction_figure_count"] == 3
        ai_job_id, ai_detail = _create_and_wait(
            client,
            preflight=ai_preflight,
            reinforcement_source="ai_suggested",
        )

        assert len(normalizer_gateway.calls) == 1
        assert rebar_gateway.item_call_counts == {
            "wall:N5012:X": 2,
            "wall:N5012:Y": 1,
            "wall:N5012:Z": 3,
        }
        x_calls = [
            call
            for call in rebar_gateway.calls
            if call["item_id"] == "wall:N5012:X"
        ]
        assert x_calls[0]["repair_context"] is None
        assert x_calls[1]["repair_context"] == {
            "round": 1,
            "excluded_candidate_ids": [
                x_calls[0]["candidate_ids"][-1]
            ],
            "errors": [
                {
                    "code": "NOT_MINIMUM_EXCESS",
                    "candidate_id": x_calls[0]["candidate_ids"][-1],
                    "message": (
                        "同一优先级内存在未舍入超额面积更小的候选；"
                        "更优候选为 "
                        + ", ".join(x_calls[0]["candidate_ids"][:-1])
                    ),
                }
            ],
        }
        assert all(call["skill_id"] == "recommend-rebar-from-smx" for call in rebar_gateway.calls)

        output = ai_detail["calculation_book_output"]
        summary = output["ai_rebar_suggestion"]
        assert output["reinforcement_source"] == "ai_suggested"
        assert summary["model"] == "fake-structured-rebar"
        assert summary["skill_id"] == "recommend-rebar-from-smx"
        assert summary["skill_version"] == "1.0.0"
        assert len(summary["skill_sha256"]) == 64
        assert summary["call_count"] == 6
        assert summary["repair_round_count"] == 1
        assert summary["suggested_direction_count"] == 2
        assert summary["blank_direction_count"] == 1
        assert (
            summary["suggested_direction_count"]
            + summary["blank_direction_count"]
            == ai_preflight["wall_direction_figure_count"]
        )
        assert output["warnings"] == [
            {
                "code": "AI_BASE_FAILURE_LIMIT",
                "scope": "wall",
                "identity": "N5012",
                "direction": "Z",
                "source_sheet": None,
                "source_row": None,
                "source_cells": {},
                "reason": (
                    "人工智能连续三次调用或协议失败，"
                    "当前方向已留空，请人工复核"
                ),
                "blank_fields": ["Z"],
            }
        ]

        word = client.get(
            f"/api/jobs/{ai_job_id}/download/calculation-book"
        )
        assert word.status_code == 200
        assert word.content.startswith(b"PK")
        log = client.get(
            f"/api/jobs/{ai_job_id}/download/calculation-book-log"
        )
        assert log.status_code == 200
        assert log.headers["content-type"] == "text/plain; charset=utf-8"
        records = [json.loads(line) for line in log.text.splitlines()]
        assert records[-1]["event"] == "task_completed"
        assert sum(
            record["event"] == "ai_call_failed"
            and record["details"]["item_ids"] == ["wall:N5012:Z"]
            for record in records
        ) == 3
        assert any(
            record["event"] == "validation_completed"
            and record["details"].get("item_id") == "wall:N5012:X"
            and record["details"].get("status") == "invalid"
            and record["details"].get("error_codes")
            == ["NOT_MINIMUM_EXCESS"]
            for record in records
        )
