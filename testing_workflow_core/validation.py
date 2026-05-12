from __future__ import annotations

from typing import Any

from .template import PLACEHOLDER_PATTERN

VALID_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
BUILTIN_CONTEXT_KEYS = {
    "run_id",
    "timestamp",
    "run_timestamp",
    "user_index",
    "agent_id",
    "iteration_index",
    "run_email_suffix",
    "run_mobile",
    "peer_doctor_id",
    "peer_doctor_email",
    "peer_access_token",
    "api_key",
}
GENERATED_CONTEXT_KEYS = {
    "doctor_first_name",
    "doctor_last_name",
    "doctor_fullname",
    "doctor_email_local",
    "registration_number",
    "years_of_experience",
    "date_of_birth",
    "gender",
    "medical_council_board",
    "short_bio",
    "identity_source",
    "identity_pool_index",
    "identity_error",
    "doctor_tone",
    "profile_focus",
    "onboarding_motivation",
    "job_title_signup",
    "job_title_current",
    "experience_start_date",
    "education_degree_name",
    "education_school_name",
    "education_field_name",
    "education_start_date",
    "education_end_date",
    "education_grade",
    "updated_education_school_name",
    "updated_education_grade",
    "language_name",
    "language_proficiency_level",
    "skill_name",
    "consultation_modes",
    "doctor_search_term",
    "post_visibility",
    "post_reaction_type",
    "network_action",
    "post_mentions",
    "post_video_url",
    "profile_search_style",
    "engagement_preference",
    "profile_generation_source",
    "profile_generation_error",
    "behavior_generation_source",
    "behavior_generation_error",
    "profile_image_path",
    "cover_image_path",
    "post_image_path",
    "post_image_url",
    "profile_photo_url",
    "cover_photo_url",
}
MASTER_DATA_CONTEXT_KEYS = {
    "company_id",
    "company_name",
    "specialization_id",
    "sub_specialization_id",
    "additional_specialization_id",
    "specialization_name",
    "specialization_source",
    "company_source",
}


