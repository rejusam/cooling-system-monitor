# Cooling System Condition Monitoring -- ETL Pipeline

## Background

Earlier this year I built a [commercial analytics project](https://github.com/rejusam/bakery-sales-intelligence) that explored transaction-level patterns in retail data -- product pairing, temporal demand, weather effects. That work focused on the analysis layer: what insights can you pull from data that's already structured and ready to query.

But it left me with a question that kept nagging at me: **what happens before the analysis?** In a real operation -- say, a fleet of connected coolers across dozens of sites -- someone has to take raw sensor dumps and turn them into something queryable. That's the data engineering problem, and it's where I wanted to go deeper.

I went looking for a public dataset that had real sensor data from cooling equipment, and found the [UCI Hydraulic Systems dataset](https://archive.ics.uci.edu/dataset/447). It comes from a test rig at ZeMA gGmbH in Germany where they ran a hydraulic system with a cooling-filtration circuit through 2,205 operational cycles while varying the condition of four components -- including the cooler. Each cycle captures 60 seconds of data from 17 sensors: temperature, pressure, motor power, vibration, cooling efficiency, and flow rate. The cooler condition is labelled at three degradation levels (100%, 20%, 3%), which gives you ground truth for condition monitoring.

What I liked about this dataset is that it captures the same kind of signals you'd see in commercial refrigeration -- temperature trends, compressor power draw, efficiency degradation -- but with labelled failure states that you rarely get from production equipment.

## What I Built

A straightforward ETL pipeline in Python that takes the raw sensor files and turns them into a clean, queryable SQLite database, with a Streamlit dashboard for exploring the results.

**Extract**: Load 10 sensor files (tab-delimited matrices where each row is a 60-second cycle) and the condition labels.

**Transform**: Average each 60-second cycle down to a single reading per sensor. Map the 2,205 cycles across 20 cooling units spread over 10 sites in 5 NZ regions. Generate 15-minute timestamps to simulate a fleet reporting cadence.

**Load**: Write everything into a SQLite database with two tables (`units` and `readings`), a foreign key relationship, and indexes on the columns I'd be querying most.

```
  Raw .txt files       Python (NumPy)        SQLite         Streamlit
  ┌────────────┐      ┌──────────────┐      ┌────────────┐  ┌──────────────┐
  │ 10 sensor  │─────>│ Cycle means  │─────>│ units (20) │─>│ Interactive  │
  │ matrices + │      │ Fleet assign │      │ readings   │  │ dashboard    │
  │ labels     │      │ Timestamps   │      │  (2,200)   │  │              │
  └────────────┘      └──────────────┘      └────────────┘  └──────────────┘
```

On top of the database I wrote 10 analytical SQL queries covering the kinds of questions you'd ask about a cooling fleet:

- Which units are degraded and need maintenance?
- How does temperature behaviour differ between healthy and failing coolers?
- Can we detect anomalous readings using per-unit Z-scores?
- What do hourly operational patterns look like?
- Which sites have the highest failure rates?

The queries use JOINs, CTEs, window functions, conditional aggregation, and subqueries -- the things I'd actually need day-to-day working with sensor data in a relational database.

I also built a Streamlit dashboard on top of the database so you can visually explore the fleet -- condition breakdowns, temperature distributions, per-unit Z-score anomaly detection, and a drilldown view where you can pick any unit and see its sensor history with a rolling average overlay.

## Data Source

**UCI Condition Monitoring of Hydraulic Systems**
- https://archive.ics.uci.edu/dataset/447
- Helwig et al., "Condition Monitoring of a Complex Hydraulic System Using Multivariate Statistics", I2MTC-2015, doi:10.1109/I2MTC.2015.7151267
- 2,205 cycles, 17 sensors, cooler condition labels at 100% / 20% / 3%

## Database Schema

```
units                               readings
──────────────────                  ──────────────────────────────
unit_id     (PK)                    reading_id   (PK, autoincrement)
unit_code   (e.g. CLR-0001)        unit_id      (FK → units)
model                               timestamp
region                              avg_temp_c
site                                pressure_bar
install_date                        motor_power_w
                                    vibration_mm_s
                                    cooling_efficiency_pct
                                    cooling_power_kw
                                    flow_rate_l_min
                                    cooler_condition  (100/20/3)
                                    valve_condition
                                    pump_leakage
                                    accumulator_bar
                                    is_stable
```

## Running It

```bash
# install dependencies
pip install numpy streamlit plotly pandas

# download the dataset
mkdir -p data/raw/hydraulic_systems
curl -L -o hs.zip "https://archive.ics.uci.edu/static/public/447/condition+monitoring+of+hydraulic+systems.zip"
unzip hs.zip -d data/raw/hydraulic_systems/

# run the pipeline
python etl_pipeline.py

# run the analysis (terminal)
python run_analysis.py

# or query directly
sqlite3 cooling_monitor.db < analysis_queries.sql

# launch the dashboard
streamlit run dashboard.py
```

## What I Learned

The thing that surprised me most was how clearly cooler condition shows up in the temperature data. Failing coolers (3% condition) run about 18 C hotter on average than healthy ones. That's a massive signal -- you don't need sophisticated ML to flag these units, a simple statistical threshold per unit catches them cleanly.

I also found that the Z-score approach to anomaly detection works better than fixed thresholds here. Each unit has a slightly different operating baseline (depends on where it sits in the test rig's circuit), so what counts as "anomalous" needs to be relative to that unit's own history. This is something I'd expect to matter even more in a real fleet where coolers are in different ambient conditions.

## Files

```
etl_pipeline.py       -- the ETL script (extract, transform, load)
run_analysis.py       -- runs the SQL queries and prints formatted results
analysis_queries.sql  -- standalone SQL file (10 queries)
dashboard.py          -- Streamlit dashboard (fleet overview, conditions, anomalies, unit drilldown)
cooling_monitor.db    -- generated database (not tracked in git)
```
