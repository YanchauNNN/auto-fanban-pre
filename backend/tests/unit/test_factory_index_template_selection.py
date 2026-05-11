from __future__ import annotations

from pathlib import Path


def test_factory_index_template_selection_uses_configured_target_project(tmp_path: Path) -> None:
    from src.audit_replace.factory_index_bridge import FactoryIndexMapReplacementService
    from src.config.runtime_config import FactoryIndexMapsConfig, RuntimeConfig

    config = RuntimeConfig(base_dir=tmp_path)
    config.factory_index_maps = FactoryIndexMapsConfig(
        template_dir=Path("documents_bin/factory_index_maps"),
        templates={"1818": "1818项目厂房索引图.dwg", "2026": "2026项目厂房索引图.dwg"},
        island_templates={
            "1916": {"3": "1916项目3号岛厂房索引图.dwg", "4": "1916项目4号岛厂房索引图.dwg"},
            "2016": {"1": "2016项目1号岛厂房索引图.dwg", "2": "2016项目2号岛厂房索引图.dwg"},
        },
    )
    service = FactoryIndexMapReplacementService(config=config)

    selection = service.select_template(
        source_project_no="2016",
        target_project_no="1818",
        source_filename="20162KA-JGS03-A.dwg",
    )

    assert selection is not None
    assert selection.project_no == "1818"
    assert selection.variant is None
    assert selection.path == tmp_path / "documents_bin" / "factory_index_maps" / "1818项目厂房索引图.dwg"


def test_factory_index_template_selection_uses_explicit_island_variant(tmp_path: Path) -> None:
    from src.audit_replace.factory_index_bridge import FactoryIndexMapReplacementService
    from src.config.runtime_config import FactoryIndexMapsConfig, RuntimeConfig

    config = RuntimeConfig(base_dir=tmp_path)
    config.factory_index_maps = FactoryIndexMapsConfig(
        template_dir=Path("documents_bin/factory_index_maps"),
        island_templates={
            "1916": {"3": "1916项目3号岛厂房索引图.dwg", "4": "1916项目4号岛厂房索引图.dwg"},
        },
    )
    service = FactoryIndexMapReplacementService(config=config)

    selection = service.select_template(
        source_project_no="2016",
        target_project_no="1916",
        source_filename="20162KA-JGS03-A.dwg",
        target_variant="4号岛",
    )

    assert selection is not None
    assert selection.project_no == "1916"
    assert selection.variant == "4"
    assert selection.path == tmp_path / "documents_bin" / "factory_index_maps" / "1916项目4号岛厂房索引图.dwg"


def test_factory_index_template_selection_infers_2016_island_from_filename(tmp_path: Path) -> None:
    from src.audit_replace.factory_index_bridge import FactoryIndexMapReplacementService
    from src.config.runtime_config import FactoryIndexMapsConfig, RuntimeConfig

    config = RuntimeConfig(base_dir=tmp_path)
    config.factory_index_maps = FactoryIndexMapsConfig(
        template_dir=Path("documents_bin/factory_index_maps"),
        island_templates={
            "2016": {"1": "2016项目1号岛厂房索引图.dwg", "2": "2016项目2号岛厂房索引图.dwg"},
        },
    )
    service = FactoryIndexMapReplacementService(config=config)

    selection = service.select_template(
        source_project_no="2026",
        target_project_no="2016",
        source_filename="20261DA-JGS01-E-纯净版.dwg",
    )

    assert selection is not None
    assert selection.project_no == "2016"
    assert selection.variant == "1"
    assert selection.path == tmp_path / "documents_bin" / "factory_index_maps" / "2016项目1号岛厂房索引图.dwg"
