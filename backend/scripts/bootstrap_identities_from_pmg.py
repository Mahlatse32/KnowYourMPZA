"""Bootstrap politicians and committees from existing PMG-derived data.

Use this when People's Assembly access is blocked for the runner but PMG
meetings, attendance, questions, and documents are already present.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from scripts.identity_bootstrap_utils import run_pmg_identity_bootstrap


def main() -> int:
    with SessionLocal() as db:
        result = run_pmg_identity_bootstrap(db)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