def find_placeholders(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        found.update(match.group(1) for match in PLACEHOLDER_PATTERN.finditer(value))
    elif isinstance(value, dict):
        for item in value.values():
            found.update(find_placeholders(item))
    elif isinstance(value, list):
        for item in value:
            found.update(find_placeholders(item))
    return found


def validate_run_config(suite: dict[str, Any], errors: list[str]) -> None:
    run_cfg = suite.get("run", {})
    if not isinstance(run_cfg, dict):
        errors.append("Top-level 'run' must be an object when present.")
        return

    for field in ("virtual_users", "iterations_per_user", "max_workers", "default_retries"):
        if field not in run_cfg:
            continue
        value = run_cfg[field]
        if not isinstance(value, int):
            errors.append(f"run.{field} must be an integer.")
        elif value < 1:
            errors.append(f"run.{field} must be >= 1.")

    if "default_timeout_seconds" in run_cfg:
        default_timeout_seconds = run_cfg["default_timeout_seconds"]
        if not isinstance(default_timeout_seconds, (int, float)):
            errors.append("run.default_timeout_seconds must be numeric.")
        elif float(default_timeout_seconds) <= 0:
            errors.append("run.default_timeout_seconds must be > 0.")

    virtual_users = run_cfg.get("virtual_users")
    max_workers = run_cfg.get("max_workers")
    if isinstance(virtual_users, int) and isinstance(max_workers, int) and max_workers > virtual_users:
        errors.append("run.max_workers cannot exceed run.virtual_users.")

    if "ramp_up_seconds" in run_cfg:
        ramp_up_seconds = run_cfg["ramp_up_seconds"]
        if not isinstance(ramp_up_seconds, (int, float)):
            errors.append("run.ramp_up_seconds must be numeric.")
        elif float(ramp_up_seconds) < 0:
            errors.append("run.ramp_up_seconds must be >= 0.")

    if "think_time_ms" in run_cfg:
        think_time_ms = run_cfg["think_time_ms"]
        if isinstance(think_time_ms, (int, float)):
            if float(think_time_ms) < 0:
                errors.append("run.think_time_ms must be >= 0.")
        elif isinstance(think_time_ms, list):
            if len(think_time_ms) != 2 or not all(isinstance(item, (int, float)) for item in think_time_ms):
                errors.append("run.think_time_ms list form must be [min_ms, max_ms] numeric values.")
            elif any(float(item) < 0 for item in think_time_ms):
                errors.append("run.think_time_ms list values must be >= 0.")
        else:
            errors.append("run.think_time_ms must be numeric or [min_ms, max_ms].")


def validate_step_shape(
    wf_name: str,
    step: dict[str, Any],
    available_context: set[str],
    known_step_names: set[str],
    errors: list[str],
) -> None:
    step_name = step.get("name", "unnamed_step")

    if "name" not in step or not isinstance(step_name, str) or not step_name.strip():
        errors.append(f"Workflow '{wf_name}' has a step with a missing or empty 'name'.")

    method = step.get("method")
    if method is None:
        errors.append(f"Workflow '{wf_name}' step '{step_name}' missing 'method'.")
    elif not isinstance(method, str) or method.upper() not in VALID_METHODS:
        errors.append(f"Workflow '{wf_name}' step '{step_name}' has invalid method '{method}'.")

    url = step.get("url")
    if url is None:
        errors.append(f"Workflow '{wf_name}' step '{step_name}' missing 'url'.")
    elif not isinstance(url, str) or not url.strip():
        errors.append(f"Workflow '{wf_name}' step '{step_name}' has an invalid 'url'.")

    enabled = step.get("enabled", True)
    if not isinstance(enabled, bool):
        errors.append(f"Workflow '{wf_name}' step '{step_name}' has non-boolean 'enabled'.")

    dependency_name = step.get("depends_on")
    if dependency_name is not None:
        if not isinstance(dependency_name, str) or not dependency_name.strip():
            errors.append(f"Workflow '{wf_name}' step '{step_name}' has invalid 'depends_on'.")
        elif dependency_name == step_name:
            errors.append(f"Workflow '{wf_name}' step '{step_name}' cannot depend on itself.")
        elif dependency_name not in known_step_names:
            errors.append(
                f"Workflow '{wf_name}' step '{step_name}' depends on unknown step '{dependency_name}'."
            )

    if "json" in step and "data" in step:
        errors.append(f"Workflow '{wf_name}' step '{step_name}' cannot define both 'json' and 'data'.")
    if "json" in step and "files" in step:
        errors.append(f"Workflow '{wf_name}' step '{step_name}' cannot define both 'json' and 'files'. Use 'data' for multipart form fields.")

    files = step.get("files")
    if files is not None:
        if not isinstance(files, dict) or not files:
            errors.append(f"Workflow '{wf_name}' step '{step_name}' files must be a non-empty object.")
        elif "data" in step and not isinstance(step.get("data"), dict):
            errors.append(f"Workflow '{wf_name}' step '{step_name}' data must be an object when used with files.")
        else:
            for field_name, field_value in files.items():
                if not isinstance(field_name, str) or not field_name.strip():
                    errors.append(f"Workflow '{wf_name}' step '{step_name}' has an invalid files field name.")
                    continue
                valid_value = False
                if isinstance(field_value, str) and field_value.strip():
                    valid_value = True
                elif isinstance(field_value, dict):
                    path_value = field_value.get("path")
                    valid_value = isinstance(path_value, str) and bool(path_value.strip())
                elif isinstance(field_value, list) and field_value:
                    valid_value = all(
                        (isinstance(item, str) and item.strip())
                        or (
                            isinstance(item, dict)
                            and isinstance(item.get("path"), str)
                            and bool(str(item.get("path")).strip())
                        )
                        for item in field_value
                    )
                if not valid_value:
                    errors.append(
                        f"Workflow '{wf_name}' step '{step_name}' files.{field_name} must be a file path string, a path object, or a non-empty list of them."
                    )

    expected = step.get("expected")
    if expected is not None and not isinstance(expected, dict):
        errors.append(f"Workflow '{wf_name}' step '{step_name}' expected must be an object.")
    elif isinstance(expected, dict):
        if "status_code" in expected and not isinstance(expected["status_code"], int):
            errors.append(f"Workflow '{wf_name}' step '{step_name}' expected.status_code must be an integer.")
        if "max_response_time_ms" in expected and not isinstance(expected["max_response_time_ms"], (int, float)):
            errors.append(
                f"Workflow '{wf_name}' step '{step_name}' expected.max_response_time_ms must be numeric."
            )
        if "body_contains" in expected:
            body_contains = expected["body_contains"]
            if isinstance(body_contains, str):
                pass
            elif isinstance(body_contains, list) and all(isinstance(item, str) and item for item in body_contains):
                pass
            else:
                errors.append(
                    f"Workflow '{wf_name}' step '{step_name}' expected.body_contains must be a string or non-empty string list."
                )
        if "json_path_equals" in expected and not isinstance(expected["json_path_equals"], dict):
            errors.append(
                f"Workflow '{wf_name}' step '{step_name}' expected.json_path_equals must be an object."
            )

    save_fields = step.get("save")
    if save_fields is not None and not isinstance(save_fields, dict):
        errors.append(f"Workflow '{wf_name}' step '{step_name}' save must be an object.")
    elif isinstance(save_fields, dict):
        for var_name, path_spec in save_fields.items():
            if not isinstance(var_name, str) or not var_name.strip():
                errors.append(f"Workflow '{wf_name}' step '{step_name}' has invalid save key '{var_name}'.")
            if isinstance(path_spec, list):
                if not path_spec or not all(isinstance(item, str) and item.strip() for item in path_spec):
                    errors.append(
                        f"Workflow '{wf_name}' step '{step_name}' save path list for '{var_name}' must contain non-empty strings."
                    )
            elif not isinstance(path_spec, str) or not path_spec.strip():
                errors.append(
                    f"Workflow '{wf_name}' step '{step_name}' save path for '{var_name}' must be a non-empty string or string list."
                )

    required_fields = step.get("required_fields")
    if required_fields is not None:
        if not isinstance(required_fields, list) or not required_fields:
            errors.append(f"Workflow '{wf_name}' step '{step_name}' required_fields must be a non-empty string list.")
        elif not all(isinstance(item, str) and item.strip() for item in required_fields):
            errors.append(f"Workflow '{wf_name}' step '{step_name}' required_fields must contain non-empty strings.")

    for placeholder in sorted(find_placeholders(step)):
        if placeholder not in available_context:
            errors.append(
                f"Workflow '{wf_name}' step '{step_name}' references unknown placeholder '{placeholder}'."
            )


def validate_workflows(
    suite: dict[str, Any],
    errors: list[str],
    generated_context_keys: set[str],
) -> list[str]:
    checks: list[str] = []
    context = suite.get("context", {})
    if context is not None and not isinstance(context, dict):
        errors.append("Top-level 'context' must be an object when present.")
        context = {}

    workflows = suite.get("workflows", [])
    if not isinstance(workflows, list) or not workflows:
        errors.append("Top-level 'workflows' must be a non-empty list.")
        return checks

    base_context = set(context.keys()) | BUILTIN_CONTEXT_KEYS | generated_context_keys | MASTER_DATA_CONTEXT_KEYS
    all_step_names: list[str] = []
    for wf in workflows:
        steps = wf.get("steps", [])
        if isinstance(steps, list):
            for step in steps:
                raw_name = step.get("name")
                if isinstance(raw_name, str):
                    all_step_names.append(raw_name)

    available_context = set(base_context)
    known_step_names = set(all_step_names)
    for wf in workflows:
        wf_name = wf.get("name", "unnamed_workflow")
        if "name" not in wf or not isinstance(wf_name, str) or not wf_name.strip():
            errors.append("Each workflow must have a non-empty 'name'.")
        enabled = wf.get("enabled", True)
        if not isinstance(enabled, bool):
            errors.append(f"Workflow '{wf_name}' has non-boolean 'enabled'.")

        steps = wf.get("steps", [])
        if not isinstance(steps, list) or not steps:
            errors.append(f"Workflow '{wf_name}' has no steps.")
            continue

        step_names: list[str] = []
        for step in steps:
            raw_name = step.get("name")
            if isinstance(raw_name, str):
                step_names.append(raw_name)

        duplicate_names: set[str] = set()
        seen_names: set[str] = set()
        for name in step_names:
            if name in seen_names:
                duplicate_names.add(name)
            seen_names.add(name)
        for duplicate_name in sorted(duplicate_names):
            errors.append(f"Workflow '{wf_name}' has duplicate step name '{duplicate_name}'.")

        for step in steps:
            step_name = step.get("name", "unnamed_step")
            validate_step_shape(wf_name, step, available_context, known_step_names, errors)
            checks.append(f"{wf_name}::{step_name}")

            save_fields = step.get("save", {})
            if isinstance(save_fields, dict):
                available_context.update(str(var_name) for var_name in save_fields.keys())

    return checks
