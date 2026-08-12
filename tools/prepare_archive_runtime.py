from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"


def main() -> int:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    from src.deploy.archive_runtime import prepare_archive_runtime

    parser = argparse.ArgumentParser(
        description="下载、校验并准备部署包专用的便携 7-Zip 私有运行时缓存。"
    )
    parser.parse_args()

    cache_dir = prepare_archive_runtime(repo_root=REPO_ROOT)
    print(cache_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
