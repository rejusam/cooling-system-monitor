"""
Streamlit dashboard for the cooling system monitoring database.

Usage:
    streamlit run dashboard.py
"""
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DB_PATH = Path(__file__).parent / "cooling_monitor.db"

# -- Page config --------------------------------------------------------------
st.set_page_config(page_title="Cooling Fleet Monitor", layout="wide")


@st.cache_resource
def get_connection():
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)


def load_query(sql):
    con = get_connection()
    return pd.read_sql_query(sql, con)


# -- Sidebar ------------------------------------------------------------------
st.sidebar.title("Cooling Fleet Monitor")
st.sidebar.markdown(
    "Operational dashboard for a fleet of 20 cooling units "
    "across 5 NZ regions. Built on the UCI Hydraulic Systems dataset."
)

page = st.sidebar.radio(
    "View",
    ["Fleet Overview", "Condition Analysis", "Anomaly Detection", "Unit Drilldown"],
)

# -- Data ---------------------------------------------------------------------
readings = load_query("""
    SELECT r.*, u.unit_code, u.model, u.region, u.site
    FROM readings r JOIN units u ON r.unit_id = u.unit_id
""")
readings["timestamp"] = pd.to_datetime(readings["timestamp"])

units = load_query("SELECT * FROM units")


# =============================================================================
# PAGE: Fleet Overview
# =============================================================================
if page == "Fleet Overview":
    st.title("Fleet Overview")

    # KPIs
    total_units = len(units)
    total_readings = len(readings)
    failing = readings[readings["cooler_condition"] == 3]["unit_id"].nunique()
    avg_temp = readings["avg_temp_c"].mean()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Units", total_units)
    c2.metric("Total Readings", f"{total_readings:,}")
    c3.metric("Units with Failures", failing)
    c4.metric("Avg Temperature", f"{avg_temp:.1f} °C")

    st.markdown("---")

    col_left, col_right = st.columns(2)

    # Units and readings by region
    with col_left:
        st.subheader("Units by Region")
        region_summary = (
            readings.groupby("region")
            .agg(units=("unit_id", "nunique"), readings=("reading_id", "count"))
            .reset_index()
            .sort_values("units", ascending=False)
        )
        fig = px.bar(
            region_summary, x="region", y="units",
            color="region", text_auto=True,
        )
        fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Units")
        st.plotly_chart(fig, key="region_units")

    # Condition distribution
    with col_right:
        st.subheader("Condition Distribution")
        cond_map = {100: "Healthy (100%)", 20: "Reduced (20%)", 3: "Failing (3%)"}
        cond_counts = (
            readings["cooler_condition"]
            .map(cond_map)
            .value_counts()
            .reset_index()
        )
        cond_counts.columns = ["Condition", "Count"]
        fig = px.pie(
            cond_counts, names="Condition", values="Count",
            color="Condition",
            color_discrete_map={
                "Healthy (100%)": "#2ecc71",
                "Reduced (20%)": "#f39c12",
                "Failing (3%)": "#e74c3c",
            },
        )
        st.plotly_chart(fig, key="cond_pie")

    # Site failure rate table
    st.subheader("Site Failure Rates")
    site_stats = load_query("""
        SELECT u.region || ' — ' || u.site AS location,
            COUNT(DISTINCT u.unit_id) AS units,
            SUM(CASE WHEN r.cooler_condition = 3 THEN 1 ELSE 0 END) AS failure_readings,
            ROUND(SUM(CASE WHEN r.cooler_condition = 3 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS failure_pct
        FROM readings r JOIN units u ON r.unit_id = u.unit_id
        GROUP BY u.region, u.site
        ORDER BY failure_pct DESC
    """)
    st.dataframe(site_stats, width="stretch", hide_index=True)


