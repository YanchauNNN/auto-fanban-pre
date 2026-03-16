"""
配置加载单元测试

每个模块完成后必须运行：pytest tests/unit/test_config.py -v
"""

from pathlib import Path

from src.config import BusinessSpec, RuntimeConfig, SpecLoader, get_config, load_spec, reload_config


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
        SpecLoader.clear_cache()

        loaded = load_spec()

        assert loaded.schema_version == "9.9"

    def test_env_override_does_not_leak_spec_cache(self, tmp_path: Path, monkeypatch):
        """临时 FANBAN_SPEC_PATH 不能污染后续测试进程内的真实规范加载"""
        repo_root = Path(__file__).resolve().parents[3]
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        spec_file = tmp_path / "bundle" / "documents" / "参数规范.yaml"
        spec_file.parent.mkdir(parents=True)
        spec_file.write_text("schema_version: '9.9'\n", encoding="utf-8")

        monkeypatch.chdir(run_dir)
        monkeypatch.setenv("FANBAN_SPEC_PATH", str(spec_file))
        SpecLoader.clear_cache()
        assert load_spec().schema_version == "9.9"

        monkeypatch.delenv("FANBAN_SPEC_PATH", raising=False)
        monkeypatch.chdir(repo_root)

        reloaded = load_spec()

        assert reloaded.schema_version == "2.0"


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
        assert runtime_config.autocad.install_dir == ""
        assert runtime_config.autocad.ctb_path == ""
        assert runtime_config.autocad.prog_id_candidates == [
            "AutoCAD.Application.24.1",
            "AutoCAD.Application.24.0",
            "AutoCAD.Application",
        ]
        assert runtime_config.autocad.pc3_name == "打印PDF2.pc3"
        assert runtime_config.audit_check.enabled is True
        assert runtime_config.audit_check.lexicon_path.endswith("documents_bin\\词库收集.xlsx")
        assert runtime_config.audit_check.project_column_header_pattern == r"^\d{4}$"
        assert runtime_config.audit_check.include_rows == [1, 2, "3+"]
        assert runtime_config.audit_check.generic_identifier_like.regex == r"^[A-Z0-9-]{6,}$"
        assert runtime_config.audit_check.generic_identifier_like.exempt_embed_patterns == [
            r"^[A-Z]{3}\d{4}[A-Z]$",
        ]
        assert runtime_config.audit_check.context_rules.date_like[0] == r"^\d{4}[-/.]\d{1,2}$"
        assert runtime_config.audit_check.matching_policy.suppress_project_no_in_dimension_like is True

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

    def test_env_override_does_not_leak_runtime_config(self, tmp_path: Path, monkeypatch):
        """临时 FANBAN_RUNTIME_SPEC_PATH 不能污染后续测试进程内的默认运行期配置"""
        repo_root = Path(__file__).resolve().parents[3]
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

        monkeypatch.delenv("FANBAN_RUNTIME_SPEC_PATH", raising=False)
        monkeypatch.chdir(repo_root)

        restored = get_config()

        assert restored.concurrency.max_workers == 2

    def test_runtime_config_resolves_audit_lexicon_path_from_repo_root_sibling(
        self,
        tmp_path: Path,
    ):
        """运行期规范位于 documents/ 下时，documents_bin 资源应解析到仓库根目录同级。"""
        runtime_spec = tmp_path / "documents" / "参数规范_运行期.yaml"
        runtime_spec.parent.mkdir(parents=True)
        runtime_spec.write_text(
            """
runtime_options:
  audit_check:
    lexicon_path:
      type: str
      default: "documents_bin\\\\词库收集.xlsx"
""".strip(),
            encoding="utf-8",
        )

        config = RuntimeConfig.from_yaml(runtime_spec)

        assert Path(config.audit_check.lexicon_path) == (
            tmp_path / "documents_bin" / "词库收集.xlsx"
        ).resolve()

