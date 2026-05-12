"""
simulate_agents.py — Dry-run agent simulation.

Shows exactly what data gets generated per agent and what every step's
HTTP request body/URL looks like after placeholder rendering.
No real HTTP calls are made; master data is loaded from local CSVs.

Usage:
    py simulate_agents.py                        # all 3 identity modes, 2 agents
    py simulate_agents.py --mode ollama          # ollama only
    py simulate_agents.py --mode template --agents 5 --iterations 2
    py simulate_agents.py --suite tests/referral_suite.json --workflows "Doctor Auth + Profile"
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

# Force UTF-8 stdout so box/arrow chars render on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── CLI args (parse before any env mutation) ─────────────────────────────────
parser = argparse.ArgumentParser(description="Agent dry-run simulation")
parser.add_argument("--mode", default="all",
                    choices=["template", "pool", "ollama", "all"],
                    help="Identity mode(s) to simulate")
parser.add_argument("--agents", type=int, default=2, help="Number of virtual users")
parser.add_argument("--iterations", type=int, default=1, help="Iterations per agent")
parser.add_argument("--suite", default="tests/unified_comprehensive_suite.json",
                    help="Suite JSON file to load")
parser.add_argument("--workflows", default="",
                    help="Comma-separated workflow names to render steps for (default: first workflow only)")
parser.add_argument("--ollama-model", default="",
                    help="Ollama model override (default: llama3:latest if available)")
parser.add_argument("--no-steps", action="store_true",
                    help="Skip step rendering, only show generated context")
args = parser.parse_args()

# ── Ensure we run from repo root ─────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

# ── Set Ollama model before imports touch env ─────────────────────────────────
# The .env has llama3.1 commented out; we default to llama3:latest which is installed.
if args.ollama_model:
    os.environ["OLLAMA_MODEL"] = args.ollama_model
elif not os.environ.get("OLLAMA_MODEL"):
    os.environ["OLLAMA_MODEL"] = "llama3:latest"

# Disable Stable Diffusion for the sim (no GPU needed)
os.environ.setdefault("GENERATE_IMAGES", "false")
# Use Ollama for post generation when in ollama mode (controlled per-mode below)
os.environ["OLLAMA_GENERATE_POSTS"] = "false"

from dotenv import load_dotenv
load_dotenv()

from testing_workflow_core.seed import agent_seed
from testing_workflow_core.suite_loader import load_suite
from testing_workflow_core.template import render_value
from testing_workflow_core.execution import (
    load_exported_catalogs,
    pick_company_from_catalog,
    pick_specialization_from_catalog,
)
from testing_workflow_core.image_generation import generate_social_content_for_agent
from testing_workflow_ollama_agentic.session import (
    FUNCTIONAL_GROUPS,
    FUNCTIONAL_DEPENDENCIES,
    ACTION_LIBRARY,
)

# ── Helpers ───────────────────────────────────────────────────────────────────
DIVIDER   = "=" * 70
SECTION   = "─" * 70
BOX_TOP   = "┌" + "─" * 68 + "┐"
BOX_BOT   = "└" + "─" * 68 + "┘"


def box_line(label: str, value: Any, indent: int = 2) -> str:
    prefix = " " * indent
    label_fmt = f"{label:<22}"
    val_str = str(value) if not isinstance(value, list) else ", ".join(str(v) for v in value)
    line = f"{prefix}{label_fmt}: {val_str}"
    if len(line) > 68:
        line = line[:65] + "..."
    return f"│ {line:<66} │"


def _compute_run_mobile(run_timestamp: int, user_index: int, iteration_index: int) -> str:
    base = 7_000_000_000
    span = 2_999_999_999
    value = base + ((run_timestamp + (user_index * 7919) + (iteration_index * 17)) % span)
    return str(value)


def _resolve(ctx: dict[str, Any]) -> dict[str, Any]:
    """Multi-pass placeholder resolution within the context itself."""
    resolved = dict(ctx)
    for _ in range(6):
        missing: set[str] = set()
        updated = {k: render_value(v, resolved, missing) for k, v in resolved.items()}
        if updated == resolved:
            break
        resolved = updated
    return resolved


def build_base_context(
    suite_ctx: dict[str, Any],
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
) -> dict[str, Any]:
    run_email_suffix = f"{run_timestamp}"
    run_mobile = _compute_run_mobile(run_timestamp, user_index, iteration_index)
    return {
        **suite_ctx,
        "run_id":            f"sim-{run_timestamp}",
        "timestamp":         str(run_timestamp),
        "run_timestamp":     str(run_timestamp),
        "user_index":        str(user_index),
        "agent_id":          f"agent-{user_index:03d}",
        "iteration_index":   str(iteration_index),
        "run_email_suffix":  run_email_suffix,
        "run_mobile":        run_mobile,
        "doctor_mobile":     run_mobile,
        # Peer context mocked — agents discover this at runtime via registry
        "peer_doctor_id":    "PEER-DR-MOCK-001",
        "peer_doctor_email": "peer@example.com",
        "peer_access_token": "***REDACTED***",
        # Simulated saved values from prior steps (for placeholder resolution)
        "signin_doctor_id":          f"DR-SIM-{user_index:03d}",
        "signin_access_token":       "***REDACTED***",
        "doctor_id":                 f"DR-SIM-{user_index:03d}",
        "created_post_id":           f"POST-SIM-{user_index:03d}",
        "updated_post_id":           f"POST-SIM-{user_index:03d}",
        "created_referral_id":       f"REF-SIM-{user_index:03d}",
        "referral_id":               f"REF-SIM-{user_index:03d}",
        "cancel_referral_id":        f"REF-SIM-CANCEL-{user_index:03d}",
        "referred_doctor_id":        "PEER-DR-MOCK-001",
        "education_id":              f"EDU-SIM-{user_index:03d}",
        "experience_id":             f"EXP-SIM-{user_index:03d}",
    }


def enrich_with_identity_and_catalog(
    ctx: dict[str, Any],
    rng: random.Random,
    mode: str,
    run_timestamp: int,
    user_index: int,
    iteration_index: int,
    companies: list[dict[str, Any]],
    specs: list[dict[str, Any]],
    virtual_users: int,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (enriched_context, timing_notes)."""
    timing: dict[str, str] = {}

    # Set mode for this call
    os.environ["DOCTOR_IDENTITY_MODE"] = mode

    from testing_workflow_core.doctor_persona import (
        build_doctor_identity,
        build_doctor_profile_context,
        build_doctor_behavior_context,
    )

    # Identity
    t0 = time.perf_counter()
    identity = build_doctor_identity(rng, run_timestamp, user_index, iteration_index)
    timing["identity"] = f"{(time.perf_counter()-t0)*1000:.0f}ms"
    ctx.update(identity)

    # Catalog picks (from local CSV — no API)
    company_id, company_name = pick_company_from_catalog(
        list(companies), run_timestamp, user_index, iteration_index, virtual_users
    )
    spec_id, spec_name = pick_specialization_from_catalog(
        list(specs), run_timestamp, user_index, iteration_index, virtual_users
    )
    ctx.update({
        "company_id":            company_id or "COMP-FALLBACK",
        "company_name":          company_name or "General Hospital",
        "specialization_id":     spec_id or "MS01",
        "specialization_name":   spec_name or "General Medicine",
        "sub_specialization_id": "SS01",
        "specialization_source": "csv",
        "company_source":        "csv",
    })

    # Profile & behavior
    t1 = time.perf_counter()
    profile = build_doctor_profile_context(rng, ctx, run_timestamp, user_index, iteration_index)
    timing["profile"] = f"{(time.perf_counter()-t1)*1000:.0f}ms"
    ctx.update(profile)

    t2 = time.perf_counter()
    behavior = build_doctor_behavior_context(rng, ctx, run_timestamp, user_index, iteration_index)
    timing["behavior"] = f"{(time.perf_counter()-t2)*1000:.0f}ms"
    ctx.update(behavior)

    # Social content (LangChain post chain if ollama, else fallback)
    t3 = time.perf_counter()
    if mode == "ollama":
        os.environ["OLLAMA_GENERATE_POSTS"] = "true"
    else:
        os.environ["OLLAMA_GENERATE_POSTS"] = "false"
    social = generate_social_content_for_agent(rng, ctx, user_index, iteration_index)
    timing["social"] = f"{(time.perf_counter()-t3)*1000:.0f}ms"
    ctx.update(social)

    # Build composed email
    email_local = str(ctx.get("doctor_email_local", "doctor"))
    email_suffix = str(ctx.get("run_email_suffix", "0"))
    ctx["doctor_email"] = f"{email_local}.{email_suffix}@example.com"

    # Final multi-pass resolve
    ctx = _resolve(ctx)
    return ctx, timing


