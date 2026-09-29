import streamlit as st
import pandas as pd
import duckdb
import os
import io
import json
import re
import calendar
import plotly.express as px
from groq import Groq
from dotenv import load_dotenv
from src.auth import require_auth
from src.display_formatting import (
    format_numeric_dataframe,
    format_numeric_value,
    is_monetary_column,
)
from src.sales_analytics import summarize_sales

SLATE_GRAY = "#2F4F4F"
TEAL = "#008080"
LIGHT_GRAY = "#E0E0E0"
DARK_TEAL = "#006666"
ICE_WHITE = "#F0F8FF"
CHART_PALETTE = [TEAL, DARK_TEAL, SLATE_GRAY, LIGHT_GRAY, ICE_WHITE]

load_dotenv()
api_key = os.getenv("GROQ_API_KEY")

st.set_page_config(page_title="OmniPulse Analytics", page_icon="🤖", layout="wide")

# STOP EXECUTION IF NOT LOGGED IN
require_auth()

st.title("Ask More Insight About your Data")

if not api_key:
    st.error("Groq API key not found. Please add it to your .env file.")
    st.stop()

if 'dataset_path' not in st.session_state or not st.session_state.dataset_path:
    st.warning("Please upload and shape a dataset on the main page first.")
    st.stop()

client = Groq(api_key=api_key)
parquet_path = st.session_state.dataset_path.replace("\\", "/")
profile = st.session_state.data_profile
schema_columns = profile.get("Columns", profile.get("Metrics", []) + profile.get("Dimensions", []))

if "messages" not in st.session_state:
    st.session_state.messages = []

title_col, clear_col = st.columns([5, 1])
with clear_col:
    if st.session_state.messages and st.button("Clear conversation", key="clear_chat_history"):
        st.session_state.messages = []
        st.rerun()

def render_downloads(result_df, key):
    csv_data = result_df.to_csv(index=False).encode("utf-8")
    excel_buffer = io.BytesIO()
    result_df.to_excel(excel_buffer, index=False)
    csv_column, excel_column = st.columns(2)
    csv_column.download_button(
        "Download CSV",
        data=csv_data,
        file_name="analysis_results.csv",
        mime="text/csv",
        key=f"download_csv_{key}",
    )
    excel_column.download_button(
        "Download Excel",
        data=excel_buffer.getvalue(),
        file_name="analysis_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"download_excel_{key}",
    )


def build_conversation_messages(system_prompt, history, max_messages=12):
    conversation = [{"role": "system", "content": system_prompt}]
    for entry in history[-max_messages:]:
        role = entry.get("role")
        if role not in {"user", "assistant"}:
            continue

        content = str(entry.get("content", ""))
        result_df = entry.get("data")
        if role == "assistant" and isinstance(result_df, pd.DataFrame):
            result_rows = result_df.head(8).to_json(orient="records", date_format="iso")
            result_note = (
                f"\nPrior query result ({len(result_df)} rows total; first 8 shown): {result_rows}"
            )
            content = f"{content}{result_note}"
        conversation.append({"role": role, "content": content})
    return conversation


for message_index, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "chart" in message:
            st.plotly_chart(
                message["chart"],
                use_container_width=True,
                key=f"chat_history_chart_{message_index}",
            )
        if "data" in message:
            st.dataframe(format_numeric_dataframe(message["data"]), use_container_width=True)
            render_downloads(message["data"], f"history_{message_index}")

custom_metrics_context = ""
if 'custom_metrics' in st.session_state and st.session_state.custom_metrics:
    custom_metrics_context = "\nCRITICAL: The user has defined the following custom virtual metrics. You MUST use these exact SQL formulas if the user asks for them:\n"
    for name, sql in st.session_state.custom_metrics.items():
        custom_metrics_context += f"- {name}: {sql}\n"

