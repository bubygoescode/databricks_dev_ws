# Databricks notebook source
# MAGIC %md
# MAGIC # silver_validate
# MAGIC **Implements**: FS-VAL-001-POC..005-POC (WBXCHK-01..05 reference validation checks)
# MAGIC 
# MAGIC Part of WBXAGT POC pipeline. See TS-WBXAGT-001-POC-COMPONENTS.md §3.

# COMMAND ----------

from pyspark.sql import functions as F
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("silver_validate")

SILVER_SCHEMA = "sandbox_others.silver_wanderbricks_agent"
MODIFIABLE_STATUSES = {"pending", "confirmed"}  # PRD OQ-01, confirmed by profiling

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Get tickets ready for validation

# COMMAND ----------

# Tickets in VALIDATING state with an actionable intent
tickets_to_validate = spark.sql(f"""
    SELECT t.ticket_id, tc.intent, tc.extracted_booking_id
    FROM {SILVER_SCHEMA}.tickets t
    JOIN (
        SELECT ticket_id, intent, extracted_booking_id,
               ROW_NUMBER() OVER (PARTITION BY ticket_id ORDER BY classified_at DESC) as rn
        FROM {SILVER_SCHEMA}.ticket_classification
    ) tc ON t.ticket_id = tc.ticket_id AND tc.rn = 1
    WHERE t.current_status = 'VALIDATING'
""").collect()

logger.info(f"Found {len(tickets_to_validate)} tickets to validate")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Validation checks (WBXCHK-01..05)

# COMMAND ----------

def insert_validation_result(ticket_id, check_id, result, detail):
    """Insert a single validation result row."""
    detail_escaped = detail.replace("'", "''")
    spark.sql(f"""
        INSERT INTO {SILVER_SCHEMA}.ticket_validation
        VALUES (uuid(), '{ticket_id}', '{check_id}', '{result}', '{detail_escaped}', current_timestamp())
    """)


def run_wbxchk_01(ticket_id, extracted_booking_id):
    """WBXCHK-01: Booking exists and is modifiable (FS-VAL-001-POC)."""
    if extracted_booking_id is None:
        insert_validation_result(ticket_id, "WBXCHK-01", "FAIL",
                                 "No booking_id extracted from ticket — cannot validate.")
        return None

    booking = spark.sql(f"""
        SELECT booking_id, status, user_id, property_id
        FROM {SILVER_SCHEMA}.bookings
        WHERE booking_id = {extracted_booking_id}
    """).collect()

    if not booking:
        insert_validation_result(ticket_id, "WBXCHK-01", "FAIL",
                                 f"Booking {extracted_booking_id} does not exist in silver.bookings.")
        return None

    booking_row = booking[0]
    status = booking_row["status"]

    if status in MODIFIABLE_STATUSES:
        insert_validation_result(ticket_id, "WBXCHK-01", "PASS",
                                 f"Booking {extracted_booking_id} exists with modifiable status '{status}'.")
    else:
        insert_validation_result(ticket_id, "WBXCHK-01", "FAIL",
                                 f"Booking {extracted_booking_id} has non-modifiable status '{status}'.")

    return booking_row


def run_wbxchk_02_03(ticket_id, booking_row):
    """WBXCHK-02: Property exists. WBXCHK-03: Host is active & verified (FS-VAL-002-POC)."""
    if booking_row is None:
        insert_validation_result(ticket_id, "WBXCHK-02", "FAIL",
                                 "Cannot check property — booking not found.")
        insert_validation_result(ticket_id, "WBXCHK-03", "FAIL",
                                 "Cannot check host — booking not found.")
        return

    property_id = booking_row["property_id"]

    # WBXCHK-02: Property existence (no status field — OQ-02)
    prop = spark.sql(f"""
        SELECT property_id, host_id FROM {SILVER_SCHEMA}.properties
        WHERE property_id = {property_id}
    """).collect()

    if not prop:
        insert_validation_result(ticket_id, "WBXCHK-02", "FAIL",
                                 f"Property {property_id} does not exist.")
        insert_validation_result(ticket_id, "WBXCHK-03", "FAIL",
                                 "Cannot check host — property not found.")
        return

    insert_validation_result(ticket_id, "WBXCHK-02", "PASS",
                             f"Property {property_id} exists (existence-only check, no status field available).")

    # WBXCHK-03: Host active & verified
    host_id = prop[0]["host_id"]
    host = spark.sql(f"""
        SELECT host_id, is_active, is_verified FROM {SILVER_SCHEMA}.hosts
        WHERE host_id = {host_id}
    """).collect()

    if not host:
        insert_validation_result(ticket_id, "WBXCHK-03", "FAIL",
                                 f"Host {host_id} does not exist.")
        return

    host_row = host[0]
    if host_row["is_active"] and host_row["is_verified"]:
        insert_validation_result(ticket_id, "WBXCHK-03", "PASS",
                                 f"Host {host_id} is active and verified.")
    else:
        reasons = []
        if not host_row["is_active"]:
            reasons.append("is_active=false")
        if not host_row["is_verified"]:
            reasons.append("is_verified=false")
        insert_validation_result(ticket_id, "WBXCHK-03", "FAIL",
                                 f"Host {host_id} failed: {', '.join(reasons)}.")


