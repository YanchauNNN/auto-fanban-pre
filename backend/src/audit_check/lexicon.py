from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from openpyxl import load_workbook

from .models import AuditLexicon

_PROJECT_NO_RE = re.compile(r"^\d{4}$")
_SPACE_RE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACE_RE.sub(" ", text)
    return text.strip().upper()


class AuditLexiconLoader:
    def load(self, workbook_path: str | Path) -> AuditLexicon:
        workbook = load_workbook(workbook_path, read_only=True, data_only=True)
        worksheet = workbook[workbook.sheetnames[0]]

        project_columns: list[tuple[int, str]] = []
        for column in range(2, worksheet.max_column + 1):
            raw = worksheet.cell(1, column).value
            if raw is None:
                continue
            project_no = str(raw).strip()
            if _PROJECT_NO_RE.fullmatch(project_no):
                project_columns.append((column, project_no))

        project_options = [project_no for _, project_no in project_columns]
        allowed: dict[str, set[str]] = {project_no: set() for project_no in project_options}
        token_projects: dict[str, set[str]] = {}

        for row in range(1, worksheet.max_row + 1):
            for column, project_no in project_columns:
                raw = worksheet.cell(row, column).value
                if raw is None:
                    continue
                normalized = normalize_text(str(raw))
                if not normalized:
                    continue
                allowed[project_no].add(normalized)
                token_projects.setdefault(normalized, set()).add(project_no)

        foreign: dict[str, set[str]] = {}
        all_tokens = set(token_projects)
        for project_no in project_options:
            foreign[project_no] = all_tokens.difference(allowed[project_no])

        return AuditLexicon(
            project_options=project_options,
            allowed_texts=allowed,
            foreign_texts=foreign,
            token_projects=token_projects,
        )
