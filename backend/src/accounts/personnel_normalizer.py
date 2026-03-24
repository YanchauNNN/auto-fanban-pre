from __future__ import annotations

from ..models import NormalizedPersonnel, PersonnelSnapshot
from .account_registry import AccountRegistry


class PersonnelNormalizer:
    def __init__(self, registry: AccountRegistry) -> None:
        self.registry = registry

    def normalize(self, field_name: str, raw_value: str | None) -> NormalizedPersonnel:
        text = str(raw_value or "").strip()
        if not text:
            return NormalizedPersonnel(field_name=field_name, raw_value=raw_value, status="empty")

        if "@" in text:
            name_part, account_part = text.split("@", 1)
            by_name = self.registry.find_by_name(name_part.strip())
            if len(by_name) == 1:
                account = by_name[0]
                return NormalizedPersonnel(
                    field_name=field_name,
                    raw_value=text,
                    normalized_value=f"{account.display_name}@{account.account_id}",
                    matched_account=account.account_id,
                    matched_name=account.display_name,
                    match_strategy="name_override_compound",
                    status="matched",
                )
            by_account = self.registry.get_account(account_part.strip())
            if by_account is not None:
                return NormalizedPersonnel(
                    field_name=field_name,
                    raw_value=text,
                    normalized_value=f"{by_account.display_name}@{by_account.account_id}",
                    matched_account=by_account.account_id,
                    matched_name=by_account.display_name,
                    match_strategy="account_from_compound",
                    status="matched",
                )
            return NormalizedPersonnel(
                field_name=field_name,
                raw_value=text,
                status="invalid",
                errors=["ambiguous_name" if len(by_name) > 1 else "unresolved_personnel"],
            )

        by_name = self.registry.find_by_name(text)
        if len(by_name) == 1:
            account = by_name[0]
            return NormalizedPersonnel(
                field_name=field_name,
                raw_value=text,
                normalized_value=f"{account.display_name}@{account.account_id}",
                matched_account=account.account_id,
                matched_name=account.display_name,
                match_strategy="name",
                status="matched",
            )
        if len(by_name) > 1:
            return NormalizedPersonnel(field_name=field_name, raw_value=text, status="ambiguous", errors=["duplicate_name_needs_selection"])

        by_account = self.registry.get_account(text)
        if by_account is not None:
            return NormalizedPersonnel(
                field_name=field_name,
                raw_value=text,
                normalized_value=f"{by_account.display_name}@{by_account.account_id}",
                matched_account=by_account.account_id,
                matched_name=by_account.display_name,
                match_strategy="account",
                status="matched",
            )
        return NormalizedPersonnel(field_name=field_name, raw_value=text, status="invalid", errors=["unresolved_personnel"])

    def normalize_fields(self, values: dict[str, str | None]) -> PersonnelSnapshot:
        return PersonnelSnapshot(members={field_name: self.normalize(field_name, raw_value) for field_name, raw_value in values.items()})