def run_wbxchk_04(ticket_id, extracted_booking_id):
    """WBXCHK-04: No conflicting in-flight booking_updates (FS-VAL-003-POC)."""
    if extracted_booking_id is None:
        insert_validation_result(ticket_id, "WBXCHK-04", "PASS",
                                 "No booking_id to check for conflicting updates.")
        return

    # Check for unresolved updates (no corresponding APPROVED/REJECTED ticket)
    conflicts = spark.sql(f"""
        SELECT bu.booking_update_id
        FROM {SILVER_SCHEMA}.booking_updates bu
        WHERE bu.booking_id = {extracted_booking_id}
          AND NOT EXISTS (
            SELECT 1 FROM {SILVER_SCHEMA}.tickets t
            JOIN {SILVER_SCHEMA}.ticket_classification tc ON t.ticket_id = tc.ticket_id
            WHERE tc.extracted_booking_id = bu.booking_id
              AND t.current_status IN ('APPROVED', 'REJECTED')
          )
    """).collect()

    if conflicts:
        conflict_ids = ", ".join([str(c["booking_update_id"]) for c in conflicts[:5]])
        insert_validation_result(ticket_id, "WBXCHK-04", "WARN",
                                 f"Conflicting unresolved update(s) found for booking {extracted_booking_id}: {conflict_ids}.")
    else:
        insert_validation_result(ticket_id, "WBXCHK-04", "PASS",
                                 f"No conflicting unresolved updates for booking {extracted_booking_id}.")


def run_wbxchk_05(ticket_id, extracted_booking_id, booking_row):
    """WBXCHK-05: Requester identity matches booking owner (FS-VAL-004-POC)."""
    if booking_row is None or extracted_booking_id is None:
        insert_validation_result(ticket_id, "WBXCHK-05", "FAIL",
                                 "Cannot verify requester identity — booking not found.")
        return

    # Get ticket's user_id from support_messages
    ticket_user = spark.sql(f"""
        SELECT DISTINCT user_id FROM {SILVER_SCHEMA}.support_messages
        WHERE ticket_id = '{ticket_id}'
    """).collect()

    if not ticket_user:
        insert_validation_result(ticket_id, "WBXCHK-05", "FAIL",
                                 "Cannot determine ticket requester user_id.")
        return

    ticket_user_id = ticket_user[0]["user_id"]
    booking_user_id = booking_row["user_id"]

    if ticket_user_id == booking_user_id:
        insert_validation_result(ticket_id, "WBXCHK-05", "PASS",
                                 f"Requester (user {ticket_user_id}) matches booking owner.")
    else:
        insert_validation_result(ticket_id, "WBXCHK-05", "FAIL",
                                 f"Requester (user {ticket_user_id}) does NOT match booking owner (user {booking_user_id}).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Run all checks per ticket

# COMMAND ----------

for ticket_row in tickets_to_validate:
    ticket_id = ticket_row["ticket_id"]
    intent = ticket_row["intent"]
    extracted_booking_id = ticket_row["extracted_booking_id"]

    # Non-actionable intents skip validation (Components §3.1 step 5)
    if intent in ("GENERAL_QUESTION", "NOT_ACTIONABLE"):
        logger.info(f"Ticket {ticket_id}: intent={intent}, skipping validation (non-actionable)")
    else:
        # Run all 5 checks
        booking_row = run_wbxchk_01(ticket_id, extracted_booking_id)
        run_wbxchk_02_03(ticket_id, booking_row)
        run_wbxchk_04(ticket_id, extracted_booking_id)
        run_wbxchk_05(ticket_id, extracted_booking_id, booking_row)
        logger.info(f"Ticket {ticket_id}: all WBXCHK checks completed")

    # Update status to VALIDATED (Components §3.1 step 6)
    spark.sql(f"""
        UPDATE {SILVER_SCHEMA}.tickets
        SET current_status = 'VALIDATED', updated_at = current_timestamp()
        WHERE ticket_id = '{ticket_id}'
    """)

    # Count pass/fail/warn for the log detail
    results = spark.sql(f"""
        SELECT result, COUNT(*) as cnt
        FROM {SILVER_SCHEMA}.ticket_validation
        WHERE ticket_id = '{ticket_id}'
        GROUP BY result
    """).collect()
    summary_parts = [f"{r['result']}={r['cnt']}" for r in results]
    summary_str = ", ".join(summary_parts) if summary_parts else "no checks (non-actionable)"

    # Activity log
    spark.sql(f"""
        INSERT INTO {SILVER_SCHEMA}.ticket_activity_log
        VALUES (
            uuid(), '{ticket_id}', 'VALIDATION_RUN',
            'Validation completed: {summary_str}',
            'SYSTEM', current_timestamp()
        )
    """)

# COMMAND ----------

logger.info(f"silver_validate completed. Processed {len(tickets_to_validate)} tickets.")