system_prompt = f"""
You are the expert data analyst for OmniPulse Analytics.
The user has a Parquet dataset located at '{parquet_path}'.
Available column names (use these exact names): {json.dumps(schema_columns)}
Numeric columns: {json.dumps(profile.get("Metrics", []))}
Text/category columns: {json.dumps(profile.get("Dimensions", []))}
{custom_metrics_context}

Rules:
1. Answer ONLY questions related to this dataset. If unrelated, set "type" to "error".
2. Retail analysis definitions and safeguards:
    - Revenue over time: parse date/time columns with TRY_CAST("date column" AS DATE) when stored as text; group at the requested day, week, or month grain and order chronologically. Return one row per time bucket for line or area charts.
    - When asked which month has the most/least sales, return the calendar month name (January through December), never only a numeric month. Use strftime(date_value, '%B') as the display label and rank by the requested sales measure. If comparing specific years, include the year as well.
    - For a request covering named months such as March through August, return the requested months in calendar order and use the full month name as the single month dimension. Do not return a second numeric month column.
    - Period growth: aggregate the requested current and prior periods first, then calculate (current - prior) / NULLIF(prior, 0) * 100. State when the requested comparison period is absent.
    - Day/hour timing: derive weekday or hour from the date/time column with DuckDB date functions and aggregate order count, units, or sales. Use heatmap for two-dimensional time patterns.
    - AOV: total revenue divided by COUNT(DISTINCT order ID), not row count, when order IDs exist.
    - Customer segmentation: count distinct orders per customer; define returning customers as customers with more than one distinct order, and state the repeat-rate denominator.
    - Basket/co-occurrence: self-join distinct order-item pairs on order ID, exclude an item paired with itself, and count distinct orders per pair.
    - Category/brand performance: aggregate the requested measure by that dimension. For Pareto, sort descending and calculate cumulative share of the grand total with a window function.
    - Discount impact: compare units, sales/revenue, and profit across discount groups only when the required columns exist. Do not assume whether discount is a rate or amount; infer only when the column clearly encodes it, otherwise ask or report the assumption. Do not claim causation.
    - Dead stock: only identify zero/slow-selling products when the dataset includes a product universe or inventory snapshot and a usable date/window. Transaction-only data cannot prove unsold stock; explain the limitation.
    - Data health: report detectable nulls, duplicate rows, and negative values using available cleaned data. The uploaded file is cleaned before chat: text nulls may have become UNKNOWN and negative numeric values may have been made absolute, so do not claim to detect original-file issues that are no longer represented.
    - Numeric profiling: for requested numeric columns, provide count, mean, median, min, max, standard deviation, and quartiles using DuckDB aggregates/quantiles.
    - Executive summaries: answer with evidence-based bullets across every supplied overview section, including dataset size, numeric measures, category leaders, dates, sales/profit, and data quality. Call out missing/unavailable measures. Do not invent findings or claim a computation not present in the result.
    - If required columns are missing, say exactly what is unavailable and ask for the needed column rather than fabricating a result.
3. DuckDB SQL Rules:
   - FROM clause MUST be: FROM '{parquet_path}'
    - Double-quote every column name, especially names containing spaces or punctuation.
   - For text matching, always use ILIKE and wrap the search term in wildcards (e.g., ILIKE '%term%').
   - When doing math (+, -) use COALESCE(..., 0.0) to prevent type mismatches.
   - CRITICAL: When doing comparative filtering (>, <, =), DO NOT use COALESCE. Instead, explicitly exclude missing data (e.g., WHERE col1 > col2 AND col1 IS NOT NULL AND col2 IS NOT NULL).
    - Use COUNT(DISTINCT "order id") for orders and COUNT(DISTINCT "customer id") for customers when those fields exist.
    - For filtered exports, return the matching records/columns requested by the user, not an aggregate unless they request one.
    - Always include the identifying dimension(s) with grouped metrics. Limit exploratory detail tables to 500 rows unless the user explicitly requests an export or a larger result.
4. Return ONLY a single JSON object.

JSON Schema:
{{
    "sql": "Valid DuckDB SQL string or null if unanswerable.",
     "type": "text | bar | line | area | pie | heatmap | table | error",
    "x": "Column/alias for chart x-axis (or null)",
    "y": "Column/alias for chart y-axis (or null)",
     "z": "Numeric value column for heatmap (or null)",
    "message": "A professional explanation of the query. IMPORTANT: Do NOT guess the outcome in this message. Keep it neutral (e.g., 'Here is the analysis of losses...' instead of 'Yes, there are losses'). Do not mention SQL errors or retries."
}}

Chart selection:
- If the result groups a numeric measure by a category, use "bar" and set x/y to those result aliases.
- Use "line" or "area" for a time series, "pie" for a small positive share/composition result, and "heatmap" for two-dimensional time patterns (set x, y, z).
- Use "table" only when charting would be misleading, such as detailed records, multiple unrelated measures, or a scalar answer.
"""

