"""
运行期配置 - 读取 documents/参数规范_运行期.yaml

职责：
- 加载并发/超时/路径等运行参数
- 提供环境变量覆盖机制
- 类型安全的配置访问
"""

from __future__ import annotations

import os
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


class Module5CadRunnerConfig(BaseModel):
    """模块5 CAD运行器配置"""

    accoreconsole_exe: str = ""
    script_dir: str = r"..\backend\src\cad\scripts"
    task_timeout_sec: int = 900
    retry: int = 1
    locale: str = "en-US"
    max_parallel_dxf: int = 1


class Module5DotNetBridgeConfig(BaseModel):
    """模块5 .NET 桥接配置"""

    enabled: bool = True
    dll_path: str = (
        r"..\backend\src\cad\dotnet\Module5CadBridge\bin\Release\net48\Module5CadBridge.dll"
    )
    command_name: str = "M5BRIDGE_RUN"
    netload_each_run: bool = True
    fallback_to_lisp_on_error: bool = True


class Module5SelectionConfig(BaseModel):
    """模块5选集配置"""

    engine: str = "dotnet"
    mode: str = "database"
    bbox_margin_percent: float = 0.015
    empty_selection_retry_margin_percent: float = 0.03
    hard_retry_margin_percent: float = 0.25
    db_unknown_bbox_policy: str = "keep_if_uncertain"
    db_fallback_to_crossing: bool = True


class Module5PlotConfig(BaseModel):
    """模块5打印配置"""

    pc3_name: str = "打印PDF2.pc3"
    ctb_name: str = "fanban_monochrome.ctb"
    paper_from_frame: bool = True
    use_monochrome: bool = True
    center_plot: bool = False
    plot_offset_mm: dict[str, float] = Field(
        default_factory=lambda: {"x": 0.0, "y": 0.0},
    )
    plot_window_top_right_expand_ratio: float = 0.0001
    scale_mode: str = "manual_integer_from_geometry"
    scale_integer_rounding: str = "round"
    margins_mm: dict[str, float] = Field(
        default_factory=lambda: {
            "top": 0.0,
            "bottom": 0.0,
            "left": 0.0,
            "right": 0.0,
        },
    )


class Module5OutputConfig(BaseModel):
    """模块5输出策略配置"""

    plot_engine: str = "dotnet"
    a4_multipage_pdf: str = "dotnet_multipage"
    on_frame_fail: str = "flag_and_continue"
    pdf_from_split_dwg_mode: str = "always"
    split_stage_plot_enabled: bool = False
    plot_preferred_area: str = "window"
    plot_fallback_area: str = "none"
    plot_session_mode: str = "per_source_batch"
    plot_from_source_window_enabled: bool = True
    plot_fallback_to_split_on_failure: bool = True
    pdf_validation_min_size_bytes: int = 1024
    pdf_validation_min_stream_bytes: int = 64


class Module5ExportConfig(BaseModel):
    """模块5导出配置"""

    pdf_engine: str = "python"
    engine: str = "cad_dxf"
    cad_runner: Module5CadRunnerConfig = Field(default_factory=Module5CadRunnerConfig)
    dotnet_bridge: Module5DotNetBridgeConfig = Field(
        default_factory=Module5DotNetBridgeConfig,
    )
    selection: Module5SelectionConfig = Field(default_factory=Module5SelectionConfig)
    plot: Module5PlotConfig = Field(default_factory=Module5PlotConfig)
    output: Module5OutputConfig = Field(default_factory=Module5OutputConfig)


class AutoCADConfig(BaseModel):
    """AutoCAD 运行配置（模块5增量链路）"""

    install_dir: str = ""
    prog_id_candidates: list[str] = Field(
        default_factory=lambda: [
            "AutoCAD.Application.24.1",
            "AutoCAD.Application.24.0",
            "AutoCAD.Application",
        ],
    )
    visible: bool = False
    plot_timeout_sec: int = 300
    ctb_path: str = ""
    pc3_name: str = "打印PDF2.pc3"
    retry: int = 1


class PDFEngineConfig(BaseModel):
    """PDF引擎配置"""

    preferred: str = "office_com"
    fallback: str = "libreoffice"


class AuditCheckGenericIdentifierConfig(BaseModel):
    """纠错 generic_identifier_like 配置"""

    regex: str = r"^[A-Z0-9-]{6,}$"
    exempt_embed_patterns: list[str] = Field(
        default_factory=lambda: [r"^[A-Z]{3}\d{4}[A-Z]$"],
    )


class AuditCheckContextRulesConfig(BaseModel):
    """纠错上下文分类规则"""

    date_like: list[str] = Field(
        default_factory=lambda: [
            r"^\d{4}[-/.]\d{1,2}$",
            r"^\d{4}[-/.]\d{1,2}([-/.:]\d{1,2})+$",
            r"^\d{4}年\d{1,2}月(\d{1,2}日?)?$",
        ],
    )
    dimension_like: list[str] = Field(default_factory=lambda: [r"^\d+(?:\s*[X×*]\s*\d+)+$"])
    code_like_internal: list[str] = Field(
        default_factory=lambda: [r"^\d{4}[A-Z0-9]+(?:-[A-Z0-9]+){1,2}$"],
    )
    code_like_external: list[str] = Field(default_factory=lambda: [r"^[A-Z0-9]{19}$"])


