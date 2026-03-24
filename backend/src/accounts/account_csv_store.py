from __future__ import annotations

import csv

from ..config import BusinessSpec, load_spec


class AccountCsvStore:
    def __init__(self, spec: BusinessSpec | None = None) -> None:
        self.spec = spec or load_spec()
        features = self.spec.get_management_features()
        account_cfg = dict(features.get("account") or {})
        self.csv_path = self.spec.resolve_repo_path(account_cfg.get("csv_source") or "documents_bin/姓名角色表.csv")
        self.field_map = dict(account_cfg.get("fields") or {})

    def read_rows(self) -> tuple[list[dict[str, str]], list[str]]:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.csv_path.exists():
            headers = [value for value in self.field_map.values() if value]
            self.write_rows([], headers)
            return [], headers

        with open(self.csv_path, encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = list(reader.fieldnames or [])
            rows = [
                {str(key or ""): str(value or "") for key, value in row.items()}
                for row in reader
            ]
        return rows, headers

    def write_rows(self, rows: list[dict[str, str]], headers: list[str]) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.csv_path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({header: row.get(header, "") for header in headers})
