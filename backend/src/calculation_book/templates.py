from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from docxtpl import DocxTemplate

from .models import CalculationBookTemplate

TEMPLATE_FILENAMES = {
    CalculationBookTemplate.INTERNAL_STRUCTURE: "内部结构计算书.docx",
    CalculationBookTemplate.NUCLEAR_ISLAND_PLANT: "核岛厂房计算书.docx",
}


class TemplateContractError(ValueError):
    pass


def resolve_template_path(root: Path, template_type: CalculationBookTemplate) -> Path:
    path = root / TEMPLATE_FILENAMES[template_type]
    if not path.is_file():
        raise FileNotFoundError(f"未找到计算书模板：{path}")
    return path


def get_template_variables(path: Path) -> set[str]:
    if not path.is_file():
        raise FileNotFoundError(f"未找到计算书模板：{path}")
    try:
        return set(DocxTemplate(path).get_undeclared_template_variables())
    except Exception as exc:  # noqa: BLE001
        raise TemplateContractError(f"无法读取计算书模板变量：{path.name}") from exc


def validate_template_context(path: Path, context: Mapping[str, object]) -> None:
    missing = sorted(get_template_variables(path) - set(context))
    if missing:
        raise TemplateContractError(f"计算书模板缺少上下文变量：{', '.join(missing)}")
