"""
运行期配置 - 读取 documents/参数规范_运行期.yaml

职责：
- 加载并发/超时/路径等运行参数
- 提供环境变量覆盖机制
- 类型安全的配置访问
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class ConcurrencyConfig(BaseModel):
    """并发配置"""

    max_workers: int = 2
    max_jobs: int = 4
    max_queue: int = 20


class TimeoutConfig(BaseModel):
    """超时配置"""

    oda_convert_sec: int = 600
    office_export_sec: int = 300
    pdf_export_sec: int = 300


class RetryConfig(BaseModel):
    """重试配置"""

    max_retries: int = 2
    retry_backoff_ms: int = 1000


class ODAConfig(BaseModel):
    """ODA转换器配置"""

    exe_path: str = ""
    work_dir: str | None = None


class Module5ExportConfig(BaseModel):
    """模块5导出配置"""

    pdf_engine: str = "python"


class AutoCADConfig(BaseModel):
    """AutoCAD 运行配置（模块5增量链路）"""

    install_dir: str = r"D:\Program Files\Autodesk\AutoCAD 2021"
    prog_id_candidates: list[str] = Field(
        default_factory=lambda: [
            "AutoCAD.Application.24.1",
            "AutoCAD.Application.24.0",
            "AutoCAD.Application",
        ],
    )
    visible: bool = False
    plot_timeout_sec: int = 300
    ctb_path: str = r"Plotters\Plot Styles\monochrome.ctb"
    pc3_name: str = "DWG To PDF.pc3"
    retry: int = 1


class PDFEngineConfig(BaseModel):
    """PDF引擎配置"""

    preferred: str = "office_com"
    fallback: str = "libreoffice"


class UploadLimitsConfig(BaseModel):
    """上传限制"""

    max_files: int = 50
    max_total_mb: int = 2048
    allowed_exts: list[str] = Field(default_factory=lambda: [".dwg"])
    min_free_disk_mb: int = 10240


class LifecycleConfig(BaseModel):
    """生命周期配置"""

    retention_hours: int = 168
    cleanup_on_cancel: bool = True
    cleanup_cron: str = "0 3 * * *"


class LoggingConfig(BaseModel):
    """日志配置"""

    log_level: str = "INFO"
    log_to_file: bool = True


class MultiDwgPolicyConfig(BaseModel):
    """多DWG处理与冲突策略"""

    per_dwg_isolation: bool = True
    same_name_dwg: str = "error"
    code_conflict: str = "error"
    output_grouping: str = "by_dwg"
    manifest_grouping: str = "by_dwg"


class DxfPdfExportConfig(BaseModel):
    """DXF→PDF 渲染配置（ACI线宽映射 + 黑白控制）"""

    aci1_linewidth_mm: float = 0.4
    aci_default_linewidth_mm: float = 0.18
    monochrome: bool = True
    screening: int = 100
    font_dirs: list[str] = Field(default_factory=lambda: ["fronts/Fonts", "Fonts"])
    fallback_font_family: list[str] = Field(
        default_factory=lambda: ["SimSun", "Microsoft YaHei", "SimHei"],
    )


class RuntimeConfig(BaseSettings):
    """运行期配置（支持环境变量覆盖）"""

    # 基础路径
    base_dir: Path = Path(".")
    storage_dir: Path = Path("storage")
    spec_path: Path = Path("documents/参数规范.yaml")
    runtime_spec_path: Path = Path("documents/参数规范_运行期.yaml")

    # 各子配置
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)
    retries: RetryConfig = Field(default_factory=RetryConfig)
    oda: ODAConfig = Field(default_factory=ODAConfig)
    module5_export: Module5ExportConfig = Field(default_factory=Module5ExportConfig)
    autocad: AutoCADConfig = Field(default_factory=AutoCADConfig)
    pdf_engine: PDFEngineConfig = Field(default_factory=PDFEngineConfig)
    upload_limits: UploadLimitsConfig = Field(default_factory=UploadLimitsConfig)
    lifecycle: LifecycleConfig = Field(default_factory=LifecycleConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    multi_dwg_policy: MultiDwgPolicyConfig = Field(default_factory=MultiDwgPolicyConfig)
    dxf_pdf_export: DxfPdfExportConfig = Field(default_factory=DxfPdfExportConfig)

    model_config = {
        "env_prefix": "FANBAN_",
        "env_nested_delimiter": "__",
        "arbitrary_types_allowed": True,
    }

    @classmethod
    def from_yaml(cls, yaml_path: str | Path) -> RuntimeConfig:
        """从YAML文件加载配置"""
        path = Path(yaml_path)
        if not path.exists():
            return cls()

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        runtime_opts = data.get("runtime_options", {})

        config = cls(
            concurrency=ConcurrencyConfig(**cls._extract(runtime_opts, "concurrency")),
            timeouts=TimeoutConfig(**cls._extract(runtime_opts, "timeouts")),
            retries=RetryConfig(**cls._extract(runtime_opts, "retries")),
            oda=ODAConfig(**cls._extract(runtime_opts, "oda_converter")),
            module5_export=Module5ExportConfig(
                **cls._extract(runtime_opts, "module5_export"),
            ),
            autocad=AutoCADConfig(**cls._extract(runtime_opts, "autocad")),
            pdf_engine=PDFEngineConfig(**cls._extract(runtime_opts, "pdf_engine")),
            upload_limits=UploadLimitsConfig(**cls._extract(runtime_opts, "upload_limits")),
            lifecycle=LifecycleConfig(**cls._extract(runtime_opts, "lifecycle")),
            logging=LoggingConfig(**cls._extract(runtime_opts, "logging")),
            multi_dwg_policy=MultiDwgPolicyConfig(
                **cls._extract(runtime_opts, "multi_dwg_policy"),
            ),
            dxf_pdf_export=DxfPdfExportConfig(
                **cls._extract(runtime_opts, "dxf_pdf_export"),
            ),
        )

        config._resolve_paths(base_dir=path.parent)
        return config

    @staticmethod
    def _extract(data: dict[str, Any], key: str) -> dict[str, Any]:
        """提取并展平配置"""
        section = data.get(key, {})
        result = {}
        for k, v in section.items():
            if isinstance(v, dict) and "default" in v:
                result[k] = v["default"]
            elif not isinstance(v, dict):
                result[k] = v
        return result

    def _resolve_paths(self, base_dir: Path) -> None:
        """解析相对路径配置为绝对路径（基于配置文件所在目录）"""
        if self.oda.exe_path:
            exe_path = Path(self.oda.exe_path)
            if not exe_path.is_absolute():
                self.oda.exe_path = str((base_dir / exe_path).resolve())
        if self.oda.work_dir:
            work_dir = Path(self.oda.work_dir)
            if not work_dir.is_absolute():
                self.oda.work_dir = str((base_dir / work_dir).resolve())
        if self.autocad.install_dir:
            install_dir = Path(self.autocad.install_dir)
            if not install_dir.is_absolute():
                self.autocad.install_dir = str((base_dir / install_dir).resolve())
        if self.autocad.ctb_path:
            ctb_path = Path(self.autocad.ctb_path)
            if not ctb_path.is_absolute():
                autocad_base = Path(self.autocad.install_dir) if self.autocad.install_dir else base_dir
                self.autocad.ctb_path = str((autocad_base / ctb_path).resolve())

    def get_job_dir(self, job_id: str) -> Path:
        """获取任务工作目录"""
        return self.storage_dir / "jobs" / job_id

    def ensure_dirs(self) -> None:
        """确保必要目录存在"""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        (self.storage_dir / "jobs").mkdir(exist_ok=True)


# 全局配置实例
_config: RuntimeConfig | None = None


def get_config() -> RuntimeConfig:
    """获取全局配置（惰性加载）"""
    global _config
    if _config is None:
        default_path = Path("documents/参数规范_运行期.yaml")
        if not default_path.exists():
            fallback_path = Path("config/参数规范_运行期.yaml")
            if fallback_path.exists():
                default_path = fallback_path
        _config = RuntimeConfig.from_yaml(default_path)
    return _config


def reload_config(yaml_path: str | Path | None = None) -> RuntimeConfig:
    """重新加载配置"""
    global _config
    path = yaml_path or "documents/参数规范_运行期.yaml"
    _config = RuntimeConfig.from_yaml(path)
    return _config
