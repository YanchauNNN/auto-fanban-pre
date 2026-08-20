"""
配置加载单元测试

每个模块完成后必须运行：pytest tests/unit/test_config.py -v
"""

import zlib
from pathlib import Path

from src.config import BusinessSpec, RuntimeConfig, SpecLoader, get_config, load_spec, reload_config


class TestSpecLoader:
    """规范加载器测试"""

    def test_load_spec(self, spec: BusinessSpec):
        """测试加载规范"""
        assert spec.schema_version == "2.0"
        postprocess = spec.titleblock_extract["replace_postprocess"]
        assert postprocess["target_status"] == "CFC"
        assert postprocess["status_pattern"] == "^[A-Z]{2,6}$"

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
        """A2+0.5 图幅应在打印PDF2.pc3关联PMP中落盘为921x450媒体。"""
        variants = spec.get_paper_variants()
        assert variants["CNPE_A2+0.5"].W == 891.0
        assert variants["CNPE_A2+0.5"].H == 420.0
        assert variants["CNPE_A2+0.5"].profile == "BASE10"

        raw_variant = spec.titleblock_extract["paper_variants"]["CNPE_A2+0.5"]
        assert raw_variant["打印PDF2.pc3文件中对应纸张"] == "UserDefinedMetric (921.00 x 450.00毫米)"

    def test_managed_pdf2_pmp_contains_a2_plus_half_media(self):
        """托管打印PDF2资源必须包含A2+0.5(921x450)自定义媒体。"""
        repo_root = Path(__file__).resolve().parents[3]
        pmp_path = repo_root / "documents" / "Resources" / "tszdef-02fc5f1cb3db4a5b8afc9cce5dca6cd1.pmp"
        data = pmp_path.read_bytes()
        compressed_offset = data.find(b"\x78\xda")
        assert compressed_offset >= 0
        payload = zlib.decompress(data[compressed_offset:]).decode("latin1")

        assert "name=\"UserDefinedMetric (921.00 x 450.00" in payload
        localized_label = "localized_name=\"A2+0.5(921.00 x 450.00 毫米)".encode(
            "gbk"
        ).decode("latin1")
        assert localized_label in payload
        assert "media_bounds_urx=921.0" in payload
        assert "media_bounds_ury=450.0" in payload
        assert "printable_bounds_llx=10.0" in payload
        assert "printable_bounds_lly=10.0" in payload
        assert "printable_bounds_urx=911.0" in payload
        assert "printable_bounds_ury=440.0" in payload

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
            "grayscale": "fanban_monochrome-huidu.ctb",
            "review_white": "打白图.ctb",
            "telecom": "通信打印样式.ctb",
            "telecom_thin": "通信打印样式细线.ctb",
            "steel_liner": "结构二室大图.ctb",
        }
        assert "fanban_monochrome-huidu.ctb" in runtime_config.plot_assets.managed_ctb_names
        assert "通信打印样式.ctb" in runtime_config.plot_assets.managed_ctb_names
        assert "通信打印样式细线.ctb" in runtime_config.plot_assets.managed_ctb_names
        assert runtime_config.module5_export.plot.paper_variant_pc3_overrides == {}
        assert runtime_config.module5_export.plot.plot_offset_mm == {"x": 0.0, "y": 0.0}
        assert runtime_config.module5_export.plot.plot_window_bottom_left_expand_ratio == 0.0001
        assert runtime_config.module5_export.plot.plot_window_top_right_expand_ratio == 0.0002
        assert runtime_config.module5_export.plot.paper_variant_window_expand_overrides == {}
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
            r"^(?:[0-9][A-Z]{2})[A-Z]{3}\d{4}[A-Z][,，]?$",
        ]
        assert runtime_config.audit_check.context_rules.date_like[0] == r"^\d{4}[-/.]\d{1,2}$"
        assert runtime_config.audit_check.matching_policy.suppress_project_no_in_dimension_like is True
        assert runtime_config.deliverable_consistency_fix.enabled is True
        assert runtime_config.deliverable_consistency_fix.failure_policy == "flag_and_continue"
        assert runtime_config.deliverable_consistency_fix.source_scope == "staged_source_before_split"
        assert runtime_config.deliverable_consistency_fix.paper_size.template_range == "B53:B79"
        assert runtime_config.deliverable_consistency_fix.fields == ["paper_size_text", "scale_text"]
        alignment = runtime_config.deliverable_consistency_fix.internal_external_code_alignment
        assert alignment.internal_sheet_pattern == r"-(?P<sheet>\d{3})$"
        assert alignment.external_code_length == 19
        assert alignment.external_sheet_start_1_based == 9
        assert alignment.sheet_number_length == 3

    def test_a2_half_uses_default_pdf2_pc3_from_runtime_yaml(self):
        """A2+0.5 媒体已进入打印PDF2后，运行期不应再切换到打印PDF3。"""
        repo_root = Path(__file__).resolve().parents[3]
        config = RuntimeConfig.from_yaml(repo_root / "documents" / "参数规范_运行期.yaml")

        assert config.module5_export.plot.paper_variant_pc3_overrides == {}
        assert config.module5_export.plot.paper_variant_window_expand_overrides == {
            "CNPE_A1+1/4": {
                "bottom_left_expand_ratio": 0.0,
                "top_right_expand_ratio": 0.0,
            },
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

    def test_runtime_spec_path_resolves_from_backend_runtime_cwd(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """部署环境手动启动 uvicorn 时，应从 backend-runtime 上一级读取 documents。"""
        from src.config.runtime_config import _resolve_runtime_spec_path

        deploy_root = tmp_path / "FanBanServer"
        backend_runtime = deploy_root / "backend-runtime"
        backend_runtime.mkdir(parents=True)
        runtime_spec = deploy_root / "documents" / "参数规范_运行期.yaml"
        runtime_spec.parent.mkdir(parents=True)
        runtime_spec.write_text("runtime_options: {}\n", encoding="utf-8")

        monkeypatch.chdir(backend_runtime)
        monkeypatch.delenv("FANBAN_RUNTIME_SPEC_PATH", raising=False)

        assert _resolve_runtime_spec_path().resolve() == runtime_spec.resolve()

    def test_runtime_config_prefers_backend_runtime_cad_paths_in_deploy_layout(
        self,
        tmp_path: Path,
    ):
        """部署包中 CAD 脚本和 Bridge DLL 应优先解析到 backend-runtime。"""
        deploy_root = tmp_path / "FanBanServer"
        runtime_spec = deploy_root / "documents" / "参数规范_运行期.yaml"
        runtime_spec.parent.mkdir(parents=True)
        script_dir = deploy_root / "backend-runtime" / "backend" / "src" / "cad" / "scripts"
        script_dir.mkdir(parents=True)
        bridge_dll = (
            deploy_root
            / "backend-runtime"
            / "backend"
            / "src"
            / "cad"
            / "dotnet"
            / "Module5CadBridge"
            / "bin"
            / "Release"
            / "net48"
            / "Module5CadBridge.dll"
        )
        bridge_dll.parent.mkdir(parents=True)
        bridge_dll.write_bytes(b"fake")
        runtime_spec.write_text(
            r"""
runtime_options:
  module5_export:
    cad_runner:
      script_dir:
        type: str
        default: '..\backend\src\cad\scripts'
    dotnet_bridge:
      dll_path:
        type: str
        default: '..\backend\src\cad\dotnet\Module5CadBridge\bin\Release\net48\Module5CadBridge.dll'
""".strip(),
            encoding="utf-8",
        )

        config = RuntimeConfig.from_yaml(runtime_spec)

        assert Path(config.module5_export.cad_runner.script_dir) == script_dir.resolve()
        assert Path(config.module5_export.dotnet_bridge.dll_path) == bridge_dll.resolve()

    def test_runtime_config_corrects_stale_absolute_backend_src_cad_env(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        """旧 runtime.env 写死 backend/src/cad 时，应改用部署包 backend-runtime 资源。"""
        deploy_root = tmp_path / "FanBanServer"
        runtime_spec = deploy_root / "documents" / "参数规范_运行期.yaml"
        runtime_spec.parent.mkdir(parents=True)
        script_dir = deploy_root / "backend-runtime" / "backend" / "src" / "cad" / "scripts"
        script_dir.mkdir(parents=True)
        bridge_dll = (
            deploy_root
            / "backend-runtime"
            / "backend"
            / "src"
            / "cad"
            / "dotnet"
            / "Module5CadBridge"
            / "bin"
            / "Release"
            / "net48"
            / "Module5CadBridge.dll"
        )
        bridge_dll.parent.mkdir(parents=True)
        bridge_dll.write_bytes(b"fake")
        runtime_spec.write_text("runtime_options: {}\n", encoding="utf-8")
        monkeypatch.setenv(
            "FANBAN_MODULE5_EXPORT__CAD_RUNNER__SCRIPT_DIR",
            str(deploy_root / "backend" / "src" / "cad" / "scripts"),
        )
        monkeypatch.setenv(
            "FANBAN_MODULE5_EXPORT__DOTNET_BRIDGE__DLL_PATH",
            str(
                deploy_root
                / "backend"
                / "src"
                / "cad"
                / "dotnet"
                / "Module5CadBridge"
                / "bin"
                / "Release"
                / "net48"
                / "Module5CadBridge.dll",
            ),
        )

        config = RuntimeConfig.from_yaml(runtime_spec)

        assert Path(config.module5_export.cad_runner.script_dir) == script_dir.resolve()
        assert Path(config.module5_export.dotnet_bridge.dll_path) == bridge_dll.resolve()

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

    def test_runtime_config_reads_titleblock_print_style_replacements(
        self,
        tmp_path: Path,
    ):
        """图签打印字体替换及区域外扩应从运行期 YAML 落盘读取。"""
        runtime_spec = tmp_path / "documents" / "参数规范_运行期.yaml"
        runtime_spec.parent.mkdir(parents=True)
        runtime_spec.write_text(
            """
runtime_options:
  font_preflight:
    titleblock_print_style_replacements:
      type: object
      default:
        "宋体": { font: "tssdeng.shx", bigfont: "tssdchn.shx" }
    titleblock_print_region_padding_mm:
      type: float
      default: 1.5
""".strip(),
            encoding="utf-8",
        )

        config = RuntimeConfig.from_yaml(runtime_spec)

        assert config.font_preflight.titleblock_print_style_replacements == {
            "宋体": {
                "font": "tssdeng.shx",
                "bigfont": "tssdchn.shx",
            }
        }
        assert config.font_preflight.titleblock_print_region_padding_mm == 1.5

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

    def test_runtime_config_reads_font_compatibility_font_alt(
        self,
        tmp_path: Path,
    ):
        """兼容打印使用的 AutoCAD 字体兜底应从运行期 YAML 落盘读取。"""
        runtime_spec = tmp_path / "documents" / "参数规范_运行期.yaml"
        runtime_spec.parent.mkdir(parents=True)
        runtime_spec.write_text(
            """
runtime_options:
  font_preflight:
    font_compatibility_font_alt:
      type: str
      default: "tssdchn.shx"
""".strip(),
            encoding="utf-8",
        )

        config = RuntimeConfig.from_yaml(runtime_spec)

        assert config.font_preflight.font_compatibility_font_alt == "tssdchn.shx"

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
        assert unit_consistency.protected_unit_text_patterns["1907"]
        assert unit_consistency.additional_unit_text_patterns == [
            r"(?P<unit_no>[0-9])\s*反\s*应\s*堆",
        ]

    def test_runtime_standard_review_reads_values_from_yaml(self):
        """规范审查的开关、规范库路径和 y 容差应由运行期 YAML 提供。"""
        repo_root = Path(__file__).resolve().parents[3]
        config = RuntimeConfig.from_yaml(repo_root / "documents" / "参数规范_运行期.yaml")
        standard_review = config.audit_check.standard_review

        assert standard_review.enabled is True
        assert Path(standard_review.library_path) == repo_root / "documents_bin" / "规范库.xlsx"
        assert standard_review.sheet_name == "DatStdItem"
        assert standard_review.same_line_y_tolerance == 5.0
        assert standard_review.same_text_pairing_enabled is True
        assert standard_review.format_variant_compatibility_enabled is True
        assert standard_review.pairing.same_entity_name_before_code_enabled is True
        assert standard_review.pairing.same_entity_code_before_name_enabled is True
        assert standard_review.pairing.multiple_pairs_in_one_entity_enabled is True
        assert standard_review.pairing.fallback_name_keywords == ["标准", "规范", "规程", "图集"]
        assert standard_review.pairing.fallback_min_name_length == 4
        assert standard_review.pairing.continuation_line_enabled is True
        assert standard_review.pairing.continuation_line_y_height_factor == 2.2
        assert standard_review.pairing.continuation_line_x_height_factor == 1.0
        assert config.audit_check.matching_policy.project_no_date_contexts == [
            "date_like",
            "titleblock_date",
        ]
        assert config.audit_check.matching_policy.project_no_numeric_run_whitelist_enabled is True
        assert config.audit_check.matching_policy.project_no_numeric_run_min_digits == 5
        assert (
            config.audit_check.matching_policy.project_no_numeric_run_requires_non_letter_suffix
            is True
        )
        assert (
            config.audit_check.matching_policy.project_no_exact_numeric_semantic_gate_enabled
            is True
        )
        assert config.audit_check.matching_policy.project_no_exact_numeric_detection_contexts == [
            "titleblock_engineering_no",
        ]
        assert (
            config.audit_check.matching_policy.project_no_exact_numeric_semantic_gate_requires_frame
            is True
        )
        assert config.audit_check.matching_policy.project_no_numeric_annotation_layer_patterns == [
            r"^NHJTTT_OpenLine$",
        ]
        assert config.font_preflight.titleblock_print_style_replacements == {}

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

    def test_change_page_extract_runtime_is_yaml_backed(self):
        repo_root = Path(__file__).resolve().parents[3]
        config = RuntimeConfig.from_yaml(repo_root / "documents" / "参数规范_运行期.yaml")
        change_page = config.change_page_extract

        assert change_page.max_archives == 50
        assert change_page.allowed_extensions == [".zip", ".rar", ".7z"]
        assert change_page.zip_metadata_encodings == ["utf-8", "gbk"]
        assert change_page.result_line_template == "{name}，共{pages}页；"
        assert change_page.archive_extractor.executable == (
            repo_root / "bin" / "7-Zip" / "7z.exe"
        ).resolve()
        assert change_page.archive_extractor.fallback_executables == [
            (repo_root / "build" / "runtime-cache" / "7-Zip" / "7z.exe").resolve()
        ]

    def test_change_page_extract_archive_path_env_override_keeps_path_type(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        executable = tmp_path / "7-Zip" / "7z.exe"
        monkeypatch.setenv(
            "FANBAN_CHANGE_PAGE_EXTRACT__ARCHIVE_EXTRACTOR__EXECUTABLE",
            str(executable),
        )

        repo_root = Path(__file__).resolve().parents[3]
        config = RuntimeConfig.from_yaml(
            repo_root / "documents" / "参数规范_运行期.yaml"
        )

        assert config.change_page_extract.archive_extractor.executable == executable
        assert isinstance(
            config.change_page_extract.archive_extractor.executable,
            Path,
        )

    def test_archive_extractor_prefers_existing_primary_then_development_fallback(self, tmp_path):
        from src.config.runtime_config import ArchiveExtractorRuntimeConfig

        primary = tmp_path / "bin" / "7-Zip" / "7z.exe"
        fallback = tmp_path / "build" / "runtime-cache" / "7-Zip" / "7z.exe"
        config = ArchiveExtractorRuntimeConfig(
            executable=primary,
            fallback_executables=[fallback],
        )

        fallback.parent.mkdir(parents=True)
        fallback.write_bytes(b"fallback")
        assert config.effective_executable() == fallback

        primary.parent.mkdir(parents=True)
        primary.write_bytes(b"primary")
        assert config.effective_executable() == primary

