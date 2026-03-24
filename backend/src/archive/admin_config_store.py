from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import RuntimeConfig, get_config


class AdminConfigStore:
    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or get_config()
        self.path = self.config.management.admin_config_path

    def get(self) -> dict[str, Any]:
        self._ensure_exists()
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"archive_root_path": ""}

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get()
        current.update(payload)
        self.path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return current

    def get_archive_root_path(self) -> Path | None:
        raw = str(self.get().get("archive_root_path") or "").strip()
        return Path(raw).resolve() if raw else None

    def _ensure_exists(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(
                json.dumps({"archive_root_path": ""}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
