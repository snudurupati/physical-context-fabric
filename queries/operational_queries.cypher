// ============================================================
// Physical Context Fabric — Cypher Query Library
// Operational queries for robot telemetry knowledge graph
//
// MEMGRAPH SYNTAX RULES:
// - Always alias properties in RETURN
// - Always use aliases in ORDER BY, never original variables
// - Omit label filters on node variables in relationship patterns
//   e.g. MATCH (r)-[:EXPERIENCED]->(a)
//   NOT  MATCH (r:Robot)-[:EXPERIENCED]->(a:Anomaly)
// ============================================================


// ------------------------------------------------------------
// 1. Fleet anomaly summary — all robots
// ------------------------------------------------------------
MATCH (r)-[:EXPERIENCED]->(a)
RETURN r.robot_id AS robot,
       a.type AS anomaly_type,
       count(a) AS total
ORDER BY robot, total DESC;


// ------------------------------------------------------------
// 2. Geographic clustering — where do anomalies occur?
//    Buckets position into 0.5m grid cells
// ------------------------------------------------------------
MATCH (r)-[:EXPERIENCED]->(a)-[:OCCURRED_IN]->(es)
RETURN r.robot_id AS robot,
       round(toFloat(a.position_x) * 2) / 2 AS grid_x,
       round(toFloat(a.position_y) * 2) / 2 AS grid_y,
       count(a) AS anomalies_in_cell
ORDER BY robot, anomalies_in_cell DESC
LIMIT 15;


// ------------------------------------------------------------
// 3. Most dangerous map regions across entire fleet
// ------------------------------------------------------------
MATCH (r)-[:EXPERIENCED]->(a)-[:OCCURRED_IN]->(es)
RETURN round(toFloat(a.position_x) * 2) / 2 AS grid_x,
       round(toFloat(a.position_y) * 2) / 2 AS grid_y,
       count(a) AS total_anomalies,
       collect(DISTINCT r.robot_id) AS affected_robots
ORDER BY total_anomalies DESC
LIMIT 5;


// ------------------------------------------------------------
// 4. Events preceding the last anomaly for a robot
//    "What was the robot doing 30 seconds before it stopped?"
// ------------------------------------------------------------
MATCH (r)-[:GENERATED]->(e)
MATCH (r)-[:EXPERIENCED]->(a)
WHERE toFloat(e.timestamp) < toFloat(a.timestamp)
  AND toFloat(e.timestamp) > toFloat(a.timestamp) - 30
  AND r.robot_id = 'robot_001'
RETURN e.timestamp AS ts,
       e.event_type AS event,
       e.position_x AS x,
       e.position_y AS y,
       e.linear_vel AS vel
ORDER BY ts DESC
LIMIT 20;


// ------------------------------------------------------------
// 5. Robot operational summary
// ------------------------------------------------------------
MATCH (r)-[:EXPERIENCED]->(a)
RETURN r.robot_id AS robot,
       r.first_seen AS first_seen,
       r.last_seen AS last_seen,
       count(DISTINCT a) AS total_anomalies
ORDER BY total_anomalies DESC;


// ------------------------------------------------------------
// 6. Anomaly rate by robot — anomalies per minute
//    Requires first_seen and last_seen to be set
// ------------------------------------------------------------
MATCH (r)-[:EXPERIENCED]->(a)
WITH r.robot_id AS robot,
     r.first_seen AS first_seen,
     r.last_seen AS last_seen,
     count(a) AS total
RETURN robot,
       total AS anomalies,
       first_seen,
       last_seen
ORDER BY anomalies DESC;


// ------------------------------------------------------------
// 7. Time between anomalies for a single robot
//    Is the robot degrading over time?
// ------------------------------------------------------------
MATCH (r)-[:EXPERIENCED]->(a)
WHERE r.robot_id = 'robot_001'
WITH a
ORDER BY a.timestamp ASC
WITH collect(a) AS anomalies
UNWIND range(0, size(anomalies) - 2) AS i
WITH anomalies[i] AS a1, anomalies[i+1] AS a2
RETURN a1.timestamp AS first_anomaly,
       a2.timestamp AS second_anomaly,
       round((toFloat(a2.timestamp) - toFloat(a1.timestamp)) * 10) / 10
         AS seconds_between
ORDER BY first_anomaly ASC
LIMIT 10;


// ------------------------------------------------------------
// 8. Keyframe history for a robot — ground truth snapshots
// ------------------------------------------------------------
MATCH (r)-[:GENERATED]->(e)
WHERE r.robot_id = 'robot_001'
  AND e.frame_type = 'keyframe'
RETURN e.timestamp AS ts,
       e.position_x AS x,
       e.position_y AS y,
       e.linear_vel AS vel,
       e.event_type AS state
ORDER BY ts DESC
LIMIT 10;


// ------------------------------------------------------------
// 9. Full graph — all nodes and relationships
//    Use in Memgraph Lab for visual exploration
// ------------------------------------------------------------
MATCH (r)-[rel]->(n)
OPTIONAL MATCH (n)-[rel2]->(m)
RETURN r, rel, n, rel2, m;


// ------------------------------------------------------------
// 10. Clear all PCF data (use with caution)
//     Preserves non-PCF nodes (Account, RiskSignal etc.)
// ------------------------------------------------------------
// MATCH (n)
// WHERE n:Robot OR n:Event OR n:Anomaly OR n:Environment_State
// DETACH DELETE n;
