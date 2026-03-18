import importlib.util
from pathlib import Path


def _load_bootstrap_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "API" / "app" / "bootstrap.py"
    spec = importlib.util.spec_from_file_location("test_api_bootstrap_module", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_infer_repo_root_supports_deployed_backend_runtime_layout(tmp_path: Path):
    bootstrap = _load_bootstrap_module()
    deploy_root = tmp_path / "FanBanServer"
    module_file = deploy_root / "backend-runtime" / "API" / "app" / "bootstrap.py"
    module_file.parent.mkdir(parents=True, exist_ok=True)
    module_file.write_text("# fake deployed bootstrap", encoding="utf-8")

    assert bootstrap.infer_repo_root(module_file) == deploy_root
