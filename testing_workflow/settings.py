from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    tests_file: Path
    report_file: Path
    default_timeout_seconds: float


def load_settings() -> Settings:
    return Settings(
        tests_file=Path(os.getenv("API_TESTS_FILE", "tests/doctor_signup_sample_workflow.json")),
        report_file=Path(os.getenv("API_REPORT_FILE", "reports/latest_report.json")),
        default_timeout_seconds=float(os.getenv("DEFAULT_TIMEOUT_SECONDS", "15")),
    )
