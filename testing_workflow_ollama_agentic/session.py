from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import random
import time
from pathlib import Path
from threading import Lock
from typing import Any

import requests

from .reports import build_agentic_report, report_status, write_agentic_report
from .runtime import safe_int_env
from testing_workflow_core.doctor_persona import (
    build_doctor_behavior_context,
    build_doctor_identity,
    build_doctor_profile_context,
)
from testing_workflow_core.execution import (
    compute_run_mobile,
    ensure_peer_context,
    execute_step,
    load_exported_catalogs,
    pick_company_from_catalog,
    pick_specialization_from_catalog,
    register_signed_in_agent,
    resolve_context_vars,
    sanitize_report_value,
    value_requires_peer_context,
)
from testing_workflow_core.seed import agent_seed
from testing_workflow_core.image_generation import (
    generate_images_for_agent,
    generate_social_content_for_agent,
    images_enabled,
)


FUNCTIONAL_GROUPS = {
    "auth_profile": [
        "signup", "signin", "update_intro", "add_experience", "update_experience",
        "add_education", "update_education", "add_language", "add_skill",
        "update_cover_photo",
    ],
    "doctor_discovery": [
        "get_main_specializations", "get_sub_specializations",
        "get_all_doctors", "get_doctor_by_id", "doctor_search",
    ],
    "social_network": [
        "create_post", "update_post", "get_home_feed", "get_profile_posts",
        "post_like", "get_likes", "home_feed_using_cursor", "get_detail_post",
        "send_connection", "delete_post",
    ],
    "referral_system": [
        "create_referral", "get_referrals", "get_referral_detail",
        "total_referred_pending", "update_referral", "send_reminder",
        "referred_count", "received_count", "frequently_referred",
        "accept_referral", "update_patient_status",
        "total_received_patients", "total_referred_accepted",
    ],
    "credit_tracking": [
        "credit_header", "credit_by_sender", "credit_by_receiver",
        "update_credit_sender", "update_credit_receiver",
    ],
    "referral_lifecycle": [
        "create_cancel_referral", "get_referrals_for_cancel",
        "cancel_referral", "delete_referral",
    ],
}

FUNCTIONAL_DEPENDENCIES = {
    "doctor_discovery": ["auth_profile"],
    "social_network": ["auth_profile"],
    "referral_system": ["auth_profile"],
    "credit_tracking": ["referral_system"],
    "referral_lifecycle": ["referral_system"],
}

ACTION_LIBRARY = {
    # ── Auth & profile ──────────────────────────────────────────────────────
    "signup":               "Doctor SignUp",
    "signin":               "Doctor SignIn",
    "update_intro":         "Update Intro",
    "add_experience":       "Add Experience",
    "update_experience":    "Update Experience",
    "add_education":        "Add Education",
    "update_education":     "Update Education",
    "add_language":         "Add Language",
    "add_skill":            "Add Skill",
    "update_cover_photo":   "Update Cover Photo",
    # ── Doctor discovery ────────────────────────────────────────────────────
    "get_main_specializations": "Get All Main Specializations",
    "get_sub_specializations":  "Get All Sub Specializations",
    "get_all_doctors":          "Get All Doctors",
    "get_doctor_by_id":         "Get Doctor By Id",
    "doctor_search":            "Doctor Search",
    # ── Social network ──────────────────────────────────────────────────────
    "create_post":              "Create Post",
    "update_post":              "Update Post",
    "get_home_feed":            "Get Home Feed",
    "get_profile_posts":        "Get Profile Posts",
    "post_like":                "Post Like",
    "get_likes":                "Get Likes",
    "home_feed_using_cursor":   "Home Feed Using Cursor",
    "get_detail_post":          "Get Detail Post",
    "send_connection":          "Send Connection Request",
    "delete_post":              "Delete Post",
    # ── Referral system ─────────────────────────────────────────────────────
    "create_referral":          "Create Referral",
    "get_referrals":            "Get All Referred By Creator",
    "get_referral_detail":      "Get Referral By Id",
    "total_referred_pending":   "Total Referred Patients PENDING",
    "update_referral":          "Update Referral",
    "send_reminder":            "Send Reminder",
    "referred_count":           "Referred Count",
    "received_count":           "Received Count",
    "frequently_referred":      "Frequently Referred Doctor",
    "accept_referral":          "Update Status Accept",
    "update_patient_status":    "Update Patient Status Admitted",
    "total_received_patients":  "Total Received Patients",
    "total_referred_accepted":  "Total Referred Patients Accepted",
    # ── Credit tracking ─────────────────────────────────────────────────────
    "credit_header":            "Total Credit Points Header",
    "credit_by_sender":         "Get Credit Points By Sender",
    "credit_by_receiver":       "Get Credit Points By Receiver",
    "update_credit_sender":     "Update Credit Status By Sender",
    "update_credit_receiver":   "Update Credit Status By Receiver",
    # ── Referral lifecycle (cancel / delete) ────────────────────────────────
    "create_cancel_referral":   "Create Cancel Test Referral",
    "get_referrals_for_cancel": "Get All Referred for Cancel",
    "cancel_referral":          "Cancel Referred",
    "delete_referral":          "Delete Referral",
}

