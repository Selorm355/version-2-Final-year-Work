import streamlit as st
import pandas as pd
import duckdb
import os
import json
import re
import plotly.express as px
from groq import Groq
from dotenv import load_dotenv
from src.auth import require_auth

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")

st.set_page_config(page_title="AI Assistant", page_icon="🤖", layout="wide")

# STOP EXECUTION IF NOT LOGGED IN
require_auth()

st.title("Ask Your Data")

if not api_key:
    st.error("Groq API key not found. Please add it to your .env file.")
    st.stop()

if 'dataset_path' not in st.session_state or not st.session_state.dataset_path:
    st.warning("Please upload and shape a dataset on the main page first.")
    st.stop()

client = Groq(api_key=api_key)
parquet_path = st.session_state.dataset_path.replace("\\", "/")
profile = st.session_state.data_profile

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "chart" in message:
            st.plotly_chart(message["chart"], use_container_width=True)
        if "data" in message:
            st.dataframe(message["data"])

custom_metrics_context = ""
if 'custom_metrics' in st.session_state and st.session_state.custom_metrics:
    custom_metrics_context = "\nCRITICAL: The user has defined the following custom virtual metrics. You MUST use these exact SQL formulas if the user asks for them:\n"
    for name, sql in st.session_state.custom_metrics.items():
        custom_metrics_context += f"- {name}: {sql}\n"

system_prompt = f"""
You are the expert data analyst for OmniPulse Analytics.
The user has a Parquet dataset located at '{parquet_path}'.
Available schema: {profile}
{custom_metrics_context}

Rules:
1. Answer ONLY questions related to this dataset. If unrelated, set "type" to "error".
2. DuckDB SQL Rules:
   - FROM clause MUST be: FROM '{parquet_path}'
   - Wrap column names containing spaces in double quotes.
   - For text matching, always use ILIKE and wrap the search term in wildcards (e.g., ILIKE '%term%').
   - When doing math (+, -) use COALESCE(..., 0.0) to prevent type mismatches.
   - CRITICAL: When doing comparative filtering (>, <, =), DO NOT use COALESCE. Instead, explicitly exclude missing data (e.g., WHERE col1 > col2 AND col1 IS NOT NULL AND col2 IS NOT NULL).
   - Always SELECT the descriptive columns (e.g., Patient_Name, Item_Name) alongside your calculated metrics so the user knows who or what the numbers belong to.
3. Return ONLY a single JSON object.

JSON Schema:
{{
    "sql": "Valid DuckDB SQL string or null if unanswerable.",
    "type": "text | bar | line | pie | table | error",
    "x": "Column/alias for chart x-axis (or null)",
    "y": "Column/alias for chart y-axis (or null)",
    "message": "A professional explanation of the query. IMPORTANT: Do NOT guess the outcome in this message. Keep it neutral (e.g., 'Here is the analysis of losses...' instead of 'Yes, there are losses'). Do not mention SQL errors or retries."
}}
"""

def extract_json(raw_text: str) -> dict:
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return json.loads(raw_text)

def run_query_with_retry(client, initial_sql, prompt, system_prompt):
    con = duckdb.connect()
    try:
        return con.execute(initial_sql).df(), None
    except Exception as first_err:
        con.close()
        
        retry_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "My initial SQL query failed."},
            {"role": "user", "content": f"The query failed with error: {str(first_err)}. Rewrite the SQL to strictly answer my original question. CRITICAL: In your JSON 'message', do NOT mention SQL, errors, type mismatch, or casting. Provide only the professional business insight."}
        ]
        
        try:
            fix_resp = client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=retry_messages,
                response_format={"type": "json_object"},
                temperature=0.0
            )
            fixed_payload = extract_json(fix_resp.choices[0].message.content)
            fixed_sql = fixed_payload.get("sql")
            
            con = duckdb.connect()
            df = con.execute(fixed_sql).df()
            return df, fixed_payload
        except Exception as second_err:
            return None, str(second_err)
    finally:
        try:
            con.close()
        except:
            pass

