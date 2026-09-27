import streamlit as st
import pandas as pd
import os
import plotly.express as px
from dotenv import load_dotenv
from groq import Groq

# --- Modular Backend Imports ---
from src.ingestion import save_raw_upload
from src.cleaning import clean_dataset_with_duckdb, profile_dataframe, get_paginated_data
from src.formulas import generate_virtual_metric, validate_formula
from src.auth import require_auth

# --- Configuration & Auth ---
load_dotenv()
api_key = os.getenv("GROQ_API_KEY")

st.set_page_config(page_title="Analytics Engine", layout="wide")

# STOP EXECUTION IF NOT LOGGED IN
require_auth()

if not api_key:
    st.error("Groq API key not found. Please add it to your .env file.")
    st.stop()

client = Groq(api_key=api_key)

TEMP_DIR = "temp_data"
os.makedirs(TEMP_DIR, exist_ok=True)

@st.cache_data
def load_parquet_data(file_path):
    return pd.read_parquet(file_path)

# --- Session State Management ---
if 'dataset_path' not in st.session_state:
    st.session_state.dataset_path = None
if 'data_profile' not in st.session_state:
    st.session_state.data_profile = None
if 'page_offset' not in st.session_state:
    st.session_state.page_offset = 0
if 'custom_metrics' not in st.session_state:
    st.session_state.custom_metrics = {}

# --- Sidebar Controls ---
with st.sidebar:
    st.header("Workspace Controls")
    if st.session_state.dataset_path:
        if st.button("Reset Session & Clear Data", type="primary"):
            if os.path.exists(st.session_state.dataset_path):
                os.remove(st.session_state.dataset_path)
            # Retain authentication state when clearing data
            auth_status = st.session_state.authenticated
            username = st.session_state.username
            display_name = st.session_state.user_display_name
            
            st.session_state.clear()
            
            st.session_state.authenticated = auth_status
            st.session_state.username = username
            st.session_state.user_display_name = display_name
            
            load_parquet_data.clear()
            st.rerun()

st.title("Data Engine")

# --- Step 1: Upload & Clean ---
if st.session_state.dataset_path is None:
    uploaded_file = st.file_uploader("Upload CSV or Excel", type=['csv', 'xlsx'])
    
    if uploaded_file is not None:
        with st.spinner("Ingesting and standardizing data out-of-core..."):
            raw_path, file_id = save_raw_upload(uploaded_file, TEMP_DIR)
            clean_path = os.path.join(TEMP_DIR, f"clean_{file_id}.parquet")
            clean_dataset_with_duckdb(raw_path, clean_path)
            
            clean_df = pd.read_parquet(clean_path)
            clean_df, profile = profile_dataframe(clean_df)
            clean_df.to_parquet(clean_path, index=False)
            
            st.session_state.dataset_path = clean_path
            st.session_state.data_profile = profile
            st.session_state.page_offset = 0
            st.session_state.custom_metrics = {}
            
            if os.path.exists(raw_path):
                os.remove(raw_path)
                
            st.rerun()

# --- Post-Upload UI ---
if st.session_state.dataset_path and st.session_state.data_profile:
    profile = st.session_state.data_profile
    
    st.success("File processed, cleaned, and cached.")
    
    st.header("Dataset Preview")
    
    col_prev, col_page, col_next = st.columns([1, 8, 1])
    with col_prev:
        if st.button("⬅️ Previous") and st.session_state.page_offset >= 100:
            st.session_state.page_offset -= 100
            st.rerun()
    with col_page:
        st.write(f"Showing rows {st.session_state.page_offset} to {st.session_state.page_offset + 100}")
    with col_next:
        if st.button("Next ➡️"):
            st.session_state.page_offset += 100
            st.rerun()
            
    preview_df = get_paginated_data(st.session_state.dataset_path, limit=100, offset=st.session_state.page_offset)
    st.dataframe(preview_df, use_container_width=True)
    
    st.divider()

    st.header("1. Shape Data")
    
    with st.expander("➕ Define Custom Metric with AI", expanded=True):
        st.info("💡 Describe how to calculate your metric in plain English. For example: 'Net Profit is Cash In Hand minus Tax'.")
        
        user_metric_desc = st.text_area("Metric Description", placeholder="e.g., Calculate RevPAR by dividing Total Revenue by Available Rooms")
        
        if st.button("Generate Metric", type="primary"):
            if user_metric_desc:
                with st.spinner("Translating logic and verifying against database schema..."):
                    metric_payload = generate_virtual_metric(client, user_metric_desc, profile)
                    
                    if metric_payload.get("error"):
                        st.error(f"Could not build metric: {metric_payload['error']}")
                    else:
                        metric_name = metric_payload.get("name", "Custom Metric")
                        sql_formula = metric_payload.get("formula")
                        
                        is_valid, validation_err = validate_formula(st.session_state.dataset_path, sql_formula)
                        
                        if is_valid:
                            st.session_state.custom_metrics[metric_name] = sql_formula
                            st.success(f"Successfully added virtual metric: '{metric_name}'!")
                        else:
                            st.error(f"Validation failed. The formula attempted an incompatible operation. Details: {validation_err}")
            else:
                st.warning("Please describe the metric first.")
        
        if st.session_state.custom_metrics:
            st.markdown("### Active Virtual Metrics")
            for m_name, m_sql in st.session_state.custom_metrics.items():
                st.code(f"{m_name}: {m_sql}", language="sql")