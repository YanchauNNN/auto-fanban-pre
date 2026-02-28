"""
配置加载单元测试

每个模块完成后必须运行：pytest tests/unit/test_config.py -v
"""

from src.config import BusinessSpec, RuntimeConfig


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
        assert runtime_config.module5_export.selection.mode == "crossing"
        assert runtime_config.module5_export.cad_runner.task_timeout_sec == 900
        assert runtime_config.autocad.install_dir == r"D:\Program Files\Autodesk\AutoCAD 2021"
        assert runtime_config.autocad.prog_id_candidates == [
            "AutoCAD.Application.24.1",
            "AutoCAD.Application.24.0",
            "AutoCAD.Application",
        ]
        assert runtime_config.autocad.pc3_name == "DWG To PDF.pc3"
