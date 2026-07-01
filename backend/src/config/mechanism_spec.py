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
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


DEFAULT_MECHANISM_SPEC_PATH = Path("documents") / "参数规范-3.yaml"
MECHANISM_SPEC_PATH_ENV_VAR = "FANBAN_MECHANISM_SPEC_PATH"
_FORBIDDEN_TOP_LEVEL_KEYS = {
    "management_features",
    "runtime_options",
    "doc_generation",
    "titleblock_extract",
}
_FACTORY_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,3}$")


class PermissionsConfig(BaseModel):
    account_admin_roles: list[str] = Field(default_factory=lambda: ["管理员"])
    workflow_admin_roles: list[str] = Field(default_factory=lambda: ["管理员"])
    workload_scope_roles: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "office": ["室主任", "所领导", "管理员"],
            "institute": ["所领导", "管理员"],
            "admin": ["管理员"],
        },
    )

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


class AuditDisplayConfig(BaseModel):
    forbidden_terms: list[str] = Field(default_factory=lambda: ["工种"])
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


class DeploymentMechanismConfig(BaseModel):
    spec_name: str = "参数规范.yaml"
    runtime_spec_name: str = "参数规范_运行期.yaml"
    mechanism_spec_name: str = "参数规范-3.yaml"
    default_frontend_api_port: int = 8000
    managed_pdf2_pc3_name: str = "打印PDF2.pc3"
    managed_monochrome_ctb_name: str = "fanban_monochrome.ctb"
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
    audit_display: AuditDisplayConfig = Field(default_factory=AuditDisplayConfig)
    audit_replace: AuditReplaceMechanismConfig = Field(default_factory=AuditReplaceMechanismConfig)
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
    def audit_display(self) -> AuditDisplayConfig:
        return self.backend_mechanism.audit_display

    @property
    def audit_replace(self) -> AuditReplaceMechanismConfig:
        return self.backend_mechanism.audit_replace

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
