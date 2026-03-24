from __future__ import annotations

from ..models import AccountSnapshot, TaskGroup


class WorkloadQueries:
    def personal(self, account: AccountSnapshot, groups: list[TaskGroup]) -> dict[str, object]:
        entries = []
        total = 0.0
        for group in groups:
            for entry in group.workload.contributor_entries:
                if entry.account_id != account.account_id:
                    continue
                payload = entry.model_dump(mode='json')
                payload['group_id'] = group.group_id
                entries.append(payload)
                total += float(entry.workload_a1)
        return {'scope': 'me', 'total_workload_a1': round(total, 2), 'entries': entries}

    def office(self, account: AccountSnapshot, groups: list[TaskGroup]) -> dict[str, object]:
        entries = []
        total = 0.0
        for group in groups:
            if group.owner_snapshot is None or group.owner_snapshot.creator_office != account.office_name:
                continue
            for entry in group.workload.contributor_entries:
                payload = entry.model_dump(mode='json')
                payload['group_id'] = group.group_id
                entries.append(payload)
                total += float(entry.workload_a1)
        return {'scope': 'office', 'office_name': account.office_name, 'total_workload_a1': round(total, 2), 'entries': entries}

    def institute(self, groups: list[TaskGroup]) -> dict[str, object]:
        entries = []
        total = 0.0
        for group in groups:
            for entry in group.workload.contributor_entries:
                payload = entry.model_dump(mode='json')
                payload['group_id'] = group.group_id
                entries.append(payload)
                total += float(entry.workload_a1)
        return {'scope': 'institute', 'total_workload_a1': round(total, 2), 'entries': entries}

    def admin(self, groups: list[TaskGroup]) -> dict[str, object]:
        totals: dict[str, float] = {}
        for group in groups:
            for entry in group.workload.contributor_entries:
                key = entry.account_id or 'unknown'
                totals[key] = round(totals.get(key, 0.0) + float(entry.workload_a1), 2)
        return {'scope': 'admin', 'totals_by_account': totals}
