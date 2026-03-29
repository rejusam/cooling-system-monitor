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
    return pd.read_sql_query(sql, get_connection())


# -- Sidebar ------------------------------------------------------------------
st.sidebar.title("Cooling Fleet Monitor")
st.sidebar.markdown(
    "Sensor data from the "
    "[UCI Hydraulic Systems dataset](https://archive.ics.uci.edu/dataset/447) "
    "(ZeMA, Germany), mapped to a simulated fleet of 20 cooling "
    "units across 5 NZ regions."
)

page = st.sidebar.radio(
    "View",
    [
        "Fleet Overview",
        "Maintenance Candidates",
        "Healthy vs Failing",
        "Anomaly Detection",
        "Hourly Patterns",
        "Site Failure Rates",
        "Unit Drilldown",
    ],
)

# -- Data ---------------------------------------------------------------------
readings = load_query("""
    SELECT r.*, u.unit_code, u.model, u.region, u.site
    FROM readings r JOIN units u ON r.unit_id = u.unit_id
""")
readings["timestamp"] = pd.to_datetime(readings["timestamp"])

units = load_query("SELECT * FROM units")

COND_COLORS = {"Healthy": "#2ecc71", "Reduced": "#f39c12", "Failing": "#e74c3c"}
COND_LABELS = {100: "Healthy", 20: "Reduced", 3: "Failing"}


# =============================================================================
# PAGE: Fleet Overview
# =============================================================================
if page == "Fleet Overview":
    st.title("Fleet Overview")

    total_units = len(units)
    total_readings = len(readings)
    failing_units = readings[readings["cooler_condition"] == 3]["unit_id"].nunique()
    avg_temp = readings["avg_temp_c"].mean()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Units", total_units)
    c2.metric("Total Readings", f"{total_readings:,}")
    c3.metric("Units with Failures", failing_units)
    c4.metric("Avg Temperature", f"{avg_temp:.1f} °C")

    st.markdown("---")

    col_left, col_right = st.columns(2)

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

    # Region-level stats table
    st.subheader("Region Summary")
    region_stats = load_query("""
        SELECT u.region,
            COUNT(DISTINCT u.unit_id) AS units,
            COUNT(*) AS readings,
            ROUND(AVG(r.avg_temp_c), 1) AS avg_temp_c,
            ROUND(AVG(r.motor_power_w), 0) AS avg_power_w,
            ROUND(AVG(r.cooling_efficiency_pct), 1) AS avg_efficiency_pct
        FROM readings r JOIN units u ON r.unit_id = u.unit_id
        GROUP BY u.region ORDER BY units DESC
    """)
    st.dataframe(region_stats, width="stretch", hide_index=True)


# =============================================================================
# PAGE: Maintenance Candidates
# "Which units are degraded and need maintenance?"
# =============================================================================
elif page == "Maintenance Candidates":
    st.title("Which units are degraded and need maintenance?")

    worst_units = load_query("""
        SELECT u.unit_code, u.model, u.region, u.site,
            ROUND(AVG(r.cooler_condition), 0) AS avg_condition,
            ROUND(AVG(r.avg_temp_c), 1) AS avg_temp_c,
            ROUND(AVG(r.motor_power_w), 0) AS avg_power_w,
            SUM(CASE WHEN r.cooler_condition = 3 THEN 1 ELSE 0 END) AS failure_readings,
            COUNT(*) AS total_readings
        FROM readings r JOIN units u ON r.unit_id = u.unit_id
        GROUP BY u.unit_id
        ORDER BY avg_condition ASC
    """)

    # Highlight the worst
    urgent = worst_units[worst_units["avg_condition"] <= 20]
    st.metric("Units needing attention", len(urgent))

    st.markdown("---")

    # Bar chart: average condition per unit
    st.subheader("Average Condition by Unit")
    fig = px.bar(
        worst_units, x="unit_code", y="avg_condition",
        color="avg_condition",
        color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
        range_color=[0, 100],
        labels={"avg_condition": "Avg Condition (%)", "unit_code": ""},
    )
    fig.add_hline(y=50, line_dash="dash", line_color="grey",
                  annotation_text="50% threshold")
    fig.update_layout(xaxis_tickangle=-45, coloraxis_showscale=False)
    st.plotly_chart(fig, key="maint_bar")

    # Full table
    st.subheader("All Units Ranked by Condition")
    st.dataframe(worst_units, width="stretch", hide_index=True)


