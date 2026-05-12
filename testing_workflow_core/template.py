from __future__ import annotations

import re
from typing import Any

PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


def render_value(value: Any, context_vars: dict[str, Any], missing: set[str]) -> Any:
    if isinstance(value, str):
        full_match = PLACEHOLDER_PATTERN.fullmatch(value)
        if full_match:
            key = full_match.group(1)
            if key not in context_vars:
                missing.add(key)
                return value
            resolved = context_vars[key]
            if resolved is value:
                return resolved
            return render_value(resolved, context_vars, missing)

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in context_vars:
                missing.add(key)
                return match.group(0)
            return str(context_vars[key])

        return PLACEHOLDER_PATTERN.sub(replace, value)

    if isinstance(value, dict):
        return {k: render_value(v, context_vars, missing) for k, v in value.items()}

    if isinstance(value, list):
        return [render_value(item, context_vars, missing) for item in value]

    return value