st.caption("Ask about trends, period growth, AOV, repeat customers, basket pairs, category performance, discounts, inventory velocity, or data quality.")

st.markdown("**Try an analysis**")
suggestion_columns = st.columns(3)
suggested_questions = [
    "Give me an executive overview of the data",
    "Plot monthly revenue trends",
    "Which products sold the most?",
]
for index, (suggestion_column, suggestion) in enumerate(zip(suggestion_columns, suggested_questions)):
    if suggestion_column.button(suggestion, key=f"chat_suggestion_{index}", use_container_width=True):
        st.session_state.pending_chat_prompt = suggestion
        st.rerun()

def extract_json(raw_text: str) -> dict:
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    return json.loads(raw_text)

def run_query_with_retry(client, initial_sql, prompt, system_prompt, conversation_messages=None):
    con = duckdb.connect()
    try:
        return con.execute(initial_sql).df(), None
    except Exception as first_err:
        con.close()
        
        retry_messages = list(conversation_messages or [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ])
        retry_messages.extend([
            {"role": "assistant", "content": "My initial SQL query failed."},
            {"role": "user", "content": f"The query failed with error: {str(first_err)}. Rewrite the SQL to strictly answer my original question. CRITICAL: In your JSON 'message', do NOT mention SQL, errors, type mismatch, or casting. Provide only the professional business insight."}
        ])
        
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


def summarize_query_results(client, prompt, result_df):
    preview_limit = 250
    result_preview = result_df.head(preview_limit).to_json(orient="records", date_format="iso")
    truncated_note = (
        f"The result contains {len(result_df)} rows; only the first {preview_limit} are shown below. "
        "Do not make claims about omitted rows."
        if len(result_df) > preview_limit
        else "The complete query result is shown below."
    )
    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "system",
                "content": (
                    "Write a concise executive summary of the supplied dataset query result. "
                    "Use only values and comparisons supported by the result; do not invent causes, "
                    "metrics, or conclusions. Use 3-5 concise bullets when useful."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User question: {prompt}\n"
                    f"Query context: {truncated_note}\n"
                    f"Result columns: {json.dumps(list(result_df.columns))}\n"
                    f"Result rows: {result_preview}"
                ),
            },
        ],
        temperature=0.0,
    )
    return response.choices[0].message.content.strip()


def is_executive_overview_request(prompt):
    return bool(re.search(
        r"\b(executive overview|executive summary|full overview|dataset overview|"
        r"high[- ]level overview|overview of (the )?(dataset|data|business)|"
        r"summari[sz]e (the )?(dataset|data|business)|"
        r"key insights|all insights|more insights|insights from (the )?(dataset|data))\b",
        prompt,
        re.IGNORECASE,
    ))