# =============================================================================
# PAGE: Healthy vs Failing
# "How does temperature behaviour differ between healthy and failing coolers?"
# =============================================================================
elif page == "Healthy vs Failing":
    st.title("How does temperature differ between healthy and failing coolers?")

    plot_df = readings.copy()
    plot_df["condition_label"] = plot_df["cooler_condition"].map(COND_LABELS)

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Temperature Distribution")
        fig = px.box(
            plot_df, x="condition_label", y="avg_temp_c",
            color="condition_label", color_discrete_map=COND_COLORS,
            labels={"avg_temp_c": "Avg Temperature (°C)", "condition_label": ""},
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, key="temp_box")

    with col_right:
        st.subheader("Motor Power Distribution")
        fig = px.box(
            plot_df, x="condition_label", y="motor_power_w",
            color="condition_label", color_discrete_map=COND_COLORS,
            labels={"motor_power_w": "Motor Power (W)", "condition_label": ""},
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, key="power_box")

    # Summary stats table
    st.subheader("Group Statistics")
    cond_stats = load_query("""
        SELECT
            CASE WHEN cooler_condition = 100 THEN 'Healthy (100%)'
                 WHEN cooler_condition = 20  THEN 'Reduced (20%)'
                 ELSE 'Failing (3%)' END AS condition_group,
            COUNT(*) AS n,
            ROUND(AVG(avg_temp_c), 2) AS mean_temp_c,
            ROUND(MIN(avg_temp_c), 2) AS min_temp_c,
            ROUND(MAX(avg_temp_c), 2) AS max_temp_c,
            ROUND(AVG(motor_power_w), 1) AS mean_power_w,
            ROUND(AVG(cooling_efficiency_pct), 1) AS mean_efficiency_pct
        FROM readings
        GROUP BY cooler_condition
        ORDER BY cooler_condition DESC
    """)
    st.dataframe(cond_stats, width="stretch", hide_index=True)

    # Correlation: power & efficiency vs condition
    st.subheader("Power & Efficiency by Condition Level")
    corr_data = load_query("""
        SELECT cooler_condition,
            ROUND(AVG(motor_power_w), 1) AS avg_power_w,
            ROUND(AVG(cooling_efficiency_pct), 1) AS avg_efficiency_pct,
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
        y=corr_data["avg_efficiency_pct"], name="Avg Efficiency (%)",
    ))
    fig.update_layout(
        barmode="group", xaxis_title="Cooler Condition", yaxis_title="Value",
    )
    st.plotly_chart(fig, key="corr_bars")


# =============================================================================
# PAGE: Anomaly Detection
# "Can we detect anomalous readings using per-unit Z-scores?"
# =============================================================================
elif page == "Anomaly Detection":
    st.title("Can we detect anomalous readings using per-unit Z-scores?")
    st.markdown(
        "Each unit has a different operating baseline, so a fixed temperature "
        "threshold doesn't work well. Instead, this flags readings where "
        "temperature deviates more than **2 standard deviations** from that "
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

    c1, c2, c3 = st.columns(3)
    c1.metric("Anomalous Readings", len(anomalies))
    c2.metric("Units Affected", anomalies["unit_code"].nunique() if len(anomalies) > 0 else 0)
    failing_anomalies = anomalies[anomalies["cooler_condition"] == 3] if len(anomalies) > 0 else anomalies
    c3.metric("Linked to Failing Condition", len(failing_anomalies))

    if len(anomalies) > 0:
        st.markdown("---")

        # Z-score scatter
        st.subheader("Z-Score by Unit")
        anomalies["condition_label"] = anomalies["cooler_condition"].map(COND_LABELS)
        fig = px.scatter(
            anomalies, x="unit_code", y="z_score",
            color="condition_label", size=anomalies["z_score"].abs(),
            color_discrete_map=COND_COLORS,
            labels={"z_score": "Z-Score", "unit_code": "Unit"},
        )
        fig.add_hline(y=2, line_dash="dash", line_color="grey", annotation_text="z = 2")
        fig.add_hline(y=-2, line_dash="dash", line_color="grey", annotation_text="z = -2")
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, key="anomaly_scatter")

        # Table
        st.subheader("Anomaly Details")
        st.dataframe(
            anomalies[["unit_code", "region", "timestamp", "temp_c", "unit_mean", "z_score", "cooler_condition"]],
            width="stretch", hide_index=True,
        )
    else:
        st.info("No anomalies detected at the 2-sigma threshold.")


# =============================================================================
# PAGE: Hourly Patterns
# "What do hourly operational patterns look like?"
# =============================================================================
elif page == "Hourly Patterns":
    st.title("What do hourly operational patterns look like?")

    readings["hour"] = readings["timestamp"].dt.hour

    hourly = readings.groupby("hour").agg(
        readings=("reading_id", "count"),
        avg_temp_c=("avg_temp_c", "mean"),
        avg_power_w=("motor_power_w", "mean"),
        avg_efficiency=("cooling_efficiency_pct", "mean"),
    ).reset_index()
    hourly = hourly.round(2)

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Avg Temperature by Hour")
        fig = px.line(
            hourly, x="hour", y="avg_temp_c",
            markers=True,
            labels={"avg_temp_c": "Temperature (°C)", "hour": "Hour of Day"},
        )
        fig.update_traces(line_color="#e74c3c")
        fig.update_layout(xaxis=dict(dtick=1))
        st.plotly_chart(fig, key="hourly_temp")

    with col_right:
        st.subheader("Avg Motor Power by Hour")
        fig = px.line(
            hourly, x="hour", y="avg_power_w",
            markers=True,
            labels={"avg_power_w": "Power (W)", "hour": "Hour of Day"},
        )
        fig.update_traces(line_color="#9b59b6")
        fig.update_layout(xaxis=dict(dtick=1))
        st.plotly_chart(fig, key="hourly_power")

    st.subheader("Avg Cooling Efficiency by Hour")
    fig = px.bar(
        hourly, x="hour", y="avg_efficiency",
        labels={"avg_efficiency": "Efficiency (%)", "hour": "Hour of Day"},
        text_auto=".1f",
    )
    fig.update_traces(marker_color="#3498db")
    fig.update_layout(xaxis=dict(dtick=1))
    st.plotly_chart(fig, key="hourly_eff")

    # Reading count by hour
    st.subheader("Readings per Hour")
    fig = px.bar(
        hourly, x="hour", y="readings",
        labels={"readings": "Count", "hour": "Hour of Day"},
        text_auto=True,
    )
    fig.update_traces(marker_color="#95a5a6")
    fig.update_layout(xaxis=dict(dtick=1))
    st.plotly_chart(fig, key="hourly_count")


# =============================================================================
# PAGE: Site Failure Rates
# "Which sites have the highest failure rates?"
# =============================================================================
elif page == "Site Failure Rates":
    st.title("Which sites have the highest failure rates?")

    site_stats = load_query("""
        SELECT u.region, u.site,
            u.region || ' — ' || u.site AS location,
            COUNT(DISTINCT u.unit_id) AS units,
            ROUND(AVG(r.cooler_condition), 0) AS avg_condition,
            SUM(CASE WHEN r.cooler_condition = 3 THEN 1 ELSE 0 END) AS failure_readings,
            COUNT(*) AS total_readings,
            ROUND(SUM(CASE WHEN r.cooler_condition = 3 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS failure_pct
        FROM readings r JOIN units u ON r.unit_id = u.unit_id
        GROUP BY u.region, u.site
        ORDER BY failure_pct DESC
    """)

    worst_site = site_stats.iloc[0]
    best_site = site_stats.iloc[-1]

    c1, c2 = st.columns(2)
    c1.metric("Highest failure rate", f"{worst_site['location']}",
              delta=f"{worst_site['failure_pct']}%", delta_color="inverse")
    c2.metric("Lowest failure rate", f"{best_site['location']}",
              delta=f"{best_site['failure_pct']}%", delta_color="normal")

    st.markdown("---")

    # Horizontal bar chart
    st.subheader("Failure Rate by Site")
    fig = px.bar(
        site_stats.sort_values("failure_pct"),
        x="failure_pct", y="location", orientation="h",
        color="failure_pct",
        color_continuous_scale=["#2ecc71", "#f39c12", "#e74c3c"],
        labels={"failure_pct": "Failure %", "location": ""},
    )
    fig.update_layout(coloraxis_showscale=False, yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, key="site_fail_bar")

    # Full table
    st.subheader("Site Details")
    st.dataframe(
        site_stats[["location", "units", "avg_condition", "failure_readings", "total_readings", "failure_pct"]],
        width="stretch", hide_index=True,
    )


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
    unit_data["temp_4pt_avg"] = unit_data["avg_temp_c"].rolling(window=4, min_periods=1).mean()

    # KPIs for this unit
    avg_cond = unit_data["cooler_condition"].mean()
    fail_pct = (unit_data["cooler_condition"] == 3).sum() / len(unit_data) * 100
    c1, c2, c3 = st.columns(3)
    c1.metric("Avg Condition", f"{avg_cond:.0f}%")
    c2.metric("Failure Readings", f"{fail_pct:.1f}%")
    c3.metric("Total Readings", len(unit_data))

    st.markdown("---")

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
    unit_data["cond_label"] = unit_data["cooler_condition"].map(COND_LABELS)
    fig = px.scatter(
        unit_data, x="timestamp", y="cond_label",
        color="cond_label", color_discrete_map=COND_COLORS,
        labels={"cond_label": "Condition", "timestamp": ""},
    )
    fig.update_layout(showlegend=False, yaxis_title="")
    st.plotly_chart(fig, key="unit_cond_timeline")

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
