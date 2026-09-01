from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import RuntimeConfig
from src.config.runtime_config import ManagementRuntimeConfig


def test_runtime_yaml_configures_task_group_reconciliation_interval() -> None:
    repo_root = Path(__file__).resolve().parents[3]

    config = RuntimeConfig.from_yaml(repo_root / "documents" / "参数规范_运行期.yaml")

    assert config.management.task_group_reconciliation_interval_seconds == 30
    assert config.management.task_group_lock_timeout_seconds == 5.0
    assert config.management.task_group_lock_poll_interval_seconds == 0.05
    assert config.management.replacement_cleanup_claim_ttl_seconds == 300.0


@pytest.mark.parametrize(
    "field_name",
    [
        "task_group_reconciliation_interval_seconds",
        "task_group_lock_timeout_seconds",
        "task_group_lock_poll_interval_seconds",
        "replacement_cleanup_claim_ttl_seconds",
    ],
)
def test_task_group_concurrency_runtime_values_must_be_positive(field_name: str) -> None:
    with pytest.raises(ValidationError):
        ManagementRuntimeConfig(**{field_name: 0})