ACTION_PREREQUISITES = {
    # auth
    "signin":                   ["signup"],
    "update_intro":             ["signin"],
    # profile
    "add_experience":           ["signin"],
    "update_experience":        ["add_experience"],
    "add_education":            ["signin"],
    "update_education":         ["add_education"],
    "add_language":             ["signin"],
    "add_skill":                ["signin"],
    "update_cover_photo":       ["signin"],
    # discovery
    "get_main_specializations": ["signin"],
    "get_sub_specializations":  ["signin"],
    "get_all_doctors":          ["signin"],
    "get_doctor_by_id":         ["signin"],
    "doctor_search":            ["signin"],
    # social
    "create_post":              ["signin"],
    "update_post":              ["create_post"],
    "get_home_feed":            ["create_post"],
    "get_profile_posts":        ["create_post"],
    "post_like":                ["signin"],
    "get_likes":                ["post_like"],
    "home_feed_using_cursor":   ["signin"],
    "get_detail_post":          ["signin"],
    "send_connection":          ["get_detail_post"],
    "delete_post":              ["get_detail_post"],
    # referrals
    "create_referral":          ["signin"],
    "get_referrals":            ["create_referral"],
    "get_referral_detail":      ["get_referrals"],
    "total_referred_pending":   ["create_referral"],
    "update_referral":          ["get_referral_detail"],
    "send_reminder":            ["get_referral_detail"],
    "referred_count":           ["signin"],
    "received_count":           ["signin"],
    "frequently_referred":      ["signin"],
    "accept_referral":          ["get_referral_detail"],
    "update_patient_status":    ["accept_referral"],
    "total_received_patients":  ["accept_referral"],
    "total_referred_accepted":  ["accept_referral"],
    # credits
    "credit_header":            ["signin"],
    "credit_by_sender":         ["signin"],
    "credit_by_receiver":       ["accept_referral"],
    "update_credit_sender":     ["update_patient_status"],
    "update_credit_receiver":   ["update_credit_sender"],
    # lifecycle
    "create_cancel_referral":   ["signin"],
    "get_referrals_for_cancel": ["create_cancel_referral"],
    "cancel_referral":          ["get_referrals_for_cancel"],
    "delete_referral":          ["cancel_referral"],
}


def _progress_logging_enabled() -> bool:
    return str(os.getenv("AGENTIC_PROGRESS_LOGGING", "true")).strip().lower() in {"1", "true", "yes", "y"}


def _partial_reporting_enabled() -> bool:
    return str(os.getenv("AGENTIC_PARTIAL_REPORTING", "true")).strip().lower() in {"1", "true", "yes", "y"}


def _log_progress(message: str) -> None:
    if _progress_logging_enabled():
        try:
            print(message, flush=True)
        except OSError:
            pass


