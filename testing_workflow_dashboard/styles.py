from __future__ import annotations

import streamlit as st


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:wght@500;700&family=Manrope:wght@400;500;600;700&display=swap');

        :root {
            --bg: #f4efe7;
            --panel: rgba(255, 251, 247, 0.82);
            --panel-strong: rgba(255, 248, 241, 0.94);
            --ink: #1f1a17;
            --muted: #71665f;
            --gold: #b7863d;
            --forest: #23453f;
            --rose: #8f4956;
            --line: rgba(31, 26, 23, 0.08);
            --shadow: 0 22px 60px rgba(71, 53, 36, 0.14);
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(183, 134, 61, 0.18), transparent 32%),
                radial-gradient(circle at top right, rgba(35, 69, 63, 0.16), transparent 28%),
                linear-gradient(180deg, #fbf7f2 0%, var(--bg) 60%, #efe7dc 100%);
            color: var(--ink);
            font-family: 'Manrope', sans-serif;
        }

        .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
        }

        h1, h2, h3 {
            font-family: 'Fraunces', serif;
            letter-spacing: -0.02em;
            color: var(--ink);
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #1e2f2e 0%, #182523 100%);
            border-right: 1px solid rgba(255, 255, 255, 0.08);
        }

        [data-testid="stSidebar"] * {
            color: #f7f2ea;
        }

        .hero-shell, .glass-card, .metric-card, .agent-card, .failure-banner {
            border: 1px solid var(--line);
            box-shadow: var(--shadow);
        }

        .hero-shell {
            position: relative;
            overflow: hidden;
            padding: 2rem 2rem 1.6rem 2rem;
            border-radius: 28px;
            background: linear-gradient(135deg, rgba(255, 247, 238, 0.96), rgba(242, 231, 214, 0.92));
            margin-bottom: 1.25rem;
        }

        .eyebrow {
            text-transform: uppercase;
            font-size: 0.72rem;
            letter-spacing: 0.16em;
            color: var(--gold);
            font-weight: 700;
            margin-bottom: 0.6rem;
        }

        .hero-title {
            font-family: 'Fraunces', serif;
            font-size: 3rem;
            line-height: 1;
            margin: 0;
            max-width: 12ch;
        }

        .hero-copy {
            margin-top: 0.9rem;
            max-width: 65ch;
            color: var(--muted);
            font-size: 1rem;
            line-height: 1.7;
        }

        .glass-card {
            background: var(--panel);
            border-radius: 24px;
            padding: 1.1rem 1.2rem;
            backdrop-filter: blur(18px);
        }

        .metric-card {
            background: var(--panel-strong);
            border-radius: 24px;
            padding: 1rem 1.1rem;
            min-height: 132px;
        }

        .metric-label {
            color: var(--muted);
            text-transform: uppercase;
            font-size: 0.72rem;
            letter-spacing: 0.12em;
            font-weight: 700;
            margin-bottom: 0.8rem;
        }

        .metric-value {
            font-family: 'Fraunces', serif;
            font-size: 2.15rem;
            line-height: 1;
            margin-bottom: 0.45rem;
        }

        .metric-foot {
            color: var(--muted);
            font-size: 0.92rem;
        }

        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            background: rgba(35, 69, 63, 0.09);
            border: 1px solid rgba(35, 69, 63, 0.14);
            border-radius: 999px;
            padding: 0.55rem 0.95rem;
            color: #24463f;
            font-weight: 700;
            font-size: 0.88rem;
        }

        .status-pill.warning {
            background: rgba(183, 134, 61, 0.10);
            border-color: rgba(183, 134, 61, 0.18);
            color: #8d6728;
        }

        .section-title {
            font-family: 'Fraunces', serif;
            font-size: 1.45rem;
            margin-bottom: 0.2rem;
        }

        .section-copy {
            color: var(--muted);
            margin-bottom: 1rem;
        }

        .agent-card {
            background: linear-gradient(180deg, rgba(255, 251, 246, 0.98), rgba(247, 241, 233, 0.96));
            border-radius: 22px;
            padding: 1rem 1rem 0.9rem 1rem;
            margin-bottom: 0.85rem;
        }

        .agent-title {
            font-family: 'Fraunces', serif;
            font-size: 1.2rem;
            margin-bottom: 0.3rem;
        }

        .agent-copy {
            color: var(--muted);
            font-size: 0.92rem;
            margin-bottom: 0.75rem;
        }

        .tag-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.45rem;
            margin-top: 0.55rem;
        }

        .tag {
            padding: 0.3rem 0.65rem;
            border-radius: 999px;
            background: rgba(183, 134, 61, 0.12);
            color: #6b501d;
            font-size: 0.8rem;
            font-weight: 700;
        }

        .failure-banner {
            background: linear-gradient(135deg, rgba(143, 73, 86, 0.10), rgba(255, 246, 248, 0.96));
            border-radius: 22px;
            padding: 1rem 1.1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

