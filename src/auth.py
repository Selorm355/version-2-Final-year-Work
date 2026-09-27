import streamlit as st
import hashlib
import json
import os

USERS_FILE = "users.json"

def hash_password(password: str) -> str:
    """Hashes a plain-text password using SHA-256."""
    return hashlib.sha256(password.strip().encode()).hexdigest()

def load_users() -> dict:
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def verify_credentials(username: str, password: str) -> tuple[bool, str]:
    users = load_users()
    uname = username.strip().lower()
    
    if uname in users:
        stored_hash = users[uname].get("password_hash")
        if stored_hash == hash_password(password):
            return True, users[uname].get("name", uname)
    return False, ""

def require_auth():
    """Guards a page. Renders login if unauthenticated and stops execution."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
        st.session_state.username = None
        st.session_state.user_display_name = None

    if st.session_state.authenticated:
        with st.sidebar:
            st.caption(f"👤 Logged in as **{st.session_state.user_display_name}**")
            if st.button("Log Out", key="logout_btn", type="secondary"):
                st.session_state.clear()
                st.rerun()
        return True

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("## 🔐 OmniPulse Login")
        st.caption("Enter your credentials to access the analytics workspace.")
        
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Sign In", type="primary", use_container_width=True)
            
            if submit:
                if not username or not password:
                    st.error("Please enter both username and password.")
                else:
                    is_valid, display_name = verify_credentials(username, password)
                    if is_valid:
                        st.session_state.authenticated = True
                        st.session_state.username = username.strip().lower()
                        st.session_state.user_display_name = display_name
                        st.rerun()
                    else:
                        st.error("Invalid username or password.")
                        
    st.stop()