from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


def _html(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def _status_markup(report: dict[str, Any]) -> str:
    status = str(report.get("status", "completed")).strip().lower()
    label = _html(status.replace("_", " ").title())
    css_class = "status-pill"
    if status != "completed":
        css_class += " warning"
    return f'<div class="{css_class}">Run Status: {label}</div>'


def render_hero(report_path: Path, report: dict[str, Any] | None) -> None:
    run_id = "Awaiting Run"
    subcopy = "Launch a premium monitoring view for doctor-agent API sessions and inspect how each agent moves through the platform."
    status_markup = '<div class="status-pill warning">No report loaded</div>'
    if report:
        run_id = _html(report.get("run_id", "Unknown Run"))
        summary = report.get("summary", {})
        subcopy = (
            f"Latest run processed {int(summary.get('total_steps', 0))} actions across "
            f"{int(summary.get('unique_agents', 0))} doctor agents. "
            "Use this dashboard to monitor flow quality, throughput, and agent-by-agent behavior."
        )
        status_markup = _status_markup(report)
    st.markdown(
        f"""
        <section class="hero-shell">
            <div class="eyebrow">Agentic Monitoring Suite</div>
            <h1 class="hero-title">Doctor Agent Control Room</h1>
            <p class="hero-copy">{subcopy}</p>
            <div style="display:flex; gap:0.75rem; flex-wrap:wrap; margin-top:1rem;">
                {status_markup}
                <div class="status-pill">Run ID: {run_id}</div>
                <div class="status-pill">Report: {_html(report_path.name)}</div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _metric_card(label: str, value: str, foot: str) -> str:
    return (
        '<div class="metric-card">'
        f'<div class="metric-label">{label}</div>'
        f'<div class="metric-value">{value}</div>'
        f'<div class="metric-foot">{foot}</div>'
        "</div>"
    )


def render_summary(report: dict[str, Any]) -> None:
    summary = report.get("summary", {})
    total_steps = int(summary.get("total_steps", 0))
    passed = int(summary.get("passed", 0))
    failed = int(summary.get("failed", 0))
    agents = int(summary.get("unique_agents", 0))
    errors = int(summary.get("errors", 0))
    pass_rate = 0.0 if total_steps == 0 else (passed / total_steps) * 100
    execution_density = 0.0 if agents == 0 else total_steps / agents

    st.markdown('<div class="section-title">Run Summary</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-copy">A quick read on throughput, reliability, and operating scale for the latest simulation.</div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(5)
    cards = [
        ("Actions", str(total_steps), f"{execution_density:.1f} actions per agent"),
        ("Pass Rate", f"{pass_rate:.0f}%", f"{passed} passed / {failed} failed"),
        ("Agents", str(agents), f"{int(summary.get('virtual_users', agents))} requested"),
        ("Failures", str(failed), "Critical run blockers and endpoint mismatches"),
        ("Errors", str(errors), "System-level issues outside step failures"),
    ]
    for col, card in zip(cols, cards):
        with col:
            st.markdown(_metric_card(*card), unsafe_allow_html=True)


def render_topline_charts(report: dict[str, Any]) -> None:
    agents = report.get("agents", [])
    if not agents:
        return
    st.markdown('<div class="section-title">Performance View</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-copy">Compare pass and fail distribution across agents and inspect action density.</div>',
        unsafe_allow_html=True,
    )
    chart_cols = st.columns([1.2, 0.8])
    agent_frame = pd.DataFrame(
        [
            {
                "Agent": agent.get("agent_id"),
                "Passed": int(agent.get("passed_steps", 0)),
                "Failed": int(agent.get("failed_steps", 0)),
                "Executed": int(agent.get("executed_actions", 0)),
            }
            for agent in agents
        ]
    )
    with chart_cols[0]:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.bar_chart(agent_frame.set_index("Agent")[["Passed", "Failed"]], use_container_width=True, height=280)
        st.markdown("</div>", unsafe_allow_html=True)
    with chart_cols[1]:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.dataframe(agent_frame, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)


def render_failures(report: dict[str, Any]) -> None:
    results = report.get("results", [])
    failures = [item for item in results if item.get("passed") is False and item.get("skipped") is not True]
    st.markdown('<div class="section-title">Failure Watch</div>', unsafe_allow_html=True)
    if not failures:
        st.success("No failed actions in the current report.")
        return
    st.markdown(
        '<div class="failure-banner">The latest run contains failed actions. Review the table below to trace the exact agent, endpoint, and validation mismatch.</div>',
        unsafe_allow_html=True,
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Agent": item.get("agent_id"),
                    "Step": item.get("step"),
                    "Status": item.get("status_code"),
                    "Response Time (ms)": item.get("response_time_ms"),
                    "Errors": " | ".join(item.get("errors", [])),
                }
                for item in failures
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )


def render_agent_gallery(report: dict[str, Any]) -> None:
    agents = report.get("agents", [])
    st.markdown('<div class="section-title">Agent Gallery</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-copy">Browse each doctor agent as a monitored operating unit, then drill into its action history.</div>',
        unsafe_allow_html=True,
    )
    if not agents:
        st.info("No agent summaries found yet.")
        return

    gallery_cols = st.columns(3)
    for index, agent in enumerate(agents):
        col = gallery_cols[index % 3]
        pending_actions = agent.get("pending_actions", [])
        status_text = "Healthy" if int(agent.get("failed_steps", 0)) == 0 else "Needs Review"
        with col:
            st.markdown(
                f"""
                <div class="agent-card">
                    <div class="agent-title">{_html(agent.get('agent_id', 'Unknown Agent'))}</div>
                    <div class="agent-copy">{_html(agent.get('specialization_name', ''))} at {_html(agent.get('company_name', ''))}</div>
                    <div class="agent-copy">Passed {int(agent.get('passed_steps', 0))} steps, failed {int(agent.get('failed_steps', 0))}, executed {int(agent.get('executed_actions', 0))} actions.</div>
                    <div class="tag-row">
                        <span class="tag">{_html(status_text)}</span>
                        <span class="tag">{_html(agent.get('identity_source', 'unknown'))}</span>
                        <span class="tag">{_html(agent.get('planner_source', 'unknown'))}</span>
                    </div>
                    <div class="tag-row">
                        <span class="tag">Pending {len(pending_actions)}</span>
                        <span class="tag">{_html(agent.get('doctor_session_goal', 'explore_platform'))}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    selected_agent = st.selectbox(
        "Deep dive into an agent",
        options=[agent.get("agent_id", "unknown_agent") for agent in agents],
        index=0,
    )
    agent = next((item for item in agents if item.get("agent_id") == selected_agent), None)
    if not agent:
        return

    detail_cols = st.columns([0.92, 1.08])
    with detail_cols[0]:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown(f"### {agent.get('agent_id', 'Unknown Agent')}")
        st.caption(
            f"{agent.get('specialization_name', '')} | {agent.get('company_name', '')} | "
            f"Goal: {agent.get('doctor_session_goal', '')}"
        )
        st.write("Planned actions:", ", ".join(agent.get("planned_actions", [])) or "None")
        st.write("Pending actions:", ", ".join(agent.get("pending_actions", [])) or "None")
        st.write("Identity source:", agent.get("identity_source", "unknown"))
        st.write("Profile generation source:", agent.get("profile_generation_source", "unknown"))
        st.write("Behavior generation source:", agent.get("behavior_generation_source", "unknown"))
        st.markdown("</div>", unsafe_allow_html=True)
    with detail_cols[1]:
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        history = pd.DataFrame(agent.get("action_history", []))
        if history.empty:
            st.info("No action history available.")
        else:
            st.dataframe(history, use_container_width=True, hide_index=True, height=360)
        st.markdown("</div>", unsafe_allow_html=True)


def render_report_explorer(report: dict[str, Any], report_path: Path) -> None:
    st.markdown('<div class="section-title">Report Explorer</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-copy">Use the detailed tables for audit-style inspection, then open the raw JSON when you need the full payload.</div>',
        unsafe_allow_html=True,
    )
    with st.expander(f"Raw Report JSON - {report_path.name}"):
        st.json(report)
