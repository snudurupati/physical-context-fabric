# Cypher Query Library

Operational queries for the Physical Context Fabric knowledge graph.

## Usage

Run queries in Memgraph Lab at `http://localhost:3000`
or via the Memgraph Python driver.

## Query Index

| # | Query | Answers |
|---|---|---|
| 1 | All anomalies | What failures has this robot had? |
| 2 | Anomaly frequency | Which failure type is most common? |
| 3 | Geographic clustering | Where do failures cluster on the map? |
| 4 | Events before anomaly | What was the robot doing 30s before failure? |
| 5 | Robot summary | How many events and anomalies total? |
| 6 | Dangerous regions | Which map regions have the most failures? |
| 7 | Time between anomalies | Is the robot degrading over time? |
| 8 | Clear data | Reset the graph |