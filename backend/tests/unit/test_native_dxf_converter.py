from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.cad.native_dxf_converter import AutoCadDwgToDxfConverter
from src.config.runtime_config import RuntimeConfig


def test_native_dxf_fallback_options_are_loaded_from_runtime_yaml() -> None:
    config = RuntimeConfig.from_yaml(Path("documents/参数规范_运行期.yaml"))

    assert config.oda.native_dxf_fallback_enabled is True
    assert config.oda.native_dxf_fallback_version == "AC1032"
    assert config.oda.native_dxf_fallback_precision == 16


def test_native_dxf_converter_runs_dotnet_bridge_with_dwg_input(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sample.dwg"
    source.write_text("dwg", encoding="utf-8")
    output_dir = tmp_path / "out"

    class _Runner:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def run(self, **kwargs):
            self.calls.append(kwargs)
            payload = json.loads(kwargs["task_json"].read_text(encoding="utf-8"))
            output = Path(payload["output_dxf"])
            output.write_text("0\nEOF\n", encoding="utf-8")
            kwargs["result_json"].write_text(
                json.dumps({"errors": [], "output_dxf": str(output)}),
                encoding="utf-8",
            )

    bridge = SimpleNamespace(
        enabled=True,
        dll_path="Module5CadBridge.dll",
        command_name="M5BRIDGE_RUN",
        netload_each_run=True,
    )
    config = SimpleNamespace(
        oda=SimpleNamespace(
            native_dxf_fallback_version="AC1032",
            native_dxf_fallback_precision=16,
        ),
        module5_export=SimpleNamespace(dotnet_bridge=bridge),
    )
    runner = _Runner()

    result = AutoCadDwgToDxfConverter(config=config, runner=runner).dwg_to_dxf(
        source,
        output_dir,
    )

    assert result == output_dir / "sample.dxf"
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["source_dxf"] == source
    payload = json.loads(call["task_json"].read_text(encoding="utf-8"))
    assert payload["workflow_stage"] == "dwg_to_dxf"
    assert payload["source_dxf"] == str(source)
    assert payload["output_dxf"] == str(result)
    assert payload["dxf_version"] == "AC1032"
    assert payload["dxf_precision"] == 16
    assert payload["engines"]["dotnet_bridge"]["enabled"] is True
