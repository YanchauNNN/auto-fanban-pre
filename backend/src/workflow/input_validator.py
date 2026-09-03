from __future__ import annotations

from ..config import BusinessSpec, load_spec
from ..models import AccountSnapshot, PersonnelSnapshot


class WorkflowInputValidator:
    def __init__(self, spec: BusinessSpec | None = None) -> None:
        self.spec = spec or load_spec()
        self.workflow_cfg = dict(self.spec.get_management_features().get("workflow") or {})

    def validate_for_initiator(self, personnel_snapshot: PersonnelSnapshot, initiator: AccountSnapshot) -> list[str]:
        """Validate active workflow participants, preserving historical IED metadata."""
        active_fields = {str(node["assignee_source"]) for node in self.workflow_cfg["nodes"]}
        active = PersonnelSnapshot(members={
            key: member for key, member in personnel_snapshot.members.items() if key in active_fields
        })
        errors = self.validate_submit(active)
        for key, member in active.members.items():
            if member.matched_account == initiator.account_id:
                errors.append(f"workflow_role_duplicate:initiator:{key}")
        return errors

    def validate_submit(self, personnel_snapshot: PersonnelSnapshot) -> list[str]:
        errors: list[str] = []
        members = personnel_snapshot.members
        one_review_cfg = dict(self.workflow_cfg.get('one_review') or {})
        checked_by_key = str(one_review_cfg.get('assignee_source') or 'ied_checked_by')
        require_checked_by = bool(one_review_cfg.get('require_checked_by'))
        if require_checked_by:
            checked = members.get(checked_by_key)
            if checked is None or checked.status != 'matched' or not checked.matched_account:
                errors.append('ied_checked_by_required')
        for field_name, personnel in members.items():
            if personnel.status in {'invalid', 'ambiguous'}:
                errors.append(f'{field_name}:{personnel.errors[0] if personnel.errors else personnel.status}')
        unique_fields = list((self.workflow_cfg.get('deduplication_rules') or {}).get('unique_role_fields') or [])
        matched_accounts: dict[str, str] = {}
        for field_name in unique_fields:
            personnel = members.get(field_name)
            if personnel is None or not personnel.matched_account:
                continue
            if personnel.matched_account in matched_accounts:
                errors.append(f'workflow_role_duplicate:{matched_accounts[personnel.matched_account]}:{field_name}')
            else:
                matched_accounts[personnel.matched_account] = field_name
        return errors