# =============================================================================
# PAGE: Condition Analysis
# =============================================================================
elif page == "Condition Analysis":
    st.title("Condition Analysis")

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Temperature by Condition")
        cond_labels = {100: "Healthy", 20: "Reduced", 3: "Failing"}
        plot_df = readings.copy()
        plot_df["condition_label"] = plot_df["cooler_condition"].map(cond_labels)
        fig = px.box(
            plot_df, x="condition_label", y="avg_temp_c",
            color="condition_label",
            color_discrete_map={
                "Healthy": "#2ecc71", "Reduced": "#f39c12", "Failing": "#e74c3c"
            },
            labels={"avg_temp_c": "Avg Temperature (°C)", "condition_label": ""},
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, key="temp_box")

    with col_right:
        st.subheader("Motor Power by Condition")
        fig = px.box(
            plot_df, x="condition_label", y="motor_power_w",
            color="condition_label",
            color_discrete_map={
                "Healthy": "#2ecc71", "Reduced": "#f39c12", "Failing": "#e74c3c"
            },
            labels={"motor_power_w": "Motor Power (W)", "condition_label": ""},
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, key="power_box")

    # Condition summary stats
    st.subheader("Condition Group Statistics")
    cond_stats = load_query("""
        SELECT
            CASE WHEN cooler_condition = 100 THEN 'Healthy (100%)'
                 WHEN cooler_condition = 20  THEN 'Reduced (20%)'
                 ELSE 'Failing (3%)' END AS condition_group,
            COUNT(*) AS n,
            ROUND(AVG(avg_temp_c), 2) AS mean_temp_c,
            ROUND(AVG(motor_power_w), 1) AS mean_power_w,
            ROUND(AVG(cooling_efficiency_pct), 1) AS mean_efficiency_pct,
            ROUND(AVG(vibration_mm_s), 3) AS mean_vibration
        FROM readings
        GROUP BY cooler_condition
        ORDER BY cooler_condition DESC
    """)
    st.dataframe(cond_stats, width="stretch", hide_index=True)

    # Power vs condition correlation
    st.subheader("Power & Efficiency vs Condition Level")
    corr_data = load_query("""
        SELECT cooler_condition,
            ROUND(AVG(motor_power_w), 1) AS avg_power_w,
            ROUND(AVG(cooling_efficiency_pct), 1) AS avg_efficiency,
            ROUND(AVG(vibration_mm_s), 3) AS avg_vibration
        FROM readings GROUP BY cooler_condition ORDER BY cooler_condition
    """)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=corr_data["cooler_condition"].astype(str) + "%",
        y=corr_data["avg_power_w"], name="Avg Power (W)",
    ))
    fig.add_trace(go.Bar(
        x=corr_data["cooler_condition"].astype(str) + "%",
        y=corr_data["avg_efficiency"], name="Avg Efficiency (%)",
    ))
    fig.update_layout(
        barmode="group", xaxis_title="Cooler Condition",
        yaxis_title="Value",
    )
    st.plotly_chart(fig, key="corr_bars")


# =============================================================================
# PAGE: Anomaly Detection
# =============================================================================
elif page == "Anomaly Detection":
    st.title("Temperature Anomaly Detection")
    st.markdown(
        "Anomalies identified using **per-unit Z-scores**: readings where "
        "temperature deviates more than 2 standard deviations from that "
        "unit's own mean."
    )

    anomalies = load_query("""
        WITH stats AS (
            SELECT unit_id, AVG(avg_temp_c) AS mu,
                SQRT(AVG(avg_temp_c * avg_temp_c) - AVG(avg_temp_c) * AVG(avg_temp_c)) AS sigma
            FROM readings GROUP BY unit_id HAVING sigma > 0
        )
        SELECT u.unit_code, u.region, r.timestamp,
            ROUND(r.avg_temp_c, 2) AS temp_c,
            ROUND(s.mu, 2) AS unit_mean,
            ROUND((r.avg_temp_c - s.mu) / s.sigma, 2) AS z_score,
            r.cooler_condition
        FROM readings r
        JOIN units u ON r.unit_id = u.unit_id
        JOIN stats s ON r.unit_id = s.unit_id
        WHERE ABS(r.avg_temp_c - s.mu) / s.sigma > 2.0
        ORDER BY ABS(r.avg_temp_c - s.mu) / s.sigma DESC
    """)

    col_left, col_right = st.columns([1, 1])
    with col_left:
        st.metric("Anomalous Readings", len(anomalies))
    with col_right:
        st.metric(
            "Units Affected",
            anomalies["unit_code"].nunique() if len(anomalies) > 0 else 0,
        )

    if len(anomalies) > 0:
        # Z-score scatter
        st.subheader("Z-Score Distribution of Anomalies")
        cond_labels = {100: "Healthy", 20: "Reduced", 3: "Failing"}
        anomalies["condition_label"] = anomalies["cooler_condition"].map(cond_labels)
        fig = px.scatter(
            anomalies, x="unit_code", y="z_score",
            color="condition_label", size=anomalies["z_score"].abs(),
            color_discrete_map={
                "Healthy": "#2ecc71", "Reduced": "#f39c12", "Failing": "#e74c3c"
            },
            labels={"z_score": "Z-Score", "unit_code": "Unit"},
        )
        fig.add_hline(y=2, line_dash="dash", line_color="grey", annotation_text="z = 2")
        fig.add_hline(y=-2, line_dash="dash", line_color="grey", annotation_text="z = -2")
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, key="anomaly_scatter")

        # Anomaly table
        st.subheader("Anomaly Details")
        st.dataframe(
            anomalies[["unit_code", "region", "timestamp", "temp_c", "unit_mean", "z_score", "cooler_condition"]],
            width="stretch", hide_index=True,
        )
    else:
        st.info("No anomalies detected at the 2-sigma threshold.")


