import streamlit as st
import pandas as pd
import os

# --- Modular Backend Imports ---
from src.ingestion import save_raw_upload
from src.cleaning import clean_dataset_with_duckdb, profile_dataframe, get_paginated_data
from src.auth import require_auth
from src.sales_analytics import summarize_sales
from src.display_formatting import format_numeric_dataframe

def find_column(columns, hints, excluded_hints=()):
    normalized_columns = {
        column: column.lower().replace("_", " ").replace("-", " ")
        for column in columns
    }
    for hint in hints:
        for column, normalized in normalized_columns.items():
            if hint in normalized and not any(excluded in normalized for excluded in excluded_hints):
                return column
    return None

# --- Configuration & Auth ---
st.set_page_config(page_title="OmniPulse Analytics", layout="wide")

# STOP EXECUTION IF NOT LOGGED IN
require_auth()

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

st.title("Data Engine")
st.caption(
    "Upload a CSV or Excel file to capture every column header, clean the data, "
    "and review a structured preview with automatic dataset insights."
)
st.markdown(
    """
    <style>
    [data-testid="stMain"] .block-container h1 { margin-bottom: 2.1rem; }
    [data-testid="stMain"] .block-container h2 { margin-top: 2.4rem; margin-bottom: 1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

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
            
            if os.path.exists(raw_path):
                os.remove(raw_path)
                
            st.rerun()

# --- Post-Upload UI ---
if st.session_state.dataset_path and st.session_state.data_profile:
    profile = st.session_state.data_profile
    
    st.success("File processed, cleaned, and cached.")

    with st.expander("All Column Headers", expanded=True):
        st.caption("Every header detected in the uploaded file, listed in its original order with an inferred data type.")
        headers_df = pd.DataFrame({
            "Header": profile["Columns"],
            "Detected type": [
                "Numeric" if column in profile["Metrics"] else "Text / category"
                for column in profile["Columns"]
            ],
        })
        st.dataframe(headers_df, hide_index=True, use_container_width=True)

    st.header("Dataset Preview")
    st.caption(
        "Cleaned preview of your uploaded data. Browse the cleaned rows in order; "
        "numeric values are formatted for readability without changing the underlying data."
    )
    preview_df = get_paginated_data(
        st.session_state.dataset_path,
        limit=100,
        offset=st.session_state.page_offset,
    )
    
    col_prev, col_page, col_next = st.columns([1, 8, 1])
    with col_prev:
        if st.button("⬅️ Previous") and st.session_state.page_offset >= 100:
            st.session_state.page_offset -= 100
            st.rerun()
    with col_page:
        first_row = st.session_state.page_offset + 1
        last_row = st.session_state.page_offset + len(preview_df)
        st.write(f"Showing rows {first_row} to {last_row}")
    with col_next:
        if st.button("Next ➡️"):
            st.session_state.page_offset += 100
            st.rerun()

    preview_df.index = range(
        st.session_state.page_offset + 1,
        st.session_state.page_offset + len(preview_df) + 1,
    )
    preview_display = format_numeric_dataframe(preview_df)
    st.dataframe(preview_display, use_container_width=True)

    st.header("Dataset Insights")
    st.caption(
        "Insights from your dataset. Review automatically calculated revenue, profit, "
        "product performance, order totals, and averages; use the product filter to focus on one item."
    )
    insights_df = load_parquet_data(st.session_state.dataset_path)
    all_columns = list(insights_df.columns)
    numeric_columns = profile.get("Metrics", [])
    dimension_columns = profile.get("Dimensions", [])
    product_column = find_column(
        dimension_columns,
        ("product", "item", "sku", "article", "stock keeping"),
    )
    quantity_column = find_column(
        numeric_columns,
        ("quantity sold", "units sold", "items sold", "qty", "quantity", "units"),
        ("price", "amount", "revenue", "sales", "cost", "discount", "profit"),
    )
    revenue_column = find_column(
        numeric_columns,
        ("revenue", "turnover", "sales", "gross amount", "net amount", "total amount", "amount", "total"),
        ("discount", "cost", "profit", "quantity", "qty", "unit", "count", "percent"),
    )
    unit_price_column = find_column(
        numeric_columns,
        ("unit price", "selling price", "sale price", "price per unit", "price"),
    )
    total_cost_column = find_column(
        numeric_columns,
        ("total cost", "cost total", "total cogs", "cost amount", "cost of goods"),
        ("unit", "per unit", "quantity"),
    )
    unit_cost_column = find_column(
        numeric_columns,
        ("unit cost", "cost per unit", "unit purchase cost", "purchase price", "cost price"),
    )
    order_column = find_column(
        all_columns,
        ("order id", "order number", "invoice", "transaction id", "receipt", "ticket id"),
    )

    filtered_insights_df = insights_df
    selected_product = None
    if product_column:
        product_options = sorted(
            insights_df[product_column].fillna("UNKNOWN").astype(str).unique().tolist(),
            key=str.casefold,
        )
        selected_product = st.selectbox(
            "Filter insights by product",
            options=[None, *product_options],
            format_func=lambda value: "All products" if value is None else value,
            key="dataset_insight_product_filter",
        )
        if selected_product is not None:
            filtered_insights_df = insights_df[
                insights_df[product_column].fillna("UNKNOWN").astype(str) == selected_product
            ]
    else:
        st.info("No product/item column was detected, so product filtering is unavailable.")

    analysis_columns = list(dict.fromkeys(
        column for column in (
            product_column, quantity_column, revenue_column, unit_price_column,
            total_cost_column, unit_cost_column, order_column
        ) if column
    ))
    analysis_df = filtered_insights_df[analysis_columns]
    product_summary, totals = summarize_sales(
        analysis_df,
        product_column=product_column,
        quantity_column=quantity_column,
        sales_column=revenue_column,
        unit_price_column=unit_price_column if revenue_column is None else None,
        cost_column=total_cost_column,
        unit_cost_column=unit_cost_column if total_cost_column is None else None,
    )

    if revenue_column is None and unit_price_column is None:
        total_revenue_label = "Revenue column not found"
        total_revenue_value = "Not available"
        revenue_total = None
    else:
        revenue_total = totals.get("Sales")
        total_revenue_label = "Total revenue"
        total_revenue_value = f"₵{revenue_total:,.2f}" if revenue_total is not None else "Not available"

    profit_total = totals.get("Profit")
    if profit_total is None:
        total_profit_value = "Cost column not found"
    else:
        total_profit_value = f"₵{profit_total:,.2f}"

    most_sold_value = "Product column not found"
    least_sold_value = "Product column not found"
    if product_column and not product_summary.empty:
        most_sold = product_summary.iloc[0]
        least_sold = product_summary.iloc[-1]
        unit_label = "units" if quantity_column else "rows"
        most_sold_value = f"{most_sold['Product']} ({most_sold['Units Sold']:,.0f} {unit_label})"
        least_sold_value = f"{least_sold['Product']} ({least_sold['Units Sold']:,.0f} {unit_label})"

    best_performing_value = "Product data not available"
    if product_column and not product_summary.empty:
        performance_measure = next(
            (measure for measure in ("Profit", "Sales", "Units Sold") if measure in product_summary),
            None,
        )
        if performance_measure:
            best_performing = product_summary.sort_values(
                performance_measure, ascending=False
            ).iloc[0]
            if performance_measure in {"Profit", "Sales"}:
                measure_label = "profit" if performance_measure == "Profit" else "revenue"
                performance_value = f"₵{best_performing[performance_measure]:,.2f} {measure_label}"
            else:
                performance_value = f"{best_performing[performance_measure]:,.0f} units"
            volume_label = "units sold" if quantity_column else "records"
            volume_value = f"{best_performing['Units Sold']:,.0f} {volume_label}"
            best_performing_value = (
                f"{best_performing['Product']} ({performance_value}; {volume_value})"
            )

    transaction_count = (
        filtered_insights_df[order_column].nunique()
        if order_column
        else len(filtered_insights_df)
    )
    if revenue_total is not None and transaction_count:
        average_value_label = "Average order value" if order_column else "Average revenue per row"
        average_value = f"₵{revenue_total / transaction_count:,.2f}"
    else:
        average_value_label = "Average order value"
        average_value = "Not available"

    if quantity_column and transaction_count:
        average_units_label = "Average items per order" if order_column else "Average items per record"
        average_units_value = f"{totals['Units Sold'] / transaction_count:,.2f}"
    else:
        average_units_label = "Average items per order"
        average_units_value = "Quantity column not found"

    with st.container(key="dataset_insight_metrics"):
        st.markdown(
            """
            <style>
            .st-key-dataset_insight_metrics [data-testid="stMetricLabel"] { font-size: .78rem; }
            .st-key-dataset_insight_metrics [data-testid="stMetricValue"] { font-size: 1.15rem; }
            .st-key-dataset_insight_metrics [data-testid="stMetric"] {
                border: 1px solid #E0E0E0;
                border-radius: 6px;
                padding: .65rem .8rem;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        insight_metrics = [
            (total_revenue_label, total_revenue_value),
            ("Total profit", total_profit_value),
            ("Total orders" if order_column else "Records analyzed", f"{transaction_count:,}"),
            (average_value_label, average_value),
            (average_units_label, average_units_value),
        ]
        if selected_product is None:
            insight_metrics.extend([
                ("Most items sold", most_sold_value),
                ("Least items sold", least_sold_value),
                ("Best-performing product", best_performing_value),
            ])
        for row_start in range(0, len(insight_metrics), 2):
            metric_columns = st.columns(2)
            for metric_column, (label, value) in zip(
                metric_columns, insight_metrics[row_start:row_start + 2]
            ):
                metric_column.metric(label, value)

    st.markdown(
        """
        <style>
        .st-key-get_more_insights button {
            min-height: 3.6rem;
            border: 1px solid #006666;
            border-radius: 8px;
            background: #008080;
            color: #F0F8FF;
            font-size: 1.08rem;
            font-weight: 700;
            box-shadow: 0 5px 14px rgba(0, 102, 102, .22);
            transition: background-color .15s ease, transform .15s ease, box-shadow .15s ease;
        }
        .st-key-get_more_insights button:hover {
            background: #006666;
            border-color: #006666;
            color: #F0F8FF;
            transform: translateY(-1px);
            box-shadow: 0 7px 18px rgba(0, 102, 102, .28);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _, insight_button_column, _ = st.columns([1, 2, 1])
    with insight_button_column:
        if st.button(
            "✦  Get More Insights",
            key="get_more_insights",
            use_container_width=True,
        ):
            st.switch_page("pages/1_chat.py")

    if product_column and not quantity_column:
        st.caption("No quantity column was detected, so best/least sellers are ranked by row frequency.")