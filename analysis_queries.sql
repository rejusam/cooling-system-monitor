-- =========================================================================
-- Analytical queries on the cooling system monitoring database
-- Run: sqlite3 cooling_monitor.db < analysis_queries.sql
-- =========================================================================

.mode column
.headers on
.width 10 8 10 10 10 10 10

-- 1. Fleet overview: units per region with average health indicators
SELECT
    u.region,
    COUNT(DISTINCT u.unit_id) AS units,
    COUNT(*) AS readings,
    ROUND(AVG(r.avg_temp_c), 1) AS avg_temp,
    ROUND(AVG(r.motor_power_w), 0) AS avg_power,
    ROUND(AVG(r.cooling_efficiency_pct), 1) AS avg_eff
FROM readings r
JOIN units u ON r.unit_id = u.unit_id
GROUP BY u.region
ORDER BY units DESC;


-- 2. Cooler condition breakdown: how many readings at each degradation level
SELECT
    cooler_condition AS condition_pct,
    CASE cooler_condition
        WHEN 100 THEN 'Full efficiency'
        WHEN 20  THEN 'Reduced efficiency'
        WHEN 3   THEN 'Near failure'
    END AS label,
    COUNT(*) AS reading_count,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM readings), 1) AS pct_of_total
FROM readings
GROUP BY cooler_condition
ORDER BY cooler_condition DESC;


-- 3. Units with the worst average condition (candidates for maintenance)
SELECT
    u.unit_code,
    u.model,
    u.region,
    u.site,
    ROUND(AVG(r.cooler_condition), 0) AS avg_condition,
    ROUND(AVG(r.avg_temp_c), 1) AS avg_temp,
    ROUND(AVG(r.motor_power_w), 0) AS avg_power,
    COUNT(*) AS readings
FROM readings r
JOIN units u ON r.unit_id = u.unit_id
GROUP BY u.unit_id
ORDER BY avg_condition ASC
LIMIT 10;


-- 4. Temperature comparison: healthy vs degraded coolers
SELECT
    CASE
        WHEN cooler_condition = 100 THEN 'Healthy (100%)'
        WHEN cooler_condition = 20  THEN 'Reduced (20%)'
        WHEN cooler_condition = 3   THEN 'Failing (3%)'
    END AS condition_group,
    COUNT(*) AS n,
    ROUND(AVG(avg_temp_c), 2) AS mean_temp,
    ROUND(MIN(avg_temp_c), 2) AS min_temp,
    ROUND(MAX(avg_temp_c), 2) AS max_temp,
    ROUND(AVG(motor_power_w), 1) AS mean_power
FROM readings
GROUP BY cooler_condition
ORDER BY cooler_condition DESC;


-- 5. Hourly pattern: average temperature and power by hour of day
SELECT
    CAST(STRFTIME('%H', timestamp) AS INTEGER) AS hour,
    COUNT(*) AS readings,
    ROUND(AVG(avg_temp_c), 2) AS avg_temp,
    ROUND(AVG(motor_power_w), 1) AS avg_power,
    ROUND(AVG(cooling_efficiency_pct), 1) AS avg_efficiency
FROM readings
GROUP BY hour
ORDER BY hour;


-- 6. Anomaly detection: readings where temperature deviates more than 2
--    standard deviations from that unit's mean (per-unit Z-score approach)
WITH unit_stats AS (
    SELECT
        unit_id,
        AVG(avg_temp_c) AS mean_temp,
        -- Use population std dev approximation
        SQRT(AVG(avg_temp_c * avg_temp_c) - AVG(avg_temp_c) * AVG(avg_temp_c)) AS std_temp
    FROM readings
    GROUP BY unit_id
    HAVING std_temp > 0
)
SELECT
    u.unit_code,
    r.timestamp,
    ROUND(r.avg_temp_c, 2) AS temp_c,
    ROUND(s.mean_temp, 2) AS unit_mean,
    ROUND((r.avg_temp_c - s.mean_temp) / s.std_temp, 2) AS z_score,
    r.cooler_condition
FROM readings r
JOIN units u ON r.unit_id = u.unit_id
JOIN unit_stats s ON r.unit_id = s.unit_id
WHERE ABS(r.avg_temp_c - s.mean_temp) / s.std_temp > 2.0
ORDER BY ABS(r.avg_temp_c - s.mean_temp) / s.std_temp DESC
LIMIT 15;


-- 7. Correlation proxy: do failing coolers draw more power?
--    Compare average power consumption across condition levels
SELECT
    cooler_condition,
    ROUND(AVG(motor_power_w), 1) AS avg_power_w,
    ROUND(AVG(vibration_mm_s), 3) AS avg_vibration,
    ROUND(AVG(cooling_efficiency_pct), 1) AS avg_efficiency,
    ROUND(AVG(cooling_power_kw), 3) AS avg_cooling_kw
FROM readings
GROUP BY cooler_condition
ORDER BY cooler_condition;


-- 8. Multi-fault analysis: readings where multiple components are degraded
SELECT
    u.unit_code,
    r.timestamp,
    r.cooler_condition AS cooler,
    r.valve_condition AS valve,
    r.pump_leakage AS pump_leak,
    r.accumulator_bar AS accum,
    r.avg_temp_c AS temp,
    r.motor_power_w AS power
FROM readings r
JOIN units u ON r.unit_id = u.unit_id
WHERE r.cooler_condition < 100
  AND r.valve_condition < 100
  AND r.pump_leakage > 0
ORDER BY r.cooler_condition ASC, r.valve_condition ASC
LIMIT 10;


-- 9. Running average: 4-reading moving average of temperature per unit
--    (window function)
SELECT
    u.unit_code,
    r.timestamp,
    ROUND(r.avg_temp_c, 2) AS temp_c,
    ROUND(AVG(r.avg_temp_c) OVER (
        PARTITION BY r.unit_id
        ORDER BY r.timestamp
        ROWS BETWEEN 3 PRECEDING AND CURRENT ROW
    ), 2) AS temp_moving_avg,
    r.cooler_condition
FROM readings r
JOIN units u ON r.unit_id = u.unit_id
WHERE u.unit_code = 'CLR-0001'
ORDER BY r.timestamp
LIMIT 20;


-- 10. Site-level summary: which sites need attention?
SELECT
    u.region || ' - ' || u.site AS location,
    COUNT(DISTINCT u.unit_id) AS units,
    ROUND(AVG(r.cooler_condition), 0) AS avg_condition,
    SUM(CASE WHEN r.cooler_condition = 3 THEN 1 ELSE 0 END) AS failure_readings,
    ROUND(
        SUM(CASE WHEN r.cooler_condition = 3 THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
        1
    ) AS failure_pct
FROM readings r
JOIN units u ON r.unit_id = u.unit_id
GROUP BY u.region, u.site
ORDER BY failure_pct DESC;
