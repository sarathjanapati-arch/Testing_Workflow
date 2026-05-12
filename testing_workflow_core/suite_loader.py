from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _normalize_step(step: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(step)

    request = step.get("request")
    if isinstance(request, dict):
        for key in ("method", "url", "headers", "params", "json", "data", "files"):
            if key in request and key not in normalized:
                normalized[key] = request[key]

    policy = step.get("policy")
    if isinstance(policy, dict):
        policy_key_map = {
            "timeout": "timeout_seconds",
            "timeout_seconds": "timeout_seconds",
            "retries": "retries",
            "retry_delay": "retry_delay_seconds",
            "retry_delay_seconds": "retry_delay_seconds",
            "retry_on_status_codes": "retry_on_status_codes",
        }
        for source_key, target_key in policy_key_map.items():
            if source_key in policy and target_key not in normalized:
                normalized[target_key] = policy[source_key]

    assertions = step.get("assert")
    if isinstance(assertions, dict) and "expected" not in normalized:
        normalized["expected"] = assertions

    extract = step.get("extract")
    if isinstance(extract, dict) and "save" not in normalized:
        normalized["save"] = extract

    return normalized


def _normalize_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(workflow)
    steps = workflow.get("steps", [])
    if isinstance(steps, list):
        normalized["steps"] = [
            _normalize_step(step) if isinstance(step, dict) else step
            for step in steps
        ]
    return normalized


def normalize_suite(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    workflows = payload.get("workflows", [])
    if isinstance(workflows, list):
        normalized["workflows"] = [
            _normalize_workflow(workflow) if isinstance(workflow, dict) else workflow
            for workflow in workflows
        ]
    return normalized


def load_suite(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Test suite file not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Suite file must contain a top-level JSON object.")

    workflows = payload.get("workflows")
    if not isinstance(workflows, list) or not workflows:
        raise ValueError("Suite file must contain a non-empty 'workflows' array.")

    normalized = normalize_suite(payload)

    api_key = os.getenv("API_KEY")
    if api_key:
        context = dict(normalized.get("context", {}))
        context["api_key"] = api_key
        normalized = {**normalized, "context": context}

    return normalized
