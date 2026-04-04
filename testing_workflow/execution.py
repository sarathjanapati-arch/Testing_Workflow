from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import random
from threading import Lock
import time
import mimetypes
from typing import Any

import requests

from .doctor_persona import build_doctor_identity
from .image_generation import generate_images_for_agent, images_enabled
from .json_path import json_path_get
from .template import PLACEHOLDER_PATTERN, render_value

REDACTED = "***REDACTED***"
SENSITIVE_KEYS = {
    "authorization",
    "token",
    "refreshToken",
    "accessToken",
    "idToken",
    "apiKey",
    "secret",
    "password",
    "rawPassword",
    "pazzword",
}


def _resolve_context_vars(raw_context: dict[str, Any]) -> dict[str, Any]:
    resolved = dict(raw_context)
    for _ in range(5):
        missing: set[str] = set()
        updated = {k: render_value(v, resolved, missing) for k, v in resolved.items()}
        if updated == resolved:
            break
        resolved = updated
    return resolved


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).strip() in SENSITIVE_KEYS or str(key).strip().lower() in {name.lower() for name in SENSITIVE_KEYS}:
                redacted[key] = REDACTED
            else:
                redacted[key] = _redact_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _safe_preview(response: requests.Response | None) -> str:
    if response is None:
        return ""
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type.lower():
        try:
            text = json.dumps(_redact_value(response.json()), ensure_ascii=True)
        except ValueError:
            text = response.text
    else:
        text = response.text
    return text[:500]


def _should_retry_step(
    step_name: str,
    response: requests.Response | None,
    exception: Exception | None,
    validation_errors: list[str],
) -> bool:
    if exception is not None:
        return True
    if response is None or not validation_errors:
        return False

    status_code = response.status_code
    normalized_step = step_name.strip().lower()

    if normalized_step == "doctor signup":
        return status_code >= 500 or status_code in {408, 429}
    if normalized_step == "doctor signin":
        return status_code in {401, 408, 425, 429} or status_code >= 500

    return False


def _validate_response(step: dict[str, Any], response: requests.Response | None, elapsed_ms: float, exception: Exception | None) -> list[str]:
    errors: list[str] = []
    expected = step.get("expected", {})

    if exception is not None:
        return [f"Request failed: {exception}"]
    if response is None:
        return ["No response returned."]

    expected_status = expected.get("status_code")
    if expected_status is not None and response.status_code != expected_status:
        errors.append(f"Expected status {expected_status}, got {response.status_code}")

    max_ms = expected.get("max_response_time_ms")
    if max_ms is not None and elapsed_ms > float(max_ms):
        errors.append(f"Expected response time <= {max_ms}ms, got {elapsed_ms:.2f}ms")

    json_equals = expected.get("json_path_equals")
    if json_equals is not None:
        try:
            payload = response.json()
        except ValueError:
            return errors + ["Expected JSON response for json_path_equals validation."]

        if not isinstance(json_equals, dict):
            return errors + ["expected.json_path_equals must be an object map."]

        for path, expected_value in json_equals.items():
            try:
                actual_value = json_path_get(payload, str(path))
            except KeyError as err:
                errors.append(str(err))
                continue
            if actual_value != expected_value:
                errors.append(f"JSON path '{path}' expected {expected_value!r}, got {actual_value!r}")

    return errors


def _compute_run_mobile(run_timestamp: int, user_index: int, iteration_index: int) -> str:
    base = 7_000_000_000
    span = 2_999_999_999
    value = base + ((run_timestamp + (user_index * 7919) + (iteration_index * 17)) % span)
    return str(value)