def format_executive_overview_message(overview_df):
    """Turn the evidence table into bullets without another LLM call."""
    def find_row(section, insight_hint):
        matches = overview_df[
            (overview_df["Section"] == section)
            & (overview_df["Insight"].str.contains(insight_hint, case=False, na=False))
        ]
        if matches.empty:
            return None
        row = matches.iloc[0]
        return row["Insight"], row["Value"]

    bullet_specs = [
        ("Dataset", "Total records"),
        ("Sales performance", "Total revenue"),
        ("Sales performance", "Total profit"),
        ("Sales performance", "Total units sold"),
        ("Sales performance", "Distinct orders"),
        ("Sales performance", "Average order value"),
        ("Product performance", "Top products"),
        ("Product performance", "Least performing product"),
        ("Product performance", "Most units sold"),
        ("Date range", "earliest"),
        ("Date range", "latest"),
        ("Data quality", "Duplicate"),
    ]
    bullets = []
    for section, hint in bullet_specs:
        match = find_row(section, hint)
        if match:
            bullets.append(f"- **{match[0]}:** {match[1]}")

    if not bullets:
        for _, row in overview_df.head(8).iterrows():
            bullets.append(f"- **{row['Insight']}:** {row['Value']}")

    return "**Executive overview**\n\n" + "\n".join(bullets)


