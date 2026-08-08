"""
后端机制参数规范加载器 - 读取 documents/参数规范-3.yaml

职责：
- 承载不属于业务规范、也不属于运行期基础配置的后端机制参数
- 禁止重复声明已由前两份 YAML 管理的根域
- 提供按路径和环境变量覆盖的惰性加载入口
"""

from __future__ import annotations

import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator

DEFAULT_MECHANISM_SPEC_PATH = Path("documents") / "参数规范-3.yaml"
MECHANISM_SPEC_PATH_ENV_VAR = "FANBAN_MECHANISM_SPEC_PATH"
_FORBIDDEN_TOP_LEVEL_KEYS = {
    "management_features",
    "runtime_options",
    "doc_generation",
    "titleblock_extract",
}
_FACTORY_CODE_RE = re.compile(r"^(?:[A-Z][A-Z0-9]{1,3}|\d{3})$")
_WINDOWS_INVALID_FILENAME_CHARS = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED_FILENAME_STEMS = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def _windows_filename_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).rstrip(" .").casefold()


def _validate_windows_basename(value: str, *, label: str) -> str:
    if Path(value).name != value or value in {".", ".."}:
        raise ValueError(f"{label} must be a basename")
    if value != value.rstrip(" ."):
        raise ValueError(f"{label} must not end with a dot or space")
    if any(character in _WINDOWS_INVALID_FILENAME_CHARS for character in value):
        raise ValueError(f"{label} contains a Windows-invalid character")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{label} contains a control character")
    stem = value.split(".", 1)[0].casefold()
    if stem in _WINDOWS_RESERVED_FILENAME_STEMS:
        raise ValueError(f"{label} uses a Windows-reserved name")
    return value


class PermissionsConfig(BaseModel):
    account_admin_roles: list[str] = Field(default_factory=list)
    workflow_admin_roles: list[str] = Field(default_factory=list)
    workload_scope_roles: dict[str, list[str]] = Field(default_factory=dict)

    def roles_for_scope(self, scope: str) -> set[str]:
        return {str(role) for role in self.workload_scope_roles.get(scope, [])}


class ArchiveDefaultsConfig(BaseModel):
    engineering_no: str = "UNKNOWN_ENGINEERING"
    subitem_no: str = "UNKNOWN_SUBITEM"
    album_internal_code: str = "UNKNOWN_ALBUM"
    revision: str = "A"


class WorkloadSettlementConfig(BaseModel):
    include_initiator: bool = True
    initiator_role_key: str = "initiator"
    include_approved_nodes: bool = True
    node_role_key_source: str = "node_key"


class WorkflowRuntimeConfig(BaseModel):
    approval_terminal_status: str = ""
    archive_trigger_status: str = ""
    active_conflict_statuses: list[str] = Field(default_factory=list)


class TaskGroupSubmissionConditionConfig(BaseModel):
    source: Literal["params", "options"] = "params"
    field: str = Field(min_length=1)
    equals: bool = True
    default: bool = True


class TaskGroupSubmissionArtifactRequirementConfig(BaseModel):
    field: Literal["package_zip", "ied_xlsx"]
    not_declared_error: str = Field(min_length=1)
    not_found_error: str = Field(min_length=1)
    required_when: TaskGroupSubmissionConditionConfig | None = None


