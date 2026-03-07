"""
配置加载单元测试

每个模块完成后必须运行：pytest tests/unit/test_config.py -v
"""

from pathlib import Path

from src.config import BusinessSpec, RuntimeConfig, SpecLoader, load_spec, reload_config


class TestSpecLoader:
    """规范加载器测试"""

    def test_load_spec(self, spec: BusinessSpec):
        """测试加载规范"""
        assert spec.schema_version == "2.0"

    def test_get_paper_variants(self, spec: BusinessSpec):
        """测试获取图幅配置"""
        variants = spec.get_paper_variants()
        assert len(variants) > 0

        # 检查A1配置
        if "CNPE_A1" in variants:
            a1 = variants["CNPE_A1"]
            assert a1.W == 841.0
            assert a1.H == 594.0
            assert a1.profile == "BASE10"

    def test_get_roi_profile(self, spec: BusinessSpec):
        """测试获取ROI配置"""
        profile = spec.get_roi_profile("BASE10")
        assert profile is not None
        assert "内部编码" in profile.fields

    def test_get_cover_bindings(self, spec: BusinessSpec):
        """测试获取封面落点配置"""
        bindings_common = spec.get_cover_bindings("2016")
        bindings_1818 = spec.get_cover_bindings("1818")

        # 1818和通用落点应该不同
        assert bindings_common is not None
        assert bindings_1818 is not None

    def test_get_mappings(self, spec: BusinessSpec):
        """测试获取映射表"""
        mappings = spec.get_mappings()

        # 检查专业代码映射
        if "discipline_to_code" in mappings:
            assert mappings["discipline_to_code"].get("结构") == "JG"

    def test_load_spec_uses_env_override_when_default_path_missing(self, tmp_path: Path, monkeypatch):
        """打包运行时应优先读取 FANBAN_SPEC_PATH 指向的规范文件"""
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        spec_file = tmp_path / "bundle" / "documents" / "参数规范.yaml"
        spec_file.parent.mkdir(parents=True)
        spec_file.write_text("schema_version: '9.9'\n", encoding="utf-8")

        monkeypatch.chdir(run_dir)
        monkeypatch.setenv("FANBAN_SPEC_PATH", str(spec_file))
        SpecLoader.load.cache_clear()

        loaded = load_spec()

        assert loaded.schema_version == "9.9"


class TestRuntimeConfig:
    """运行期配置测试"""

    def test_default_config(self, runtime_config: RuntimeConfig):
        """测试默认配置"""
        assert runtime_config.concurrency.max_workers == 2
        assert runtime_config.timeouts.oda_convert_sec == 600

    def test_get_job_dir(self, runtime_config: RuntimeConfig):
        """测试获取任务目录"""
        job_dir = runtime_config.get_job_dir("test-job-id")
        assert "test-job-id" in str(job_dir)

    def test_module5_autocad_defaults(self, runtime_config: RuntimeConfig):
        """测试模块5 AutoCAD 默认配置"""
        assert runtime_config.module5_export.pdf_engine == "python"
        assert runtime_config.module5_export.engine == "cad_dxf"
        assert runtime_config.module5_export.dotnet_bridge.enabled is True
        assert runtime_config.module5_export.selection.engine == "dotnet"
        assert runtime_config.module5_export.output.plot_engine == "dotnet"
        assert runtime_config.module5_export.plot.center_plot is False
        assert runtime_config.module5_export.plot.plot_offset_mm == {"x": 0.0, "y": 0.0}
        assert runtime_config.module5_export.plot.plot_window_top_right_expand_ratio == 0.0001
        assert runtime_config.module5_export.plot.scale_mode == "manual_integer_from_geometry"
        assert runtime_config.module5_export.plot.scale_integer_rounding == "round"
        assert runtime_config.module5_export.plot.margins_mm == {
            "top": 0.0,
            "bottom": 0.0,
            "left": 0.0,
            "right": 0.0,
        }
        assert runtime_config.module5_export.selection.mode == "database"
        assert runtime_config.module5_export.output.a4_multipage_pdf == "dotnet_multipage"
        assert runtime_config.module5_export.output.pdf_from_split_dwg_mode == "always"
        assert runtime_config.module5_export.output.split_stage_plot_enabled is False
        assert runtime_config.module5_export.output.plot_preferred_area == "window"
        assert runtime_config.module5_export.output.plot_fallback_area == "none"
        assert runtime_config.module5_export.output.plot_session_mode == "per_source_batch"
        assert runtime_config.module5_export.output.plot_from_source_window_enabled is True
        assert runtime_config.module5_export.output.plot_fallback_to_split_on_failure is True
        assert runtime_config.module5_export.output.pdf_validation_min_size_bytes == 1024
        assert runtime_config.module5_export.output.pdf_validation_min_stream_bytes == 64
        assert runtime_config.module5_export.cad_runner.task_timeout_sec == 900
        assert runtime_config.autocad.install_dir == r"D:\Program Files\AUTOCAD\AutoCAD 2022"
        assert runtime_config.autocad.prog_id_candidates == [
            "AutoCAD.Application.24.1",
            "AutoCAD.Application.24.0",
            "AutoCAD.Application",
        ]
        assert runtime_config.autocad.pc3_name == "打印PDF2.pc3"

    def test_reload_config_uses_env_override_when_default_runtime_spec_missing(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """打包运行时应优先读取 FANBAN_RUNTIME_SPEC_PATH 指向的运行期规范"""
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        runtime_spec = tmp_path / "bundle" / "documents" / "参数规范_运行期.yaml"
        runtime_spec.parent.mkdir(parents=True)
        runtime_spec.write_text(
            """
runtime_options:
  concurrency:
    max_workers:
      type: int
      default: 7
""".strip(),
            encoding="utf-8",
        )

        monkeypatch.chdir(run_dir)
        monkeypatch.setenv("FANBAN_RUNTIME_SPEC_PATH", str(runtime_spec))

        config = reload_config()

        assert config.concurrency.max_workers == 7
