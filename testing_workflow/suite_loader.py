from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_suite(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Test suite file not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Suite file must contain a top-level JSON object.")

    workflows = payload.get("workflows")
    if not isinstance(workflows, list) or not workflows:
        raise ValueError("Suite file must contain a non-empty 'workflows' array.")

    return payload