if prompt := st.chat_input("E.g., What are the items that generated losses?"):
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        with st.spinner("Analyzing data..."):
            try:
                response = client.chat.completions.create(
                    model="openai/gpt-oss-20b",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1
                )
            except Exception as e:
                err_msg = str(e)
                if "Failed to validate JSON" in err_msg or "json_validate_failed" in err_msg:
                    st.error("The AI tried to build a query so complex it broke its own formatting. Try rephrasing, e.g., 'Show me profit by item'.")
                else:
                    st.error(f"Connection Error: {err_msg}")
                st.stop()
                
            try:
                ai_payload = extract_json(response.choices[0].message.content.strip())
                
                sql_query = ai_payload.get("sql")
                viz_type = ai_payload.get("type", "text")
                x_col = ai_payload.get("x")
                y_col = ai_payload.get("y")
                message = ai_payload.get("message", "Here are the insights:")

                new_state_msg = {"role": "assistant", "content": message}

                if viz_type == "error" or not sql_query:
                    st.markdown(message)
                    st.session_state.messages.append(new_state_msg)
                    st.stop()

                result_df, retry_payload = run_query_with_retry(client, sql_query, prompt, system_prompt)
                
                if retry_payload and isinstance(retry_payload, dict):
                    viz_type = retry_payload.get("type", viz_type)
                    x_col = retry_payload.get("x", x_col)
                    y_col = retry_payload.get("y", y_col)
                    message = retry_payload.get("message", message)

                if result_df is None or result_df.empty:
                    message = "I analyzed the dataset based on your request, but there are no records matching your criteria (e.g., this dataset contains no losses)."
                    new_state_msg["content"] = message
                    st.markdown(message)
                    st.info("The SQL query executed successfully, but returned 0 rows.")
                else:
                    st.markdown(message)
                    new_state_msg["content"] = message

                    if viz_type == "text":
                        if len(result_df) == 1 and len(result_df.columns) == 1:
                            val = result_df.iloc[0, 0]
                            col_name = result_df.columns[0].lower()
                            
                            if pd.notna(val) and isinstance(val, (int, float)):
                                if any(k in col_name for k in ['night', 'qty', 'quantity', 'count', 'stay', 'day', 'days', 'age']):
                                    formatted_val = f"{int(round(val))}" 
                                else:
                                    formatted_val = f"GHC {val:,.2f}" 
                            else:
                                formatted_val = str(val)
                                
                            st.metric(label="Result", value=formatted_val)
                            new_state_msg["content"] += f"\n\n**Result:** {formatted_val}"
                        else:
                            st.dataframe(result_df, use_container_width=True)
                            new_state_msg["data"] = result_df

                    elif viz_type in ["table", "text"]:
                        st.dataframe(result_df, use_container_width=True)
                        new_state_msg["data"] = result_df

                    elif viz_type in ["bar", "line", "pie"]:
                        if x_col not in result_df.columns or y_col not in result_df.columns:
                            if len(result_df.columns) >= 2:
                                x_col = result_df.columns[0]
                                y_col = result_df.columns[-1]
                            else:
                                viz_type = "table"

                        if viz_type == "bar":
                            fig = px.bar(result_df, x=x_col, y=y_col, title=f"{y_col} by {x_col}")
                        elif viz_type == "line":
                            fig = px.line(result_df, x=x_col, y=y_col, title=f"{y_col} over {x_col}")
                        elif viz_type == "pie":
                            agg_df = result_df[result_df[y_col] > 0].copy()
                            if len(agg_df) > 10:
                                top_9 = agg_df.nlargest(9, y_col)
                                other_sum = agg_df[~agg_df[x_col].isin(top_9[x_col])][y_col].sum()
                                other_df = pd.DataFrame({x_col: ['Other'], y_col: [other_sum]})
                                agg_df = pd.concat([top_9, other_df], ignore_index=True)
                            fig = px.pie(agg_df, names=x_col, values=y_col, title=f"{y_col} Share by {x_col}")
                            fig.update_traces(textposition='inside', textinfo='percent+label')

                        st.plotly_chart(fig, use_container_width=True)
                        new_state_msg["chart"] = fig

                st.session_state.messages.append(new_state_msg)

            except Exception as e:
                st.error(f"Analysis Error: {str(e)}")