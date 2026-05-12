from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .reports import load_json_file


DEFAULT_TESTS_FILE = "tests/unified_comprehensive_suite.json"
DEFAULT_REPORT_FILE = "reports/latest_agentic_report_ollama.json"

FUNCTIONAL_GOAL_OPTIONS = [
    "Auth/Profile",
    "Doctor Discovery",
    "Social Network",
    "Referral System",
    "Credit Tracking",
    "Referral Lifecycle",
]

FUNCTIONAL_GOAL_ENV_MAP = {
    "Auth/Profile": "auth_profile",
    "Doctor Discovery": "doctor_discovery",
    "Social Network": "social_network",
    "Referral System": "referral_system",
    "Credit Tracking": "credit_tracking",
    "Referral Lifecycle": "referral_lifecycle",
}


@dataclass(frozen=True)
class SuiteDefaults:
    virtual_users: int
    max_workers: int
    iterations_per_user: int


def load_suite_defaults(path: str) -> SuiteDefaults:
    suite = load_json_file(path) or {}
    run_config: dict[str, Any] = suite.get("run", {}) if isinstance(suite, dict) else {}
    virtual_users = int(run_config.get("virtual_users", 3) or 3)
    return SuiteDefaults(
        virtual_users=virtual_users,
        max_workers=int(run_config.get("max_workers", virtual_users) or virtual_users),
        iterations_per_user=int(run_config.get("iterations_per_user", 1) or 1),
    )


def selected_goals_to_env(functional_goals: list[str]) -> str:
    selected = [FUNCTIONAL_GOAL_ENV_MAP[goal] for goal in functional_goals if goal in FUNCTIONAL_GOAL_ENV_MAP]
    return ",".join(selected) or "auth_profile"

