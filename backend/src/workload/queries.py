from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from ..models import AccountSnapshot, TaskGroup
from ..task_groups.display_name import build_task_group_display_fields


@dataclass(frozen=True)
class WorkloadQueryFilters:
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None
    valid_only: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "status": self.status,
            "valid_only": self.valid_only,
        }


class WorkloadQueries:
    def personal(
        self,
        account: AccountSnapshot,
        groups: list[TaskGroup],
        filters: WorkloadQueryFilters | None = None,
    ) -> dict[str, object]:
        active_filters = filters or WorkloadQueryFilters()
        entries = []
        total = 0.0
        for group in groups:
            if not self._group_matches(group, active_filters):
                continue
            group_display_fields = build_task_group_display_fields(group)
            for entry in group.workload.contributor_entries:
                if entry.account_id != account.account_id or not self._entry_matches(entry.settled_at, active_filters):
                    continue
                payload = entry.model_dump(mode='json')
                payload['group_id'] = group.group_id
                payload['group_display_name'] = group_display_fields['display_name']
                payload['album_internal_code'] = group_display_fields['album_internal_code']
                payload['settlement_status'] = group.workload.settlement_status.value
                entries.append(payload)
                total += float(entry.workload_a1)
        return {
            'scope': 'me',
            'filters': active_filters.as_dict(),
            'total_workload_a1': round(total, 2),
            'entries': entries,
        }

    def office(
        self,
        account: AccountSnapshot,
        groups: list[TaskGroup],
        filters: WorkloadQueryFilters | None = None,
    ) -> dict[str, object]:
        active_filters = filters or WorkloadQueryFilters()
        entries = []
        total = 0.0
        for group in groups:
            if group.owner_snapshot is None or group.owner_snapshot.creator_office != account.office_name:
                continue
            if not self._group_matches(group, active_filters):
                continue
            group_display_fields = build_task_group_display_fields(group)
            for entry in group.workload.contributor_entries:
                if not self._entry_matches(entry.settled_at, active_filters):
                    continue
                payload = entry.model_dump(mode='json')
                payload['group_id'] = group.group_id
                payload['group_display_name'] = group_display_fields['display_name']
                payload['album_internal_code'] = group_display_fields['album_internal_code']
                payload['settlement_status'] = group.workload.settlement_status.value
                entries.append(payload)
                total += float(entry.workload_a1)
        return {
            'scope': 'office',
            'filters': active_filters.as_dict(),
            'office_name': account.office_name,
            'total_workload_a1': round(total, 2),
            'entries': entries,
        }

    def institute(
        self,
        groups: list[TaskGroup],
        filters: WorkloadQueryFilters | None = None,
    ) -> dict[str, object]:
        active_filters = filters or WorkloadQueryFilters()
        entries = []
        total = 0.0
        for group in groups:
            if not self._group_matches(group, active_filters):
                continue
            group_display_fields = build_task_group_display_fields(group)
            for entry in group.workload.contributor_entries:
                if not self._entry_matches(entry.settled_at, active_filters):
                    continue
                payload = entry.model_dump(mode='json')
                payload['group_id'] = group.group_id
                payload['group_display_name'] = group_display_fields['display_name']
                payload['album_internal_code'] = group_display_fields['album_internal_code']
                payload['settlement_status'] = group.workload.settlement_status.value
                entries.append(payload)
                total += float(entry.workload_a1)
        return {
            'scope': 'institute',
            'filters': active_filters.as_dict(),
            'total_workload_a1': round(total, 2),
            'entries': entries,
        }

    def admin(
        self,
        groups: list[TaskGroup],
        filters: WorkloadQueryFilters | None = None,
    ) -> dict[str, object]:
        active_filters = filters or WorkloadQueryFilters()
        totals: dict[str, float] = {}
        entries: list[dict[str, object]] = []
        for group in groups:
            if not self._group_matches(group, active_filters):
                continue
            group_display_fields = build_task_group_display_fields(group)
            for entry in group.workload.contributor_entries:
                if not self._entry_matches(entry.settled_at, active_filters):
                    continue
                key = entry.account_id or 'unknown'
                totals[key] = round(totals.get(key, 0.0) + float(entry.workload_a1), 2)
                payload = entry.model_dump(mode='json')
                payload['group_id'] = group.group_id
                payload['group_display_name'] = group_display_fields['display_name']
                payload['album_internal_code'] = group_display_fields['album_internal_code']
                payload['settlement_status'] = group.workload.settlement_status.value
                entries.append(payload)
        return {
            'scope': 'admin',
            'filters': active_filters.as_dict(),
            'entries': entries,
            'totals_by_account': totals,
        }

    @staticmethod
    def _group_matches(group: TaskGroup, filters: WorkloadQueryFilters) -> bool:
        if filters.valid_only and group.workload.settlement_status.value != 'settled':
            return False
        status = (filters.status or '').strip().lower()
        if not status:
            return True
        return status in {
            group.workload.settlement_status.value.lower(),
            group.workflow.status.value.lower(),
            group.archive.status.value.lower(),
        }

    @staticmethod
    def _entry_matches(settled_at: datetime | None, filters: WorkloadQueryFilters) -> bool:
        if filters.start_date is None and filters.end_date is None:
            return True
        if settled_at is None:
            return False
        settled_date = settled_at.date()
        if filters.start_date and settled_date < filters.start_date:
            return False
        if filters.end_date and settled_date > filters.end_date:
            return False
        return True
