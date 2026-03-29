"""
ETL Pipeline: Hydraulic Cooling System Condition Monitoring

Extracts sensor data from the UCI Hydraulic Systems dataset,
transforms it into a clean relational structure, and loads it
into a SQLite database for analysis.

Source: https://archive.ics.uci.edu/dataset/447
Citation: Helwig et al., I2MTC-2015, doi:10.1109/I2MTC.2015.7151267

Usage:
    python etl_pipeline.py
"""
import sqlite3
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# -- Config ----------------------------------------------------------------
RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "hydraulic_systems"
DB_PATH = Path(__file__).parent / "cooling_monitor.db"
NUM_UNITS = 20
START_DATE = datetime(2024, 1, 1)
INTERVAL_MIN = 15


# ==========================================================================
# EXTRACT
# ==========================================================================
def extract_sensor(filename):
    """Read a tab-delimited sensor file. Each row is one 60-second cycle."""
    path = RAW_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing: {path}")
    return np.loadtxt(path, delimiter="\t")


def extract_all():
    """Load all sensor files and condition labels."""
    print("[Extract] Loading sensor files...")
    data = {
        "ts1": extract_sensor("TS1.txt"),   # temperature sensor 1 (C)
        "ts2": extract_sensor("TS2.txt"),   # temperature sensor 2 (C)
        "ts3": extract_sensor("TS3.txt"),   # temperature sensor 3 (C)
        "ts4": extract_sensor("TS4.txt"),   # temperature sensor 4 (C)
        "ps1": extract_sensor("PS1.txt"),   # pressure sensor 1 (bar)
        "eps1": extract_sensor("EPS1.txt"), # motor power (W)
        "vs1": extract_sensor("VS1.txt"),   # vibration (mm/s)
        "ce": extract_sensor("CE.txt"),     # cooling efficiency (%)
        "cp": extract_sensor("CP.txt"),     # cooling power (kW)
        "fs1": extract_sensor("FS1.txt"),   # volume flow (l/min)
    }

    # Condition labels: cooler, valve, pump, accumulator, stable flag
    profile = np.loadtxt(RAW_DIR / "profile.txt", delimiter="\t").astype(int)

    n_cycles = data["ts1"].shape[0]
    print(f"  Loaded {n_cycles} cycles, {len(data)} sensors")
    return data, profile, n_cycles


# ==========================================================================
# TRANSFORM
# ==========================================================================

# Simulated fleet metadata
SITES = [
    ("Auckland", "Rosedale"), ("Auckland", "Ponsonby"), ("Auckland", "Newmarket"),
    ("Wellington", "CBD"), ("Wellington", "Petone"),
    ("Christchurch", "Riccarton"), ("Christchurch", "Airport"),
    ("Hamilton", "The Base"), ("Hamilton", "Chartwell"),
    ("Dunedin", "George St"),
]

MODELS = ["SC-500", "DC-800", "OD-1200", "MC-300"]


def build_units():
    """Create metadata for each cooling unit in the fleet."""
    units = []
    for i in range(NUM_UNITS):
        region, site = SITES[i % len(SITES)]
        units.append({
            "unit_id": i + 1,
            "unit_code": f"CLR-{i+1:04d}",
            "model": MODELS[i % len(MODELS)],
            "region": region,
            "site": site,
            "install_date": (START_DATE - timedelta(days=180 + i * 30)).date().isoformat(),
        })
    return units


