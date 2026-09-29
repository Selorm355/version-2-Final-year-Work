import streamlit as st
import hashlib
import hmac
import json
import os
import re
import secrets

USERS_FILE = "users.json"

def hash_password(password: str) -> str:
    """Hash passwords with PBKDF2 and a per-password random salt."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        bytes.fromhex(salt),
        260_000,
    ).hex()
    return f"pbkdf2_sha256${salt}${digest}"

def load_users() -> dict:
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_users(users: dict) -> None:
    with open(USERS_FILE, "w") as users_file:
        json.dump(users, users_file, indent=2)


def register_account(company_name: str, email: str, password: str, industry_type: str):
    company_name = company_name.strip()
    email = email.strip().lower()
    allowed_industries = {"retail", "hospitality", "healthcare"}

    if not company_name:
        return False, "Enter a company name."
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return False, "Enter a valid email address."
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    if industry_type.lower() not in allowed_industries:
        return False, "Choose Retail, Hospitality, or Healthcare."

    users = load_users()
    if email in users:
        return False, "An account with this email already exists."

    users[email] = {
        "name": company_name,
        "company_name": company_name,
        "email": email,
        "industry_type": industry_type.lower(),
        "password_hash": hash_password(password),
    }
    save_users(users)
    return True, email


def _password_matches(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _, salt, expected = stored_hash.split("$", 2)
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), bytes.fromhex(salt), 260_000
            ).hex()
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False

    legacy_hash = hashlib.sha256(password.strip().encode()).hexdigest()
    return hmac.compare_digest(legacy_hash, stored_hash or "")

def verify_credentials(username: str, password: str) -> tuple[bool, str]:
    users = load_users()
    uname = username.strip().lower()
    
    if uname in users:
        stored_hash = users[uname].get("password_hash")
        if _password_matches(password, stored_hash):
            if not stored_hash.startswith("pbkdf2_sha256$"):
                users[uname]["password_hash"] = hash_password(password)
                save_users(users)
            return True, users[uname].get("name", uname)
    return False, ""


def _reset_workspace():
    dataset_path = st.session_state.get("dataset_path")
    if dataset_path and os.path.exists(dataset_path):
        os.remove(dataset_path)

    retained_state = {
        key: st.session_state.get(key)
        for key in (
            "authenticated",
            "username",
            "user_display_name",
            "company_name",
            "email",
            "industry_type",
        )
    }
    st.session_state.clear()
    for key, value in retained_state.items():
        st.session_state[key] = value
    st.cache_data.clear()
    st.rerun()


def _show_auth_styles():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
        .stApp {
            background:
                radial-gradient(ellipse at 12% 8%, rgba(0, 128, 128, .12), transparent 34%),
                radial-gradient(ellipse at 88% 88%, rgba(224, 224, 224, .7), transparent 32%),
                #F0F8FF;
            color: #2F4F4F;
            font-family: 'DM Sans', sans-serif;
        }
        [data-testid="stSidebar"] { display: none; }
        [data-testid="stHeader"] { background: transparent; }
        .block-container { max-width: 1120px; padding-top: 2.5rem; padding-bottom: 2.5rem; }
        .auth-brand {
            display: inline-block;
            align-self: center;
            padding: .65rem 1.1rem;
            border: 1px solid #008080;
            border-radius: 8px;
            background: rgba(240, 248, 255, .88);
            color: #006666;
            font-weight: 700;
            font-size: 1rem;
            box-shadow: 0 3px 12px rgba(0, 128, 128, .18), 0 0 18px rgba(0, 128, 128, .14);
        }
        .st-key-landing_center {
            box-sizing: border-box;
            min-height: calc(100vh - 5rem);
            display: flex;
            flex-direction: column;
            justify-content: center;
            padding: clamp(2rem, 6vh, 4rem) 0;
            text-align: center;
        }
        .st-key-landing_center [data-testid="stMarkdownContainer"] { text-align: center; }
        .st-key-landing_center .auth-brand,
        .st-key-landing_center .auth-hero-title,
        .st-key-landing_center .auth-copy,
        .st-key-landing_center .auth-band { text-align: center; }
        .st-key-landing_center .auth-copy { margin-left: auto; margin-right: auto; }
        .st-key-landing_center .auth-tags { justify-content: center; }
        .st-key-landing_center .auth-band { text-align: center; }
        .st-key-landing_center .st-key-landing_actions { margin-top: clamp(1.5rem, 3vh, 2.25rem); }
        .st-key-landing_center .st-key-landing_actions [data-testid="stHorizontalBlock"] { justify-content: center; }
        .auth-hero-title {
            color: #2F4F4F; font: 800 5rem/1.02 'Manrope', sans-serif;
            letter-spacing: -.045em; margin: 1.2rem 0 1rem;
        }
        .auth-hero-title span { color: #008080; }
        .auth-copy { color: #2F4F4F; font-size: 1.1rem; line-height: 1.7; max-width: 650px; }
        .auth-tags { display: flex; flex-wrap: wrap; gap: .6rem; margin: 1.6rem 0 2rem; }
        .auth-tag {
            border: 1px solid #E0E0E0; background: rgba(240,248,255,.9);
            color: #006666; border-radius: 999px; padding: .48rem .8rem;
            font-size: .86rem; font-weight: 600;
        }
        .auth-band {
            border-top: 1px solid #E0E0E0; margin: clamp(2rem, 4vh, 3rem) auto 0; padding-top: 1.2rem;
            max-width: 760px; width: 100%;
            color: #2F4F4F; font-size: .85rem;
        }
        .auth-panel-title { font: 800 2.1rem/1.15 'Manrope', sans-serif; color: #2F4F4F; text-align: center; }
        .auth-panel-copy { color: #2F4F4F; margin: .4rem 0 1.2rem; text-align: center; }
        div[data-testid="stForm"] {
            background: rgba(240,248,255,.96); border: 1px solid #E0E0E0;
            border-radius: 12px; padding: 1.25rem 1.3rem;
            box-shadow: 0 18px 50px rgba(47, 79, 79, .08);
        }
        .auth-link-row a.auth-inline-link,
        .auth-link-row a.auth-inline-link:visited { color: #008080 !important; font-weight: 700; text-decoration: none; }
        .auth-link-row a.auth-inline-link:hover { color: #006666 !important; text-decoration: underline; }
        .auth-link-row { color: #2F4F4F; margin-top: 1rem; text-align: center; }
        div.stButton > button, div[data-testid="stFormSubmitButton"] > button {
            border-radius: 7px; min-height: 2.8rem; font-weight: 700;
            border-color: #008080;
        }
        div[data-testid="stFormSubmitButton"] > button[kind="primary"],
        div.stButton > button[kind="primary"] { background: #008080; color: #F0F8FF; }
        div[data-testid="stFormSubmitButton"] > button[kind="primary"]:hover,
        div.stButton > button[kind="primary"]:hover { background: #006666; border-color: #006666; }
        @media (max-width: 700px) {
            .block-container { padding-top: 1.25rem; padding-bottom: 1.25rem; }
            .st-key-landing_center { min-height: calc(100vh - 2.5rem); padding: 2rem 0; }
            .auth-hero-title { font-size: 3rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _show_landing_page():
    _show_auth_styles()
    with st.container(key="landing_center"):
        st.markdown('<div class="auth-brand">OMNIPULSE &nbsp; / &nbsp; ANALYTICS WORKSPACE</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="auth-hero-title">Your data.<br><span>Your next move.</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="auth-copy">Bring your business data into one clear workspace. '
            'Clean it, explore it, and ask better questions with AI-powered analytics.</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="auth-tags">'
            '<span class="auth-tag">Retail</span><span class="auth-tag">Hospitality</span>'
            '<span class="auth-tag">Healthcare</span><span class="auth-tag">Automated cleaning</span>'
            '<span class="auth-tag">AI data assistant</span></div>',
            unsafe_allow_html=True,
        )

        with st.container(key="landing_actions"):
            _, login_column, signup_column, _ = st.columns([2.5, 1.6, 1.9, 2.5])
            with login_column:
                if st.button("Log In", type="primary", use_container_width=True, key="landing_login"):
                    st.session_state.auth_screen = "login"
                    st.rerun()
            with signup_column:
                if st.button("Create an Account", use_container_width=True, key="landing_signup"):
                    st.session_state.auth_screen = "register"
                    st.rerun()

        st.markdown(
            '<div class="auth-band">A practical analytics workspace for teams turning everyday '
            'business data into confident decisions.</div>',
            unsafe_allow_html=True,
        )


def _show_login_page():
    _show_auth_styles()
    back_column, _ = st.columns([1, 7])
    with back_column:
        if st.button("← Home", key="login_home"):
            st.session_state.auth_screen = "landing"
            st.rerun()

    left, center, right = st.columns([1.4, 3.2, 1.4])
    with center:
        st.markdown('<div class="auth-panel-title">Welcome back</div>', unsafe_allow_html=True)
        st.markdown('<div class="auth-panel-copy">Sign in to your company workspace.</div>', unsafe_allow_html=True)
        with st.form("login_form"):
            username = st.text_input("Email address", placeholder="name@company.com")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            submit = st.form_submit_button("Log In", type="primary", use_container_width=True)

            if submit:
                if not username or not password:
                    st.error("Please enter both email and password.")
                else:
                    normalized_email = username.strip().lower()
                    is_valid, display_name = verify_credentials(normalized_email, password)
                    if is_valid:
                        account = load_users().get(normalized_email, {})
                        st.session_state.authenticated = True
                        st.session_state.username = normalized_email
                        st.session_state.user_display_name = display_name
                        st.session_state.company_name = account.get("company_name", display_name)
                        st.session_state.email = account.get("email", normalized_email)
                        st.session_state.industry_type = account.get("industry_type")
                        st.switch_page("app.py")
                    else:
                        st.error("Invalid email or password.")
        st.markdown(
            '<div class="auth-link-row">New to OmniPulse? '
            '<a class="auth-inline-link" href="?action=register" target="_self">Create account</a></div>',
            unsafe_allow_html=True,
        )


def _show_registration_page():
    _show_auth_styles()
    back_column, _ = st.columns([1, 7])
    with back_column:
        if st.button("← Home", key="register_home"):
            st.session_state.auth_screen = "landing"
            st.rerun()

    left, center, right = st.columns([1.4, 3.2, 1.4])
    with center:
        st.markdown('<div class="auth-panel-title">Create your workspace</div>', unsafe_allow_html=True)
        st.markdown('<div class="auth-panel-copy">Register your company to get started.</div>', unsafe_allow_html=True)
        with st.form("registration_form"):
            company_name = st.text_input("Company name", placeholder="Your registered business name")
            email = st.text_input("Email address", placeholder="name@company.com")
            industry_type = st.selectbox("Industry type", ["Retail", "Hospitality", "Healthcare"])
            password = st.text_input("Password", type="password", help="Use at least 8 characters.")
            confirm_password = st.text_input("Confirm password", type="password")
            create_account = st.form_submit_button(
                "Create Account", type="primary", use_container_width=True
            )

            if create_account:
                if password != confirm_password:
                    st.error("The passwords do not match.")
                else:
                    created, result = register_account(
                        company_name, email, password, industry_type
                    )
                    if created:
                        account = load_users()[result]
                        st.session_state.authenticated = True
                        st.session_state.username = result
                        st.session_state.user_display_name = account["company_name"]
                        st.session_state.company_name = account["company_name"]
                        st.session_state.email = result
                        st.session_state.industry_type = account["industry_type"]
                        st.switch_page("app.py")
                    else:
                        st.error(result)
        st.markdown(
            '<div class="auth-link-row">Already have an account? '
            '<a class="auth-inline-link" href="?action=login" target="_self">Log in</a></div>',
            unsafe_allow_html=True,
        )


def require_auth():
    """Guards a page. Renders login if unauthenticated and stops execution."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
        st.session_state.username = None
        st.session_state.user_display_name = None

    if st.session_state.authenticated:
        with st.sidebar:
            st.markdown(
                "<style>[data-testid='stSidebarNav'] { display: none; }</style>",
                unsafe_allow_html=True,
            )
            st.caption(f"👤 Logged in as **{st.session_state.user_display_name}**")
            st.markdown("#### Workspace")
            st.page_link("pages/0_home.py", label="Home", icon=":material/home:")
            st.page_link("app.py", label="Data Engine", icon=":material/table_view:")
            st.page_link("pages/1_chat.py", label="Insight Chatbot", icon=":material/chat:")
            st.divider()
            if st.button("Reset Session & Clear Data", key="reset_workspace_btn", type="primary"):
                _reset_workspace()
            if st.button("Log Out", key="logout_btn", type="secondary"):
                st.session_state.clear()
                st.rerun()
        return True

    _show_auth_styles()
    if "auth_screen" not in st.session_state:
        st.session_state.auth_screen = "landing"

    action = st.query_params.get("action") or st.query_params.get("auth")
    if isinstance(action, list):
        action = action[0] if action else None
    if action in {"login", "register"}:
        st.query_params.clear()
        st.session_state.auth_screen = action
        st.rerun()

    auth_screen = st.session_state.get("auth_screen", "landing")
    if auth_screen == "login":
        _show_login_page()
    elif auth_screen == "register":
        _show_registration_page()
    else:
        _show_landing_page()

    st.stop()