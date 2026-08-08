from __future__ import annotations

from src.models import TaskGroup
from src.workload.models import WorkloadContributorEntry
from src.workload.queries import WorkloadQueries


def _group_with_workload_entries(*entries: WorkloadContributorEntry) -> TaskGroup:
    group = TaskGroup(group_id="group-workload", project_no="2016")
    group.workload.contributor_entries = list(entries)
    return group


def test_admin_workload_returns_one_total_consistent_with_accounts_and_entries() -> None:
    group = _group_with_workload_entries(
        WorkloadContributorEntry(role_key="initiator", account_id="alice", workload_a1=1.11),
        WorkloadContributorEntry(role_key="one_review", account_id="alice", workload_a1=2.22),
        WorkloadContributorEntry(role_key="two_review", account_id="bob", workload_a1=3.33),
    )

    result = WorkloadQueries().admin([group])

    assert result["total_workload_a1"] == 6.66
    assert result["total_workload_a1"] == round(sum(result["totals_by_account"].values()), 2)
    assert result["total_workload_a1"] == round(
        sum(float(entry["workload_a1"]) for entry in result["entries"]),
        2,
    )


def test_admin_workload_quantizes_each_public_account_total_before_summing() -> None:
    group = _group_with_workload_entries(
        WorkloadContributorEntry(role_key="initiator", account_id="alice", workload_a1=0.004),
        WorkloadContributorEntry(role_key="one_review", account_id="alice", workload_a1=0.004),
    )

    result = WorkloadQueries().admin([group])

    assert result["totals_by_account"] == {"alice": 0.01}
    assert result["total_workload_a1"] == 0.01


def test_admin_workload_total_matches_two_quantized_fractional_account_totals() -> None:
    group = _group_with_workload_entries(
        WorkloadContributorEntry(role_key="initiator", account_id="alice", workload_a1=0.004),
        WorkloadContributorEntry(role_key="one_review", account_id="bob", workload_a1=0.004),
    )

    result = WorkloadQueries().admin([group])

    assert result["totals_by_account"] == {"alice": 0.0, "bob": 0.0}
    assert result["total_workload_a1"] == round(sum(result["totals_by_account"].values()), 2)
    assert result["total_workload_a1"] == 0.0


def test_admin_workload_uses_existing_python_rounding_for_public_totals() -> None:
    group = _group_with_workload_entries(
        WorkloadContributorEntry(role_key="initiator", account_id="alice", workload_a1=2.675),
    )

    result = WorkloadQueries().admin([group])

    assert result["totals_by_account"] == {"alice": 2.67}
    assert result["total_workload_a1"] == 2.67