def render_step_request(step: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    missing: set[str] = set()
    return {
        "method":  render_value(step.get("method", "GET"), ctx, missing),
        "url":     render_value(step.get("url", ""), ctx, missing),
        "headers": render_value(step.get("headers", {}), ctx, missing),
        "body":    render_value(step.get("json") or step.get("data") or {}, ctx, missing),
        "params":  render_value(step.get("params") or {}, ctx, missing),
        "missing": sorted(missing),
    }


def print_context_block(ctx: dict[str, Any]) -> None:
    print(BOX_TOP)
    print(box_line("Name",         ctx.get("doctor_fullname", "")))
    print(box_line("Email",        ctx.get("doctor_email", "")))
    print(box_line("Mobile",       ctx.get("doctor_mobile", "")))
    print(box_line("Reg Number",   ctx.get("registration_number", "")))
    print(box_line("DOB",          ctx.get("date_of_birth", "")))
    print(box_line("Gender",       ctx.get("gender", "")))
    print(box_line("Experience",   f"{ctx.get('years_of_experience', '')} years"))
    print(box_line("Board",        ctx.get("medical_council_board", "")))
    print(box_line("Bio",          ctx.get("short_bio", "")))
    print(box_line("Identity src", ctx.get("identity_source", "")))
    if ctx.get("identity_error"):
        print(box_line("⚠ ID error",  ctx["identity_error"]))
    print("│" + " " * 68 + "│")

    print(box_line("Company",      f"{ctx.get('company_name','')} ({ctx.get('company_id','')})"))
    print(box_line("Specialization", f"{ctx.get('specialization_name','')} ({ctx.get('specialization_id','')})"))
    print(box_line("Sub Spec ID",  ctx.get("sub_specialization_id", "")))
    print("│" + " " * 68 + "│")

    print(box_line("Job title",    ctx.get("job_title_signup", "")))
    print(box_line("Job current",  ctx.get("job_title_current", "")))
    print(box_line("Education",    f"{ctx.get('education_degree_name','')} @ {ctx.get('education_school_name','')}"))
    print(box_line("Language",     f"{ctx.get('language_name','')} ({ctx.get('language_proficiency_level','')})"))
    print(box_line("Skill",        ctx.get("skill_name", "")))
    print(box_line("Prof src",     ctx.get("profile_generation_source", "")))
    if ctx.get("profile_generation_error"):
        print(box_line("⚠ Profile err", ctx["profile_generation_error"]))
    print("│" + " " * 68 + "│")

    print(box_line("Consultation", ctx.get("consultation_modes", [])))
    print(box_line("Post vis.",    ctx.get("post_visibility", "")))
    print(box_line("Reaction",     ctx.get("post_reaction_type", "")))
    print(box_line("Search term",  ctx.get("doctor_search_term", "")))
    print(box_line("Behav src",    ctx.get("behavior_generation_source", "")))
    if ctx.get("behavior_generation_error"):
        print(box_line("⚠ Behav err", ctx["behavior_generation_error"]))
    print("│" + " " * 68 + "│")

    print(box_line("Post content", ctx.get("post_content", "")))
    print(box_line("Tags",         [ctx.get("post_tag_1",""), ctx.get("post_tag_2",""), ctx.get("post_tag_3","")]))
    print(BOX_BOT)


def print_action_plan() -> None:
    print("\n  Agentic Action Plan (FUNCTIONAL_GROUPS execution order):")
    for group, actions in FUNCTIONAL_GROUPS.items():
        deps = FUNCTIONAL_DEPENDENCIES.get(group, [])
        dep_str = f"  [requires: {', '.join(deps)}]" if deps else ""
        print(f"    {group:<22}{dep_str}")
        for action in actions:
            step_name = ACTION_LIBRARY.get(action, action)
            print(f"      → {action:<28} ≡  \"{step_name}\"")


def print_step_rendering(suite: dict[str, Any], ctx: dict[str, Any], workflow_filter: list[str]) -> None:
    workflows = suite.get("workflows", [])
    if workflow_filter:
        workflows = [w for w in workflows if w.get("name", "") in workflow_filter]
    if not workflows:
        workflows = suite.get("workflows", [])[:1]

    for workflow in workflows:
        wf_name = workflow.get("name", "Unnamed")
        steps = workflow.get("steps", [])
        print(f"\n  Workflow: {wf_name}  ({len(steps)} steps)")
        print(f"  {'─'*66}")
        for step in steps:
            rendered = render_step_request(step, ctx)
            depends = step.get("depends_on")
            dep_note = f" [depends_on: {depends}]" if depends else ""
            print(f"\n    ▸ {step.get('name','')}{dep_note}")
            print(f"      {rendered['method']}  {rendered['url']}")
            if rendered["params"]:
                print(f"      params  : {json.dumps(rendered['params'], ensure_ascii=False)}")
            if rendered["body"]:
                body_str = json.dumps(rendered["body"], ensure_ascii=False, indent=8)
                print(f"      body    :\n{body_str}")
            if rendered["missing"]:
                print(f"      ⚠ missing placeholders: {rendered['missing']}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    modes = ["template", "pool", "ollama"] if args.mode == "all" else [args.mode]
    num_agents    = args.agents
    num_iters     = args.iterations
    suite_path    = Path(args.suite)
    wf_filter     = [w.strip() for w in args.workflows.split(",") if w.strip()]
    run_timestamp = int(time.time())

    print(f"\n{DIVIDER}")
    print(f"  AGENT SIMULATION — DRY RUN (no real HTTP calls)")
    print(DIVIDER)
    print(f"  Modes       : {', '.join(modes)}")
    print(f"  Agents      : {num_agents}   Iterations: {num_iters}")
    print(f"  Suite       : {suite_path}")
    print(f"  Ollama model: {os.environ['OLLAMA_MODEL']}")
    print(f"  Timestamp   : {run_timestamp}")

    # Load suite
    print(f"\n  Loading suite...", end=" ")
    try:
        suite = load_suite(suite_path)
    except Exception as err:
        print(f"\n  ERROR loading suite: {err}")
        sys.exit(1)
    suite_ctx = dict(suite.get("context", {}))
    run_cfg   = suite.get("run", {})
    virtual_users = run_cfg.get("virtual_users", num_agents)
    print(f"OK — {len(suite.get('workflows', []))} workflows loaded")

    # Load catalogs from CSV
    print(f"  Loading catalogs...", end=" ")
    companies_tuple, specs_tuple = load_exported_catalogs()
    companies = list(companies_tuple)
    specs     = list(specs_tuple)
    print(f"OK — {len(companies)} companies, {len(specs)} specializations")

    # ── Print action plan once ─────────────────────────────────────────────
    print(f"\n{SECTION}")
    print_action_plan()

    # ── Per-mode simulation ────────────────────────────────────────────────
    for mode in modes:
        print(f"\n{DIVIDER}")
        print(f"  IDENTITY MODE: {mode.upper()}")
        print(DIVIDER)

        for user_idx in range(1, num_agents + 1):
            for iter_idx in range(1, num_iters + 1):
                seed  = agent_seed(run_timestamp, user_idx, iter_idx)
                rng   = random.Random(seed)

                print(f"\n  Agent {user_idx} / Iteration {iter_idx}  (seed={seed})")
                print(f"  {SECTION[:66]}")

                # Build base + enrich
                ctx = build_base_context(suite_ctx, run_timestamp, user_idx, iter_idx)
                t_start = time.perf_counter()
                try:
                    ctx, timing = enrich_with_identity_and_catalog(
                        ctx, rng, mode,
                        run_timestamp, user_idx, iter_idx,
                        companies, specs, virtual_users,
                    )
                    total_ms = (time.perf_counter() - t_start) * 1000
                    timing_str = " | ".join(f"{k}={v}" for k, v in timing.items())
                    print(f"  Generation: {timing_str} | total={total_ms:.0f}ms\n")
                    print_context_block(ctx)
                except Exception as err:
                    print(f"  ERROR generating context: {err}")
                    import traceback; traceback.print_exc()
                    continue

                # Step rendering
                if not args.no_steps:
                    print_step_rendering(suite, ctx, wf_filter)

    print(f"\n{DIVIDER}")
    print(f"  Simulation complete.")
    print(DIVIDER)


if __name__ == "__main__":
    main()