class AuditCheckMatchingPolicyConfig(BaseModel):
    """纠错匹配策略配置"""

    roi_context_priority: bool = True
    allow_embedded_match_in_titleblock: bool = True
    suppress_project_no_in_date_like: bool = True
    suppress_project_no_in_dimension_like: bool = True


class AuditCheckConfig(BaseModel):
    """纠错运行配置"""

    enabled: bool = True
    lexicon_path: str = r"documents_bin\词库收集.xlsx"
    project_column_header_pattern: str = r"^\d{4}$"
    include_rows: list[int | str] = Field(default_factory=lambda: [1, 2, "3+"])
    generic_identifier_like: AuditCheckGenericIdentifierConfig = Field(
        default_factory=AuditCheckGenericIdentifierConfig,
    )
    context_rules: AuditCheckContextRulesConfig = Field(default_factory=AuditCheckContextRulesConfig)
    matching_policy: AuditCheckMatchingPolicyConfig = Field(
        default_factory=AuditCheckMatchingPolicyConfig,
    )


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
    audit_check: AuditCheckConfig = Field(default_factory=AuditCheckConfig)
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

        yaml_values = {
            "concurrency": ConcurrencyConfig(**cls._extract(runtime_opts, "concurrency")),
            "timeouts": TimeoutConfig(**cls._extract(runtime_opts, "timeouts")),
            "retries": RetryConfig(**cls._extract(runtime_opts, "retries")),
            "oda": ODAConfig(**cls._extract(runtime_opts, "oda_converter")),
            "module5_export": Module5ExportConfig(
                **cls._extract(runtime_opts, "module5_export"),
            ),
            "autocad": AutoCADConfig(**cls._extract(runtime_opts, "autocad")),
            "pdf_engine": PDFEngineConfig(**cls._extract(runtime_opts, "pdf_engine")),
            "audit_check": AuditCheckConfig(**cls._extract(runtime_opts, "audit_check")),
            "upload_limits": UploadLimitsConfig(**cls._extract(runtime_opts, "upload_limits")),
            "lifecycle": LifecycleConfig(**cls._extract(runtime_opts, "lifecycle")),
            "logging": LoggingConfig(**cls._extract(runtime_opts, "logging")),
            "multi_dwg_policy": MultiDwgPolicyConfig(
                **cls._extract(runtime_opts, "multi_dwg_policy"),
            ),
            "dxf_pdf_export": DxfPdfExportConfig(
                **cls._extract(runtime_opts, "dxf_pdf_export"),
            ),
        }

        # BaseSettings 直接传参会压过环境变量；这里先按 YAML 组装，再显式应用 FANBAN_* 覆盖。
        config = cls.model_validate(yaml_values)
        config._apply_env_overrides()
        config._normalize_root_paths(base_dir=path.parent)
        config._resolve_paths(base_dir=path.parent)
        return config

    @staticmethod
    def _extract(data: dict[str, Any], key: str) -> dict[str, Any]:
        """提取并展平配置"""
        section = data.get(key, {})
        extracted = RuntimeConfig._extract_tree(section)
        return extracted if isinstance(extracted, dict) else {}

    @staticmethod
    def _extract_tree(node: Any) -> Any:
        """递归提取 default 值，兼容嵌套配置结构。"""
        if isinstance(node, dict):
            if "default" in node and any(k in node for k in ("type", "desc", "required")):
                return node["default"]
            # 叶子参数允许无 default（例如可选 work_dir），此时应返回 None，
            # 避免把参数元数据对象误当作真实配置值。
            if "default" not in node and "type" in node:
                has_nested_value = any(isinstance(v, (dict, list)) for v in node.values())
                if not has_nested_value:
                    return None
            result: dict[str, Any] = {}
            for k, v in node.items():
                extracted = RuntimeConfig._extract_tree(v)
                if extracted is None and isinstance(v, dict):
                    continue
                result[k] = extracted
            return result
        return node

    @staticmethod
    def _parse_env_value(raw: str) -> Any:
        """尽量按 YAML 字面量解析环境变量值（bool/int/list 等）。"""
        parsed = yaml.safe_load(raw)
        return raw if parsed is None else parsed

    def _apply_env_overrides(self) -> None:
        """应用 FANBAN_* 覆盖（支持 __ 嵌套路径）。"""
        prefix = "FANBAN_"
        for env_key, env_val in os.environ.items():
            if not env_key.startswith(prefix):
                continue
            path_tokens = [x.lower() for x in env_key[len(prefix) :].split("__") if x]
            if not path_tokens:
                continue
            self._set_nested_value(path_tokens, self._parse_env_value(env_val))

    def _set_nested_value(self, path_tokens: list[str], value: Any) -> None:
        """按路径 token 在配置对象内写值，忽略未知键。"""
        cursor: Any = self
        for token in path_tokens[:-1]:
            if isinstance(cursor, BaseModel):
                if not hasattr(cursor, token):
                    return
                cursor = getattr(cursor, token)
                continue
            if isinstance(cursor, dict):
                if token not in cursor:
                    return
                cursor = cursor[token]
                continue
            return

        leaf = path_tokens[-1]
        if isinstance(cursor, BaseModel):
            if hasattr(cursor, leaf):
                setattr(cursor, leaf, value)
        elif isinstance(cursor, dict):
            cursor[leaf] = value

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
                autocad_base = (
                    Path(self.autocad.install_dir) if self.autocad.install_dir else base_dir
                )
                self.autocad.ctb_path = str((autocad_base / ctb_path).resolve())
        if self.module5_export.cad_runner.accoreconsole_exe:
            accore = Path(self.module5_export.cad_runner.accoreconsole_exe)
            if not accore.is_absolute():
                self.module5_export.cad_runner.accoreconsole_exe = str(
                    (base_dir / accore).resolve(),
                )
        if self.module5_export.cad_runner.script_dir:
            script_dir = Path(self.module5_export.cad_runner.script_dir)
            if not script_dir.is_absolute():
                self.module5_export.cad_runner.script_dir = str(
                    (base_dir / script_dir).resolve(),
                )
        if self.module5_export.dotnet_bridge.dll_path:
            dll_path = Path(self.module5_export.dotnet_bridge.dll_path)
            if not dll_path.is_absolute():
                self.module5_export.dotnet_bridge.dll_path = str(
                    (base_dir / dll_path).resolve(),
                )
        if self.audit_check.lexicon_path:
            lexicon_path = Path(self.audit_check.lexicon_path)
            if not lexicon_path.is_absolute():
                self.audit_check.lexicon_path = str((self.base_dir / lexicon_path).resolve())

    def _normalize_root_paths(self, base_dir: Path) -> None:
        """???????????????????? Path???????????"""
        project_root = self._resolve_project_root(base_dir)
        self.base_dir = self._resolve_root_path(self.base_dir, project_root)
        self.storage_dir = self._coerce_path(self.storage_dir)
        self.spec_path = self._coerce_path(self.spec_path)
        self.runtime_spec_path = self._coerce_path(self.runtime_spec_path)

    @staticmethod
    def _coerce_path(value: str | Path) -> Path:
        return value if isinstance(value, Path) else Path(value)

    @classmethod
    def _resolve_root_path(cls, value: str | Path, project_root: Path) -> Path:
        path = cls._coerce_path(value)
        if path.is_absolute():
            return path
        return (project_root / path).resolve()

    @staticmethod
    def _resolve_project_root(config_dir: Path) -> Path:
        normalized = config_dir.resolve()
        if normalized.name.lower() in {"documents", "config"}:
            return normalized.parent
        return normalized

    def get_job_dir(self, job_id: str) -> Path:
        """获取任务工作目录"""
        return self.storage_dir / "jobs" / job_id

    def ensure_dirs(self) -> None:
        """确保必要目录存在"""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        (self.storage_dir / "jobs").mkdir(exist_ok=True)


