from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config.ai.ai_spec import AiReadOnlyHostAccessConfig


class ReadOnlyToolError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _AllowedRoot:
    root_id: str
    path: Path


class ReadOnlyHostTools:
    def __init__(
        self,
        *,
        server_root: Path,
        config: AiReadOnlyHostAccessConfig,
    ) -> None:
        self.server_root = Path(server_root).resolve()
        self.config = config
        self._denied_names = {item.strip().lower() for item in config.denied_names if item.strip()}
        self._denied_suffixes = {
            _normalized_suffix(item) for item in config.denied_suffixes if item.strip()
        }
        self._roots = self._resolve_allowed_roots(config.allowed_roots) if config.enabled else {}

    @property
    def available_root_ids(self) -> list[str]:
        return list(self._roots)

    def definitions(self) -> list[dict[str, Any]]:
        if not self._roots:
            return []
        root_schema = {"type": "string", "enum": self.available_root_ids}
        path_schema = {
            "type": "string",
            "description": "相对于所选只读根目录的路径，使用正斜杠。",
        }
        return [
            _tool_definition(
                "list_directory",
                "列出后端允许目录中的一层文件和子目录，不读取文件内容。",
                {
                    "root": root_schema,
                    "path": {**path_schema, "default": ""},
                },
                ["root"],
            ),
            _tool_definition(
                "search_files",
                "按文件名在后端允许目录中递归搜索，只返回相对路径。",
                {
                    "root": root_schema,
                    "query": {"type": "string", "minLength": 1},
                },
                ["root", "query"],
            ),
            _tool_definition(
                "get_file_info",
                "读取后端允许路径的名称、类型、大小和修改时间，不读取文件内容。",
                {"root": root_schema, "path": path_schema},
                ["root", "path"],
            ),
            _tool_definition(
                "read_text_file",
                "读取后端允许目录中的小型文本文件。禁止数据库、密钥、配置密钥和可执行文件。",
                {"root": root_schema, "path": path_schema},
                ["root", "path"],
            ),
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "list_directory": self._list_directory,
            "search_files": self._search_files,
            "get_file_info": self._get_file_info,
            "read_text_file": self._read_text_file,
        }
        handler = handlers.get(name)
        if handler is None:
            raise ReadOnlyToolError("unknown_tool", f"unsupported read-only tool: {name}")
        return handler(arguments)

    def _list_directory(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root = self._root(arguments)
        target = self._resolve_path(root, arguments.get("path", ""), require_exists=True)
        if not target.is_dir():
            raise ReadOnlyToolError("not_a_directory", "the requested path is not a directory")
        entries = []
        try:
            children = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        except OSError as exc:
            raise ReadOnlyToolError("path_unreadable", "the requested directory cannot be read") from exc
        result_limit = max(int(self.config.max_search_results), 1)
        truncated = False
        for child in children:
            if self._is_denied(child):
                continue
            try:
                safe_child = self._ensure_contained(root, child)
            except ReadOnlyToolError:
                continue
            try:
                stat = safe_child.stat()
            except OSError:
                continue
            if len(entries) >= result_limit:
                truncated = True
                break
            entries.append(
                {
                    "name": child.name,
                    "type": "directory" if safe_child.is_dir() else "file",
                    "size": stat.st_size if safe_child.is_file() else None,
                },
            )
        return {
            "ok": True,
            "root": root.root_id,
            "path": self._relative(root, target),
            "entries": entries,
            "truncated": truncated,
        }

    def _search_files(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root = self._root(arguments)
        query = str(arguments.get("query", "")).strip().lower()
        if not query:
            raise ReadOnlyToolError("invalid_arguments", "search query is required")
        matches: list[str] = []
        pending: list[tuple[Path, int]] = [(root.path, 0)]
        while pending and len(matches) < self.config.max_search_results:
            directory, depth = pending.pop()
            try:
                children = sorted(directory.iterdir(), key=lambda item: item.name.lower(), reverse=True)
            except OSError:
                continue
            for child in children:
                if self._is_denied(child):
                    continue
                try:
                    safe_child = self._ensure_contained(root, child)
                except ReadOnlyToolError:
                    continue
                if safe_child.is_dir():
                    if depth < self.config.max_depth:
                        pending.append((safe_child, depth + 1))
                    continue
                if safe_child.is_file() and query in child.name.lower():
                    matches.append(self._relative(root, safe_child))
                    if len(matches) >= self.config.max_search_results:
                        break
        matches.sort(key=str.lower)
        return {"ok": True, "root": root.root_id, "query": query, "matches": matches}

    def _get_file_info(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root = self._root(arguments)
        target = self._resolve_path(root, arguments.get("path"), require_exists=True)
        stat = target.stat()
        return {
            "ok": True,
            "root": root.root_id,
            "path": self._relative(root, target),
            "name": target.name,
            "type": "directory" if target.is_dir() else "file",
            "size": stat.st_size if target.is_file() else None,
            "modified_at": stat.st_mtime,
        }

    def _read_text_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root = self._root(arguments)
        target = self._resolve_path(root, arguments.get("path"), require_exists=True)
        if not target.is_file():
            raise ReadOnlyToolError("not_a_file", "the requested path is not a file")
        size = target.stat().st_size
        if size > self.config.max_read_bytes:
            raise ReadOnlyToolError(
                "file_too_large",
                f"file exceeds the {self.config.max_read_bytes}-byte read limit",
            )
        try:
            payload = target.read_bytes()
        except OSError as exc:
            raise ReadOnlyToolError("path_unreadable", "the requested file cannot be read") from exc
        if b"\x00" in payload:
            raise ReadOnlyToolError("binary_file_denied", "binary file content is not allowed")
        content = _decode_text(payload)
        return {
            "ok": True,
            "root": root.root_id,
            "path": self._relative(root, target),
            "content": content,
            "encoding": "text",
            "truncated": False,
        }

    def _root(self, arguments: dict[str, Any]) -> _AllowedRoot:
        root_id = str(arguments.get("root", "")).strip().replace("\\", "/")
        root = self._roots.get(root_id)
        if root is None:
            raise ReadOnlyToolError("unknown_root", "the requested read-only root is unavailable")
        return root

    def _resolve_path(
        self,
        root: _AllowedRoot,
        value: object,
        *,
        require_exists: bool,
    ) -> Path:
        raw = str(value or "").strip()
        relative = Path(raw.replace("/", "\\")) if raw else Path()
        if relative.is_absolute():
            raise ReadOnlyToolError("path_outside_allowed_root", "absolute paths are not allowed")
        if self._path_parts_denied(relative):
            raise ReadOnlyToolError("file_denied", "the requested file is denied by policy")
        candidate = self._ensure_contained(root, root.path / relative)
        if require_exists and not candidate.exists():
            raise ReadOnlyToolError("path_not_found", "the requested path does not exist")
        if candidate.exists() and self._is_denied(candidate):
            raise ReadOnlyToolError("file_denied", "the requested file is denied by policy")
        return candidate

    def _ensure_contained(self, root: _AllowedRoot, path: Path) -> Path:
        try:
            resolved = path.resolve(strict=False)
            resolved.relative_to(root.path)
        except (OSError, ValueError) as exc:
            raise ReadOnlyToolError(
                "path_outside_allowed_root",
                "the requested path escapes the allowed root",
            ) from exc
        return resolved

    def _is_denied(self, path: Path) -> bool:
        return self._path_parts_denied(path) or path.suffix.lower() in self._denied_suffixes

    def _path_parts_denied(self, path: Path) -> bool:
        return any(part.lower() in self._denied_names for part in path.parts) or any(
            _normalized_suffix(part) in self._denied_suffixes for part in path.parts
        )

    def _relative(self, root: _AllowedRoot, path: Path) -> str:
        relative = path.relative_to(root.path)
        return "" if relative == Path() else relative.as_posix()

    def _resolve_allowed_roots(self, configured: list[str]) -> dict[str, _AllowedRoot]:
        roots: dict[str, _AllowedRoot] = {}
        for value in configured:
            root_id = str(value).strip().replace("\\", "/").strip("/")
            if not root_id:
                continue
            relative = Path(root_id.replace("/", "\\"))
            if relative.is_absolute() or ".." in relative.parts:
                continue
            candidate = (self.server_root / relative).resolve(strict=False)
            try:
                candidate.relative_to(self.server_root)
            except ValueError:
                continue
            if candidate.is_dir():
                roots[root_id] = _AllowedRoot(root_id=root_id, path=candidate)
        return roots


def _tool_definition(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def _normalized_suffix(value: str) -> str:
    normalized = value.strip().lower()
    return normalized if normalized.startswith(".") else f".{normalized}"


def _decode_text(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ReadOnlyToolError("binary_file_denied", "the file is not recognized as text")