def transform(data, profile, n_cycles):
    """
    Convert raw cycle-level sensor matrices into flat rows.

    Each cycle becomes one reading: we take the mean of the 60-second
    window for each sensor. Cycles are distributed across cooling units.
    """
    print("[Transform] Building readings...")
    cycles_per_unit = n_cycles // NUM_UNITS
    units = build_units()
    readings = []

    for unit_idx, unit in enumerate(units):
        start_cycle = unit_idx * cycles_per_unit
        end_cycle = min(start_cycle + cycles_per_unit, n_cycles)

        for offset, cycle in enumerate(range(start_cycle, end_cycle)):
            ts = START_DATE + timedelta(minutes=offset * INTERVAL_MIN)

            readings.append({
                "unit_id": unit["unit_id"],
                "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "avg_temp_c": round(float(np.mean([
                    data["ts1"][cycle].mean(),
                    data["ts2"][cycle].mean(),
                    data["ts3"][cycle].mean(),
                    data["ts4"][cycle].mean(),
                ])), 2),
                "pressure_bar": round(float(data["ps1"][cycle].mean()), 2),
                "motor_power_w": round(float(data["eps1"][cycle].mean()), 1),
                "vibration_mm_s": round(float(data["vs1"][cycle].mean()), 3),
                "cooling_efficiency_pct": round(float(data["ce"][cycle].mean()), 1),
                "cooling_power_kw": round(float(data["cp"][cycle].mean()), 3),
                "flow_rate_l_min": round(float(data["fs1"][cycle].mean()), 2),
                "cooler_condition": int(profile[cycle, 0]),
                "valve_condition": int(profile[cycle, 1]),
                "pump_leakage": int(profile[cycle, 2]),
                "accumulator_bar": int(profile[cycle, 3]),
                "is_stable": bool(profile[cycle, 4] == 0),
            })

    print(f"  Generated {len(readings)} readings for {len(units)} units")
    return units, readings


# ==========================================================================
# LOAD
# ==========================================================================
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS units (
    unit_id       INTEGER PRIMARY KEY,
    unit_code     TEXT NOT NULL UNIQUE,
    model         TEXT NOT NULL,
    region        TEXT NOT NULL,
    site          TEXT NOT NULL,
    install_date  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS readings (
    reading_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id                 INTEGER NOT NULL REFERENCES units(unit_id),
    timestamp               TEXT NOT NULL,
    avg_temp_c              REAL,
    pressure_bar            REAL,
    motor_power_w           REAL,
    vibration_mm_s          REAL,
    cooling_efficiency_pct  REAL,
    cooling_power_kw        REAL,
    flow_rate_l_min         REAL,
    cooler_condition        INTEGER,
    valve_condition         INTEGER,
    pump_leakage            INTEGER,
    accumulator_bar         INTEGER,
    is_stable               INTEGER
);

CREATE INDEX IF NOT EXISTS idx_readings_unit ON readings(unit_id);
CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(timestamp);
CREATE INDEX IF NOT EXISTS idx_readings_condition ON readings(cooler_condition);
"""


def load(units, readings):
    """Create SQLite database and insert all data."""
    print(f"[Load] Writing to {DB_PATH.name}...")

    if DB_PATH.exists():
        DB_PATH.unlink()

    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()

    # Create schema
    cur.executescript(CREATE_TABLES_SQL)

    # Insert units
    cur.executemany(
        "INSERT INTO units (unit_id, unit_code, model, region, site, install_date) "
        "VALUES (:unit_id, :unit_code, :model, :region, :site, :install_date)",
        units,
    )

    # Insert readings
    reading_cols = [
        "unit_id", "timestamp", "avg_temp_c", "pressure_bar", "motor_power_w",
        "vibration_mm_s", "cooling_efficiency_pct", "cooling_power_kw",
        "flow_rate_l_min", "cooler_condition", "valve_condition",
        "pump_leakage", "accumulator_bar", "is_stable",
    ]
    placeholders = ", ".join(f":{c}" for c in reading_cols)
    cur.executemany(
        f"INSERT INTO readings ({', '.join(reading_cols)}) VALUES ({placeholders})",
        readings,
    )

    con.commit()
    row_count = cur.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    print(f"  units: {len(units)} rows")
    print(f"  readings: {row_count} rows")
    con.close()


# ==========================================================================
# MAIN
# ==========================================================================
def main():
    print("=" * 50)
    print("Cooling System ETL Pipeline")
    print("=" * 50)

    data, profile, n_cycles = extract_all()
    units, readings = transform(data, profile, n_cycles)
    load(units, readings)

    print("=" * 50)
    print("Done.")
    print("=" * 50)


if __name__ == "__main__":
    main()