def _load_exported_catalogs() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    companies_path = Path("data_exports/companies.json")
    specs_path = Path("data_exports/main_specializations.json")

    companies: list[dict[str, Any]] = []
    specs: list[dict[str, Any]] = []

    if companies_path.exists():
        try:
            payload = json.loads(companies_path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                companies = [item for item in payload if isinstance(item, dict)]
        except Exception:
            companies = []

    if specs_path.exists():
        try:
            payload = json.loads(specs_path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                specs = [item for item in payload if isinstance(item, dict)]
        except Exception:
            specs = []

    return companies, specs


def _pick_company_from_catalog(
    companies: list[dict[str, Any]],
    rng: random.Random,
) -> tuple[str | None, str | None]:
    if not companies:
        return None, None
    item = rng.choice(companies)
    company_id = item.get("company_id") or item.get("companyId")
    company_name = item.get("company_name") or item.get("companyName")
    return (
        None if company_id is None else str(company_id),
        None if company_name is None else str(company_name),
    )


def _pick_specialization_from_catalog(
    specs: list[dict[str, Any]],
    rng: random.Random,
) -> tuple[str | None, str | None]:
    if not specs:
        return None, None
    item = rng.choice(specs)
    specialization_id = item.get("id") or item.get("specialization_id")
    specialization_name = item.get("name") or item.get("specialization_name")
    return (
        None if specialization_id is None else str(specialization_id),
        None if specialization_name is None else str(specialization_name),
    )


def _extract_saved_value(json_body: Any, path_spec: Any) -> tuple[bool, Any]:
    if isinstance(path_spec, list):
        for candidate in path_spec:
            try:
                return True, json_path_get(json_body, str(candidate))
            except KeyError:
                continue
        return False, None

    if not isinstance(path_spec, str) or not path_spec.strip():
        return False, None

    try:
        return True, json_path_get(json_body, str(path_spec))
    except KeyError:
        return False, None


def _normalize_request_headers(headers: Any, has_files: bool) -> Any:
    if not isinstance(headers, dict):
        return headers
    normalized = dict(headers)
    if has_files:
        for key in list(normalized.keys()):
            if str(key).strip().lower() == "content-type":
                normalized.pop(key, None)
    return normalized


def _build_request_files(files_config: Any) -> tuple[Any, list[Any]]:
    if not isinstance(files_config, dict):
        return None, []

    opened_handles: list[Any] = []
    request_files: list[tuple[str, Any]] = []

    def open_file_entry(field_name: str, raw_value: Any) -> None:
        if isinstance(raw_value, str):
            file_path = Path(raw_value)
            handle = file_path.open("rb")
            opened_handles.append(handle)
            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            request_files.append((field_name, (file_path.name, handle, content_type)))
            return

        if isinstance(raw_value, dict):
            path_value = raw_value.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                raise ValueError(f"files.{field_name} requires a non-empty 'path'.")
            file_path = Path(path_value)
            handle = file_path.open("rb")
            opened_handles.append(handle)
            file_name = raw_value.get("filename") or file_path.name
            content_type = raw_value.get("content_type") or mimetypes.guess_type(str(file_name))[0] or "application/octet-stream"
            request_files.append((field_name, (str(file_name), handle, str(content_type))))
            return

        raise ValueError(
            f"files.{field_name} must be a file path string or an object with path/filename/content_type."
        )

    for field_name, raw_value in files_config.items():
        if isinstance(raw_value, list):
            for item in raw_value:
                open_file_entry(str(field_name), item)
        else:
            open_file_entry(str(field_name), raw_value)

    return request_files, opened_handles


def _sample_think_time_seconds(think_time_config: Any, rng: random.Random) -> float:
    if think_time_config is None:
        return 0.0
    if isinstance(think_time_config, (int, float)):
        return max(0.0, float(think_time_config) / 1000.0)
    if (
        isinstance(think_time_config, list)
        and len(think_time_config) == 2
        and all(isinstance(item, (int, float)) for item in think_time_config)
    ):
        lower_ms = min(float(think_time_config[0]), float(think_time_config[1]))
        upper_ms = max(float(think_time_config[0]), float(think_time_config[1]))
        return max(0.0, rng.uniform(lower_ms, upper_ms) / 1000.0)
    return 0.0


def _build_social_content(
    rng: random.Random,
    context_vars: dict[str, Any],
    user_index: int,
    iteration_index: int,
) -> dict[str, Any]:
    first_name = str(context_vars.get("doctor_first_name") or "Doctor").strip()
    specialization_name = str(
        context_vars.get("specialization_name")
        or context_vars.get("specialization_id")
        or "specialist care"
    ).strip()
    years = context_vars.get("years_of_experience", "")
    company_name = str(context_vars.get("company_name") or "our care team").strip()

    post_openers = [
        f"Hello DocSynapse, I am {first_name} and excited to connect with fellow doctors here.",
        f"Joining DocSynapse today as {first_name}. Looking forward to meaningful clinical conversations.",
        f"Happy to be here on DocSynapse. I am {first_name} and eager to learn from this community.",
        f"Thrilled to join DocSynapse as {first_name}. Hoping to collaborate with peers across specialties.",
    ]
    post_focuses = [
        f"My current focus is {specialization_name} with special interest in practical, patient-first care.",
        f"I work primarily in {specialization_name} and enjoy discussing real-world cases and better workflows.",
        f"I am building my network around {specialization_name}, continuity of care, and better patient outcomes.",
        f"I would love to connect with doctors interested in {specialization_name}, referrals, and collaborative practice.",
    ]
    post_closers = [
        f"Currently practicing with {company_name} and open to learning from everyone here.",
        "Looking forward to sharing experience, learning, and building strong professional connections.",
        "Would love to exchange ideas on daily practice, referrals, and evidence-based care.",
        "Happy to collaborate, discuss cases at a high level, and learn from this network.",
    ]
    update_closers = [
        "Updating my intro after settling in, and I am already enjoying the conversations here.",
        "A quick update after connecting with a few peers here, this community looks really promising.",
        "Refining this post after a few interactions, and I am excited for more collaboration ahead.",
        "Already finding this network useful, especially for professional learning and referrals.",
    ]
    tag_sets = [
        ["introduction", "networking", "docsynapse"],
        ["newhere", "doctorcommunity", "collaboration"],
        ["specialistcare", "referrals", "learning"],
        ["medicalnetwork", "clinicalpractice", "connections"],
    ]

    create_content = " ".join(
        [
            rng.choice(post_openers),
            rng.choice(post_focuses),
            f"I bring about {years} years of experience to my practice." if years != "" else "",
            rng.choice(post_closers),
        ]
    ).strip()

    update_content = " ".join(
        [
            create_content,
            rng.choice(update_closers),
            f"Run marker {user_index}-{iteration_index}.",
        ]
    ).strip()

    tag_set = rng.choice(tag_sets)
    public_image_url = "https://acintyotech-public.s3.ap-south-1.amazonaws.com/assets/e04a8228-ccee-4794-95e3-3d2a6a19474b.jpg"

    return {
        "post_content": create_content,
        "update_post_content": update_content,
        "post_tag_1": tag_set[0],
        "post_tag_2": tag_set[1],
        "post_tag_3": tag_set[2],
        "profile_photo_url": public_image_url,
        "cover_photo_url": public_image_url,
    }


def _step_uses_placeholder(value: Any, placeholder_name: str) -> bool:
    if isinstance(value, str):
        return any(match.group(1) == placeholder_name for match in PLACEHOLDER_PATTERN.finditer(value))
    if isinstance(value, dict):
        return any(_step_uses_placeholder(item, placeholder_name) for item in value.values())
    if isinstance(value, list):
        return any(_step_uses_placeholder(item, placeholder_name) for item in value)
    return False


def _value_requires_peer_context(
    value: Any,
    context_vars: dict[str, Any],
    visited_context_keys: set[str] | None = None,
) -> bool:
    if visited_context_keys is None:
        visited_context_keys = set()

    if _step_uses_placeholder(value, "peer_doctor_id") or _step_uses_placeholder(value, "peer_access_token"):
        return True

    if isinstance(value, str):
        for match in PLACEHOLDER_PATTERN.finditer(value):
            placeholder_name = match.group(1)
            if placeholder_name in {"peer_doctor_id", "peer_access_token"}:
                return True
            if placeholder_name in visited_context_keys:
                continue
            if placeholder_name in context_vars:
                visited_context_keys.add(placeholder_name)
                if _value_requires_peer_context(context_vars[placeholder_name], context_vars, visited_context_keys):
                    return True
        return False

    if isinstance(value, dict):
        return any(_value_requires_peer_context(item, context_vars, set(visited_context_keys)) for item in value.values())

    if isinstance(value, list):
        return any(_value_requires_peer_context(item, context_vars, set(visited_context_keys)) for item in value)

    return False


def _register_signed_in_agent(
    shared_doctor_registry: dict[int, dict[str, str]],
    registry_lock: Lock,
    user_index: int,
    context_vars: dict[str, Any],
) -> None:
    doctor_id = context_vars.get("signin_doctor_id")
    doctor_email = context_vars.get("doctor_email")
    access_token = context_vars.get("signin_access_token")
    if not isinstance(doctor_id, str) or not doctor_id.strip():
        return
    if not isinstance(access_token, str) or not access_token.strip():
        return
    with registry_lock:
        shared_doctor_registry[user_index] = {
            "doctor_id": doctor_id,
            "doctor_email": "" if doctor_email is None else str(doctor_email),
            "access_token": access_token,
        }


def _pick_peer_agent(
    shared_doctor_registry: dict[int, dict[str, str]],
    registry_lock: Lock,
    user_index: int,
) -> dict[str, str] | None:
    with registry_lock:
        candidates = [
            payload
            for candidate_user_index, payload in sorted(shared_doctor_registry.items())
            if candidate_user_index != user_index
        ]
    if not candidates:
        return None
    return candidates[0]


def _ensure_peer_context(
    context_vars: dict[str, Any],
    shared_doctor_registry: dict[int, dict[str, str]],
    registry_lock: Lock,
    user_index: int,
    timeout_seconds: float = 8.0,
    poll_interval_seconds: float = 0.25,
) -> dict[str, Any]:
    if context_vars.get("peer_doctor_id"):
        return context_vars

    deadline = time.perf_counter() + timeout_seconds
    selected_peer: dict[str, str] | None = None
    while time.perf_counter() < deadline:
        selected_peer = _pick_peer_agent(shared_doctor_registry, registry_lock, user_index)
        if selected_peer is not None:
            break
        time.sleep(poll_interval_seconds)

    if selected_peer is None:
        return context_vars

    updated_context = dict(context_vars)
    updated_context["peer_doctor_id"] = selected_peer.get("doctor_id", "")
    updated_context["peer_doctor_email"] = selected_peer.get("doctor_email", "")
    updated_context["peer_access_token"] = selected_peer.get("access_token", "")
    return updated_context


def _execute_step(
    workflow_name: str,
    step: dict[str, Any],
    context_vars: dict[str, Any],
    default_timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    step_name = step.get("name", "unnamed_step")
    missing_vars: set[str] = set()
    rendered_step = render_value(step, context_vars, missing_vars)

    if missing_vars:
        return (
            {
                "workflow": workflow_name,
                "step": step_name,
                "method": rendered_step.get("method"),
                "url": rendered_step.get("url"),
                "attempt": 1,
                "status_code": None,
                "response_time_ms": 0.0,
                "passed": False,
                "skipped": False,
                "skip_reason": None,
                "errors": [f"Missing context variable: {name}" for name in sorted(missing_vars)],
                "response_preview": "",
            },
            context_vars,
            [],
        )

    step_name_normalized = str(step_name).strip().lower()
    default_retries = 0
    default_retry_delay_seconds = 0.0
    if step_name_normalized == "doctor signup":
        default_retries = 2
        default_retry_delay_seconds = 1.5
    elif step_name_normalized == "doctor signin":
        default_retries = 3
        default_retry_delay_seconds = 2.0

    retries = int(rendered_step.get("retries", default_retries))
    retry_delay_seconds = float(rendered_step.get("retry_delay_seconds", default_retry_delay_seconds))
    timeout_seconds = float(rendered_step.get("timeout_seconds", default_timeout_seconds))
    attempt = 1
    executed_attempt = 0
    last_response: requests.Response | None = None
    last_exception: Exception | None = None
    elapsed_ms = 0.0
    validation_errors: list[str] = []

    while attempt <= retries + 1:
        start = time.perf_counter()
        executed_attempt = attempt
        last_response = None
        last_exception = None
        opened_handles: list[Any] = []
        try:
            request_files, opened_handles = _build_request_files(rendered_step.get("files"))
            last_response = requests.request(
                method=str(rendered_step["method"]).upper(),
                url=str(rendered_step["url"]),
                headers=_normalize_request_headers(rendered_step.get("headers"), request_files is not None),
                params=rendered_step.get("params"),
                json=rendered_step.get("json"),
                data=rendered_step.get("data"),
                files=request_files,
                timeout=timeout_seconds,
            )
        except Exception as err:
            last_exception = err
        finally:
            for handle in opened_handles:
                try:
                    handle.close()
                except Exception:
                    pass
        elapsed_ms = (time.perf_counter() - start) * 1000
        validation_errors = _validate_response(rendered_step, last_response, elapsed_ms, last_exception)
        if not validation_errors:
            break
        if attempt <= retries and _should_retry_step(step_name, last_response, last_exception, validation_errors):
            time.sleep(retry_delay_seconds)
        else:
            break
        attempt += 1

    passed = len(validation_errors) == 0
    preview = _safe_preview(last_response)
    status_code = None if last_response is None else last_response.status_code
    result = {
        "workflow": workflow_name,
        "step": step_name,
        "method": rendered_step.get("method"),
        "url": rendered_step.get("url"),
        "attempt": executed_attempt,
        "status_code": status_code,
        "response_time_ms": round(elapsed_ms, 2),
        "passed": passed,
        "skipped": False,
        "skip_reason": None,
        "errors": validation_errors,
        "response_preview": preview,
    }

    execution_errors: list[str] = []
    new_context = dict(context_vars)
    if passed:
        save_fields = rendered_step.get("save", {})
        if isinstance(save_fields, dict):
            json_body: Any = None
            if last_response is not None:
                try:
                    json_body = last_response.json()
                except ValueError:
                    json_body = None
            for var_name, path in save_fields.items():
                if json_body is None:
                    execution_errors.append(
                        f"Workflow '{workflow_name}' step '{step_name}' cannot save '{var_name}': response is not JSON."
                    )
                    continue
                found, saved_value = _extract_saved_value(json_body, path)
                if found:
                    new_context[var_name] = saved_value
                else:
                    execution_errors.append(
                        f"Workflow '{workflow_name}' step '{step_name}' failed to save '{var_name}': no matching path found in {path!r}"
                    )

    return result, new_context, execution_errors


def _execute_agent(
    suite: dict[str, Any],
    default_timeout_seconds: float,
    run_timestamp: int,
    user_index: int,
    iterations_per_user: int,
    prefetched_context: dict[str, Any],
    company_catalog: list[dict[str, Any]],
    specialization_catalog: list[dict[str, Any]],
    shared_doctor_registry: dict[int, dict[str, str]],
    registry_lock: Lock,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    agent_id = f"agent_{user_index}"
    base_context: dict[str, Any] = {
        "run_timestamp": run_timestamp,
        "user_index": user_index,
        "agent_id": agent_id,
        **suite.get("context", {}),
        **prefetched_context,
    }
    base_context = _resolve_context_vars(base_context)

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    context_vars = dict(base_context)
    run_config = suite.get("run", {})
    think_time_config = run_config.get("think_time_ms")
    ramp_up_seconds = float(run_config.get("ramp_up_seconds", 0.0) or 0.0)

    if ramp_up_seconds > 0 and user_index > 1:
        max_denominator = max(1, int(run_config.get("virtual_users", 1)) - 1)
        stagger_seconds = ramp_up_seconds * ((user_index - 1) / max_denominator)
        time.sleep(max(0.0, stagger_seconds))

    workflows = suite.get("workflows", [])
    for iteration_index in range(1, iterations_per_user + 1):
        rng = random.Random((run_timestamp * 1_000_003) + (user_index * 9_973) + iteration_index)
        context_vars["iteration_index"] = iteration_index
        context_vars["run_email_suffix"] = f"{run_timestamp}_{user_index}_{iteration_index}"
        context_vars["run_mobile"] = _compute_run_mobile(run_timestamp, user_index, iteration_index)
        context_vars.update(build_doctor_identity(rng, run_timestamp, user_index, iteration_index))
        context_vars.update(_build_social_content(rng, context_vars, user_index, iteration_index))
        if images_enabled(context_vars):
            try:
                generated = generate_images_for_agent(
                    output_dir=Path("tmp/generated_images"),
                    run_timestamp=run_timestamp,
                    user_index=user_index,
                    iteration_index=iteration_index,
                    doctor_fullname=str(context_vars.get("doctor_fullname") or "Doctor"),
                    specialization_name=str(
                        context_vars.get("specialization_name")
                        or context_vars.get("specialization_id")
                        or "Specialist care"
                    ),
                    post_content=str(context_vars.get("post_content") or ""),
                )
                context_vars["profile_image_path"] = generated.profile_path
                context_vars["cover_image_path"] = generated.cover_path
                context_vars["post_image_path"] = generated.post_path
            except Exception as err:
                errors.append(f"Image generation failed for agent {agent_id}: {err}")
        random_company_id, random_company_name = _pick_company_from_catalog(company_catalog, rng)
        random_spec_id, random_spec_name = _pick_specialization_from_catalog(specialization_catalog, rng)
        if random_company_id:
            context_vars["company_id"] = random_company_id
        if random_company_name:
            context_vars["company_name"] = random_company_name
        if random_spec_id:
            context_vars["specialization_id"] = random_spec_id
        if random_spec_name:
            context_vars["specialization_name"] = random_spec_name
        context_vars = _resolve_context_vars(context_vars)
        step_status_by_name: dict[str, bool] = {}

        for workflow in workflows:
            wf_name = workflow.get("name", "unnamed_workflow")
            for step in workflow.get("steps", []):
                step_name = step.get("name", "unnamed_step")
                if step_name == "Send Connection Request" or _value_requires_peer_context(step, context_vars):
                    context_vars = _ensure_peer_context(
                        context_vars,
                        shared_doctor_registry,
                        registry_lock,
                        user_index,
                    )
                if step.get("enabled", True) is False:
                    disabled_result = {
                        "workflow": wf_name,
                        "step": step_name,
                        "method": step.get("method"),
                        "url": step.get("url"),
                        "attempt": 0,
                        "status_code": None,
                        "response_time_ms": 0.0,
                        "passed": False,
                        "skipped": True,
                        "skip_reason": "Step is disabled in suite configuration.",
                        "errors": [],
                        "response_preview": "",
                        "user_index": user_index,
                        "agent_id": agent_id,
                        "iteration_index": iteration_index,
                    }
                    results.append(disabled_result)
                    step_status_by_name[step_name] = False
                    continue

                dependency_name = step.get("depends_on")
                if dependency_name:
                    dependency_passed = step_status_by_name.get(str(dependency_name))
                    if dependency_passed is not True:
                        skipped_result = {
                            "workflow": wf_name,
                            "step": step_name,
                            "method": step.get("method"),
                            "url": step.get("url"),
                            "attempt": 0,
                            "status_code": None,
                            "response_time_ms": 0.0,
                            "passed": False,
                            "skipped": True,
                            "skip_reason": f"Dependency step '{dependency_name}' did not pass.",
                            "errors": [],
                            "response_preview": "",
                            "user_index": user_index,
                            "agent_id": agent_id,
                            "iteration_index": iteration_index,
                        }
                        results.append(skipped_result)
                        step_status_by_name[step_name] = False
                        continue

                step_result, context_vars, step_errors = _execute_step(
                    workflow_name=wf_name,
                    step=step,
                    context_vars=context_vars,
                    default_timeout_seconds=default_timeout_seconds,
                )
                step_result["user_index"] = user_index
                step_result["agent_id"] = agent_id
                step_result["iteration_index"] = iteration_index
                results.append(step_result)
                errors.extend(step_errors)
                step_status_by_name[step_name] = bool(step_result.get("passed"))
                if step_name == "Doctor SignIn" and step_result.get("passed") is True:
                    _register_signed_in_agent(
                        shared_doctor_registry,
                        registry_lock,
                        user_index,
                        context_vars,
                    )
                think_time_seconds = _sample_think_time_seconds(think_time_config, rng)
                if think_time_seconds > 0:
                    time.sleep(think_time_seconds)

    passed_steps = sum(1 for item in results if item.get("passed") is True and item.get("skipped") is not True)
    skipped_steps = sum(1 for item in results if item.get("skipped") is True)
    failed_steps = len(results) - passed_steps - skipped_steps
    agent_summary = {
        "agent_id": agent_id,
        "user_index": user_index,
        "passed_steps": passed_steps,
        "failed_steps": failed_steps,
        "skipped_steps": skipped_steps,
        "doctor_email": context_vars.get("doctor_email"),
        "doctor_mobile": context_vars.get("doctor_mobile"),
        "specialization_id": context_vars.get("specialization_id"),
        "specialization_name": context_vars.get("specialization_name"),
        "company_id": context_vars.get("company_id"),
        "company_name": context_vars.get("company_name"),
        "doctor_id": context_vars.get("doctor_id"),
        "identity_source": context_vars.get("identity_source"),
        "identity_error": context_vars.get("identity_error"),
    }
    return results, agent_summary, errors


def execute_suite(
    suite: dict[str, Any],
    default_timeout_seconds: float,
    run_timestamp: int,
    prefetched_context: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    run_config = suite.get("run", {})
    virtual_users = int(run_config.get("virtual_users", 1))
    iterations_per_user = int(run_config.get("iterations_per_user", 1))
    max_workers = int(run_config.get("max_workers", min(virtual_users, 100)))

    if virtual_users < 1:
        raise ValueError("run.virtual_users must be >= 1")
    if iterations_per_user < 1:
        raise ValueError("run.iterations_per_user must be >= 1")
    max_workers = max(1, min(max_workers, virtual_users))

    all_results: list[dict[str, Any]] = []
    agent_summaries: list[dict[str, Any]] = []
    all_errors: list[str] = []
    shared_prefetched = prefetched_context or {}
    shared_doctor_registry: dict[int, dict[str, str]] = {}
    registry_lock = Lock()
    randomize_from_exports = os.getenv("RANDOMIZE_FROM_EXPORTS", "false").strip().lower() == "true"
    if randomize_from_exports:
        company_catalog, specialization_catalog = _load_exported_catalogs()
    else:
        company_catalog, specialization_catalog = ([], [])

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                _execute_agent,
                suite,
                default_timeout_seconds,
                run_timestamp,
                user_index,
                iterations_per_user,
                shared_prefetched,
                company_catalog,
                specialization_catalog,
                shared_doctor_registry,
                registry_lock,
            )
            for user_index in range(1, virtual_users + 1)
        ]

        for future in as_completed(futures):
            results, agent_summary, errors = future.result()
            all_results.extend(results)
            agent_summaries.append(agent_summary)
            all_errors.extend(errors)

    all_results.sort(key=lambda item: (int(item["user_index"]), int(item["iteration_index"]), item["workflow"], item["step"]))
    agent_summaries.sort(key=lambda item: int(item["user_index"]))
    return all_results, agent_summaries, all_errors
