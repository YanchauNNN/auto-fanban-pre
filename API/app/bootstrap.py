from __future__ import annotations

import sys
from pathlib import Path


def infer_repo_root(module_file: str | Path) -> Path:
    module_path = Path(module_file).resolve()
    repo_like_roots: list[Path] = []
    for idx in (2, 3):
        if len(module_path.parents) > idx:
            candidate = module_path.parents[idx]
            if candidate not in repo_like_roots:
                repo_like_roots.append(candidate)

    for candidate in repo_like_roots:
        if candidate.name == "backend-runtime" and candidate.parent != candidate:
            parent_candidate = candidate.parent
            if parent_candidate not in repo_like_roots:
                repo_like_roots.append(parent_candidate)

    for candidate in repo_like_roots:
        if (candidate / "documents_bin").exists() or (candidate / "documents").exists():
            return candidate

    for candidate in repo_like_roots:
        if candidate.name == "backend-runtime" and candidate.parent != candidate:
            return candidate.parent

    return repo_like_roots[0]


REPO_ROOT = infer_repo_root(__file__)
BACKEND_ROOT = REPO_ROOT / "backend"

for path in (REPO_ROOT, BACKEND_ROOT):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)


def resolve_repo_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()
