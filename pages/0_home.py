import html

import streamlit as st

from src.auth import require_auth

st.set_page_config(page_title="OmniPulse Analytics", layout="wide")
require_auth()

st.markdown(
    """
    <style>
    [data-testid="stMain"] .block-container {
        max-width: 1120px;
        min-height: calc(100vh - 2rem);
        padding-top: 2rem;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .home-eyebrow { color: #006666; font-size: .9rem; font-weight: 700; text-align: center; }
    .st-key-home_content { margin-top: clamp(1.5rem, 5vh, 3.5rem); }
    .home-title { color: #2F4F4F; font-size: 3rem; font-weight: 800; line-height: 1.1; margin: 1rem 0; text-align: center; }
    .home-copy { color: #2F4F4F; font-size: 1.1rem; line-height: 1.6; max-width: 680px; margin: 0 auto; text-align: center; }
    .st-key-home_actions { width: 100%; margin-top: 2rem; }
    .st-key-home_actions [data-testid="stHorizontalBlock"] { justify-content: center; }
    .home-section { border-top: 1px solid #E0E0E0; margin: 3rem auto 0; padding-top: 1.5rem; text-align: center; width: min(100%, 760px); }
    @media (max-width: 700px) {
        [data-testid="stMain"] .block-container { min-height: calc(100vh - 1rem); padding-top: 1rem; }
        .home-title { font-size: 2.3rem; }
        .st-key-home_actions [data-testid="stHorizontalBlock"] { gap: .5rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

company_name = html.escape(
    st.session_state.get("company_name")
    or st.session_state.get("user_display_name", "your company")
)
industry = st.session_state.get("industry_type")
industry_label = industry.title() if industry else "Business"

with st.container(key="home_content"):
    st.markdown('<div class="home-eyebrow">OMNIPULSE ANALYTICS WORKSPACE</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="home-title">Welcome, {company_name}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="home-copy">Your {industry_label.lower()} analytics workspace is ready. '
        "Upload a dataset to explore its contents, review key insights, or continue an analysis in chat.</div>",
        unsafe_allow_html=True,
    )

    with st.container(key="home_actions"):
        _, upload_column, chatbot_column, _ = st.columns([1.2, 2, 2.4, 1.2])
        with upload_column:
            if st.button("Upload a dataset", type="primary", use_container_width=True, key="home_upload"):
                st.switch_page("app.py")
        with chatbot_column:
            if st.button("Open Insight Chatbot", use_container_width=True, key="home_chat"):
                st.switch_page("pages/1_chat.py")

    st.markdown('<div class="home-section"></div>', unsafe_allow_html=True)
    st.caption("Workspace tools are available from the sidebar at any time.")