def build_dataset_overview(parquet_path, profile):
    """Create a broad evidence table from the full cleaned dataset."""
    dataset = pd.read_parquet(parquet_path)
    overview_rows = []

    def add_overview(section, insight, value):
        overview_rows.append({"Section": section, "Insight": insight, "Value": str(value)})

    add_overview("Dataset", "Total records", f"{len(dataset):,}")
    add_overview("Dataset", "Total columns", f"{len(dataset.columns):,}")
    add_overview("Data quality", "Duplicate rows in cleaned data", f"{int(dataset.duplicated().sum()):,}")
    for column, missing_count in dataset.isna().sum().items():
        if missing_count:
            add_overview("Data quality", f"{column}: remaining missing values", f"{missing_count:,}")

    def format_statistic(value, column):
        if is_monetary_column(column):
            return format_numeric_value(value, column)
        return f"{value:,.2f}"

    for column in profile.get("Metrics", []):
        values = pd.to_numeric(dataset[column], errors="coerce").dropna()
        if values.empty:
            continue
        statistics = (
            ("Valid values", f"{len(values):,}"),
            ("Mean", format_statistic(values.mean(), column)),
            ("Median", format_statistic(values.median(), column)),
            ("Minimum", format_statistic(values.min(), column)),
            ("25th percentile", format_statistic(values.quantile(0.25), column)),
            ("75th percentile", format_statistic(values.quantile(0.75), column)),
            ("Maximum", format_statistic(values.max(), column)),
            ("Standard deviation", format_statistic(values.std(), column)),
        )
        for statistic, value in statistics:
            add_overview("Numeric profile", f"{column}: {statistic}", value)

    for column in profile.get("Dimensions", []):
        values = dataset[column].dropna().astype(str)
        if values.empty:
            continue
        counts = values.value_counts()
        add_overview("Category profile", f"{column}: distinct values", f"{values.nunique():,}")
        add_overview(
            "Category profile",
            f"{column}: most common value",
            f"{counts.index[0]} ({counts.iloc[0]:,} rows)",
        )

    for column in dataset.columns:
        if not re.search(r"date|time|timestamp", str(column), re.IGNORECASE):
            continue
        parsed_dates = pd.to_datetime(dataset[column], errors="coerce").dropna()
        if not parsed_dates.empty:
            add_overview("Date range", f"{column}: earliest date", parsed_dates.min().strftime("%Y-%m-%d"))
            add_overview("Date range", f"{column}: latest date", parsed_dates.max().strftime("%Y-%m-%d"))

    def find_column(columns, hints, excluded=()):
        for hint in hints:
            for column in columns:
                normalized = str(column).lower().replace("_", " ").replace("-", " ")
                if hint in normalized and not any(term in normalized for term in excluded):
                    return column
        return None

    numeric_columns = profile.get("Metrics", [])
    product_column = find_column(profile.get("Dimensions", []), ("product", "item", "sku", "article"))
    quantity_column = find_column(
        numeric_columns,
        ("quantity sold", "units sold", "items sold", "qty", "quantity", "units"),
        ("price", "amount", "revenue", "sales", "cost", "discount", "profit"),
    )
    revenue_column = find_column(
        numeric_columns,
        ("revenue", "turnover", "sales", "total amount", "amount"),
        ("discount", "cost", "profit", "quantity", "qty", "unit", "count", "percent"),
    )
    unit_price_column = find_column(numeric_columns, ("unit price", "selling price", "sale price", "price per unit", "price"))
    total_cost_column = find_column(
        numeric_columns,
        ("total cost", "cost total", "total cogs", "cost amount", "cost of goods"),
        ("unit", "per unit", "quantity"),
    )
    unit_cost_column = find_column(numeric_columns, ("unit cost", "cost per unit", "purchase price", "cost price"))
    order_column = find_column(dataset.columns, ("order id", "order number", "invoice", "transaction id", "receipt"))

    analysis_columns = list(dict.fromkeys(
        column for column in (
            product_column, quantity_column, revenue_column, unit_price_column,
            total_cost_column, unit_cost_column,
        ) if column
    ))
    if analysis_columns:
        product_summary, totals = summarize_sales(
            dataset[analysis_columns],
            product_column=product_column,
            quantity_column=quantity_column,
            sales_column=revenue_column,
            unit_price_column=unit_price_column if revenue_column is None else None,
            cost_column=total_cost_column,
            unit_cost_column=unit_cost_column if total_cost_column is None else None,
        )
        if "Sales" in totals:
            add_overview("Sales performance", "Total revenue", format_numeric_value(totals["Sales"], "Revenue"))
        if "Profit" in totals:
            add_overview("Sales performance", "Total profit", format_numeric_value(totals["Profit"], "Profit"))
        if "Units Sold" in totals:
            add_overview("Sales performance", "Total units sold", f"{totals['Units Sold']:,.0f}")
        if order_column:
            add_overview("Sales performance", "Distinct orders", f"{dataset[order_column].nunique():,}")
            if "Sales" in totals and dataset[order_column].nunique():
                average_order_value = totals["Sales"] / dataset[order_column].nunique()
                add_overview("Sales performance", "Average order value", format_numeric_value(average_order_value, "Revenue"))
        if product_column and not product_summary.empty:
            ranking_metric = next(
                (metric for metric in ("Profit", "Sales", "Units Sold") if metric in product_summary),
                "Units Sold",
            )
            top_products = product_summary.nlargest(5, ranking_metric)
            add_overview("Product performance", f"Top products by {ranking_metric.lower()}", "; ".join(
                f"{row['Product']} ({format_numeric_value(row[ranking_metric], ranking_metric)})"
                for _, row in top_products.iterrows()
            ))
            worst_product = product_summary.nsmallest(1, ranking_metric).iloc[0]
            add_overview(
                "Product performance",
                f"Least performing product by {ranking_metric.lower()}",
                f"{worst_product['Product']} ({format_numeric_value(worst_product[ranking_metric], ranking_metric)})",
            )
            if ranking_metric != "Units Sold":
                top_seller = product_summary.nlargest(1, "Units Sold").iloc[0]
                add_overview(
                    "Product performance",
                    "Most units sold",
                    f"{top_seller['Product']} ({top_seller['Units Sold']:,.0f} units)",
                )

    return pd.DataFrame(overview_rows)

