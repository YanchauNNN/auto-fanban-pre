"""Exercise real HTTP workflow using a copied successful job, never the live ledger."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def dump(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(source_job: Path, destination: Path, *, keep_server=False, browser_only=False):
    repo = Path(__file__).resolve().parents[1]
    destination = destination.resolve()
    if not destination.is_relative_to(repo) or destination == repo or destination.exists():
        raise ValueError("Output must be a NEW isolated directory within this worktree")
    original = json.loads(source_job.read_text(encoding="utf-8"))
    if original["status"] != "succeeded" or original["job_type"] != "deliverable":
        raise ValueError("Source must be an existing successful deliverable")
    source_package = Path(original["artifacts"]["package_zip"])
    source_manifest = source_job.parent / "manifest.json"
    source_hashes = {str(path): digest(path) for path in [source_job, source_package, source_manifest]}
    documents = destination / "documents"
    documents.mkdir(parents=True)
    for name in ["参数规范.yaml", "参数规范_运行期.yaml", "参数规范-3.yaml"]:
        shutil.copy2(repo / "documents" / name, documents / name)
    shutil.copytree(repo / "documents" / "Resources", documents / "Resources")
    (documents / "AI").mkdir()
    shutil.copy2(repo / "documents" / "AI" / "参数规范_AI.yaml", documents / "AI" / "参数规范_AI.yaml")
    (destination / "documents_bin").mkdir()
    # The real web schema reads these workbooks; keep accounts isolated below.
    for source in (repo / "documents_bin").iterdir():
        if source.is_file() and (source.suffix == ".xlsx" or source.name == "responsible_unit.json"):
            shutil.copy2(source, destination / "documents_bin" / source.name)
    people = [("smoke_design", "烟测设计", "设计人员", "结构一室"),
              ("smoke_first", "烟测一审", "室主任", "结构一室"),
              ("smoke_second", "烟测二审", "所领导", "建筑结构所"),
              ("smoke_admin", "烟测三审", "管理员", "建筑结构所"),
              ("smoke_outsider", "烟测无关人员", "设计人员", "结构二室")]
    with (destination / "documents_bin" / "姓名角色表.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["科室编码", "科室", "账号", "姓名", "角色", "密码"])
        for account, name, role, office in people:
            writer.writerow(["S01" if office == "结构一室" else "S99", office, account, name, role, "smoke-local-only"])
    storage = destination / "storage"
    job_id = "smoke-" + uuid.uuid4().hex[:16]
    job_dir = storage / "jobs" / job_id
    job_dir.mkdir(parents=True)
    cloned = json.loads(json.dumps(original))
    cloned.update(job_id=job_id, group_id=None, task_role=None, work_dir=str(job_dir))
    cloned["owner_snapshot"] = {"creator_account": "smoke_design", "creator_name": "烟测设计", "creator_role": "设计人员", "creator_office": "结构一室"}
    cloned["input_files"] = []
    for index, source in enumerate(original["input_files"]):
        target = job_dir / f"source-{index + 1}{Path(source).suffix}"
        shutil.copy2(source, target)
        cloned["input_files"].append(str(target))
    cloned["artifacts"] = dict.fromkeys(original["artifacts"])
    for field in ["package_zip", "ied_xlsx"]:
        if original["artifacts"].get(field):
            path = Path(original["artifacts"][field])
            target = job_dir / path.name
            shutil.copy2(path, target)
            cloned["artifacts"][field] = str(target)
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    manifest["job_id"] = job_id
    dump(job_dir / "job.json", cloned)
    dump(job_dir / "manifest.json", manifest)
    # A second independent copy remains unsubmitted for manual/browser entry checks.
    ui_job_id = job_id + "-ui"
    ui_job_dir = storage / "jobs" / ui_job_id
    shutil.copytree(job_dir, ui_job_dir)
    ui_job = json.loads(json.dumps(cloned).replace(str(job_dir).replace("\\", "\\\\"), str(ui_job_dir).replace("\\", "\\\\")))
    ui_job["job_id"] = ui_job_id
    dump(ui_job_dir / "job.json", ui_job)
    dump(ui_job_dir / "manifest.json", {**manifest, "job_id": ui_job_id})
    failed_id = job_id + "-failed"
    failed_dir = storage / "jobs" / failed_id
    shutil.copytree(job_dir, failed_dir)
    failed_job = json.loads(json.dumps(cloned).replace(str(job_dir).replace("\\", "\\\\"), str(failed_dir).replace("\\", "\\\\")))
    failed_job.update(job_id=failed_id, status="failed")
    dump(failed_dir / "job.json", failed_job)
    dump(failed_dir / "manifest.json", {**manifest, "job_id": failed_id})
    env = {key: value for key, value in os.environ.items() if not key.startswith("FANBAN_")}
    env.update(FANBAN_SPEC_PATH=str(documents / "参数规范.yaml"), FANBAN_RUNTIME_SPEC_PATH=str(documents / "参数规范_运行期.yaml"), FANBAN_MECHANISM_SPEC_PATH=str(documents / "参数规范-3.yaml"), FANBAN_STORAGE_DIR=str(storage), PYTHONUTF8="1")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log_handle = (destination / "server.log").open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "uvicorn", "API.app.main:app", "--host", "127.0.0.1", "--port", str(port)], cwd=repo, env=env, stdout=log_handle, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    events = []
    tokens = {}
    base = f"http://127.0.0.1:{port}"

    def request(method, path, account=None, body=None, expected=200):
        headers = {"Content-Type": "application/json"}
        if account:
            headers["Authorization"] = "Bearer " + tokens[account]
        payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        req = Request(base + path, data=payload, method=method, headers=headers)
        try:
            with urlopen(req, timeout=30) as response:
                code, raw = response.status, response.read()
        except HTTPError as exc:
            code, raw = exc.code, exc.read()
        data = json.loads(raw)
        safe = {key: value for key, value in data.items() if key != "token"}
        events.append({"method": method, "path": path, "actor": account, "status": code, "response": safe})
        dump(destination / "http-events.json", events)
        assert code == expected, (path, code, data)
        return data

    success = False
    try:
        for _ in range(80):
            if process.poll() is not None:
                raise RuntimeError("Isolated API exited; inspect server.log")
            try:
                request("GET", "/api/system/ping")
                break
            except URLError:
                time.sleep(0.25)
        else:
            raise TimeoutError("Isolated API startup timed out")
        for account, *_ in people:
            tokens[account] = request("POST", "/api/auth/login", body={"account_id": account, "password": "smoke-local-only"})["token"]
        request("GET", "/api/meta/form-schema", "smoke_design")
        request("PATCH", "/api/admin/config", "smoke_admin", {"archive_root_path": str(destination / "archive")})
        if browser_only:
            # Leave the fresh isolated ledger empty for browser-led submission.
            dump(destination / "browser-setup.json", {"source_job": str(source_job), "source_hashes": source_hashes, "job_id": job_id, "api_url": base, "api_pid": process.pid, "archive_root": str(destination / "archive")})
            print(json.dumps({"browser_ready": True, "job_id": job_id, "api_url": base, "api_pid": process.pid}, ensure_ascii=False), flush=True)
            success = True
            return
        actions = request("GET", f"/api/jobs/{job_id}/execution-actions", "smoke_design")
        assert not actions["can_cancel"] and not actions["can_retry"]
        request("POST", f"/api/jobs/{job_id}/cancel", "smoke_design", {}, 409)
        retried = request("POST", f"/api/jobs/{failed_id}/retry", "smoke_design", {})
        retry_id = retried["job_id"]
        assert retry_id != failed_id
        request("POST", f"/api/jobs/{retry_id}/cancel", "smoke_design", {})
        assert json.loads((storage / "jobs" / retry_id / "job.json").read_text(encoding="utf-8"))["status"] == "cancelled"
        assert json.loads((failed_dir / "job.json").read_text(encoding="utf-8"))["status"] == "failed"
        preview = request("GET", f"/api/jobs/{job_id}/workload-submission", "smoke_design")
        assert preview["can_submit"] and preview["group_id"] is None
        assert not list((storage / "groups").glob("*/group.json"))
        request("POST", f"/api/jobs/{job_id}/workload-submission", "smoke_outsider", {}, 403)
        request("POST", f"/api/jobs/{job_id}/workload-submission", "smoke_design", {}, 422)
        personnel = {"ied_checked_by": "烟测一审@smoke_first", "ied_reviewed_by": "烟测二审@smoke_second", "ied_approved_by": "烟测三审@smoke_admin"}
        submitted = request("POST", f"/api/jobs/{job_id}/workload-submission", "smoke_design", {"personnel": personnel})
        group_id = submitted["group_id"]
        request("POST", f"/api/jobs/{job_id}/workload-submission", "smoke_design", {"personnel": personnel}, 422)
        request("POST", f"/api/workflow/{group_id}/approve", "smoke_admin", {"factor": 1.0}, 422)
        request("POST", f"/api/workflow/{group_id}/approve", "smoke_first", {"factor": 3}, 422)
        for actor, node, factor in [("smoke_first", "one_review", 1.0), ("smoke_second", "two_review", 1.05), ("smoke_admin", "three_review", 0.95)]:
            monitor = request("GET", "/api/workflow/monitor", actor)
            card = next(item for item in monitor["items"] if item["group_id"] == group_id)
            assert card["can_approve"] and card["current_node_key"] == node
            result = request("POST", f"/api/workflow/{group_id}/approve", actor, {"node_key": node, "factor": factor})
        assert result["workflow"]["status"] == "archived"
        assert result["archive"]["status"] == "succeeded"
        assert result["workload"]["settlement_status"] == "settled"
        expected = round(preview["initial_workload_a1"] * 1.05 * 0.95, 2)
        assert result["effective_workload"] == expected
        assert len(result["workload"]["contributor_entries"]) == 4
        for account, *_ in people[:4]:
            personal = request("GET", "/api/workload/me", account)
            assert personal["total_workload_a1"] == expected and len(personal["entries"]) == 1
            assert personal["entries"][0]["account_id"] == account
        request("GET", "/api/workload/office", "smoke_first")
        request("GET", "/api/workload/institute", "smoke_second")
        request("GET", "/api/workload/admin", "smoke_admin")
        request("GET", "/api/workload/admin", "smoke_design", expected=403)
        outsider = request("GET", "/api/workflow/monitor", "smoke_outsider")
        assert not any(item["group_id"] == group_id for item in outsider["items"])
        assert json.loads((job_dir / "job.json").read_text(encoding="utf-8"))["params"] == original["params"]
        assert source_hashes == {path: digest(Path(path)) for path in source_hashes}
        summary = {"passed": True, "source_job": str(source_job), "source_job_id": original["job_id"], "source_filename": original.get("source_filename"), "job_id": job_id, "group_id": group_id, "initial_workload_a1": preview["initial_workload_a1"], "final_workload_a1": expected, "source_sha256_unchanged": True, "http_checks": len(events), "api_url": base, "api_pid": process.pid if keep_server else None, "ui_job_id": ui_job_id, "output_dir": str(destination)}
        dump(destination / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        success = True
    finally:
        if not (keep_server and success):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log_handle.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-job", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--keep-server", action="store_true")
    parser.add_argument("--browser-only", action="store_true", help="Prepare an empty isolated ledger and keep API alive for browser verification")
    args = parser.parse_args()
    run(args.source_job.resolve(), args.output_dir, keep_server=args.keep_server or args.browser_only, browser_only=args.browser_only)