# =============================================================================
# PAGE: Unit Drilldown
# =============================================================================
elif page == "Unit Drilldown":
    st.title("Unit Drilldown")

    unit_list = units["unit_code"].tolist()
    selected_unit = st.sidebar.selectbox("Select Unit", unit_list)

    unit_info = units[units["unit_code"] == selected_unit].iloc[0]
    st.markdown(
        f"**{selected_unit}** — {unit_info['model']} | "
        f"{unit_info['region']}, {unit_info['site']} | "
        f"Installed: {unit_info['install_date']}"
    )

    unit_data = readings[readings["unit_code"] == selected_unit].sort_values("timestamp")

    # Rolling average
    unit_data["temp_4pt_avg"] = unit_data["avg_temp_c"].rolling(window=4, min_periods=1).mean()

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Temperature Over Time")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=unit_data["timestamp"], y=unit_data["avg_temp_c"],
            mode="lines", name="Temperature",
            line=dict(color="#3498db", width=1),
        ))
        fig.add_trace(go.Scatter(
            x=unit_data["timestamp"], y=unit_data["temp_4pt_avg"],
            mode="lines", name="4-pt Moving Avg",
            line=dict(color="#e74c3c", width=2),
        ))
        fig.update_layout(
            yaxis_title="Temperature (°C)",
            xaxis_title="", legend=dict(orientation="h", y=-0.2),
        )
        st.plotly_chart(fig, key="unit_temp")

    with col_right:
        st.subheader("Motor Power Over Time")
        fig = px.line(
            unit_data, x="timestamp", y="motor_power_w",
            labels={"motor_power_w": "Power (W)", "timestamp": ""},
        )
        fig.update_traces(line_color="#9b59b6")
        st.plotly_chart(fig, key="unit_power")

    # Condition timeline
    st.subheader("Cooler Condition Timeline")
    cond_map = {100: "Healthy", 20: "Reduced", 3: "Failing"}
    unit_data["cond_label"] = unit_data["cooler_condition"].map(cond_map)
    fig = px.scatter(
        unit_data, x="timestamp", y="cond_label",
        color="cond_label",
        color_discrete_map={
            "Healthy": "#2ecc71", "Reduced": "#f39c12", "Failing": "#e74c3c"
        },
        labels={"cond_label": "Condition", "timestamp": ""},
    )
    fig.update_layout(showlegend=False, yaxis_title="")
    st.plotly_chart(fig, key="unit_cond_timeline")

    # Unit readings table
    with st.expander("Raw Readings"):
        display_cols = [
            "timestamp", "avg_temp_c", "pressure_bar", "motor_power_w",
            "vibration_mm_s", "cooling_efficiency_pct", "flow_rate_l_min",
            "cooler_condition",
        ]
        st.dataframe(
            unit_data[display_cols].reset_index(drop=True),
            width="stretch", hide_index=True,
        )