def infer_visualization(prompt, result_df, requested_type):
    """Choose a useful chart when the model returns a table for chartable results."""
    prompt_lower = prompt.lower()
    chart_intent = re.search(
        r"\b(chart|graph|plot|pie|bar|line|area|visuali[sz]e|show me|compare|comparison|distribution|share|"
        r"breakdown|trend|over time|by category|by product|top \d*|best[- ]selling|"
        r"least[- ]selling|most[- ]sold|heat ?map)\b",
        prompt_lower,
    )
    explicit_chart = None
    if re.search(r"\bline\s*(chart|graph)?\b", prompt_lower):
        explicit_chart = "line"
    elif re.search(r"\barea\s*(chart|graph)?\b", prompt_lower):
        explicit_chart = "area"
    elif re.search(r"\bbar\s*(chart|graph)?\b", prompt_lower):
        explicit_chart = "bar"
    elif re.search(r"\bpie\s*(chart|graph)?\b", prompt_lower):
        explicit_chart = "pie"

    if explicit_chart and len(result_df.columns) >= 2:
        return explicit_chart
    if requested_type not in {"text", "table", None}:
        return requested_type
    if not chart_intent or len(result_df.columns) < 2:
        return requested_type

    numeric_columns = [
        column for column in result_df.columns
        if pd.api.types.is_numeric_dtype(result_df[column])
    ]
    if not numeric_columns:
        return requested_type

    if "heat" in prompt_lower and len(result_df.columns) >= 3:
        return "heatmap"
    if re.search(r"\b(pie|share|distribution|composition|proportion)\b", prompt_lower):
        return "pie"
    if re.search(
        r"\b(trend|over time|daily|weekly|monthly|yearly|by date)\b|"
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(to|through|until)\s+"
        r"(january|february|march|april|may|june|july|august|september|october|november|december)\b",
        prompt_lower,
    ):
        return "line"
    return "bar"


def remove_duplicate_month_columns(result_df):
    """Keep a readable month-name column when it duplicates a numeric month column."""
    month_columns = [
        column for column in result_df.columns
        if re.search(r"\bmonth\b", str(column).lower().replace("_", " "))
    ]
    if len(month_columns) < 2:
        return result_df

    def month_numbers(series):
        numeric_values = pd.to_numeric(series, errors="coerce")
        non_null = series.notna()
        if non_null.any() and numeric_values[non_null].between(1, 12).all():
            return numeric_values

        month_lookup = {
            month.lower(): number
            for number in range(1, 13)
            for month in (calendar.month_name[number], calendar.month_abbr[number])
        }
        text_values = series.astype("string").str.strip().str.lower().map(month_lookup)
        if text_values[non_null].notna().all() and non_null.any():
            return text_values
        return None

    remove_columns = set()
    for index, first_column in enumerate(month_columns):
        first_values = month_numbers(result_df[first_column])
        if first_values is None:
            continue
        for second_column in month_columns[index + 1:]:
            second_values = month_numbers(result_df[second_column])
            if second_values is None or not first_values.equals(second_values):
                continue

            first_name = str(first_column).lower().replace("_", " ")
            second_name = str(second_column).lower().replace("_", " ")
            first_is_numeric = pd.api.types.is_numeric_dtype(result_df[first_column])
            second_is_numeric = pd.api.types.is_numeric_dtype(result_df[second_column])
            if first_is_numeric and not second_is_numeric:
                remove_columns.add(first_column)
            elif second_is_numeric and not first_is_numeric:
                remove_columns.add(second_column)
            elif "name" in first_name and "name" not in second_name:
                remove_columns.add(second_column)
            else:
                remove_columns.add(second_column)

    return result_df.drop(columns=list(remove_columns))


def name_numeric_months(result_df):
    """Replace numeric 1-12 values with month names in clearly named month columns."""
    normalized = result_df.copy()
    for column in normalized.columns:
        column_name = str(column).strip().lower().replace("_", " ")
        if not re.search(r"\b(month|month number|month num)\b", column_name):
            continue

        numeric_months = pd.to_numeric(normalized[column], errors="coerce")
        valid_months = numeric_months.dropna()
        if not valid_months.empty and valid_months.between(1, 12).all():
            normalized[column] = numeric_months.map(
                lambda month: calendar.month_name[int(month)] if pd.notna(month) else None
            )
    return normalized

chat_input = st.chat_input("Ask a retail question, e.g. monthly revenue growth or best-selling category")
pending_prompt = st.session_state.pop("pending_chat_prompt", None)
prompt = chat_input or pending_prompt

