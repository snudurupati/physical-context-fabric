// ============================================================
// Physical Context Fabric — Cypher Query Library
// Operational queries for robot telemetry knowledge graph
// ============================================================


// ------------------------------------------------------------
// 1. All anomalies for a robot, most recent first
// ------------------------------------------------------------
MATCH (r:Robot {robot_id: 'jazzypi'})-[:EXPERIENCED]->(a:Anomaly)
RETURN r.robot_id, a.type, a.timestamp, a.position_x, a.position_y,
       a.prev_velocity, a.curr_velocity
ORDER BY a.timestamp DESC
LIMIT 20;


// ------------------------------------------------------------
// 2. Anomaly frequency by type
// ------------------------------------------------------------
MATCH (r:Robot)-[:EXPERIENCED]->(a:Anomaly)
RETURN r.robot_id,
       a.type,
       count(a) AS occurrences,
       avg(a.prev_velocity) AS avg_velocity_before,
       avg(a.position_x) AS avg_x,
       avg(a.position_y) AS avg_y
ORDER BY occurrences DESC;


// ------------------------------------------------------------
// 3. Geographic clustering — where do anomalies occur?
//    Buckets position into 0.5m grid cells
// ------------------------------------------------------------
MATCH (r:Robot)-[:EXPERIENCED]->(a:Anomaly)-[:OCCURRED_IN]->(es:Environment_State)
RETURN r.robot_id,
       a.type,
       round(a.position_x * 2) / 2 AS grid_x,
       round(a.position_y * 2) / 2 AS grid_y,
       count(a) AS anomalies_in_cell
ORDER BY anomalies_in_cell DESC
LIMIT 10;


// ------------------------------------------------------------
// 4. Events preceding the last anomaly
//    "What was the robot doing before it stopped?"
// ------------------------------------------------------------
MATCH (r:Robot {robot_id: 'jazzypi'})-[:GENERATED]->(e:Event)
MATCH (r)-[:EXPERIENCED]->(a:Anomaly)
WHERE toFloat(e.timestamp) < toFloat(a.timestamp)
  AND toFloat(e.timestamp) > toFloat(a.timestamp) - 30
RETURN e.timestamp, e.event_type, e.position_x, e.position_y,
       e.linear_vel, e.angular_vel
ORDER BY e.timestamp DESC
LIMIT 20;


// ------------------------------------------------------------
// 5. Robot operational summary
// ------------------------------------------------------------
MATCH (r:Robot)
OPTIONAL MATCH (r)-[:EXPERIENCED]->(a:Anomaly)
OPTIONAL MATCH (r)-[:GENERATED]->(e:Event)
RETURN r.robot_id,
       r.first_seen,
       r.last_seen,
       count(DISTINCT a) AS total_anomalies,
       count(DISTINCT e) AS total_events;


// ------------------------------------------------------------
// 6. Most dangerous map regions
//    Regions with highest anomaly density
// ------------------------------------------------------------
MATCH (r:Robot)-[:EXPERIENCED]->(a:Anomaly)-[:OCCURRED_IN]->(es:Environment_State)
WITH round(es.position_x * 2) / 2 AS grid_x,
     round(es.position_y * 2) / 2 AS grid_y,
     collect(a.type) AS anomaly_types,
     count(a) AS total
RETURN grid_x, grid_y, total, anomaly_types
ORDER BY total DESC
LIMIT 5;


// ------------------------------------------------------------
// 7. Time between anomalies — is the robot degrading?
// ------------------------------------------------------------
MATCH (r:Robot {robot_id: 'jazzypi'})-[:EXPERIENCED]->(a:Anomaly)
WITH a ORDER BY a.timestamp ASC
WITH collect(a) AS anomalies
UNWIND range(0, size(anomalies) - 2) AS i
WITH anomalies[i] AS a1, anomalies[i+1] AS a2
RETURN a1.timestamp AS first_anomaly,
       a2.timestamp AS second_anomaly,
       toFloat(a2.timestamp) - toFloat(a1.timestamp) AS seconds_between
ORDER BY first_anomaly ASC;


// ------------------------------------------------------------
// 8. Clear all data (use with caution)
// ------------------------------------------------------------
// MATCH (n) DETACH DELETE n;