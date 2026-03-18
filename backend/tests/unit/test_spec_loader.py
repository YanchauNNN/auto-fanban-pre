from pathlib import Path

from src.config.spec_loader import SpecLoader


def test_get_template_path_supports_deployed_documents_bin_layout(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    source_spec = repo_root / "documents" / "参数规范.yaml"

    deploy_root = tmp_path / "FanBanServer"
    deploy_spec = deploy_root / "documents" / "参数规范.yaml"
    deploy_spec.parent.mkdir(parents=True, exist_ok=True)
    deploy_spec.write_text(source_spec.read_text(encoding="utf-8"), encoding="utf-8")

    expected_template = deploy_root / "documents_bin" / "设计文件模板.xlsx"
    expected_template.parent.mkdir(parents=True, exist_ok=True)
    expected_template.write_text("placeholder", encoding="utf-8")

    spec = SpecLoader.load(deploy_spec)

    assert Path(spec.get_template_path("design", "2016")) == expected_template
