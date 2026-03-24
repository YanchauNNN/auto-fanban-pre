from __future__ import annotations

from ..config import BusinessSpec, load_spec
from ..models import AccountSnapshot
from .account_csv_store import AccountCsvStore
from .account_models import (
    AccountCreatePayload,
    AccountRecord,
    AccountUpdatePayload,
    InvalidAccountRow,
)


class AccountRegistry:
    def __init__(self, store: AccountCsvStore | None = None, spec: BusinessSpec | None = None) -> None:
        self.spec = spec or load_spec()
        self.store = store or AccountCsvStore(self.spec)
        features = self.spec.get_management_features()
        self.account_cfg = dict(features.get("account") or {})
        self.field_map = dict(self.account_cfg.get("fields") or {})
        self.valid_roles = {str(item) for item in self.account_cfg.get("valid_roles") or []}
        self.default_password = str(self.account_cfg.get("admin_created_default_password") or "password")

    def list_accounts(self) -> tuple[list[AccountRecord], list[InvalidAccountRow]]:
        rows, _ = self.store.read_rows()
        accounts: list[AccountRecord] = []
        invalid_rows: list[InvalidAccountRow] = []
        seen_accounts: set[str] = set()
        for index, row in enumerate(rows, start=2):
            account, errors = self._parse_row(row, index)
            if account is not None and account.account_id in seen_accounts:
                errors = [*errors, "duplicate_account_id"]
                account.valid = False
                account.errors = errors
            if account is not None:
                seen_accounts.add(account.account_id)
            if errors:
                invalid_rows.append(InvalidAccountRow(row_number=index, raw=row, errors=errors))
            if account is not None:
                accounts.append(account)
        return accounts, invalid_rows

    def list_valid_accounts(self) -> list[AccountRecord]:
        accounts, _ = self.list_accounts()
        return [account for account in accounts if account.valid]

    def get_account(self, account_id: str) -> AccountRecord | None:
        account_key = str(account_id or "").strip()
        if not account_key:
            return None
        for account in self.list_valid_accounts():
            if account.account_id == account_key:
                return account
        return None

    def find_by_name(self, display_name: str) -> list[AccountRecord]:
        name = str(display_name or "").strip()
        if not name:
            return []
        return [account for account in self.list_valid_accounts() if account.display_name == name]

    def verify_password(self, account_id: str, password: str) -> AccountRecord | None:
        account = self.get_account(account_id)
        if account is None:
            return None
        return account if account.password == password else None

    def create_account(self, payload: AccountCreatePayload) -> AccountRecord:
        if self.get_account(payload.account_id) is not None:
            raise ValueError("account_id already exists")
        if payload.role not in self.valid_roles:
            raise ValueError("invalid role")
        rows, headers = self.store.read_rows()
        row = self._build_row(
            office_code=payload.office_code,
            office_name=payload.office_name,
            account_id=payload.account_id,
            display_name=payload.display_name,
            role=payload.role,
            password=payload.password or self.default_password,
        )
        rows.append(row)
        self.store.write_rows(rows, headers or list(row.keys()))
        account = self.get_account(payload.account_id)
        if account is None:
            raise ValueError("failed to create account")
        return account

    def update_account(self, account_id: str, payload: AccountUpdatePayload) -> tuple[AccountRecord, AccountRecord]:
        rows, headers = self.store.read_rows()
        old_account = self.get_account(account_id)
        if old_account is None:
            raise ValueError("account not found")
        target_index = self._find_row_index(rows, account_id)
        if target_index is None:
            raise ValueError("account row not found")
        new_account_id = str(payload.account_id or old_account.account_id).strip()
        if new_account_id != old_account.account_id and self.get_account(new_account_id) is not None:
            raise ValueError("new account_id already exists")
        new_role = str(payload.role or old_account.role).strip()
        if new_role not in self.valid_roles:
            raise ValueError("invalid role")
        rows[target_index] = self._build_row(
            office_code=payload.office_code if payload.office_code is not None else old_account.office_code,
            office_name=payload.office_name if payload.office_name is not None else old_account.office_name,
            account_id=new_account_id,
            display_name=payload.display_name if payload.display_name is not None else old_account.display_name,
            role=new_role,
            password=payload.password if payload.password is not None else old_account.password,
        )
        self.store.write_rows(rows, headers)
        updated = self.get_account(new_account_id)
        if updated is None:
            raise ValueError("failed to update account")
        return old_account, updated

    def set_password(self, account_id: str, new_password: str) -> AccountRecord:
        rows, headers = self.store.read_rows()
        old_account = self.get_account(account_id)
        if old_account is None:
            raise ValueError("account not found")
        target_index = self._find_row_index(rows, account_id)
        if target_index is None:
            raise ValueError("account row not found")
        rows[target_index] = self._build_row(
            office_code=old_account.office_code,
            office_name=old_account.office_name,
            account_id=old_account.account_id,
            display_name=old_account.display_name,
            role=old_account.role,
            password=new_password,
        )
        self.store.write_rows(rows, headers)
        account = self.get_account(account_id)
        if account is None:
            raise ValueError("failed to update password")
        return account

    def list_invalid_rows(self) -> list[InvalidAccountRow]:
        _, invalid_rows = self.list_accounts()
        return invalid_rows

    def to_snapshot(self, account_id: str) -> AccountSnapshot:
        account = self.get_account(account_id)
        if account is None:
            raise ValueError("account not found")
        return account.to_snapshot()

    def _parse_row(self, row: dict[str, str], row_number: int) -> tuple[AccountRecord | None, list[str]]:
        office_code = row.get(self.field_map.get("office_code", ""), "").strip() or None
        office_name = row.get(self.field_map.get("office_name", ""), "").strip() or None
        account_id = row.get(self.field_map.get("account_id", ""), "").strip()
        display_name = row.get(self.field_map.get("display_name", ""), "").strip()
        role = row.get(self.field_map.get("role", ""), "").strip()
        password = row.get(self.field_map.get("password", ""), "").strip()
        errors: list[str] = []
        if not account_id:
            errors.append("missing_account_id")
        if not display_name:
            errors.append("missing_display_name")
        if not role:
            errors.append("missing_role")
        elif role not in self.valid_roles:
            errors.append("invalid_role")
        if not password:
            errors.append("missing_password")
        if not account_id and not display_name and not role and not password:
            return None, errors
        account = AccountRecord(
            office_code=office_code,
            office_name=office_name,
            account_id=account_id or f"invalid-row-{row_number}",
            display_name=display_name or f"invalid-row-{row_number}",
            role=role or "",
            password=password,
            valid=not errors,
            row_number=row_number,
            errors=list(errors),
        )
        return account, errors

    def _build_row(
        self,
        *,
        office_code: str | None,
        office_name: str | None,
        account_id: str,
        display_name: str,
        role: str,
        password: str,
    ) -> dict[str, str]:
        row = dict.fromkeys(self.field_map.values(), "")
        row[self.field_map["office_code"]] = str(office_code or "")
        row[self.field_map["office_name"]] = str(office_name or "")
        row[self.field_map["account_id"]] = account_id
        row[self.field_map["display_name"]] = display_name
        row[self.field_map["role"]] = role
        row[self.field_map["password"]] = password
        return row

    def _find_row_index(self, rows: list[dict[str, str]], account_id: str) -> int | None:
        key = self.field_map["account_id"]
        for index, row in enumerate(rows):
            if str(row.get(key, "")).strip() == account_id:
                return index
        return None
