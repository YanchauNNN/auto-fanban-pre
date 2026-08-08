from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path

import pytest

from src.accounts.account_csv_store import AccountCsvStore
from src.accounts.account_registry import AccountRegistry
from src.auth.session_service import SessionService

from ..management_test_helpers import configure_management_env


def _make_services(monkeypatch, tmp_path) -> tuple[SessionService, SessionService]:
    configure_management_env(monkeypatch, tmp_path)
    registry = AccountRegistry(AccountCsvStore())
    return SessionService(registry), SessionService(registry)


def test_concurrent_login_and_read_never_exposes_partial_session_json(
    monkeypatch,
    tmp_path,
) -> None:
    reader, writer = _make_services(monkeypatch, tmp_path)
    existing = reader.create_session("zhangsan")
    destination_truncated = threading.Event()
    allow_destination_write = threading.Event()
    writer_errors: list[BaseException] = []
    original_open = Path.open

    def coordinated_open(path: Path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        mode = str(args[0] if args else kwargs.get("mode", "r"))
        if path == writer.path and "w" in mode:
            destination_truncated.set()
            allow_destination_write.wait(timeout=2)
        return handle

    monkeypatch.setattr(Path, "open", coordinated_open)

    def log_in() -> None:
        try:
            writer.create_session("lisi")
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)

    login_thread = threading.Thread(target=log_in, name="concurrent-login")
    login_thread.start()
    destination_truncated.wait(timeout=0.25)

    read_errors: list[BaseException] = []
    resolved = None
    try:
        resolved = reader.resolve_account(f"Bearer {existing.token}")
    except BaseException as exc:  # pragma: no cover - asserted below
        read_errors.append(exc)
    finally:
        allow_destination_write.set()
        login_thread.join(timeout=2)

    assert not login_thread.is_alive()
    assert not destination_truncated.is_set()
    assert writer_errors == []
    assert read_errors == []
    assert resolved is not None
    assert resolved.account_id == "zhangsan"


def test_concurrent_logins_across_service_instances_preserve_all_sessions(
    monkeypatch,
    tmp_path,
) -> None:
    first, second = _make_services(monkeypatch, tmp_path)
    first.create_session("zhangsan")
    both_reads_completed = threading.Barrier(2)
    original_load = SessionService._load_sessions

    def coordinated_load(service: SessionService):
        sessions = original_load(service)
        with suppress(threading.BrokenBarrierError):
            both_reads_completed.wait(timeout=0.25)
        return sessions

    monkeypatch.setattr(SessionService, "_load_sessions", coordinated_load)

    with ThreadPoolExecutor(max_workers=2) as executor:
        created = list(
            executor.map(
                lambda item: item[0].create_session(item[1]),
                ((first, "lisi"), (second, "admin")),
            )
        )

    persisted_account_ids = {session.account_id for session in first._load_sessions()}
    assert {session.account_id for session in created} == {"lisi", "admin"}
    assert persisted_account_ids == {"zhangsan", "lisi", "admin"}


def test_atomic_replace_keeps_previous_json_readable_until_commit(
    monkeypatch,
    tmp_path,
) -> None:
    reader, writer = _make_services(monkeypatch, tmp_path)
    existing = reader.create_session("zhangsan")
    replacement_ready = threading.Event()
    allow_replacement = threading.Event()
    writer_errors: list[BaseException] = []
    original_replace = os.replace

    def coordinated_replace(source, destination) -> None:
        if Path(destination) == writer.path:
            replacement_ready.set()
            allow_replacement.wait(timeout=2)
        original_replace(source, destination)

    monkeypatch.setattr(os, "replace", coordinated_replace)

    def log_in() -> None:
        try:
            writer.create_session("lisi")
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)

    login_thread = threading.Thread(target=log_in, name="atomic-session-login")
    login_thread.start()
    assert replacement_ready.wait(timeout=1)

    persisted_during_write = json.loads(reader.path.read_text(encoding="utf-8"))
    allow_replacement.set()
    login_thread.join(timeout=2)

    assert not login_thread.is_alive()
    assert writer_errors == []
    assert [item["token"] for item in persisted_during_write["sessions"]] == [existing.token]
    assert {session.account_id for session in reader._load_sessions()} == {"zhangsan", "lisi"}


def test_corrupt_session_store_fails_explicitly(monkeypatch, tmp_path) -> None:
    service, _ = _make_services(monkeypatch, tmp_path)
    service.path.write_text('{"sessions": [', encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        service.resolve_account("Bearer any-token")
