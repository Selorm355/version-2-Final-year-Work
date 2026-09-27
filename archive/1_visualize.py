import streamlit as st
import pandas as pd
import plotly.express as px
import os

st.set_page_config(page_title="Visualize Data", page_icon="📊", layout="wide")

@st.cache_data
def load_cached_data(file_path):
    """Loads the Parquet file into memory for instant chart rendering."""
    return pd.read_parquet(file_path)

st.title("Visualize Data")

# Security check: Ensure data was uploaded on the main page first
if 'dataset_path' not in st.session_state or not st.session_state.dataset_path:
    st.warning("Please upload and shape a dataset on the main page first.")
    st.stop()

# Load state and data
profile = st.session_state.data_profile
df = load_cached_data(st.session_state.dataset_path)

if not profile.get("Metrics"):
    st.error("No numeric metrics found in this dataset to visualize.")
    st.stop()

# Combine lists for X-axis options
all_x_options = profile["Dimensions"] + profile["Metrics"]

# UI: Axis Selectors
st.markdown("### Configure Chart")
col1, col2, col3 = st.columns(3)

with col1:
    x_axis = st.selectbox("X-Axis (Breakdown)", options=all_x_options)
    
with col2:
    y_axis = st.selectbox("Y-Axis (Metric)", options=profile["Metrics"])
    
with col3:
    # Heuristic Decision Engine
    if x_axis in profile["Dimensions"]:
        heuristic_default = "Line Chart"
    elif x_axis in profile["Metrics"]:
        heuristic_default = "Bar Chart"
    else:
        heuristic_default = "Scatter Plot"
        
    chart_type = st.selectbox(
        "Chart Type", 
        options=["Auto-Suggest", "Bar Chart", "Line Chart", "Pie Chart", "Scatter Plot"],
        help=f"Auto-Suggest recommends a {heuristic_default} based on your data types."
    )

# Determine final chart type
active_chart = heuristic_default if chart_type == "Auto-Suggest" else chart_type

# Render the Plotly Chart
st.markdown("---")
try:
    if active_chart == "Line Chart":
        # Group by date if there are multiple entries per day
        agg_df = df.groupby(x_axis, as_index=False)[y_axis].sum()
        fig = px.line(agg_df, x=x_axis, y=y_axis, title=f"Total {y_axis} over {x_axis}", markers=True)
        
    elif active_chart == "Bar Chart":
        # Crucial: Aggregate dimensions to prevent millions of unreadable bars
        agg_df = df.groupby(x_axis, as_index=False)[y_axis].sum()
        # Sort for better readability
        agg_df = agg_df.sort_values(by=y_axis, ascending=False).head(50) 
        fig = px.bar(agg_df, x=x_axis, y=y_axis, title=f"Top 50: Total {y_axis} by {x_axis}")
        
    elif active_chart == "Scatter Plot":
        fig = px.scatter(df, x=x_axis, y=y_axis, title=f"{y_axis} vs {x_axis}", opacity=0.6) 

    elif active_chart == "Pie Chart":
        # 1. Group and sum the data
        agg_df = df.groupby(x_axis, as_index=False)[y_axis].sum()
        
        # 2. Prevent UI crash by dropping negative metrics
        agg_df = agg_df[agg_df[y_axis] > 0]
        
        # 3. Dynamic Cardinality Handling (The "Other" Grouping)
        if len(agg_df) > 10:
            top_9 = agg_df.nlargest(9, y_axis)
            other_sum = agg_df[~agg_df[x_axis].isin(top_9[x_axis])][y_axis].sum()
            other_df = pd.DataFrame({x_axis: ['Other'], y_axis: [other_sum]})
            agg_df = pd.concat([top_9, other_df], ignore_index=True)
            
        fig = px.pie(agg_df, names=x_axis, values=y_axis, title=f"{y_axis} Share by {x_axis}")
        fig.update_traces(textposition='inside', textinfo='percent+label')
        
    # UI Polish
    fig.update_layout(
        template="plotly_white",
        margin=dict(l=20, r=20, t=50, b=20),
        hovermode="x unified",
        title_x=0.45
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
except Exception as e:
    st.error(f"Could not render chart. Error: {str(e)}")