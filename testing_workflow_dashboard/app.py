from __future__ import annotations

import traceback
from pathlib import Path

import streamlit as st

from testing_workflow_ollama_agentic.runner import run

from .config import (
    DEFAULT_REPORT_FILE,
    DEFAULT_TESTS_FILE,
    FUNCTIONAL_GOAL_OPTIONS,
    load_suite_defaults,
    selected_goals_to_env,
)
from .environment import apply_env, restore_env
from .reports import load_json_file
from .styles import inject_styles
from .views import (
    render_agent_gallery,
    render_failures,
    render_hero,
    render_report_explorer,
    render_summary,
    render_topline_charts,
)


def _render_sidebar() -> str:
    with st.sidebar:
        st.markdown("## Simulation Console")
        st.caption("Configure the doctor-agent run, then launch the monitoring session.")
        tests_file = st.text_input("Tests file", value=DEFAULT_TESTS_FILE)
        report_file = st.text_input("Report file", value=DEFAULT_REPORT_FILE)
        suite_defaults = load_suite_defaults(tests_file)
        virtual_users = st.number_input("Total agents", min_value=1, value=suite_defaults.virtual_users, step=1)
        max_workers = st.number_input("Parallel agents", min_value=1, value=max(1, suite_defaults.max_workers), step=1)
        iterations_per_user = st.number_input(
            "Iterations per agent",
            min_value=1,
            value=suite_defaults.iterations_per_user,
            step=1,
        )
        default_timeout = st.number_input("Default timeout (seconds)", min_value=1.0, value=15.0, step=1.0)
        max_actions = st.number_input("Max actions per agent", min_value=1, value=50, step=1)
        signup_failure_limit = st.number_input("Signup failure limit", min_value=1, value=2, step=1)
        auth_reset_limit = st.number_input("Auth reset limit", min_value=1, value=2, step=1)
        identity_mode = st.selectbox("Identity mode", options=["ollama", "pool", "template"], index=0)
        use_ollama_planner = st.checkbox("Use Ollama planner", value=True)
        generate_posts = st.checkbox("Generate posts with Ollama", value=True)
        generate_images = st.checkbox("Generate images", value=False)
        st.divider()
        functional_goals = st.multiselect(
            "Functional Goals",
            options=FUNCTIONAL_GOAL_OPTIONS,
            default=FUNCTIONAL_GOAL_OPTIONS,
            help="Choose which parts of the platform the agents should interact with.",
        )
        st.divider()
        if st.button("Launch Agentic Run", use_container_width=True, type="primary"):
            overrides = {
                "AGENTIC_API_TESTS_FILE": tests_file,
                "AGENTIC_API_REPORT_FILE": report_file,
                "AGENTIC_VIRTUAL_USERS": str(virtual_users),
                "AGENTIC_MAX_WORKERS": str(min(max_workers, virtual_users)),
                "AGENTIC_ITERATIONS_PER_USER": str(iterations_per_user),
                "DEFAULT_TIMEOUT_SECONDS": str(default_timeout),
                "AGENTIC_MAX_ACTIONS": str(max_actions),
                "AGENTIC_SIGNUP_FAILURE_LIMIT": str(signup_failure_limit),
                "AGENTIC_AUTH_RESET_LIMIT": str(auth_reset_limit),
                "DOCTOR_IDENTITY_MODE": identity_mode,
                "AGENTIC_USE_OLLAMA_PLANNER": str(use_ollama_planner).lower(),
                "OLLAMA_GENERATE_POSTS": str(generate_posts).lower(),
                "GENERATE_IMAGES": str(generate_images).lower(),
                "AGENTIC_PROGRESS_LOGGING": "true",
                "AGENTIC_PARTIAL_REPORTING": "true",
                "AGENTIC_FUNCTIONAL_GOALS": selected_goals_to_env(functional_goals),
            }
            previous = apply_env(overrides)
            try:
                with st.spinner("Running agentic simulation..."):
                    run()
                st.success("Run completed.")
            except Exception as err:
                st.error(f"Run failed: {err}")
                st.code(traceback.format_exc(), language="python")
            finally:
                restore_env(previous)
        if st.button("Refresh Dashboard", use_container_width=True):
            st.rerun()
    return report_file


def main() -> None:
    st.set_page_config(page_title="Agentic API Simulation", page_icon="A", layout="wide")
    inject_styles()
    report_file = _render_sidebar()

    report_path = Path(report_file)
    report = load_json_file(report_path)

    render_hero(report_path, report)

    if report is None:
        st.info("No report found yet. Launch a run from the sidebar to populate the dashboard.")
        return

    render_summary(report)
    render_topline_charts(report)
    detail_cols = st.columns([1.05, 1.2])
    with detail_cols[0]:
        render_failures(report)
    with detail_cols[1]:
        render_agent_gallery(report)
    render_report_explorer(report, report_path)