if prompt:
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        with st.spinner("Analyzing data..."):
            if is_executive_overview_request(prompt):
                try:
                    overview_df = build_dataset_overview(parquet_path, profile)
                    message = format_executive_overview_message(overview_df)
                    st.markdown(message)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": message,
                    })
                except Exception as overview_error:
                    st.error(f"Could not build the executive overview: {overview_error}")
                st.stop()

            try:
                response = client.chat.completions.create(
                    model="openai/gpt-oss-20b",
                    messages=build_conversation_messages(
                        system_prompt,
                        st.session_state.messages,
                    ),
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
                z_col = ai_payload.get("z")
                message = ai_payload.get("message", "Here are the insights:")

                new_state_msg = {"role": "assistant", "content": message}

                if viz_type == "error" or not sql_query:
                    st.markdown(message)
                    st.session_state.messages.append(new_state_msg)
                    st.stop()

                conversation_messages = build_conversation_messages(
                    system_prompt,
                    st.session_state.messages,
                )
                result_df, retry_payload = run_query_with_retry(
                    client,
                    sql_query,
                    prompt,
                    system_prompt,
                    conversation_messages,
                )

                if retry_payload and isinstance(retry_payload, dict):
                    viz_type = retry_payload.get("type", viz_type)
                    x_col = retry_payload.get("x", x_col)
                    y_col = retry_payload.get("y", y_col)
                    z_col = retry_payload.get("z", z_col)
                    message = retry_payload.get("message", message)

                if result_df is None:
                    message = "I couldn't complete that analysis after retrying the query. Please check the requested columns or rephrase the question."
                    new_state_msg["content"] = message
                    st.markdown(message)
                    if isinstance(retry_payload, str):
                        with st.expander("Technical details"):
                            st.code(retry_payload)
                elif result_df.empty:
                    message = "I analyzed the dataset based on your request, but there are no records matching your criteria (e.g., this dataset contains no losses)."
                    new_state_msg["content"] = message
                    st.markdown(message)
                    st.info("The SQL query executed successfully, but returned 0 rows.")
                else:
                    result_df = remove_duplicate_month_columns(result_df)
                    result_df = name_numeric_months(result_df)
                    viz_type = infer_visualization(prompt, result_df, viz_type)

                    if re.search(
                        r"\b(executive summary|summari[sz]e|key insights|anomal(?:y|ies)|brief)\b",
                        prompt,
                        re.IGNORECASE,
                    ):
                        try:
                            message = summarize_query_results(client, prompt, result_df)
                        except Exception:
                            message = "Here are the query results. I could not generate the requested narrative summary."

                    st.markdown(message)
                    new_state_msg["content"] = message

                    if viz_type == "text":
                        if len(result_df) == 1 and len(result_df.columns) == 1:
                            val = result_df.iloc[0, 0]
                            col_name = result_df.columns[0].lower()
                            
                            if pd.notna(val) and isinstance(val, (int, float)):
                                formatted_val = format_numeric_value(val, col_name)
                            else:
                                formatted_val = str(val)
                                
                            st.metric(label="Result", value=formatted_val)
                            new_state_msg["content"] += f"\n\n**Result:** {formatted_val}"
                            new_state_msg["data"] = result_df
                            render_downloads(result_df, f"current_{len(st.session_state.messages)}")
                        else:
                            st.dataframe(format_numeric_dataframe(result_df), use_container_width=True)
                            new_state_msg["data"] = result_df
                            render_downloads(result_df, f"current_{len(st.session_state.messages)}")

                    elif viz_type in ["table", "text"]:
                        st.dataframe(format_numeric_dataframe(result_df), use_container_width=True)
                        new_state_msg["data"] = result_df
                        render_downloads(result_df, f"current_{len(st.session_state.messages)}")

                    elif viz_type in ["bar", "line", "area", "pie", "heatmap"]:
                        if x_col not in result_df.columns or y_col not in result_df.columns:
                            if len(result_df.columns) >= 2:
                                x_col = result_df.columns[0]
                                y_col = result_df.columns[-1]
                            else:
                                viz_type = "table"
                        if viz_type == "heatmap" and z_col not in result_df.columns:
                            viz_type = "table"

                        if viz_type == "bar":
                            fig = px.bar(
                                result_df,
                                x=x_col,
                                y=y_col,
                                title=f"{y_col} by {x_col}",
                                color_discrete_sequence=CHART_PALETTE,
                            )
                            fig.update_traces(marker_color=TEAL)
                            fig.update_yaxes(
                                tickformat=",.2f" if is_monetary_column(y_col) else ",.0f",
                                tickprefix="₵" if is_monetary_column(y_col) else "",
                            )
                        elif viz_type == "line":
                            fig = px.line(
                                result_df,
                                x=x_col,
                                y=y_col,
                                title=f"{y_col} over {x_col}",
                                color_discrete_sequence=CHART_PALETTE,
                            )
                            fig.update_traces(line_color=TEAL)
                            fig.update_yaxes(
                                tickformat=",.2f" if is_monetary_column(y_col) else ",.0f",
                                tickprefix="₵" if is_monetary_column(y_col) else "",
                            )
                        elif viz_type == "area":
                            fig = px.area(
                                result_df,
                                x=x_col,
                                y=y_col,
                                title=f"{y_col} over {x_col}",
                                color_discrete_sequence=CHART_PALETTE,
                            )
                            fig.update_traces(line_color=DARK_TEAL)
                            fig.update_yaxes(
                                tickformat=",.2f" if is_monetary_column(y_col) else ",.0f",
                                tickprefix="₵" if is_monetary_column(y_col) else "",
                            )
                        elif viz_type == "heatmap":
                            fig = px.density_heatmap(
                                result_df,
                                x=x_col,
                                y=y_col,
                                z=z_col,
                                histfunc="sum",
                                title=f"{z_col} by {x_col} and {y_col}",
                                color_continuous_scale=[
                                    ICE_WHITE, LIGHT_GRAY, TEAL, DARK_TEAL, SLATE_GRAY
                                ],
                            )
                        elif viz_type == "pie":
                            agg_df = result_df[result_df[y_col] > 0].copy()
                            agg_df = agg_df.nlargest(10, y_col)
                            fig = px.pie(
                                agg_df,
                                names=x_col,
                                values=y_col,
                                title=f"{y_col} Share by {x_col}",
                                color_discrete_sequence=CHART_PALETTE,
                            )
                            pie_value_format = ",.2f" if is_monetary_column(y_col) else ",.0f"
                            pie_currency_prefix = "₵" if is_monetary_column(y_col) else ""
                            fig.update_traces(
                                textposition="auto",
                                texttemplate="%{percent}",
                                textfont_size=13,
                                hovertemplate=f"%{{label}}<br>{pie_currency_prefix}%{{value:{pie_value_format}}} (%{{percent}})<extra></extra>",
                            )
                            fig.update_layout(
                                height=680,
                                autosize=True,
                                margin={"l": 30, "r": 190, "t": 70, "b": 35},
                                legend={"orientation": "v", "x": 1.02, "y": 0.5},
                                uniformtext_minsize=11,
                                uniformtext_mode="hide",
                            )

                        if viz_type == "table":
                            st.dataframe(format_numeric_dataframe(result_df), use_container_width=True)
                            new_state_msg["data"] = result_df
                        else:
                            fig.update_layout(
                                template="plotly_white",
                                colorway=CHART_PALETTE,
                                paper_bgcolor=ICE_WHITE,
                                plot_bgcolor=ICE_WHITE,
                                font={"color": SLATE_GRAY},
                            )
                            st.plotly_chart(
                                fig,
                                use_container_width=True,
                                key=f"chat_current_chart_{len(st.session_state.messages)}",
                            )
                            new_state_msg["chart"] = fig
                            st.dataframe(format_numeric_dataframe(result_df), use_container_width=True)
                            new_state_msg["data"] = result_df
                        render_downloads(result_df, f"current_{len(st.session_state.messages)}")

                st.session_state.messages.append(new_state_msg)

            except Exception as e:
                st.error(f"Analysis Error: {str(e)}")