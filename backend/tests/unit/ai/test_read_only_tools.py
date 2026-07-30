from __future__ import annotations

from pathlib import Path

import pytest

from src.ai.read_only_tools import ReadOnlyHostTools, ReadOnlyToolError
from src.config.ai.ai_spec import AiReadOnlyHostAccessConfig


def _tools(server_root: Path, **overrides) -> ReadOnlyHostTools:
    config = AiReadOnlyHostAccessConfig(
        allowed_roots=["documents", "storage"],
        max_read_bytes=64,
        max_search_results=3,
        max_depth=3,
        **overrides,
    )
    return ReadOnlyHostTools(server_root=server_root, config=config)


def test_read_only_tools_list_search_read_and_describe_allowed_files(tmp_path: Path) -> None:
    documents = tmp_path / "documents"
    nested = documents / "rules"
    nested.mkdir(parents=True)
    (documents / "README.txt").write_text("平台说明", encoding="utf-8")
    (nested / "drawing-rule.md").write_text("图纸规则", encoding="utf-8")
    (tmp_path / "storage").mkdir()
    tools = _tools(tmp_path)

    listed = tools.execute("list_directory", {"root": "documents", "path": ""})
    searched = tools.execute("search_files", {"root": "documents", "query": "rule"})
    described = tools.execute(
        "get_file_info",
        {"root": "documents", "path": "rules/drawing-rule.md"},
    )
    content = tools.execute(
        "read_text_file",
        {"root": "documents", "path": "README.txt"},
    )

    assert listed["ok"] is True
    assert [(entry["name"], entry["type"]) for entry in listed["entries"]] == [
        ("rules", "directory"),
        ("README.txt", "file"),
    ]
    assert searched["matches"] == ["rules/drawing-rule.md"]
    assert described["type"] == "file"
    assert described["size"] == len("图纸规则".encode("utf-8"))
    assert content["content"] == "平台说明"
    assert content["truncated"] is False

    definitions = tools.definitions()
    assert {item["function"]["name"] for item in definitions} == {
        "get_file_info",
        "list_directory",
        "read_text_file",
        "search_files",
    }


@pytest.mark.parametrize(
    ("root", "relative_path", "expected_code"),
    [
        ("documents", "../outside.txt", "path_outside_allowed_root"),
        ("missing", "README.txt", "unknown_root"),
        ("documents", ".env", "file_denied"),
        ("documents", "certificate.pem", "file_denied"),
        ("documents", "chat.sqlite3", "file_denied"),
        ("documents", "helper.exe", "file_denied"),
    ],
)
def test_read_only_tools_reject_unsafe_paths(
    tmp_path: Path,
    root: str,
    relative_path: str,
    expected_code: str,
) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (tmp_path / "storage").mkdir()
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    for name in (".env", "certificate.pem", "chat.sqlite3", "helper.exe"):
        (documents / name).write_text("sensitive", encoding="utf-8")
    tools = _tools(tmp_path)

    with pytest.raises(ReadOnlyToolError) as exc_info:
        tools.execute("read_text_file", {"root": root, "path": relative_path})

    assert exc_info.value.code == expected_code


def test_read_only_tools_reject_large_and_binary_files(tmp_path: Path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (tmp_path / "storage").mkdir()
    (documents / "large.txt").write_text("x" * 65, encoding="utf-8")
    (documents / "binary.txt").write_bytes(b"text\x00binary")
    tools = _tools(tmp_path)

    with pytest.raises(ReadOnlyToolError) as large_error:
        tools.execute("read_text_file", {"root": "documents", "path": "large.txt"})
    with pytest.raises(ReadOnlyToolError) as binary_error:
        tools.execute("read_text_file", {"root": "documents", "path": "binary.txt"})

    assert large_error.value.code == "file_too_large"
    assert binary_error.value.code == "binary_file_denied"


def test_list_directory_caps_results_and_reports_truncation(tmp_path: Path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (tmp_path / "storage").mkdir()
    for index in range(5):
        (documents / f"file-{index}.txt").write_text(str(index), encoding="utf-8")
    tools = _tools(tmp_path)

    listed = tools.execute("list_directory", {"root": "documents"})

    assert len(listed["entries"]) == 3
    assert listed["truncated"] is True


def test_read_only_tools_reject_symlink_escape_when_supported(tmp_path: Path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (tmp_path / "storage").mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = documents / "outside-link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable in this Windows test environment")
    tools = _tools(tmp_path)

    with pytest.raises(ReadOnlyToolError) as exc_info:
        tools.execute("read_text_file", {"root": "documents", "path": link.name})

    assert exc_info.value.code == "path_outside_allowed_root"
