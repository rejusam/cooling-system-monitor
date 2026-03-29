"""
Run analytical queries against the cooling monitor database.

Usage:
    python run_analysis.py
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "cooling_monitor.db"
SQL_PATH = Path(__file__).parent / "analysis_queries.sql"


def run_query(con, title, sql):
    """Execute a query and print results as a formatted table."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)

    cur = con.execute(sql)
    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()

    if not rows:
        print("  (no results)")
        return

    # Calculate column widths
    widths = [len(c) for c in columns]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))

    # Print header
    header = "  ".join(str(c).ljust(w) for c, w in zip(columns, widths))
    print(header)
    print("  ".join("-" * w for w in widths))

    # Print rows
    for row in rows:
        line = "  ".join(str(v).ljust(w) for v, w in zip(row, widths))
        print(line)

    print(f"({len(rows)} rows)")


def main():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("Run etl_pipeline.py first.")
        return

    con = sqlite3.connect(str(DB_PATH))

    queries = [
        ("Fleet Overview by Region",
         """SELECT u.region, COUNT(DISTINCT u.unit_id) AS units, COUNT(*) AS readings,
            ROUND(AVG(r.avg_temp_c), 1) AS avg_temp,
            ROUND(AVG(r.motor_power_w), 0) AS avg_power
            FROM readings r JOIN units u ON r.unit_id = u.unit_id
            GROUP BY u.region ORDER BY units DESC"""),

        ("Cooler Condition Distribution",
         """SELECT cooler_condition AS cond_pct,
            CASE cooler_condition WHEN 100 THEN 'Full' WHEN 20 THEN 'Reduced' WHEN 3 THEN 'Failing' END AS label,
            COUNT(*) AS count,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM readings), 1) AS pct
            FROM readings GROUP BY cooler_condition ORDER BY cooler_condition DESC"""),

        ("Worst Units (maintenance candidates)",
         """SELECT u.unit_code, u.model, u.region,
            ROUND(AVG(r.cooler_condition), 0) AS avg_cond,
            ROUND(AVG(r.avg_temp_c), 1) AS avg_temp
            FROM readings r JOIN units u ON r.unit_id = u.unit_id
            GROUP BY u.unit_id ORDER BY avg_cond ASC LIMIT 5"""),

        ("Healthy vs Degraded: Temperature & Power",
         """SELECT CASE WHEN cooler_condition = 100 THEN 'Healthy'
            WHEN cooler_condition = 20 THEN 'Reduced' ELSE 'Failing' END AS status,
            COUNT(*) AS n, ROUND(AVG(avg_temp_c), 2) AS mean_temp,
            ROUND(AVG(motor_power_w), 1) AS mean_power
            FROM readings GROUP BY cooler_condition ORDER BY cooler_condition DESC"""),

        ("Temperature Anomalies (Z-score > 2)",
         """WITH stats AS (
                SELECT unit_id, AVG(avg_temp_c) AS mu,
                SQRT(AVG(avg_temp_c * avg_temp_c) - AVG(avg_temp_c) * AVG(avg_temp_c)) AS sigma
                FROM readings GROUP BY unit_id HAVING sigma > 0
            )
            SELECT u.unit_code, r.timestamp, ROUND(r.avg_temp_c, 2) AS temp,
            ROUND((r.avg_temp_c - s.mu) / s.sigma, 2) AS z_score, r.cooler_condition AS cond
            FROM readings r JOIN units u ON r.unit_id = u.unit_id
            JOIN stats s ON r.unit_id = s.unit_id
            WHERE ABS(r.avg_temp_c - s.mu) / s.sigma > 2.0
            ORDER BY ABS(r.avg_temp_c - s.mu) / s.sigma DESC LIMIT 10"""),

        ("Site Failure Rate",
         """SELECT u.region || ' - ' || u.site AS location,
            COUNT(DISTINCT u.unit_id) AS units,
            SUM(CASE WHEN r.cooler_condition = 3 THEN 1 ELSE 0 END) AS fail_readings,
            ROUND(SUM(CASE WHEN r.cooler_condition = 3 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS fail_pct
            FROM readings r JOIN units u ON r.unit_id = u.unit_id
            GROUP BY u.region, u.site ORDER BY fail_pct DESC"""),

        ("Moving Average: CLR-0001 Temperature (window function)",
         """SELECT u.unit_code, r.timestamp, ROUND(r.avg_temp_c, 2) AS temp_c,
            ROUND(AVG(r.avg_temp_c) OVER (
                PARTITION BY r.unit_id ORDER BY r.timestamp
                ROWS BETWEEN 3 PRECEDING AND CURRENT ROW
            ), 2) AS temp_4pt_avg, r.cooler_condition AS cond
            FROM readings r JOIN units u ON r.unit_id = u.unit_id
            WHERE u.unit_code = 'CLR-0001' ORDER BY r.timestamp LIMIT 15"""),
    ]

    for title, sql in queries:
        run_query(con, title, sql)

    con.close()
    print(f"\nAll queries executed against {DB_PATH.name}")


if __name__ == "__main__":
    main()
