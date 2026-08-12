# Databricks notebook source
# MAGIC %md
# MAGIC # gold_aggregate
# MAGIC **Implements**: FS-RPT-001-POC (intent distribution), FS-RPT-002-POC (resolution metrics),
# MAGIC FS-RPT-003-POC (sentiment trend)
# MAGIC 
# MAGIC Part of WBXAGT POC pipeline. See TS-WBXAGT-001-POC-COMPONENTS.md §5.
# MAGIC Idempotent (upsert, not append) — safe to re-run for the same day.

# COMMAND ----------

from pyspark.sql import functions as F
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gold_aggregate")

SILVER_SCHEMA = "sandbox_others.silver_wanderbricks_agent"
GOLD_SCHEMA = "sandbox_others.gold_wanderbricks_agent"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Intent Distribution (FS-RPT-001-POC)

# COMMAND ----------

# GROUP BY DATE(classified_at), intent — upsert into gold
spark.sql(f"""
    MERGE INTO {GOLD_SCHEMA}.intent_distribution AS target
    USING (
        SELECT DATE(classified_at) AS metric_date, intent, COUNT(*) AS ticket_count
        FROM {SILVER_SCHEMA}.ticket_classification
        GROUP BY DATE(classified_at), intent
    ) AS source
    ON target.metric_date = source.metric_date AND target.intent = source.intent
    WHEN MATCHED THEN UPDATE SET target.ticket_count = source.ticket_count
    WHEN NOT MATCHED THEN INSERT (metric_date, intent, ticket_count)
        VALUES (source.metric_date, source.intent, source.ticket_count)
""")

logger.info("intent_distribution updated")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Resolution Metrics (FS-RPT-002-POC)

# COMMAND ----------

# Resolution time = time from ticket creation (first STATUS_CHANGE log) to terminal status
# Override count from OVERRIDE events in activity log
spark.sql(f"""
    MERGE INTO {GOLD_SCHEMA}.resolution_metrics AS target
    USING (
        WITH terminal_tickets AS (
            SELECT t.ticket_id, t.current_status, t.created_at AS ticket_created_at,
                   t.updated_at AS resolved_at
            FROM {SILVER_SCHEMA}.tickets t
            WHERE t.current_status IN ('APPROVED', 'REJECTED')
        ),
        resolution_times AS (
            SELECT DATE(resolved_at) AS metric_date,
                   AVG((unix_timestamp(resolved_at) - unix_timestamp(ticket_created_at)) / 60.0) AS avg_resolution_minutes,
                   SUM(CASE WHEN current_status = 'APPROVED' THEN 1 ELSE 0 END) AS approve_count,
                   SUM(CASE WHEN current_status = 'REJECTED' THEN 1 ELSE 0 END) AS reject_count
            FROM terminal_tickets
            GROUP BY DATE(resolved_at)
        ),
        overrides AS (
            SELECT DATE(occurred_at) AS metric_date, COUNT(*) AS override_count
            FROM {SILVER_SCHEMA}.ticket_activity_log
            WHERE event_type = 'OVERRIDE'
            GROUP BY DATE(occurred_at)
        )
        SELECT rt.metric_date,
               rt.avg_resolution_minutes,
               rt.approve_count,
               rt.reject_count,
               COALESCE(o.override_count, 0) AS override_count,
               CASE WHEN (rt.approve_count + rt.reject_count) > 0
                    THEN COALESCE(o.override_count, 0) * 1.0 / (rt.approve_count + rt.reject_count)
                    ELSE 0.0 END AS override_rate
        FROM resolution_times rt
        LEFT JOIN overrides o ON rt.metric_date = o.metric_date
    ) AS source
    ON target.metric_date = source.metric_date
    WHEN MATCHED THEN UPDATE SET
        target.avg_resolution_minutes = source.avg_resolution_minutes,
        target.approve_count = source.approve_count,
        target.reject_count = source.reject_count,
        target.override_count = source.override_count,
        target.override_rate = source.override_rate
    WHEN NOT MATCHED THEN INSERT (metric_date, avg_resolution_minutes, approve_count, reject_count, override_count, override_rate)
        VALUES (source.metric_date, source.avg_resolution_minutes, source.approve_count, source.reject_count, source.override_count, source.override_rate)
""")

logger.info("resolution_metrics updated")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Sentiment Trend (FS-RPT-003-POC)

# COMMAND ----------

# GROUP BY date, intent (via join to classification), sentiment
spark.sql(f"""
    MERGE INTO {GOLD_SCHEMA}.sentiment_trend AS target
    USING (
        SELECT DATE(sm.message_timestamp) AS metric_date,
               COALESCE(tc.intent, 'UNCLASSIFIED') AS intent,
               sm.sentiment AS sentiment_category,
               COUNT(*) AS message_count
        FROM {SILVER_SCHEMA}.support_messages sm
        LEFT JOIN (
            SELECT ticket_id, intent,
                   ROW_NUMBER() OVER (PARTITION BY ticket_id ORDER BY classified_at DESC) AS rn
            FROM {SILVER_SCHEMA}.ticket_classification
        ) tc ON sm.ticket_id = tc.ticket_id AND tc.rn = 1
        WHERE sm.sentiment IS NOT NULL
          AND sm.message_timestamp IS NOT NULL
        GROUP BY DATE(sm.message_timestamp), COALESCE(tc.intent, 'UNCLASSIFIED'), sm.sentiment
    ) AS source
    ON target.metric_date = source.metric_date
       AND target.intent = source.intent
       AND target.sentiment_category = source.sentiment_category
    WHEN MATCHED THEN UPDATE SET target.message_count = source.message_count
    WHEN NOT MATCHED THEN INSERT (metric_date, intent, sentiment_category, message_count)
        VALUES (source.metric_date, source.intent, source.sentiment_category, source.message_count)
""")

logger.info("sentiment_trend updated")

# COMMAND ----------

logger.info("gold_aggregate completed successfully.")
