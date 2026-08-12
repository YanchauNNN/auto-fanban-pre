from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from pypdf import PdfReader


class ChangePageExtractError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChangePageExtractItem:
    name: str
    pages: int
    relative_path: str


@dataclass(frozen=True)
class ChangePageExtractResult:
    archive_name: str
    items: tuple[ChangePageExtractItem, ...]
    text: str
    pdf_count: int
    total_pages: int
    ignored_file_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "archive_name": self.archive_name,
            "items": [asdict(item) for item in self.items],
            "text": self.text,
            "pdf_count": self.pdf_count,
            "total_pages": self.total_pages,
            "ignored_file_count": self.ignored_file_count,
        }


_ATTACHMENT_PREFIX = re.compile(r"^\s*附图\s*(\d+)\s*[：:]?\s*(.*)$", re.IGNORECASE)
_NATURAL_PARTS = re.compile(r"(\d+)")


def _natural_key(value: str) -> tuple[object, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    attachment = _ATTACHMENT_PREFIX.match(normalized)
    if attachment:
        return (0, int(attachment.group(1)), attachment.group(2))
    return (1, *[int(part) if part.isdigit() else part for part in _NATURAL_PARTS.split(normalized)])


def _normalized_display_name(stem: str) -> str:
    normalized = unicodedata.normalize("NFKC", stem).strip()
    match = _ATTACHMENT_PREFIX.match(normalized)
    if match:
        suffix = match.group(2).strip()
        return f"附图{int(match.group(1))}：{suffix}" if suffix else f"附图{int(match.group(1))}"
    return normalized


class ChangePageExtractService:
    def __init__(self, *, line_template: str = "{name}，共{pages}页；") -> None:
        self.line_template = line_template

    def build_result(
        self,
        *,
        archive_name: str,
        extraction_root: Path,
        output_path: Path | None = None,
    ) -> ChangePageExtractResult:
        all_files = sorted(path for path in extraction_root.rglob("*") if path.is_file())
        pdf_files = [path for path in all_files if path.suffix.casefold() == ".pdf"]
        if not pdf_files:
            raise ChangePageExtractError(f"压缩包 {archive_name} 中没有 PDF 文件")

        basename_counts = Counter(unicodedata.normalize("NFKC", path.stem).casefold() for path in pdf_files)
        items: list[ChangePageExtractItem] = []
        for path in pdf_files:
            relative = path.relative_to(extraction_root).as_posix()
            try:
                reader = PdfReader(str(path), strict=False)
                if reader.is_encrypted:
                    raise ChangePageExtractError(f"PDF 无法读取（已加密）：{relative}")
                pages = len(reader.pages)
            except ChangePageExtractError:
                raise
            except Exception as exc:
                raise ChangePageExtractError(f"PDF 无法读取：{relative}") from exc
            if pages <= 0:
                raise ChangePageExtractError(f"PDF 页数无效：{relative}")
            stem_key = unicodedata.normalize("NFKC", path.stem).casefold()
            if basename_counts[stem_key] > 1:
                name = Path(relative).with_suffix("").as_posix()
            else:
                name = path.stem
            items.append(
                ChangePageExtractItem(
                    name=_normalized_display_name(name),
                    pages=pages,
                    relative_path=relative,
                )
            )

        items.sort(key=lambda item: _natural_key(item.name))
        text = "\n".join(
            self.line_template.format(name=item.name, pages=item.pages)
            for item in items
        )
        result = ChangePageExtractResult(
            archive_name=archive_name,
            items=tuple(items),
            text=text,
            pdf_count=len(items),
            total_pages=sum(item.pages for item in items),
            ignored_file_count=len(all_files) - len(pdf_files),
        )
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return result
