from __future__ import annotations

from typing import Any


def json_path_get(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, list):
            if not part.isdigit():
                raise KeyError(f"Expected list index at '{part}' in path '{path}'")
            index = int(part)
            if index < 0 or index >= len(current):
                raise KeyError(f"List index out of range at '{part}' in path '{path}'")
            current = current[index]
        elif isinstance(current, dict):
            if part not in current:
                raise KeyError(f"Missing key '{part}' in path '{path}'")
            current = current[part]
        else:
            raise KeyError(f"Cannot traverse '{part}' in path '{path}'")
    return current

