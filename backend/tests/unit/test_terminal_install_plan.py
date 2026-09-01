from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_PLAN = REPO_ROOT / "documents" / "终端实装安装计划.md"


def test_terminal_install_plan_leads_with_copyable_operator_commands() -> None:
    text = INSTALL_PLAN.read_text(encoding="utf-8")

    install_index = text.index("## 1. 首次安装命令")
    probe_index = text.index("## 2. 检测命令")
    update_index = text.index("## 3. 更新安装命令")
    assert install_index < probe_index < update_index
    assert install_index < 300

    assert "scripts\\prepare_terminal.ps1" in text
    assert "scripts\\run_deployment_probes.ps1" in text
    assert "-RunCalculationSmoke" in text
    assert "-CalculationArchive" in text
    assert "install\\register_backend_task.ps1" in text
    assert "直接覆盖到 `D:\\FanBanServer`" in text
    assert "$DeployRoot = 'D:\\FanBanServer'" in text
    assert "D:\\FanBanUpdate" not in text
    assert "$PackageRoot" not in text


def test_terminal_install_plan_is_concise_utf8_and_names_log_handoff() -> None:
    text = INSTALL_PLAN.read_text(encoding="utf-8")

    assert "缁堢" not in text
    assert "锛" not in text
    assert "�" not in text
    assert len(text.splitlines()) <= 220
    assert "logs\\deployment-probes" in text
    assert "backend-latest-stderr.log" in text
    assert "PASS" in text
