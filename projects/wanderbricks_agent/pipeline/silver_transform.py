# Databricks notebook source
# MAGIC %md
# MAGIC # silver_transform
# MAGIC **Implements**: FS-ING-001-POC (flatten message threads), FS-ING-002-POC (conform reference data)
# MAGIC 
# MAGIC Part of WBXAGT POC pipeline. See TS-WBXAGT-001-POC-COMPONENTS.md §1.

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import *
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("silver_transform")

BRONZE_SCHEMA = "sandbox_others.bronze_datasample_wanderbricks"
SILVER_SCHEMA = "sandbox_others.silver_wanderbricks_agent"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Flatten message threads (FS-ING-001-POC)

# COMMAND ----------

# Read bronze customer_support_logs
bronze_logs = spark.table(f"{BRONZE_SCHEMA}.customer_support_logs")

# Get existing ticket_ids in silver to avoid reprocessing
try:
    existing_msg_tickets = spark.table(f"{SILVER_SCHEMA}.support_messages") \
        .select("ticket_id").distinct()
    new_logs = bronze_logs.join(
        existing_msg_tickets,
        bronze_logs["ticket_id"] == existing_msg_tickets["ticket_id"],
        "left_anti"
    )
except Exception:
    # First run — no existing data
    new_logs = bronze_logs

logger.info(f"Found {new_logs.count()} new tickets to process")

# Separate valid vs malformed (FS-ING-001-POC error behaviour)
valid_logs = new_logs.filter(
    F.col("messages").isNotNull() & (F.size("messages") > 0)
)
malformed_logs = new_logs.filter(
    F.col("messages").isNull() | (F.size("messages") == 0)
)
malformed_count = malformed_logs.count()
if malformed_count > 0:
    logger.warning(f"Skipping {malformed_count} tickets with null/malformed messages array")

# Explode messages[] into one row per message (FS-ING-001-POC AC-1, AC-2)
messages_exploded = valid_logs.select(
    F.col("ticket_id"),
    F.col("user_id"),
    F.col("support_agent_id"),
    F.posexplode("messages").alias("msg_idx", "msg")
).select(
    F.concat(F.col("ticket_id"), F.lit("_"), F.col("msg_idx").cast("string")).alias("message_id"),
    F.col("ticket_id"),
    F.col("msg.sender").alias("sender"),
    F.col("msg.message").alias("message_text"),
    F.col("msg.sentiment").alias("sentiment"),
    F.col("msg.timestamp").alias("message_timestamp"),
    F.col("user_id").cast("bigint").alias("user_id"),
    F.col("support_agent_id"),
    F.current_timestamp().alias("ingested_at")
)

msg_count = messages_exploded.count()
if msg_count > 0:
    messages_exploded.write.format("delta").mode("append").saveAsTable(
        f"{SILVER_SCHEMA}.support_messages"
    )
    logger.info(f"Inserted {msg_count} message rows into silver.support_messages")
else:
    logger.info("No new messages to insert")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Create ticket records for new tickets (FS-TRK-001-POC)

# COMMAND ----------

# Get new ticket_ids that need a tickets row
new_ticket_ids = valid_logs.select(F.col("ticket_id")).distinct()

try:
    existing_ticket_records = spark.table(f"{SILVER_SCHEMA}.tickets").select("ticket_id")
    tickets_to_create = new_ticket_ids.join(existing_ticket_records, "ticket_id", "left_anti")
except Exception:
    tickets_to_create = new_ticket_ids

new_ticket_count = tickets_to_create.count()
if new_ticket_count > 0:
    # Insert new ticket records with status NEW
    new_tickets_df = tickets_to_create.select(
        "ticket_id",
        F.lit("NEW").alias("current_status"),
        F.lit(None).cast("string").alias("current_intent"),
        F.lit(None).cast("string").alias("assigned_reviewer"),
        F.current_timestamp().alias("created_at"),
        F.current_timestamp().alias("updated_at")
    )
    new_tickets_df.write.format("delta").mode("append").saveAsTable(
        f"{SILVER_SCHEMA}.tickets"
    )

    # Append activity log entries (Components §1.1 step 4)
    activity_entries = tickets_to_create.select(
        F.expr("uuid()").alias("log_id"),
        "ticket_id",
        F.lit("STATUS_CHANGE").alias("event_type"),
        F.lit("Ticket created from ingested support thread").alias("detail"),
        F.lit("SYSTEM").alias("actor"),
        F.current_timestamp().alias("occurred_at")
    )
    activity_entries.write.format("delta").mode("append").saveAsTable(
        f"{SILVER_SCHEMA}.ticket_activity_log"
    )
    logger.info(f"Created {new_ticket_count} new ticket records with activity log entries")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Conform reference data (FS-ING-002-POC)

# COMMAND ----------

def upsert_reference_table(bronze_table_name, pk_column):
    """MERGE bronze reference data into the corresponding silver table.
    Rows with null PK are excluded with a logged warning (FS-ING-002-POC error behaviour).
    """
    bronze_df = spark.table(f"{BRONZE_SCHEMA}.{bronze_table_name}")
    silver_table = f"{SILVER_SCHEMA}.{bronze_table_name}"

    # Exclude null PKs
    valid_df = bronze_df.filter(F.col(pk_column).isNotNull())
    excluded = bronze_df.count() - valid_df.count()
    if excluded > 0:
        logger.warning(f"{bronze_table_name}: Excluded {excluded} rows with null {pk_column}")

    # Get target columns from silver schema
    silver_cols = [f.name for f in spark.table(silver_table).schema.fields]

    # Stage source data, selecting only columns that exist in silver
    source_cols = [c for c in silver_cols if c in valid_df.columns]
    staged = valid_df.select(*source_cols)
    staged.createOrReplaceTempView(f"_staged_{bronze_table_name}")

    # Build MERGE statement
    update_set = ", ".join([f"target.`{c}` = source.`{c}`" for c in source_cols if c != pk_column])
    insert_cols = ", ".join([f"`{c}`" for c in source_cols])
    insert_vals = ", ".join([f"source.`{c}`" for c in source_cols])

    spark.sql(f"""
        MERGE INTO {silver_table} AS target
        USING _staged_{bronze_table_name} AS source
        ON target.`{pk_column}` = source.`{pk_column}`
        WHEN MATCHED THEN UPDATE SET {update_set}
        WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})
    """)
    logger.info(f"Upserted {bronze_table_name} -> silver ({staged.count()} source rows)")


# Run for each reference table
upsert_reference_table("bookings", "booking_id")
upsert_reference_table("booking_updates", "booking_update_id")
upsert_reference_table("properties", "property_id")
upsert_reference_table("hosts", "host_id")
upsert_reference_table("users", "user_id")

# COMMAND ----------

logger.info("silver_transform completed successfully.")
