import streamlit as st
import pandas as pd
import plotly.express as px

# --- Config & Constants ---
st.set_page_config(page_title="Airport Congestion Analysis", page_icon="✈️", layout="wide")

EARLY_THRESHOLD = -5  # Flights arriving more than 5 minutes early are considered "Padded"

def classify_flight(delta):
    if delta < EARLY_THRESHOLD:
        return 'Early (Padding)'
    elif delta <= 15:
        return 'On Time'
    else:
        return 'Delayed'

# --- Data Loading & Caching ---
@st.cache_data
def load_data():
    """Loads both CSVs, combines them, and caches the result for performance."""
    try:
        df_bom = pd.read_csv("data/flights_data_bom_adb.csv")
    except FileNotFoundError:
        df_bom = pd.DataFrame()
        
    try:
        df_maa = pd.read_csv("data/flights_data_maa.csv")
    except FileNotFoundError:
        df_maa = pd.DataFrame()
        
    df_combined = pd.concat([df_bom, df_maa], ignore_index=True)
    
    if not df_combined.empty:
        # Convert date column to datetime objects for filtering
        df_combined['date'] = pd.to_datetime(df_combined['date'])
        # Apply the classification logic
        df_combined['classification'] = df_combined['delta_minutes'].apply(classify_flight)
        
    return df_combined

df = load_data()

# --- UI Setup & Sidebar ---
st.title("✈️ Airport Congestion & Schedule Padding Dashboard")

if df.empty:
    st.warning("No data found! Please run your scraper scripts to generate the CSV files.")
    st.stop()

st.sidebar.header("Dashboard Filters")

# 1. Airport Filter
airports = df['airport_code'].unique().tolist()
selected_airport = st.sidebar.selectbox("Select Airport View", ["All Airports"] + airports)

# 2. Date Filter
min_date = df['date'].min().date()
max_date = df['date'].max().date()

# Handle edge case where there is only one day of data
if min_date == max_date:
    date_range = st.sidebar.date_input("Select Date Range", min_date)
    start_date, end_date = date_range, date_range
else:
    date_selection = st.sidebar.date_input("Select Date Range", [min_date, max_date])
    if len(date_selection) == 2:
        start_date, end_date = date_selection
    else:
        start_date, end_date = date_selection[0], date_selection[0]

# --- Apply Filters ---
mask = (df['date'].dt.date >= start_date) & (df['date'].dt.date <= end_date)
if selected_airport != "All Airports":
    mask = mask & (df['airport_code'] == selected_airport)

filtered_df = df[mask]

st.markdown(f"### Analyzing: {selected_airport} | {start_date} to {end_date}")

if filtered_df.empty:
    st.info("No flights match the selected criteria.")
    st.stop()

# --- Executive KPIs ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Verified Arrivals Tracked", len(filtered_df))
col2.metric(f"Early / Padded (<-{abs(EARLY_THRESHOLD)}m)", len(filtered_df[filtered_df['delta_minutes'] < EARLY_THRESHOLD]))
col3.metric("Delayed (>15m)", len(filtered_df[filtered_df['delta_minutes'] > 15]))
col4.metric("Average Delta (Minutes)", round(filtered_df['delta_minutes'].mean(), 1))

st.markdown("---")

# --- Visualizations ---
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("Average Padding by Airline")
    st.markdown("Negative values indicate early arrivals (potential schedule padding).")
    
    # Group by airline and calculate mean delta
    airline_df = filtered_df.groupby('airline')['delta_minutes'].mean().reset_index()
    # Filter out airlines with very few flights to keep the chart clean (optional, keeping all for now)
    airline_df = airline_df.sort_values(by='delta_minutes', ascending=True)

    fig_bar = px.bar(
        airline_df, x='airline', y='delta_minutes',
        color='delta_minutes', color_continuous_scale='RdBu_r', text_auto='.1f'
    )
    fig_bar.update_layout(xaxis_title="Airline", yaxis_title="Average Delta (mins)", template="plotly_dark")
    st.plotly_chart(fig_bar, use_container_width=True)

with chart_col2:
    st.subheader("Flight Status Distribution")
    st.markdown("Proportion of padded vs on-time vs delayed flights.")
    
    status_counts = filtered_df['classification'].value_counts().reset_index()
    status_counts.columns = ['classification', 'count']
    
    # Fixed color mapping so Early is always Green, Delayed is always Red
    color_map = {'Early (Padding)': '#2ca02c', 'On Time': '#1f77b4', 'Delayed': '#d62728'}
    
    fig_pie = px.pie(
        status_counts, names='classification', values='count',
        color='classification', color_discrete_map=color_map, hole=0.4
    )
    fig_pie.update_layout(template="plotly_dark")
    st.plotly_chart(fig_pie, use_container_width=True)

# --- Raw Data Table ---
st.markdown("---")
st.subheader("Raw Flight Records")
st.dataframe(
    filtered_df[['date', 'airport_code', 'airline', 'flight_number', 'origin_city', 'scheduled_time', 'actual_time', 'delta_minutes', 'classification']].sort_values(by=['date', 'scheduled_time'], ascending=[False, False]),
    use_container_width=True
)