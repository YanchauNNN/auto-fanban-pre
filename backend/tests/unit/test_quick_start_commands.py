from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
QUICK_START = REPO_ROOT / "documents" / "快速启动.txt"
CALCULATION_AI_HEADING = "计算书 AI 测试空间 codex-calculation-ai-unified"


def test_calculation_ai_quick_start_uses_three_reliable_powershell_commands() -> None:
    text = QUICK_START.read_text(encoding="utf-8")

    assert CALCULATION_AI_HEADING in text
    section = text.split(CALCULATION_AI_HEADING, maxsplit=1)[1]

    assert (
        "python -X utf8 -m uvicorn API.app.main:app "
        "--host 127.0.0.1 --port 8010"
    ) in section
    assert "python -X utf8 -m API.app.worker" in section
    assert "$env:VITE_API_PROXY_TARGET='http://127.0.0.1:8010'" in section
    assert "npm.cmd run dev -- --host 127.0.0.1 --port 5175 --strictPort" in section
    assert "npm run dev" not in section
    assert "VITE_API_BASE_URL" not in section
