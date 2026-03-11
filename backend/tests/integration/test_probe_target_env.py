from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path

import pytest


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.integration
@pytest.mark.slow
def test_probe_target_env_v2_schema_and_repo_paths(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "tools" / "probe_target_env.ps1"
    out_json = tmp_path / "probe.json"
    storage_root = tmp_path / "storage"
    port = _pick_free_port()

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-OutJson",
            str(out_json),
            "-RepoRoot",
            str(repo_root),
            "-Port",
            str(port),
            "-StorageRoot",
            str(storage_root),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.returncode == 0
    assert out_json.exists()

    payload = json.loads(out_json.read_text(encoding="utf-8-sig"))

    assert payload["schema_version"] == "fanban-env-probe@2"
    assert payload["probe_meta"]["input"]["repo_root"] == str(repo_root)
    assert payload["repo"]["exists"]["business_spec_exists"] is True
    assert payload["repo"]["exists"]["runtime_spec_exists"] is True
    assert payload["repo"]["unicode_paths"]["status"] == "pass"

    office = payload["office"]
    assert office["word_com"]["status"] in {"pass", "fail", "skip"}
    assert office["excel_com"]["status"] in {"pass", "fail", "skip"}
    assert office["word_export_smoke"]["status"] in {"pass", "fail", "skip"}
    assert office["excel_export_smoke"]["status"] in {"pass", "fail", "skip"}

    recommended = payload["recommended_runtime"]
    assert recommended["recommended_doc_workers"] == 1
    assert recommended["recommended_port"] == port
    assert recommended["recommended_storage_root"] == str(storage_root)
    assert recommended["recommended_archive_keep"] == "package_zip_only"
