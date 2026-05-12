from __future__ import annotations

import os
from typing import Any


def safe_int_env(name: str, default: int | None = None) -> int | None:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def agentic_logging_enabled() -> bool:
    return str(os.getenv("AGENTIC_PROGRESS_LOGGING", "true")).strip().lower() in {"1", "true", "yes", "y"}


def log_agentic(message: str) -> None:
    if agentic_logging_enabled():
        try:
            print(message, flush=True)
        except OSError:
            pass


def apply_run_overrides(suite: dict[str, Any]) -> dict[str, Any]:
    run_config = dict(suite.get("run", {}))

    virtual_users = safe_int_env("AGENTIC_VIRTUAL_USERS")
    if virtual_users is not None:
        run_config["virtual_users"] = max(1, virtual_users)

    max_workers = safe_int_env("AGENTIC_MAX_WORKERS")
    if max_workers is not None:
        run_config["max_workers"] = max(1, max_workers)

    iterations_per_user = safe_int_env("AGENTIC_ITERATIONS_PER_USER")
    if iterations_per_user is not None:
        run_config["iterations_per_user"] = max(1, iterations_per_user)

    if run_config:
        suite = dict(suite)
        suite["run"] = run_config
    return suite
