from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = (
    Path(__file__).resolve().parents[4]
    / "tools/ai/building-structure-standards/scripts"
)


@pytest.fixture
def writer_lock():
    spec = importlib.util.spec_from_file_location("standards_io_lock_test", SCRIPT_DIR / "standards_io.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def lock(cache_dir):
        helper = getattr(module, "cache_writer_lock", None)
        assert callable(helper), "cache writer needs a nonblocking OS lock"
        return helper(cache_dir)

    return lock


@pytest.mark.parametrize("body_failure", [False, True])
def test_writer_lock_releases_after_exit_or_exception(tmp_path, writer_lock, body_failure):
    class BodyFailure(Exception):
        pass

    try:
        with writer_lock(tmp_path):
            with (
                pytest.raises(RuntimeError, match="cache writer already active"),
                writer_lock(tmp_path),
            ):
                pytest.fail("same cache accepted a second writer")
            if body_failure:
                raise BodyFailure
    except BodyFailure:
        pass
    with writer_lock(tmp_path):
        pass


@pytest.mark.parametrize("same_cache", [False, True])
def test_writer_lock_excludes_other_process_without_waiting(tmp_path, writer_lock, same_cache):
    child_cache = tmp_path if same_cache else tmp_path / "other-cache"
    script = """
import sys
sys.path.insert(0, sys.argv[1])
from standards_io import cache_writer_lock
try:
    with cache_writer_lock(sys.argv[2]):
        print('acquired')
except RuntimeError as exc:
    print(str(exc))
    sys.exit(7)
"""
    with writer_lock(tmp_path):
        child = subprocess.run(
            [sys.executable, "-B", "-c", script, str(SCRIPT_DIR), str(child_cache)],
            capture_output=True, text=True, timeout=10,
        )
    assert child.returncode == (7 if same_cache else 0), child.stderr
    assert ("cache writer already active" if same_cache else "acquired") in child.stdout


def test_os_releases_writer_lock_when_process_exits_without_cleanup(tmp_path, writer_lock):
    script = """
import os
import sys
sys.path.insert(0, sys.argv[1])
from standards_io import cache_writer_lock
with cache_writer_lock(sys.argv[2]):
    os._exit(0)
"""
    child = subprocess.run(
        [sys.executable, "-B", "-c", script, str(SCRIPT_DIR), str(tmp_path)],
        capture_output=True, text=True, timeout=10,
    )
    assert child.returncode == 0, child.stderr
    with writer_lock(tmp_path):
        pass