def _build_partial_report(
    *,
    run_id: str,
    report_mode: str,
    results: list[dict[str, Any]],
    agent_summaries: list[dict[str, Any]],
    errors: list[str],
    status: str,
    suite: dict[str, Any] | None = None,
    prefetched_context: dict[str, Any] | None = None,
    master_api_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = build_agentic_report(
        run_id=run_id,
        status=status,
        results=results,
        agent_summaries=agent_summaries,
        errors=errors,
        suite=suite,
        prefetched_context=prefetched_context,
        master_api_checks=master_api_checks,
    )
    payload["mode"] = report_mode
    return payload


def _write_partial_report(
    report_file: str | None,
    report_payload: dict[str, Any],
) -> None:
    if not report_file or not _partial_reporting_enabled():
        return
    write_agentic_report(report_file, report_payload)


def _update_progress_state(
    progress_state: dict[str, Any] | None,
    *,
    agent_id: str,
    user_index: int,
    step_result: dict[str, Any] | None = None,
    errors: list[str] | None = None,
    action_history: list[dict[str, Any]] | None = None,
    planned_actions: list[str] | None = None,
    pending_actions: list[str] | None = None,
    executed_actions: int | None = None,
    final_summary: dict[str, Any] | None = None,
    status: str = "in_progress",
) -> None:
    if progress_state is None:
        return
    
    ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1").strip() or "llama3.1"
    
    with progress_state["lock"]:
        if step_result is not None:
            progress_state["results"].append(step_result)
        if errors:
            progress_state["errors"].extend(errors)

        if final_summary is not None:
            progress_state["agents"][agent_id] = final_summary
        else:
            existing_summary = dict(progress_state["agents"].get(agent_id, {}))
            existing_summary.update(
                {
                    "agent_id": agent_id,
                    "user_index": user_index,
                    "ai": ollama_model,
                    "action_history": action_history or existing_summary.get("action_history", []),
                    "planned_actions": planned_actions or existing_summary.get("planned_actions", []),
                    "pending_actions": pending_actions or existing_summary.get("pending_actions", []),
                    "executed_actions": executed_actions if executed_actions is not None else existing_summary.get("executed_actions", 0),
                    "status": status,
                }
            )
            progress_state["agents"][agent_id] = existing_summary

        partial_payload = _build_partial_report(
            run_id=progress_state["run_id"],
            report_mode="agentic_ollama",
            results=progress_state["results"],
            agent_summaries=sorted(progress_state["agents"].values(), key=lambda item: int(item["user_index"])),
            errors=progress_state["errors"],
            status=status,
            suite=progress_state.get("suite"),
            prefetched_context=progress_state.get("prefetched_context"),
            master_api_checks=progress_state.get("master_api_checks"),
        )
        _write_partial_report(progress_state["report_file"], partial_payload)


def _step_map_from_suite(suite: dict[str, Any]) -> dict[str, dict[str, Any]]:
    step_map: dict[str, dict[str, Any]] = {}
    for workflow in suite.get("workflows", []):
        workflow_name = workflow.get("name", "unnamed_workflow")
        if workflow.get("enabled", True) is False:
            continue
        for step in workflow.get("steps", []):
            if not isinstance(step, dict):
                continue
            if step.get("enabled", True) is False:
                continue
            step_name = step.get("name")
            if not isinstance(step_name, str):
                continue
            enriched = dict(step)
            enriched["workflow_name"] = workflow_name
            step_map[step_name] = enriched
    return step_map


def _fallback_action_plan(context_vars: dict[str, Any]) -> list[str]:
    engagement = str(context_vars.get("engagement_preference", "")).strip().lower()
    plan = [
        "signup", "signin",
        # profile
        "add_experience", "add_education", "add_language", "add_skill",
        "update_experience", "update_education", "update_cover_photo",
        # discovery
        "get_main_specializations", "get_sub_specializations",
        "get_all_doctors", "get_doctor_by_id", "doctor_search",
    ]
    social_actions = [
        "create_post", "get_home_feed", "get_profile_posts",
        "get_detail_post", "post_like", "get_likes",
        "home_feed_using_cursor", "update_post", "send_connection",
        "delete_post",
    ]
    if engagement in {"educational", "social", "active"}:
        plan.extend(social_actions)
    else:
        plan.extend([
            "get_home_feed", "get_profile_posts",
            "home_feed_using_cursor", "doctor_search",
            "send_connection", "create_post", "get_detail_post",
            "post_like", "get_likes", "update_post", "delete_post",
        ])
    plan.extend([
        # referrals
        "referred_count", "received_count", "frequently_referred",
        "create_referral", "get_referrals", "get_referral_detail",
        "total_referred_pending", "update_referral", "send_reminder",
        "accept_referral", "update_patient_status",
        "total_received_patients", "total_referred_accepted",
        # credits
        "credit_header", "credit_by_sender", "credit_by_receiver",
        "update_credit_sender", "update_credit_receiver",
        # lifecycle
        "create_cancel_referral", "get_referrals_for_cancel",
        "cancel_referral", "delete_referral",
    ])
    return list(dict.fromkeys(plan))


def _append_action_once(action_plan: list[str], action: str) -> None:
    if action in ACTION_LIBRARY and action not in action_plan:
        action_plan.append(action)


def _enabled_actions(step_map: dict[str, dict[str, Any]]) -> set[str]:
    enabled: set[str] = set()
    for action, step_name in ACTION_LIBRARY.items():
        if step_name in step_map:
            enabled.add(action)
    return enabled


def _unique_actions(actions: list[str], enabled_actions: set[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for action in actions:
        if action not in enabled_actions or action in seen:
            continue
        seen.add(action)
        ordered.append(action)
    return ordered


def _log_functional_dependencies(selected_goals: list[str]) -> None:
    _log_progress("\n--- Functional Goal Dependencies ---")
    _log_progress(f"Selected goals: {', '.join(selected_goals)}")
    
    needed_dependencies = set()
    for goal in selected_goals:
        for dep in FUNCTIONAL_DEPENDENCIES.get(goal, []):
            if dep not in selected_goals:
                needed_dependencies.add(dep)
    
    if needed_dependencies:
        _log_progress(f"Implicitly adding required dependencies: {', '.join(sorted(needed_dependencies))}")
    else:
        _log_progress("All functional dependencies are satisfied by selection.")
    _log_progress("-----------------------------------\n")


def _goal_backlog(context_vars: dict[str, Any], enabled_actions: set[str]) -> list[str]:
    selected_goals_str = str(os.getenv("AGENTIC_FUNCTIONAL_GOALS", "all")).strip().lower()
    if selected_goals_str == "all":
        selected_goals = list(FUNCTIONAL_GROUPS.keys())
    else:
        selected_goals = [g.strip() for g in selected_goals_str.split(",") if g.strip() in FUNCTIONAL_GROUPS]
    
    if not selected_goals:
        selected_goals = ["auth_profile"]
    
    # Auth/Profile is the foundational layer
    if "auth_profile" not in selected_goals:
        selected_goals.insert(0, "auth_profile")

    resolved_goals: list[str] = []
    seen_goals: set[str] = set()

    def add_goal_with_dependencies(goal: str) -> None:
        for dependency in FUNCTIONAL_DEPENDENCIES.get(goal, []):
            add_goal_with_dependencies(dependency)
        if goal not in seen_goals:
            seen_goals.add(goal)
            resolved_goals.append(goal)

    for selected_goal in selected_goals:
        add_goal_with_dependencies(selected_goal)

    final_actions = []
    for goal in resolved_goals:
        group_actions = FUNCTIONAL_GROUPS.get(goal, [])
        final_actions.extend(group_actions)
    
    return _unique_actions(final_actions, enabled_actions)


def _build_initial_action_queue(
    context_vars: dict[str, Any],
    step_map: dict[str, dict[str, Any]],
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> list[str]:
    enabled_actions = _enabled_actions(step_map)
    planned_actions = _decide_next_actions(context_vars, run_timestamp, user_index, iteration_index)
    goal_actions = _goal_backlog(context_vars, enabled_actions)
    seed_actions = ["signup", "signin"]
    return _unique_actions(seed_actions + planned_actions + goal_actions, enabled_actions)


def _enqueue_prerequisites(
    action_queue: list[str],
    action: str,
    enabled_actions: set[str],
    completed_steps: set[str],
) -> None:
    prerequisites = ACTION_PREREQUISITES.get(action, [])
    for prerequisite in reversed(prerequisites):
        prerequisite_step = ACTION_LIBRARY.get(prerequisite)
        if (
            prerequisite in enabled_actions
            and prerequisite_step not in completed_steps
        ):
            if prerequisite in action_queue:
                action_queue.remove(prerequisite)
            action_queue.insert(0, prerequisite)


def _promote(action_queue: list[str], action: str, enabled_actions: set[str]) -> None:
    if action not in enabled_actions:
        return
    if action in action_queue:
        action_queue.remove(action)
    action_queue.insert(0, action)


def _apply_state_followup(
    action_queue: list[str],
    *,
    step_name: str,
    step_result: dict[str, Any],
    enabled_actions: set[str],
) -> None:
    if step_result.get("passed") is not True:
        return

    preview = str(step_result.get("response_preview") or "")

    if step_name == "Get Home Feed":
        # Empty feed → create content first so the feed has something to show.
        if '"data": []' in preview:
            _promote(action_queue, "create_post", enabled_actions)

    elif step_name == "Get All Doctors":
        # Doctors are visible → immediately try to connect with one.
        if '"doctorId"' in preview or '"doctor_id"' in preview:
            _promote(action_queue, "send_connection", enabled_actions)

    elif step_name == "Create Post":
        # Post just published → check the feed to verify it appears.
        _promote(action_queue, "get_home_feed", enabled_actions)

    elif step_name == "Create Referral":
        # Referral created → confirm it landed in the pending queue.
        _promote(action_queue, "total_referred_pending", enabled_actions)

    elif step_name == "Doctor Search":
        # Search returned results → open the first result's profile.
        if '"doctorId"' in preview or '"doctor_id"' in preview or '"data"' in preview:
            _promote(action_queue, "get_doctor_by_id", enabled_actions)


def _reset_after_auth_mismatch(
    *,
    suite: dict[str, Any],
    prefetched_context: dict[str, Any],
    company_catalog: list[dict[str, Any]],
    specialization_catalog: list[dict[str, Any]],
    run_timestamp: int,
    user_index: int,
    base_iteration_index: int,
    reset_count: int,
    agent_id: str,
) -> tuple[dict[str, Any], list[str]]:
    context_vars, regen_errors = _materialize_agent_context(
        suite=suite,
        prefetched_context=prefetched_context,
        company_catalog=company_catalog,
        specialization_catalog=specialization_catalog,
        run_timestamp=run_timestamp,
        user_index=user_index,
        iteration_index=base_iteration_index + (reset_count * 100),
    )
    context_vars["agent_id"] = agent_id
    return context_vars, regen_errors


_ACTION_DESCRIPTIONS: dict[str, str] = {
    # auth / profile
    "signup":                   "Register a new doctor account on the platform",
    "signin":                   "Log into the doctor account",
    "add_experience":           "Add a work experience entry to the profile",
    "update_experience":        "Update an existing work experience entry",
    "add_education":            "Add an education entry to the profile",
    "update_education":         "Update an existing education entry",
    "add_language":             "Add a language the doctor speaks",
    "add_skill":                "Add a clinical skill to the profile",
    "update_cover_photo":       "Upload a new cover photo",
    # discovery
    "get_main_specializations": "Fetch the list of main medical specializations",
    "get_sub_specializations":  "Fetch sub-specializations for a given specialization",
    "get_all_doctors":          "Retrieve all doctors registered on the platform",
    "get_doctor_by_id":         "Fetch a specific doctor's full profile by ID",
    "doctor_search":            "Search for doctors by name or specialization",
    # social
    "create_post":              "Publish a new post (article, case study, image)",
    "update_post":              "Edit a previously created post",
    "get_home_feed":            "Load the personalized home feed",
    "get_profile_posts":        "View posts on the doctor's own profile",
    "post_like":                "React (like) to a post",
    "get_likes":                "See who liked a post",
    "home_feed_using_cursor":   "Paginate through the home feed using a cursor",
    "get_detail_post":          "Open a post to read its full detail",
    "send_connection":          "Send a connection request to another doctor",
    "delete_post":              "Delete a post the doctor created",
    # referrals
    "create_referral":          "Refer a patient to another doctor",
    "get_referrals":            "List all referrals the doctor has created",
    "get_referral_detail":      "Fetch full details of a specific referral",
    "total_referred_pending":   "Count referrals that are still pending",
    "update_referral":          "Update details of an existing referral",
    "send_reminder":            "Send a reminder to the referred doctor",
    "referred_count":           "View the total count of outgoing referrals",
    "received_count":           "View the total count of incoming referrals",
    "frequently_referred":      "See which doctors are most frequently referred to",
    "accept_referral":          "Accept a referral as the receiving doctor",
    "update_patient_status":    "Update the admitted patient's status",
    "total_received_patients":  "Count patients received via referral",
    "total_referred_accepted":  "Count referrals that were accepted",
    # credits
    "credit_header":            "View the credit points summary header",
    "credit_by_sender":         "See credit points earned by sending referrals",
    "credit_by_receiver":       "See credit points earned by receiving referrals",
    "update_credit_sender":     "Update the credit status on the sender side",
    "update_credit_receiver":   "Update the credit status on the receiver side",
    # lifecycle
    "create_cancel_referral":   "Create a referral specifically to test cancellation",
    "get_referrals_for_cancel": "Retrieve the referral created for cancellation",
    "cancel_referral":          "Cancel the referral",
    "delete_referral":          "Permanently delete the cancelled referral",
}


def _action_catalog_for_prompt() -> str:
    group_by_action = {
        action: group
        for group, actions in FUNCTIONAL_GROUPS.items()
        for action in actions
    }
    lines: list[str] = []
    for action, step_name in ACTION_LIBRARY.items():
        group = group_by_action.get(action, "general")
        description = _ACTION_DESCRIPTIONS.get(action, step_name)
        prerequisites = ACTION_PREREQUISITES.get(action, [])
        prerequisite_text = f"; prerequisites: {', '.join(prerequisites)}" if prerequisites else "; prerequisites: none"
        lines.append(
            f"  - {action} [{group}] -> {step_name}: {description}{prerequisite_text}"
        )
    return "\n".join(lines)


def _plan_actions_with_ollama(
    context_vars: dict[str, Any],
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> list[str]:
    ollama_url = f"{str(os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')).rstrip('/')}/api/generate"
    model = os.getenv("OLLAMA_MODEL", "llama3.1").strip() or "llama3.1"
    seed = agent_seed(run_timestamp, user_index, iteration_index, salt=503)

    action_catalog = _action_catalog_for_prompt()

    tone = str(context_vars.get("doctor_tone") or "professional").strip().lower()
    engagement = str(context_vars.get("engagement_preference") or "balanced").strip().lower()
    focus = str(context_vars.get("profile_focus") or context_vars.get("specialization_name") or "").strip()

    # Translate persona traits into concrete behavioral biases for the planner
    if tone in {"informative", "educational"}:
        tone_guidance = "prioritise create_post and discovery actions — this doctor likes to share knowledge."
    elif tone in {"warm", "friendly"}:
        tone_guidance = "prioritise send_connection, get_home_feed, and post_like — this doctor values community."
    elif tone in {"direct", "concise"}:
        tone_guidance = "prioritise referral actions early after profile setup — this doctor is referral-focused."
    elif tone in {"reflective", "thoughtful"}:
        tone_guidance = "spread actions evenly across profile, discovery, social, and referrals in that order."
    else:
        tone_guidance = "cover all functional areas with a slight preference for social and referral actions."

    if engagement in {"educational"}:
        engagement_guidance = "Lean toward discovery and posting. Include get_main_specializations and doctor_search early."
    elif engagement in {"social", "active"}:
        engagement_guidance = "Front-load social actions: create_post, get_home_feed, send_connection, post_like."
    else:
        engagement_guidance = "Balance profile completion, discovery, social engagement, and referrals."

    prompt = (
        "You are simulating a real Indian doctor using DocSynapse, a professional platform for "
        "medical networking, profile management, and patient referrals.\n\n"
        "Your task: produce a realistic, persona-consistent action sequence for THIS doctor. "
        "Return valid JSON only — a single object with key 'actions' whose value is an ordered "
        "array of action keys from the catalog below.\n\n"
        f"AVAILABLE ACTIONS:\n{action_catalog}\n\n"
        "HARD RULES (violating these breaks the session):\n"
        "1. 'signup' then 'signin' must always be first two actions.\n"
        "2. Never schedule an action before its listed prerequisites.\n"
        "3. 'update_experience' requires 'add_experience' first; 'update_education' requires 'add_education'.\n"
        "4. 'get_referral_detail' requires 'get_referrals'; 'accept_referral' requires 'get_referral_detail'.\n"
        "5. 'update_patient_status' requires 'accept_referral'; credit updates require 'update_patient_status'.\n"
        "6. Cancel/delete lifecycle ('create_cancel_referral' → 'get_referrals_for_cancel' → 'cancel_referral' → 'delete_referral') goes last.\n\n"
        "PERSONA GUIDANCE:\n"
        f"  Tone: {tone} → {tone_guidance}\n"
        f"  Engagement style: {engagement} → {engagement_guidance}\n"
        f"  Clinical focus: {focus}\n\n"
        "SEQUENCING PRINCIPLES:\n"
        "- Complete profile early (experience, education, language, skill, cover photo) so the account looks real.\n"
        "- Run discovery (specializations, search, browse) before heavy social actions.\n"
        "- Social actions (post, feed, like, connect) reflect the doctor's personality — see persona guidance.\n"
        "- Referral flows test the core platform value: create → track → update → accept → credit.\n"
        "- The sequence should read like a real doctor's first day to first week on the platform.\n\n"
        "DOCTOR PROFILE:\n"
        f"  Name: {context_vars.get('doctor_fullname', 'Doctor')}\n"
        f"  Specialty: {context_vars.get('specialization_name', '')}\n"
        f"  Institution: {context_vars.get('company_name', '')}\n"
        f"  Experience: {context_vars.get('years_of_experience', '')} years\n"
        f"  Bio: {context_vars.get('short_bio', '')}\n"
        f"  Motivation: {context_vars.get('onboarding_motivation', '')}\n"
        f"  Agent #{user_index}, seed {seed}.\n\n"
        "Return ONLY valid JSON: {\"actions\": [\"signup\", \"signin\", ...]}"
    )

    try:
        response = requests.post(
            ollama_url,
            headers={"Content-Type": "application/json"},
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": float(os.getenv("OLLAMA_TEMPERATURE", "0.7")),
                    "seed": seed,
                },
            },
            timeout=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60")),
        )
        response.raise_for_status()
        payload = response.json()
        content = payload.get("response") or payload.get("message", {}).get("content")
        data = json.loads(str(content))
        actions = data.get("actions", [])
        if not isinstance(actions, list):
            return _fallback_action_plan(context_vars)
        normalized = [str(item).strip() for item in actions if str(item).strip() in ACTION_LIBRARY]
        return normalized or _fallback_action_plan(context_vars)
    except Exception:
        return _fallback_action_plan(context_vars)


def _decide_next_actions(
    context_vars: dict[str, Any],
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> list[str]:
    if str(os.getenv("AGENTIC_USE_OLLAMA_PLANNER", "true")).strip().lower() not in {"1", "true", "yes", "y"}:
        return _fallback_action_plan(context_vars)
    return _plan_actions_with_ollama(context_vars, run_timestamp, user_index, iteration_index)


def _materialize_agent_context(
    suite: dict[str, Any],
    prefetched_context: dict[str, Any],
    company_catalog: list[dict[str, Any]],
    specialization_catalog: list[dict[str, Any]],
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> tuple[dict[str, Any], list[str]]:
    rng = random.Random(agent_seed(run_timestamp, user_index, iteration_index))
    context_vars: dict[str, Any] = {
        "run_id": str(run_timestamp),
        "timestamp": run_timestamp,
        "run_timestamp": run_timestamp,
        "user_index": user_index,
        "agent_id": f"agent_{user_index}",
        "ai": os.getenv("OLLAMA_MODEL", "llama3.1").strip() or "llama3.1",
        **suite.get("context", {}),
        **prefetched_context,
    }
    context_vars["iteration_index"] = iteration_index
    context_vars["run_email_suffix"] = f"{run_timestamp}.{user_index}.{iteration_index}"
    context_vars["run_mobile"] = compute_run_mobile(run_timestamp, user_index, iteration_index)
    errors: list[str] = []

    context_vars.update(build_doctor_identity(rng, run_timestamp, user_index, iteration_index))
    random_company_id, random_company_name = pick_company_from_catalog(
        company_catalog,
        run_timestamp=run_timestamp,
        user_index=user_index,
        iteration_index=iteration_index,
        virtual_users=int(suite.get("run", {}).get("virtual_users", 1)),
    )
    random_spec_id, random_spec_name = pick_specialization_from_catalog(
        specialization_catalog,
        run_timestamp=run_timestamp,
        user_index=user_index,
        iteration_index=iteration_index,
        virtual_users=int(suite.get("run", {}).get("virtual_users", 1)),
    )
    if random_company_id and not context_vars.get("company_id"):
        context_vars["company_id"] = random_company_id
    if random_company_name and not context_vars.get("company_name"):
        context_vars["company_name"] = random_company_name
    if random_spec_id and not context_vars.get("specialization_id"):
        context_vars["specialization_id"] = random_spec_id
        # Clear dependent IDs that were resolved for a different specialization
        context_vars.pop("sub_specialization_id", None)
        context_vars.pop("additional_specialization_id", None)
    if random_spec_name and not context_vars.get("specialization_name"):
        context_vars["specialization_name"] = random_spec_name

    context_vars.update(
        build_doctor_profile_context(rng, context_vars, run_timestamp, user_index, iteration_index)
    )
    context_vars.update(
        build_doctor_behavior_context(rng, context_vars, run_timestamp, user_index, iteration_index)
    )
    context_vars.update(
        generate_social_content_for_agent(rng, context_vars, user_index, iteration_index)
    )

    if images_enabled(context_vars):
        try:
            generated = generate_images_for_agent(
                output_dir=Path("tmp/generated_images_agentic"),
                run_timestamp=run_timestamp,
                user_index=user_index,
                iteration_index=iteration_index,
                doctor_fullname=str(context_vars.get("doctor_fullname") or "Doctor"),
                specialization_name=str(context_vars.get("specialization_name") or "Specialist care"),
                post_content=str(context_vars.get("post_content") or ""),
            )
            context_vars["profile_image_path"] = generated.profile_path
            context_vars["cover_image_path"] = generated.cover_path
            context_vars["post_image_path"] = generated.post_path
        except Exception as err:
            errors.append(f"Image generation failed for agent_{user_index}: {err}")

    return resolve_context_vars(context_vars), errors


def _execute_agent_session(
    *,
    suite: dict[str, Any],
    default_timeout_seconds: float,
    run_timestamp: int,
    user_index: int,
    prefetched_context: dict[str, Any],
    company_catalog: list[dict[str, Any]],
    specialization_catalog: list[dict[str, Any]],
    shared_doctor_registry: dict[int, dict[str, str]],
    registry_lock: Lock,
    progress_state: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1").strip() or "llama3.1"
    iteration_index = 1
    rng = random.Random(agent_seed(run_timestamp, user_index, iteration_index))
    results: list[dict[str, Any]] = []
    context_vars, errors = _materialize_agent_context(
        suite=suite,
        prefetched_context=prefetched_context,
        company_catalog=company_catalog,
        specialization_catalog=specialization_catalog,
        run_timestamp=run_timestamp,
        user_index=user_index,
        iteration_index=iteration_index,
    )
    agent_id = str(context_vars.get("agent_id"))
    step_map = _step_map_from_suite(suite)
    enabled_actions = _enabled_actions(step_map)
    action_plan = _build_initial_action_queue(
        context_vars,
        step_map,
        run_timestamp,
        user_index,
        iteration_index,
    )
    initial_action_plan = list(action_plan)
    completed_steps: set[str] = set()
    completed_actions: list[str] = []
    action_history: list[dict[str, Any]] = []
    deferred_attempts: dict[str, int] = {}
    max_deferred_attempts = max(2, safe_int_env("AGENTIC_MAX_DEFERRED_ATTEMPTS", 4) or 4)
    max_actions_default = str(len(enabled_actions) or len(ACTION_LIBRARY))
    max_actions = max(1, safe_int_env("AGENTIC_MAX_ACTIONS", int(max_actions_default)) or int(max_actions_default))
    executed_actions = 0
    auth_reset_count = 0
    max_auth_resets = max(1, safe_int_env("AGENTIC_AUTH_RESET_LIMIT", 2) or 2)
    signup_failure_count = 0
    max_signup_failures = max(1, safe_int_env("AGENTIC_SIGNUP_FAILURE_LIMIT", 2) or 2)
    stop_reason: str | None = None
    ramp_up_seconds = float(suite.get("run", {}).get("ramp_up_seconds", 0.0) or 0.0)
    virtual_users = max(1, int(suite.get("run", {}).get("virtual_users", 1) or 1))

    if ramp_up_seconds > 0 and user_index > 1:
        max_denominator = max(1, virtual_users - 1)
        stagger_seconds = ramp_up_seconds * ((user_index - 1) / max_denominator)
        time.sleep(max(0.0, stagger_seconds))

    while action_plan and executed_actions < max_actions:
        action = action_plan.pop(0)
        step_name = ACTION_LIBRARY.get(action)
        if not step_name:
            continue
        if step_name in completed_steps:
            continue
        step = step_map.get(step_name)
        if not isinstance(step, dict):
            errors.append(f"Missing step template for action '{action}' ({step_name}).")
            continue

        dependency_name = step.get("depends_on")
        if dependency_name and dependency_name not in completed_steps:
            _enqueue_prerequisites(action_plan, action, enabled_actions, completed_steps)
            deferred_attempts[action] = deferred_attempts.get(action, 0) + 1
            if deferred_attempts[action] <= max_deferred_attempts:
                _append_action_once(action_plan, action)
            continue

        if action == "signin" and not context_vars.get("doctor_email"):
            _enqueue_prerequisites(action_plan, action, enabled_actions, completed_steps)
            continue

        if action in {"get_detail_post", "post_like", "doctor_search", "home_feed_using_cursor"} and not context_vars.get("signin_access_token"):
            _enqueue_prerequisites(action_plan, action, enabled_actions, completed_steps)
            continue

        if action in {"create_post", "get_home_feed", "get_profile_posts", "update_post"} and not context_vars.get("signin_doctor_id"):
            _enqueue_prerequisites(action_plan, action, enabled_actions, completed_steps)
            continue

        if value_requires_peer_context(step, context_vars):
            context_vars = ensure_peer_context(
                context_vars,
                shared_doctor_registry,
                registry_lock,
                user_index,
                rng,
            )
            if value_requires_peer_context(step, context_vars):
                deferred_attempts[action] = deferred_attempts.get(action, 0) + 1
                if deferred_attempts[action] <= max_deferred_attempts:
                    _append_action_once(action_plan, action)
                continue

        _log_progress(f"[agent {user_index} | {ollama_model}] starting {action} -> {step_name}")
        step_result, context_vars, step_errors = execute_step(
            workflow_name=str(step.get("workflow_name", "Agentic Session")),
            step=step,
            context_vars=context_vars,
            default_timeout_seconds=float(suite.get("run", {}).get("default_timeout_seconds", default_timeout_seconds)),
            run_default_retries=int(suite.get("run", {}).get("default_retries", 0)),
        )
        step_result["user_index"] = user_index
        step_result["agent_id"] = agent_id
        step_result["iteration_index"] = iteration_index
        step_result["planned_action"] = action
        results.append(step_result)
        errors.extend(step_errors)
        executed_actions += 1
        _log_progress(
            f"[agent {user_index} | {ollama_model}] finished {step_name} | passed={bool(step_result.get('passed'))} "
            f"status={step_result.get('status_code')} time_ms={step_result.get('response_time_ms')}"
        )
        action_history.append(
            {
                "action": action,
                "step": step_name,
                "passed": bool(step_result.get("passed")),
                "status_code": step_result.get("status_code"),
                "errors": step_result.get("errors", []),
            }
        )
        _update_progress_state(
            progress_state,
            agent_id=agent_id,
            user_index=user_index,
            step_result=step_result,
            errors=step_errors,
            action_history=action_history,
            planned_actions=initial_action_plan,
            pending_actions=action_plan,
            executed_actions=executed_actions,
            status="in_progress",
        )

        if step_result.get("passed") is True:
            completed_steps.add(step_name)
            completed_actions.append(step_name)
            if step_name == "Doctor SignUp":
                signup_failure_count = 0
                context_vars["doctor_session_goal"] = "complete_profile_and_engage"
            if step_name == "Doctor SignIn":
                register_signed_in_agent(shared_doctor_registry, registry_lock, user_index, context_vars)
            _apply_state_followup(
                action_plan,
                step_name=step_name,
                step_result=step_result,
                enabled_actions=enabled_actions,
            )
        else:
            if action == "signup":
                signup_failure_count += 1
                if signup_failure_count >= max_signup_failures:
                    stop_reason = (
                        "Agent stopped: Doctor SignUp failed repeatedly "
                        f"({signup_failure_count}/{max_signup_failures}) with status {step_result.get('status_code')}."
                    )
                    step_result["stop_reason"] = stop_reason
                    step_result["errors"] = list(step_result.get("errors", [])) + [stop_reason]
                    errors.append(stop_reason)
                    action_plan = []
                    _log_progress(f"[agent {user_index}] {stop_reason}")
                    _update_progress_state(
                        progress_state,
                        agent_id=agent_id,
                        user_index=user_index,
                        errors=[stop_reason],
                        action_history=action_history,
                        planned_actions=initial_action_plan,
                        pending_actions=action_plan,
                        executed_actions=executed_actions,
                        status="blocked",
                    )
                    break
                context_vars, regen_errors = _materialize_agent_context(
                    suite=suite,
                    prefetched_context=prefetched_context,
                    company_catalog=company_catalog,
                    specialization_catalog=specialization_catalog,
                    run_timestamp=run_timestamp,
                    user_index=user_index,
                    iteration_index=iteration_index + 100,
                )
                context_vars["agent_id"] = agent_id
                errors.extend(regen_errors)
                if "signup" not in action_plan:
                    action_plan.insert(0, "signup")
            elif (
                action == "signin"
                and auth_reset_count < max_auth_resets
                and str(step_result.get("response_preview") or "").find("INVALID_CREDENTIALS") >= 0
            ):
                auth_reset_count += 1
                _log_progress(
                    f"[agent {user_index}] signin mismatch detected, regenerating identity and restarting auth "
                    f"(attempt {auth_reset_count}/{max_auth_resets})"
                )
                context_vars, regen_errors = _reset_after_auth_mismatch(
                    suite=suite,
                    prefetched_context=prefetched_context,
                    company_catalog=company_catalog,
                    specialization_catalog=specialization_catalog,
                    run_timestamp=run_timestamp,
                    user_index=user_index,
                    base_iteration_index=iteration_index,
                    reset_count=auth_reset_count,
                    agent_id=agent_id,
                )
                errors.extend(regen_errors)
                completed_steps = set()
                completed_actions = []
                deferred_attempts.pop("signin", None)
                deferred_attempts.pop("signup", None)
                action_plan = _unique_actions(
                    ["signup", "signin"] + action_plan + [item for item in initial_action_plan if item not in {"signup", "signin"}],
                    enabled_actions,
                )
            elif action in {"signin", "create_post"} and deferred_attempts.get(action, 0) < max_deferred_attempts:
                _append_action_once(action_plan, action)

    passed_steps = sum(1 for item in results if item.get("passed") is True)
    failed_steps = len(results) - passed_steps
    agent_summary = {
        "agent_id": agent_id,
        "user_index": user_index,
        "ai": ollama_model,
        "passed_steps": passed_steps,
        "failed_steps": failed_steps,
        "planned_actions": initial_action_plan,
        "pending_actions": action_plan,
        "action_history": action_history,
        "executed_actions": executed_actions,
        "doctor_email": sanitize_report_value(context_vars.get("doctor_email")),
        "doctor_id": context_vars.get("doctor_id") or context_vars.get("signin_doctor_id"),
        "specialization_id": context_vars.get("specialization_id"),
        "specialization_name": context_vars.get("specialization_name"),
        "company_id": context_vars.get("company_id"),
        "company_name": context_vars.get("company_name"),
        "identity_source": context_vars.get("identity_source"),
        "profile_generation_source": context_vars.get("profile_generation_source"),
        "behavior_generation_source": context_vars.get("behavior_generation_source"),
        "doctor_session_goal": context_vars.get("doctor_session_goal") or "explore_platform",
        "status": "blocked" if stop_reason else "completed",
        "stop_reason": stop_reason,
        "planner_source": "ollama"
        if str(os.getenv("AGENTIC_USE_OLLAMA_PLANNER", "true")).strip().lower() in {"1", "true", "yes", "y"}
        else "fallback",
    }
    _update_progress_state(
        progress_state,
        agent_id=agent_id,
        user_index=user_index,
        final_summary=agent_summary,
        status="blocked" if stop_reason else "in_progress",
    )
    return results, agent_summary, errors


def execute_agentic_sessions(
    *,
    suite: dict[str, Any],
    default_timeout_seconds: float,
    run_timestamp: int,
    prefetched_context: dict[str, Any] | None = None,
    report_file: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    selected_goals_str = str(os.getenv("AGENTIC_FUNCTIONAL_GOALS", "all")).strip().lower()
    if selected_goals_str == "all":
        selected_goals = list(FUNCTIONAL_GROUPS.keys())
    else:
        selected_goals = [g.strip() for g in selected_goals_str.split(",") if g.strip() in FUNCTIONAL_GROUPS]
    if not selected_goals:
        selected_goals = ["auth_profile"]
    _log_functional_dependencies(selected_goals)

    run_config = suite.get("run", {})
    virtual_users = int(run_config.get("virtual_users", 1))
    max_workers = max(1, min(int(run_config.get("max_workers", virtual_users)), virtual_users))

    company_catalog, specialization_catalog = load_exported_catalogs()
    shared_doctor_registry: dict[int, dict[str, str]] = {}
    registry_lock = Lock()
    all_results: list[dict[str, Any]] = []
    agent_summaries: list[dict[str, Any]] = []
    all_errors: list[str] = []
    shared_prefetched = prefetched_context or {}
    progress_state = {
        "lock": Lock(),
        "run_id": str(run_timestamp),
        "report_file": report_file,
        "suite": suite,
        "prefetched_context": shared_prefetched,
        "master_api_checks": list(shared_prefetched.get("master_api_checks", [])) if isinstance(shared_prefetched, dict) else [],
        "results": [],
        "agents": {},
        "errors": [],
    }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                _execute_agent_session,
                suite=suite,
                default_timeout_seconds=default_timeout_seconds,
                run_timestamp=run_timestamp,
                user_index=user_index,
                prefetched_context=shared_prefetched,
                company_catalog=company_catalog,
                specialization_catalog=specialization_catalog,
                shared_doctor_registry=shared_doctor_registry,
                registry_lock=registry_lock,
                progress_state=progress_state,
            )
            for user_index in range(1, virtual_users + 1)
        ]

        for future in as_completed(futures):
            try:
                results, agent_summary, errors = future.result()
            except Exception as err:
                error_message = f"Agent execution crashed: {err}"
                all_errors.append(error_message)
                with progress_state["lock"]:
                    progress_state["errors"].append(error_message)
                _log_progress(f"[agentic] {error_message}")
                continue
            all_results.extend(results)
            agent_summaries.append(agent_summary)
            all_errors.extend(errors)

    all_results.sort(key=lambda item: (int(item["user_index"]), int(item["iteration_index"]), str(item.get("step", ""))))
    agent_summaries.sort(key=lambda item: int(item["user_index"]))
    failed = sum(1 for item in all_results if item.get("passed") is False and item.get("skipped") is not True)
    final_partial_payload = _build_partial_report(
        run_id=str(run_timestamp),
        report_mode="agentic_ollama",
        results=all_results,
        agent_summaries=agent_summaries,
        errors=all_errors,
        status=report_status(failed=failed, errors=len(all_errors)),
        suite=suite,
        prefetched_context=shared_prefetched,
        master_api_checks=list(shared_prefetched.get("master_api_checks", [])) if isinstance(shared_prefetched, dict) else [],
    )
    _write_partial_report(report_file, final_partial_payload)
    return all_results, agent_summaries, all_errors
