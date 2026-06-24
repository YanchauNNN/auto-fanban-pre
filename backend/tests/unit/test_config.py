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

    def test_a2_plus_half_decimal_plot_media_is_configured(self, spec: BusinessSpec):
        """A2+0.5 图幅需要显式落盘并指向打印PDF3.pc3中的同名媒体。"""
        variants = spec.get_paper_variants()
        assert variants["CNPE_A2+0.5"].W == 891.0
        assert variants["CNPE_A2+0.5"].H == 420.0
        assert variants["CNPE_A2+0.5"].profile == "BASE10"

        raw_variant = spec.titleblock_extract["paper_variants"]["CNPE_A2+0.5"]
        assert raw_variant["打印PDF2.pc3文件中对应纸张"] == "A2+0.5"
        assert raw_variant["打印PDF3.pc3文件中对应纸张"] == (
            "UserDefinedMetric (921.00 x 450.00毫米)"
        )

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
        assert runtime_config.pdf_engine.preferred == "office_com"
        assert runtime_config.pdf_engine.fallback == "disabled"
        assert runtime_config.font_preflight.font_library_dirs == [
            Path("documents_bin/font-library/ttf"),
            Path("documents_bin/font-library/shx"),
        ]

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
        assert runtime_config.module5_export.plot.default_plot_style_key == "red_wider"
        assert runtime_config.module5_export.plot.plot_style_profiles == {
            "red_wider": "fanban_monochrome.ctb",
            "same_width": "fanban_monochrome-same width.ctb",
            "review_white": "打白图.ctb",
            "steel_liner": "结构二室大图.ctb",
        }
        assert runtime_config.module5_export.plot.paper_variant_pc3_overrides == {}
        assert runtime_config.module5_export.plot.plot_offset_mm == {"x": 0.0, "y": 0.0}
        assert runtime_config.module5_export.plot.plot_window_bottom_left_expand_ratio == 0.0001
        assert runtime_config.module5_export.plot.plot_window_top_right_expand_ratio == 0.0002
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
        assert runtime_config.audit_check.generic_identifier_like.regex == r"^[A-Z]{3}\d{4}[A-Z]$"
        assert runtime_config.audit_check.generic_identifier_like.exempt_embed_patterns == [
            r"^[A-Z]{3}\d{4}[A-Z]$",
        ]
        assert runtime_config.audit_check.context_rules.date_like[0] == r"^\d{4}[-/.]\d{1,2}$"
        assert runtime_config.audit_check.matching_policy.suppress_project_no_in_dimension_like is True
        assert runtime_config.deliverable_consistency_fix.enabled is True
        assert runtime_config.deliverable_consistency_fix.failure_policy == "flag_and_continue"
        assert runtime_config.deliverable_consistency_fix.source_scope == "staged_source_before_split"
        assert runtime_config.deliverable_consistency_fix.paper_size.template_range == "B53:B79"
        assert runtime_config.deliverable_consistency_fix.fields == ["paper_size_text", "scale_text"]

    def test_a2_half_pc3_override_is_loaded_from_runtime_yaml(self):
        """A2+0.5 备用 PC3 映射必须由运行期 YAML 落盘提供。"""
        repo_root = Path(__file__).resolve().parents[3]
        config = RuntimeConfig.from_yaml(repo_root / "documents" / "参数规范_运行期.yaml")

        assert config.module5_export.plot.paper_variant_pc3_overrides == {
            "CNPE_A2+1/2": "打印PDF3.pc3",
            "CNPE_A2+0.5": "打印PDF3.pc3",
        }

    def test_unit_consistency_business_values_are_not_python_defaults(
        self,
        runtime_config: RuntimeConfig,
    ):
        """业务映射必须从运行期 YAML 读取，Python 只提供安全空兜底。"""
        unit_consistency = runtime_config.audit_check.unit_consistency

        assert unit_consistency.enabled is False
        assert unit_consistency.project_units == {}
        assert "2016" not in unit_consistency.project_units
        assert "2026" not in unit_consistency.project_units
        assert runtime_config.factory_index_maps.templates == {}
        assert runtime_config.factory_index_maps.island_templates == {}
        assert runtime_config.factory_index_maps.source_variant_rules == {}
        assert runtime_config.font_preflight.font_compatibility_replacements == {}

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

    def test_runtime_config_reads_paths_cad_runtime_and_plot_assets(
        self,
        tmp_path: Path,
    ):
        """运行期规范应覆盖根路径、CAD槽位与打印资源参数。"""
        runtime_spec = tmp_path / "documents" / "参数规范_运行期.yaml"
        runtime_spec.parent.mkdir(parents=True)
        runtime_spec.write_text(
            """
runtime_options:
  paths:
    base_dir:
      type: str
      default: "."
    storage_dir:
      type: str
      default: "custom-storage"
    spec_path:
      type: str
      default: "documents/参数规范.yaml"
    runtime_spec_path:
      type: str
      default: "documents/参数规范_运行期.yaml"
    mechanism_spec_path:
      type: str
      default: "documents/参数规范-3.yaml"
  cad_runtime:
    slot_count:
      type: int
      default: 6
  plot_assets:
    asset_roots:
      type: "list[str]"
      default: ["assets-a", "assets-b"]
    pmp_name:
      type: str
      default: "custom.pmp"
    managed_ctb_names:
      type: "list[str]"
      default: ["custom.ctb", "review.ctb"]
    min_valid_ctb_bytes:
      type: int
      default: 4096
""".strip(),
            encoding="utf-8",
        )

        config = RuntimeConfig.from_yaml(runtime_spec)

        assert config.base_dir == tmp_path.resolve()
        assert config.storage_dir == (tmp_path / "custom-storage").resolve()
        assert config.spec_path == (tmp_path / "documents" / "参数规范.yaml").resolve()
        assert config.runtime_spec_path == runtime_spec.resolve()
        assert config.mechanism_spec_path == (tmp_path / "documents" / "参数规范-3.yaml").resolve()
        assert config.cad_runtime.slot_count == 6
        assert config.plot_assets.asset_roots == [
            (tmp_path / "assets-a").resolve(),
            (tmp_path / "assets-b").resolve(),
        ]
        assert config.plot_assets.pmp_name == "custom.pmp"
        assert config.plot_assets.managed_ctb_names == ["custom.ctb", "review.ctb"]
        assert config.plot_assets.min_valid_ctb_bytes == 4096

    def test_runtime_config_reads_default_font_library_dirs(
        self,
        tmp_path: Path,
    ):
        """运行期规范应将字体库默认目录解析为仓库根下的绝对路径。"""
        runtime_spec = tmp_path / "documents" / "参数规范_运行期.yaml"
        runtime_spec.parent.mkdir(parents=True)
        runtime_spec.write_text(
            """
runtime_options:
  font_preflight:
    font_library_dirs:
      type: "list[str]"
      default: ["documents_bin/font-library/ttf", "documents_bin/font-library/shx"]
""".strip(),
            encoding="utf-8",
        )

        config = RuntimeConfig.from_yaml(runtime_spec)

        assert config.font_preflight.font_library_dirs == [
            (tmp_path / "documents_bin" / "font-library" / "ttf").resolve(),
            (tmp_path / "documents_bin" / "font-library" / "shx").resolve(),
        ]

    def test_runtime_config_reads_font_compatibility_replacements(
        self,
        tmp_path: Path,
    ):
        """字体兼容替代表应从运行期 YAML 落盘读取。"""
        runtime_spec = tmp_path / "documents" / "参数规范_运行期.yaml"
        runtime_spec.parent.mkdir(parents=True)
        runtime_spec.write_text(
            """
runtime_options:
  font_preflight:
    font_compatibility_replacements:
      type: object
      default: { "hztxt.shx": "tssdchn.shx" }
""".strip(),
            encoding="utf-8",
        )

        config = RuntimeConfig.from_yaml(runtime_spec)

        assert config.font_preflight.font_compatibility_replacements == {
            "hztxt.shx": "tssdchn.shx",
        }

    def test_runtime_config_reads_empty_style_replacement(
        self,
        tmp_path: Path,
    ):
        """空字体实体修复策略应从运行期 YAML 落盘读取。"""
        runtime_spec = tmp_path / "documents" / "参数规范_运行期.yaml"
        runtime_spec.parent.mkdir(parents=True)
        runtime_spec.write_text(
            """
runtime_options:
  font_preflight:
    empty_style_replacement:
      type: object
      default: { "font": "tssdeng.shx", "bigfont": "tssdchn.shx" }
    empty_style_target_fields:
      type: "list[str]"
      default: ["external_code", "internal_code", "page_info"]
""".strip(),
            encoding="utf-8",
        )

        config = RuntimeConfig.from_yaml(runtime_spec)

        assert config.font_preflight.empty_style_replacement == {
            "font": "tssdeng.shx",
            "bigfont": "tssdchn.shx",
        }
        assert config.font_preflight.empty_style_target_fields == [
            "external_code",
            "internal_code",
            "page_info",
        ]

    def test_runtime_config_reads_font_compatibility_exempt_style_names(
        self,
        tmp_path: Path,
    ):
        """字体兼容豁免样式名应从运行期 YAML 落盘读取。"""
        runtime_spec = tmp_path / "documents" / "参数规范_运行期.yaml"
        runtime_spec.parent.mkdir(parents=True)
        runtime_spec.write_text(
            """
runtime_options:
  font_preflight:
    font_compatibility_exempt_style_names:
      type: "list[str]"
      default: ["宋体", "ST"]
""".strip(),
            encoding="utf-8",
        )

        config = RuntimeConfig.from_yaml(runtime_spec)

        assert config.font_preflight.font_compatibility_exempt_style_names == [
            "宋体",
            "ST",
        ]

    def test_runtime_factory_index_maps_include_1915_target_template(self):
        """1915 作为翻版目标项目时应有无需岛号的厂房索引图模板。"""
        repo_root = Path(__file__).resolve().parents[3]
        config = RuntimeConfig.from_yaml(repo_root / "documents" / "参数规范_运行期.yaml")

        assert config.factory_index_maps.templates["1915"] == "1915项目厂房索引图.dwg"
        assert (
            config.factory_index_maps.template_dir
            / config.factory_index_maps.templates["1915"]
        ).exists()

    def test_runtime_unit_consistency_reads_business_values_from_yaml(self):
        """机组一致性项目范围和匹配规则应由运行期 YAML 提供。"""
        repo_root = Path(__file__).resolve().parents[3]
        config = RuntimeConfig.from_yaml(repo_root / "documents" / "参数规范_运行期.yaml")
        unit_consistency = config.audit_check.unit_consistency

        assert unit_consistency.enabled is True
        assert unit_consistency.project_units["2016"] == ["0", "1", "2", "7", "9"]
        assert unit_consistency.project_units["2026"] == ["0", "1", "2", "7", "9"]
        assert unit_consistency.project_units["1907"] == ["0", "5", "6", "7", "9"]
        assert unit_consistency.allow_unlisted_unit_no is True
        assert unit_consistency.universal_units == ["0", "7", "9"]
        assert unit_consistency.unit_no_pattern == "^[0-9]$"
        assert "external_code_pattern" in unit_consistency.model_fields_set
        assert "unit_no" in unit_consistency.external_code_pattern

    def test_runtime_standard_review_reads_values_from_yaml(self):
        """规范审查的开关、规范库路径和 y 容差应由运行期 YAML 提供。"""
        repo_root = Path(__file__).resolve().parents[3]
        config = RuntimeConfig.from_yaml(repo_root / "documents" / "参数规范_运行期.yaml")
        standard_review = config.audit_check.standard_review

        assert standard_review.enabled is True
        assert Path(standard_review.library_path) == repo_root / "documents_bin" / "规范库.xlsx"
        assert standard_review.sheet_name == "DatStdItem"
        assert standard_review.same_line_y_tolerance == 5.0

    def test_runtime_project_no_context_whitelist_reads_from_yaml(self):
        """项目号上下文白名单应从运行期 YAML 读取，便于后续业务补充。"""
        repo_root = Path(__file__).resolve().parents[3]
        config = RuntimeConfig.from_yaml(repo_root / "documents" / "参数规范_运行期.yaml")

        assert config.audit_check.project_no_context_whitelist_prefixes == [
            "资料单",
            "提资",
            "提资单号",
            "提资单号：",
        ]
        assert config.audit_check.project_no_context_whitelist_separator_pattern == r"\s*[:：]?\s*"