# 全局配置实例
_config: RuntimeConfig | None = None
_config_source_path: Path | None = None
DEFAULT_RUNTIME_SPEC_PATH = Path("documents/参数规范_运行期.yaml")
FALLBACK_RUNTIME_SPEC_PATH = Path("config/参数规范_运行期.yaml")
RUNTIME_SPEC_PATH_ENV_VAR = "FANBAN_RUNTIME_SPEC_PATH"


def get_config() -> RuntimeConfig:
    """获取全局配置（惰性加载）"""
    global _config, _config_source_path
    path = _normalize_runtime_spec_path(_resolve_runtime_spec_path())
    if _config is None or _config_source_path != path:
        _config = RuntimeConfig.from_yaml(path)
        _config_source_path = path
    return _config


def reload_config(yaml_path: str | Path | None = None) -> RuntimeConfig:
    """重新加载配置"""
    global _config, _config_source_path
    path = _normalize_runtime_spec_path(_resolve_runtime_spec_path(yaml_path))
    _config = RuntimeConfig.from_yaml(path)
    _config_source_path = path
    return _config


def _resolve_runtime_spec_path(yaml_path: str | Path | None = None) -> Path:
    if yaml_path is not None:
        return Path(yaml_path)

    env_path = os.getenv(RUNTIME_SPEC_PATH_ENV_VAR)
    if env_path:
        return Path(env_path)

    if DEFAULT_RUNTIME_SPEC_PATH.exists():
        return DEFAULT_RUNTIME_SPEC_PATH
    if FALLBACK_RUNTIME_SPEC_PATH.exists():
        return FALLBACK_RUNTIME_SPEC_PATH
    return DEFAULT_RUNTIME_SPEC_PATH


def _normalize_runtime_spec_path(path: Path) -> Path:
    try:
        return path.resolve()
    except Exception:
        return path.absolute()