class TaskGroupSubmissionTaskRoleConfig(BaseModel):
    task_role: str = Field(min_length=1)
    missing_role_error: str = Field(min_length=1)
    duplicate_role_error: str = Field(min_length=1)
    artifacts: list[TaskGroupSubmissionArtifactRequirementConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_artifact_fields(self) -> TaskGroupSubmissionTaskRoleConfig:
        fields = [artifact.field for artifact in self.artifacts]
        duplicates = sorted({field for field in fields if fields.count(field) > 1})
        if duplicates:
            raise ValueError(f"duplicate artifact field: {', '.join(duplicates)}")
        return self


class TaskGroupSubmissionSharedPrepConfig(BaseModel):
    invalid_error: str = Field(default="shared_prep_invalid", min_length=1)
    source_missing_error: str = Field(default="shared_prep_source_missing", min_length=1)
    source_outside_error: str = Field(default="shared_prep_source_outside", min_length=1)


class TaskGroupSubmissionConfig(BaseModel):
    shared_prep: TaskGroupSubmissionSharedPrepConfig = Field(
        default_factory=TaskGroupSubmissionSharedPrepConfig
    )
    required_task_roles: list[TaskGroupSubmissionTaskRoleConfig] = Field(
        default_factory=lambda: [
            TaskGroupSubmissionTaskRoleConfig(
                task_role="deliverable_main",
                missing_role_error="deliverable_main_missing",
                duplicate_role_error="deliverable_main_duplicate",
                artifacts=[
                    TaskGroupSubmissionArtifactRequirementConfig(
                        field="package_zip",
                        not_declared_error="deliverable_package_not_declared",
                        not_found_error="deliverable_package_not_found",
                    ),
                    TaskGroupSubmissionArtifactRequirementConfig(
                        field="ied_xlsx",
                        not_declared_error="deliverable_ied_not_declared",
                        not_found_error="deliverable_ied_not_found",
                        required_when=TaskGroupSubmissionConditionConfig(
                            source="params",
                            field="include_ied_plan",
                            equals=True,
                            default=True,
                        ),
                    ),
                ],
            )
        ],
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_unique_task_roles(self) -> TaskGroupSubmissionConfig:
        roles = [requirement.task_role for requirement in self.required_task_roles]
        duplicates = sorted({role for role in roles if roles.count(role) > 1})
        if duplicates:
            raise ValueError(f"duplicate task_role: {', '.join(duplicates)}")
        return self


class WorkloadStatusOptionConfig(BaseModel):
    label: str
    value: str


class WorkloadRuntimeConfig(BaseModel):
    status_options: list[WorkloadStatusOptionConfig] = Field(default_factory=list)


class ManagementUiConfig(BaseModel):
    workload_scope_labels: dict[str, str] = Field(default_factory=dict)
    workflow_status_labels: dict[str, str] = Field(default_factory=dict)
    archive_status_labels: dict[str, str] = Field(default_factory=dict)
    empty_current_node_label: str = ""


class AuditDisplayConfig(BaseModel):
    forbidden_terms: list[str] = Field(default_factory=lambda: ["工种"])
    forbidden_term_connected_han_whitelist: list[str] = Field(
        default_factory=lambda: ["工种"],
    )
    forbidden_term_priority: dict[str, int] = Field(default_factory=lambda: {"工种": 0})
    finding_group_priority: dict[str, int] = Field(default_factory=lambda: {"工种": 0})
    directly_filtered_flag_codes: list[str] = Field(
        default_factory=lambda: [
            "PLOT_FROM_SOURCE_WINDOW",
            "PLOT_WINDOW_USED",
        ],
    )


class ProjectInferenceConfig(BaseModel):
    project_no_prefix_regex: str = (
        r"(?P<project_no>\d{4})(?=[0-9][A-Z0-9]{2,4}-[A-Z]{3}\d{2})"
        r"|^(\d{4})(?=[-_A-Z0-9]|$)"
    )
    unit_no_by_project_prefix_regex: str = (
        r"(?P<project_no>\d{4})(?P<unit_no>[0-9])(?=[A-Z0-9]{2,4}-[A-Z]{3}\d{2})"
    )
    default_project_no: str = "2016"


class AuditReplaceMechanismConfig(BaseModel):
    unit_factory_codes: list[str] = Field(default_factory=list)
    batch_filename_identity_regex: str = (
        r"(\d{4})([0-9])([A-Z0-9]{2,4})-?[A-Z]{3}\d{2}"
    )


class CalculationBookAiSuggestionDirectionConfig(BaseModel):
    diameters: list[PositiveInt] = Field(min_length=1)
    hard_priority: list[str] = Field(min_length=1)


class CalculationBookZeroOrMissingSmxConfig(BaseModel):
    fixed_spec: str = Field(default="1C14@400x400", min_length=1)


class CalculationBookAiSuggestionMechanismConfig(BaseModel):
    margin_ratio: float = Field(default=0.10, ge=0, le=1)
    xy: CalculationBookAiSuggestionDirectionConfig = Field(
        default_factory=lambda: CalculationBookAiSuggestionDirectionConfig(
            diameters=[16, 18, 20, 25, 28, 32, 36, 40],
            hard_priority=["1@200", "1@150", "2@200", "2@150"],
        )
    )
    z: CalculationBookAiSuggestionDirectionConfig = Field(
        default_factory=lambda: CalculationBookAiSuggestionDirectionConfig(
            diameters=[6, 8, 10, 12, 14, 16],
            hard_priority=[
                "1@400x400",
                "1@200x400",
                "1@200x200",
                "2@400x400",
                "2@200x400",
                "2@200x200",
            ],
        )
    )
    zero_or_missing_smx: CalculationBookZeroOrMissingSmxConfig = Field(
        default_factory=CalculationBookZeroOrMissingSmxConfig
    )
    slab_direction_mapping: dict[str, str] = Field(
        default_factory=lambda: {
            "top_x": "X",
            "middle_x": "X",
            "bottom_x": "X",
            "top_y": "Y",
            "middle_y": "Y",
            "bottom_y": "Y",
            "z": "Z",
        }
    )
    word_declaration: str = (
        "以下配筋建议由人工智能根据结果云图 SMX 值并保留不低于 10% 的面积裕度生成，"
        "供设计人员复核。"
    )


class CalculationBookMechanismConfig(BaseModel):
    ocr_threshold: int = Field(default=160, ge=0, le=255)
    ocr_legend_value_count: int = Field(default=10, ge=2)
    ocr_min_confidence: float = Field(default=50.0, ge=0, le=100)
    ocr_min_vertical_ratio: float = Field(default=0.35, ge=0, le=1)
    ocr_endpoint_absolute_tolerance: float = Field(default=1.0, ge=0)
    ocr_endpoint_relative_tolerance: float = Field(default=0.002, ge=0)
    ocr_header_crop: list[float] = Field(
        default_factory=lambda: [0.025, 0.02, 0.20, 0.24],
        min_length=4,
        max_length=4,
    )
    ocr_legend_crop: list[float] = Field(
        default_factory=lambda: [0.06, 0.84, 0.88, 1.0],
        min_length=4,
        max_length=4,
    )
    ocr_header_scale: int = Field(default=4, ge=1)
    ocr_legend_scale: int = Field(default=3, ge=1)
    chapter: str = "7.1"
    ai_suggestion: CalculationBookAiSuggestionMechanismConfig = Field(
        default_factory=CalculationBookAiSuggestionMechanismConfig
    )


class ApiRuntimeMechanismConfig(BaseModel):
    stage_labels: dict[str, str] = Field(
        default_factory=lambda: {
            "INIT": "初始化",
            "PREP_SOURCE": "准备源文件",
            "INGEST": "接收文件",
            "FONT_PREFLIGHT_AND_REPLACE": "字体预检与替换",
            "CONVERT_DWG_TO_DXF": "转换 DWG/DXF",
            "DETECT_FRAMES": "识别图框",
            "VERIFY_FRAMES_BY_ANCHOR": "锚点校验图框",
            "SCALE_FIT_AND_CHECK": "图幅比例校验",
            "EXTRACT_TITLEBLOCK_FIELDS": "提取图签字段",
            "A4_MULTIPAGE_GROUPING": "A4 多页合并",
            "FIX_TITLEBLOCK_CONSISTENCY": "修正图签一致性",
            "SPLIT_AND_RENAME": "拆分与命名",
            "EXPORT_PDF_AND_DWG": "导出 DWG/PDF",
            "GENERATE_DOCS": "生成目录和文档",
            "PACKAGE_ZIP": "生成交付压缩包",
            "DELIVERABLE_BRANCH": "执行出图子任务",
            "AUDIT_BRANCH": "执行纠错子任务",
            "DOCS_AND_PACKAGE": "整理文档与压缩包",
            "GROUP_COMPLETE": "任务包完成",
            "AUDIT_CHECK": "执行纠错识别",
            "AUDIT_REPLACE": "执行翻版替换",
            "EXPORT_REPORT": "导出纠错报告",
        },
    )
    job_completion_wait_timeout_sec: float = 3600.0
    job_summary_sync_interval_sec: float = 3.0
    worker_heartbeat_interval_sec: float = Field(default=10.0, gt=0)
    worker_claim_timeout_sec: float = Field(default=90.0, gt=0)
    jobs_activity_stream_poll_interval_sec: float = 2.0
    jobs_activity_stream_keepalive_sec: float = 15.0
    jobs_activity_stream_max_duration_sec: float = 60.0
    jobs_activity_stream_retry_ms: int = 5000

    @model_validator(mode="after")
    def validate_worker_claim_timing(self) -> ApiRuntimeMechanismConfig:
        if self.worker_claim_timeout_sec < 3 * self.worker_heartbeat_interval_sec:
            raise ValueError(
                "worker_claim_timeout_sec must be at least three times "
                "worker_heartbeat_interval_sec"
            )
        return self


class CadRuntimeMechanismConfig(BaseModel):
    min_supported_autocad_year: int = 2010
    pdf2_pc3_name: str = "打印PDF2.pc3"
    default_install_roots: list[str] = Field(
        default_factory=lambda: [
            r"D:\AUTOCAD",
            r"C:\AUTOCAD",
            r"D:\Program Files\AUTOCAD",
            r"C:\Program Files\AUTOCAD",
            r"D:\Program Files\Autodesk",
            r"C:\Program Files\Autodesk",
        ],
    )
    default_install_year_start: int = 2026
    default_install_year_end: int = 2010
    pdf_media_map: list[dict[str, Any]] = Field(
        default_factory=lambda: [
            {"size": [1189, 841], "name": "ISO_A0_(1189.00_x_841.00_MM)"},
            {"size": [841, 1189], "name": "ISO_A0_(841.00_x_1189.00_MM)"},
            {"size": [841, 594], "name": "ISO_A1_(841.00_x_594.00_MM)"},
            {"size": [594, 841], "name": "ISO_A1_(594.00_x_841.00_MM)"},
            {"size": [594, 420], "name": "ISO_A2_(594.00_x_420.00_MM)"},
            {"size": [420, 594], "name": "ISO_A2_(420.00_x_594.00_MM)"},
            {"size": [420, 297], "name": "ISO_A3_(420.00_x_297.00_MM)"},
            {"size": [297, 420], "name": "ISO_A3_(297.00_x_420.00_MM)"},
            {"size": [297, 210], "name": "ISO_A4_(297.00_x_210.00_MM)"},
            {"size": [210, 297], "name": "ISO_A4_(210.00_x_297.00_MM)"},
        ],
    )
    default_pdf_media_name: str = "ISO_A1_(841.00_x_594.00_MM)"
    office_com_retry_policy: dict[str, Any] = Field(default_factory=dict)


class InstallerConfig(BaseModel):
    filename: str
    url: str


class ArchiveRuntimeAssetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str = Field(min_length=1)
    url: str = Field(pattern=r"^https://")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: PositiveInt

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return _validate_windows_basename(value, label="archive runtime asset filename")


class ArchiveRuntimeFileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filename: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return _validate_windows_basename(value, label="archive runtime required filename")


class ArchiveRuntimeProbeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeout_sec: PositiveInt
    max_output_bytes: PositiveInt
    fixture_source_relative_path: str = Field(min_length=1)
    fixture_encoding: Literal["base64"]
    fixture_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_source_size_bytes: PositiveInt
    fixture_decoded_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_decoded_size_bytes: PositiveInt
    payload_source_relative_path: str = Field(min_length=1)
    payload_filename: str = Field(min_length=1)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_size_bytes: PositiveInt

    @field_validator("fixture_source_relative_path", "payload_source_relative_path")
    @classmethod
    def validate_source_relative_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("archive runtime probe source paths must be module-relative")
        return path.as_posix()

    @field_validator("payload_filename")
    @classmethod
    def validate_payload_filename(cls, value: str) -> str:
        return _validate_windows_basename(
            value,
            label="archive runtime probe payload filename",
        )

    @model_validator(mode="after")
    def validate_probe_paths(self) -> ArchiveRuntimeProbeConfig:
        if Path(self.payload_source_relative_path).name != self.payload_filename:
            raise ValueError(
                "archive runtime probe payload source basename must match payload_filename"
            )
        if not self.fixture_source_relative_path.casefold().endswith(".b64"):
            raise ValueError("base64 archive runtime probe fixture must use a .b64 source")
        return self


class ArchiveRuntimeMechanismConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    architecture: Literal["x64"] = "x64"
    source: ArchiveRuntimeAssetConfig
    bootstrap: ArchiveRuntimeAssetConfig
    license_url: str = Field(pattern=r"^https://")
    cache_dir: str = Field(min_length=1)
    destination_dir: str = Field(min_length=1)
    provenance_filename: str = Field(min_length=1)
    required_files: tuple[ArchiveRuntimeFileConfig, ...] = Field(min_length=1)
    required_handlers: tuple[str, ...] = Field(min_length=1)
    version_marker: str = Field(min_length=1)
    download_timeout_sec: PositiveInt
    prepare_timeout_sec: PositiveInt
    probe: ArchiveRuntimeProbeConfig

    @field_validator("cache_dir", "destination_dir")
    @classmethod
    def validate_relative_dir(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("archive runtime directories must be package-relative")
        return path.as_posix()

    @field_validator("provenance_filename")
    @classmethod
    def validate_provenance_filename(cls, value: str) -> str:
        return _validate_windows_basename(
            value,
            label="archive runtime provenance filename",
        )

    @model_validator(mode="after")
    def validate_required_names(self) -> ArchiveRuntimeMechanismConfig:
        filenames = [item.filename for item in self.required_files]
        filename_keys = [_windows_filename_key(filename) for filename in filenames]
        if len(filename_keys) != len(set(filename_keys)):
            raise ValueError("archive runtime required filenames must be unique")
        if _windows_filename_key(self.provenance_filename) in filename_keys:
            raise ValueError("archive runtime provenance filename must not be a required binary")
        if _windows_filename_key(self.source.filename) == _windows_filename_key(
            self.bootstrap.filename
        ):
            raise ValueError("archive runtime source and bootstrap filenames must be unique")
        handlers = list(self.required_handlers)
        if len(handlers) != len(set(handlers)):
            raise ValueError("archive runtime required handlers must be unique")
        return self


class DeploymentMechanismConfig(BaseModel):
    spec_name: str = "参数规范.yaml"
    runtime_spec_name: str = "参数规范_运行期.yaml"
    mechanism_spec_name: str = "参数规范-3.yaml"
    default_frontend_api_port: int = 8000
    managed_pdf2_pc3_name: str = "打印PDF2.pc3"
    managed_monochrome_ctb_name: str = "fanban_monochrome.ctb"
    archive_runtime: ArchiveRuntimeMechanismConfig | None = None
    installers: dict[str, InstallerConfig] = Field(
        default_factory=lambda: {
            "dotnet48": InstallerConfig(
                filename="ndp48-x86-x64-allos-enu.exe",
                url="https://go.microsoft.com/fwlink/?linkid=2088631",
            ),
            "vc_redist_x64": InstallerConfig(
                filename="VC_redist.x64.exe",
                url="https://aka.ms/vs/17/release/vc_redist.x64.exe",
            ),
            "python_313_x64": InstallerConfig(
                filename="python-3.13.12-embed-amd64.zip",
                url="https://www.python.org/ftp/python/3.13.12/python-3.13.12-embed-amd64.zip",
            ),
            "url_rewrite_x64": InstallerConfig(
                filename="rewrite_amd64_zh-CN.msi",
                url=(
                    "https://download.microsoft.com/download/1/2/8/"
                    "128E2E22-C1B9-44A4-BE2A-5859ED1D4592/rewrite_amd64_zh-CN.msi"
                ),
            ),
            "arr_x64": InstallerConfig(
                filename="requestRouter_amd64.msi",
                url="https://go.microsoft.com/fwlink/?LinkID=615136",
            ),
        },
    )


class BackendMechanismConfig(BaseModel):
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    archive_defaults: ArchiveDefaultsConfig = Field(default_factory=ArchiveDefaultsConfig)
    workload_settlement: WorkloadSettlementConfig = Field(default_factory=WorkloadSettlementConfig)
    workflow_runtime: WorkflowRuntimeConfig = Field(default_factory=WorkflowRuntimeConfig)
    task_group_submission: TaskGroupSubmissionConfig = Field(
        default_factory=TaskGroupSubmissionConfig
    )
    workload_runtime: WorkloadRuntimeConfig = Field(default_factory=WorkloadRuntimeConfig)
    management_ui: ManagementUiConfig = Field(default_factory=ManagementUiConfig)
    audit_display: AuditDisplayConfig = Field(default_factory=AuditDisplayConfig)
    audit_replace: AuditReplaceMechanismConfig = Field(default_factory=AuditReplaceMechanismConfig)
    calculation_book: CalculationBookMechanismConfig = Field(
        default_factory=CalculationBookMechanismConfig
    )
    project_inference: ProjectInferenceConfig = Field(default_factory=ProjectInferenceConfig)
    api_runtime: ApiRuntimeMechanismConfig = Field(default_factory=ApiRuntimeMechanismConfig)
    cad_runtime_mechanism: CadRuntimeMechanismConfig = Field(default_factory=CadRuntimeMechanismConfig)
    deployment_mechanism: DeploymentMechanismConfig = Field(default_factory=DeploymentMechanismConfig)


class MechanismSpec(BaseModel):
    schema_version: str = "1.0"
    backend_mechanism: BackendMechanismConfig = Field(default_factory=BackendMechanismConfig)
    source_path: Path | None = None

    @property
    def permissions(self) -> PermissionsConfig:
        return self.backend_mechanism.permissions

    @property
    def archive_defaults(self) -> ArchiveDefaultsConfig:
        return self.backend_mechanism.archive_defaults

    @property
    def workload_settlement(self) -> WorkloadSettlementConfig:
        return self.backend_mechanism.workload_settlement

    @property
    def workflow_runtime(self) -> WorkflowRuntimeConfig:
        return self.backend_mechanism.workflow_runtime

    @property
    def task_group_submission(self) -> TaskGroupSubmissionConfig:
        return self.backend_mechanism.task_group_submission

    @property
    def workload_runtime(self) -> WorkloadRuntimeConfig:
        return self.backend_mechanism.workload_runtime

    @property
    def management_ui(self) -> ManagementUiConfig:
        return self.backend_mechanism.management_ui

    @property
    def audit_display(self) -> AuditDisplayConfig:
        return self.backend_mechanism.audit_display

    @property
    def audit_replace(self) -> AuditReplaceMechanismConfig:
        return self.backend_mechanism.audit_replace

    @property
    def calculation_book(self) -> CalculationBookMechanismConfig:
        return self.backend_mechanism.calculation_book

    @property
    def project_inference(self) -> ProjectInferenceConfig:
        return self.backend_mechanism.project_inference

    @property
    def api_runtime(self) -> ApiRuntimeMechanismConfig:
        return self.backend_mechanism.api_runtime

    @property
    def cad_runtime_mechanism(self) -> CadRuntimeMechanismConfig:
        return self.backend_mechanism.cad_runtime_mechanism

    @property
    def deployment_mechanism(self) -> DeploymentMechanismConfig:
        return self.backend_mechanism.deployment_mechanism


class MechanismSpecLoader:
    @classmethod
    @lru_cache(maxsize=8)
    def _load_cached(cls, resolved_path: str) -> MechanismSpec:
        path = Path(resolved_path)
        if not path.exists():
            raise FileNotFoundError(f"机制参数规范文件不存在: {path}")
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        forbidden = sorted(_FORBIDDEN_TOP_LEVEL_KEYS.intersection(data.keys()))
        if forbidden:
            raise ValueError(f"参数规范-3.yaml 不允许重复声明已有根域: {', '.join(forbidden)}")
        spec = MechanismSpec(**data)
        spec.source_path = path
        _validate_permission_roles(spec, path)
        return spec

    @classmethod
    def load(cls, spec_path: str | Path = DEFAULT_MECHANISM_SPEC_PATH) -> MechanismSpec:
        path = _resolve_mechanism_spec_path(spec_path)
        return cls._load_cached(_cache_key(path))

    @classmethod
    def reload(cls, spec_path: str | Path = DEFAULT_MECHANISM_SPEC_PATH) -> MechanismSpec:
        cls.clear_cache()
        return cls.load(spec_path)

    @classmethod
    def clear_cache(cls) -> None:
        cls._load_cached.cache_clear()


def load_mechanism_spec(spec_path: str | Path = DEFAULT_MECHANISM_SPEC_PATH) -> MechanismSpec:
    return MechanismSpecLoader.load(spec_path)


def normalize_audit_replace_factory_codes(values: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        code = str(value or "").strip().upper()
        if not code or code in seen or not _FACTORY_CODE_RE.fullmatch(code):
            continue
        seen.add(code)
        normalized.append(code)
    return normalized


def append_audit_replace_factory_codes(
    values: list[str] | tuple[str, ...] | set[str],
    *,
    spec_path: str | Path = DEFAULT_MECHANISM_SPEC_PATH,
) -> list[str]:
    path = _resolve_mechanism_spec_path(spec_path)
    existing = normalize_audit_replace_factory_codes(load_mechanism_spec(path).audit_replace.unit_factory_codes)
    updated = normalize_audit_replace_factory_codes([*existing, *values])
    if updated != existing:
        _write_audit_replace_factory_codes(path, updated)
        MechanismSpecLoader.clear_cache()
    return updated


def _resolve_mechanism_spec_path(spec_path: str | Path) -> Path:
    path = Path(spec_path)
    if path == DEFAULT_MECHANISM_SPEC_PATH:
        env_path = os.getenv(MECHANISM_SPEC_PATH_ENV_VAR)
        if env_path:
            return Path(env_path)
        if path.exists():
            return path
        try:
            from .runtime_config import get_config

            configured_path = Path(get_config().mechanism_spec_path)
            if configured_path.exists():
                return configured_path
        except Exception:
            pass
    return path


def _write_audit_replace_factory_codes(path: Path, values: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "schema_version: '1.0'\n"
            "backend_mechanism:\n"
            "  audit_replace:\n"
            "    unit_factory_codes:\n"
            + "".join(f'      - "{value}"\n' for value in values),
            encoding="utf-8",
        )
        return

    lines = path.read_text(encoding="utf-8").splitlines()
    backend_index = _find_yaml_key(lines, "backend_mechanism", 0, 0, len(lines))
    if backend_index is None:
        lines.extend(["backend_mechanism:"])
        backend_index = len(lines) - 1

    backend_end = _find_yaml_block_end(lines, backend_index, 0)
    audit_index = _find_yaml_key(lines, "audit_replace", 2, backend_index + 1, backend_end)
    if audit_index is None:
        insert_at = backend_index + 1
        lines[insert_at:insert_at] = _factory_code_yaml_block(values, include_parent=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    audit_end = _find_yaml_block_end(lines, audit_index, 2)
    codes_index = _find_yaml_key(lines, "unit_factory_codes", 4, audit_index + 1, audit_end)
    replacement = _factory_code_yaml_block(values, include_parent=False)
    if codes_index is None:
        lines[audit_index + 1:audit_index + 1] = replacement
    else:
        codes_end = _find_yaml_sequence_block_end(lines, codes_index, 4)
        lines[codes_index:codes_end] = replacement
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _factory_code_yaml_block(values: list[str], *, include_parent: bool) -> list[str]:
    lines = ["  audit_replace:"] if include_parent else []
    lines.append("    unit_factory_codes:")
    lines.extend(f'      - "{value}"' for value in values)
    return lines


def _find_yaml_key(
    lines: list[str],
    key: str,
    indent: int,
    start: int,
    end: int,
) -> int | None:
    prefix = " " * indent + f"{key}:"
    for index in range(start, min(end, len(lines))):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#"):
            continue
        if lines[index].startswith(prefix):
            return index
    return None


def _find_yaml_block_end(lines: list[str], start_index: int, indent: int) -> int:
    for index in range(start_index + 1, len(lines)):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _yaml_indent(lines[index]) <= indent:
            return index
    return len(lines)


def _find_yaml_sequence_block_end(lines: list[str], start_index: int, indent: int) -> int:
    for index in range(start_index + 1, len(lines)):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#"):
            continue
        current_indent = _yaml_indent(lines[index])
        if current_indent < indent:
            return index
        if current_indent == indent and stripped.startswith("- "):
            continue
        if current_indent <= indent:
            return index
    return len(lines)


def _yaml_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _cache_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except Exception:
        return str(path.absolute())


def _validate_permission_roles(spec: MechanismSpec, mechanism_path: Path) -> None:
    valid_roles = _load_valid_business_roles(mechanism_path)
    if not valid_roles:
        return

    configured_roles: set[str] = set(spec.permissions.account_admin_roles)
    configured_roles.update(spec.permissions.workflow_admin_roles)
    for roles in spec.permissions.workload_scope_roles.values():
        configured_roles.update(str(role) for role in roles)

    invalid_roles = sorted(role for role in configured_roles if role and role not in valid_roles)
    if invalid_roles:
        raise ValueError(
            "参数规范-3.yaml permissions 包含未在参数规范.yaml "
            f"management_features.account.valid_roles 声明的角色: {', '.join(invalid_roles)}"
        )


def _load_valid_business_roles(mechanism_path: Path) -> set[str] | None:
    try:
        from .spec_loader import DEFAULT_SPEC_PATH, SPEC_PATH_ENV_VAR, load_spec

        if os.getenv(SPEC_PATH_ENV_VAR):
            business_spec = load_spec()
        else:
            sibling_spec = mechanism_path.parent / DEFAULT_SPEC_PATH.name
            if sibling_spec.exists():
                business_spec = load_spec(sibling_spec)
            elif DEFAULT_SPEC_PATH.exists():
                business_spec = load_spec()
            else:
                return None
    except Exception:
        return None

    account = business_spec.get_management_features().get("account", {})
    roles = account.get("valid_roles", [])
    return {str(role) for role in roles if str(role).strip()}
