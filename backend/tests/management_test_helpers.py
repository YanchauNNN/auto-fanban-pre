from __future__ import annotations

import csv
import shutil
from pathlib import Path

import yaml

from src.config import MechanismSpecLoader, SpecLoader, reload_config


def configure_management_env(monkeypatch, tmp_path: Path, rows: list[dict[str, str]] | None = None) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    project_root = tmp_path / "management-project"
    documents_dir = project_root / "documents"
    documents_dir.mkdir(parents=True, exist_ok=True)
    docs_bin_dir = project_root / "documents_bin"
    docs_bin_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / "documents" / "Resources", documents_dir / "Resources", dirs_exist_ok=True)

    spec_payload = yaml.safe_load((repo_root / "documents" / "参数规范.yaml").read_text(encoding="utf-8"))
    runtime_payload = yaml.safe_load(
        (repo_root / "documents" / "参数规范_运行期.yaml").read_text(encoding="utf-8")
    )
    mechanism_payload = yaml.safe_load(
        (repo_root / "documents" / "参数规范-3.yaml").read_text(encoding="utf-8")
    )

    spec_path = documents_dir / "参数规范.yaml"
    runtime_path = documents_dir / "参数规范_运行期.yaml"
    mechanism_path = documents_dir / "参数规范-3.yaml"
    spec_path.write_text(yaml.safe_dump(spec_payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    runtime_path.write_text(
        yaml.safe_dump(runtime_payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    mechanism_path.write_text(
        yaml.safe_dump(mechanism_payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    headers = ["科室编码", "科室", "账号", "姓名", "角色", "密码"]
    csv_rows = rows or [
        {
            "科室编码": "S01",
            "科室": "结构一室",
            "账号": "zhangsan",
            "姓名": "张三",
            "角色": "设计人员",
            "密码": "password",
        },
        {
            "科室编码": "S01",
            "科室": "结构一室",
            "账号": "lisi",
            "姓名": "李四",
            "角色": "室主任",
            "密码": "password",
        },
        {
            "科室编码": "S99",
            "科室": "建筑结构所",
            "账号": "wangwu",
            "姓名": "王五",
            "角色": "所领导",
            "密码": "password",
        },
        {
            "科室编码": "ADM",
            "科室": "信息中心",
            "账号": "admin",
            "姓名": "管理员",
            "角色": "管理员",
            "密码": "password",
        },
    ]
    csv_path = docs_bin_dir / "姓名角色表.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in csv_rows:
            writer.writerow({header: row.get(header, "") for header in headers})

    monkeypatch.setenv("FANBAN_SPEC_PATH", str(spec_path))
    monkeypatch.setenv("FANBAN_RUNTIME_SPEC_PATH", str(runtime_path))
    monkeypatch.setenv("FANBAN_MECHANISM_SPEC_PATH", str(mechanism_path))
    monkeypatch.setenv("FANBAN_STORAGE_DIR", str(project_root / "storage"))
    SpecLoader.clear_cache()
    MechanismSpecLoader.clear_cache()
    reload_config()
    return project_root
