# Databricks notebook source
# MAGIC %md
# MAGIC # AI_classify
# MAGIC **Implements**: FS-CLS-001-POC (classify intent), FS-CLS-002-POC (extract details),
# MAGIC FS-CLS-003-POC (fail visibly), FS-CLS-004-POC (prompt registry)
# MAGIC 
# MAGIC Part of WBXAGT POC pipeline. See TS-WBXAGT-001-POC-COMPONENTS.md §2.

# COMMAND ----------

from pyspark.sql import functions as F
import requests
import json
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AI_classify")

SILVER_SCHEMA = "sandbox_others.silver_wanderbricks_agent"
VALID_INTENTS = {"CANCELLATION", "MODIFICATION", "REFUND", "COMPLAINT", "GENERAL_QUESTION", "NOT_ACTIONABLE"}

# Optional: pin a specific prompt version for A/B testing (TC-CLS-004-05)
# Set via job parameter; defaults to None (uses active version)
try:
    pinned_version = dbutils.widgets.get("pinned_prompt_version")
    pinned_version = int(pinned_version) if pinned_version else None
except Exception:
    pinned_version = None

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Load prompt from registry (FS-CLS-004-POC)

# COMMAND ----------

def load_prompt(prompt_name="ticket_intent_classification", pinned_ver=None):
    """Load the active (or pinned) prompt template from prompt_registry.
    Fails fast if no version resolves (FS-CLS-004-POC AC-3, error behaviour).
    """
    if pinned_ver is not None:
        row = spark.sql(f"""
            SELECT template, model_endpoint, version
            FROM {SILVER_SCHEMA}.prompt_registry
            WHERE prompt_name = '{prompt_name}' AND version = {pinned_ver}
        """).collect()
    else:
        row = spark.sql(f"""
            SELECT template, model_endpoint, version
            FROM {SILVER_SCHEMA}.prompt_registry
            WHERE prompt_name = '{prompt_name}' AND is_active = TRUE
        """).collect()

    if not row:
        raise RuntimeError(
            f"No resolvable prompt for '{prompt_name}' "
            f"(pinned_version={pinned_ver}). Cannot proceed — no hardcoded fallback."
        )

    return {
        "template": row[0]["template"],
        "model_endpoint": row[0]["model_endpoint"],
        "version": row[0]["version"],
        "prompt_name": prompt_name
    }


prompt_config = load_prompt(pinned_ver=pinned_version)
logger.info(f"Loaded prompt: {prompt_config['prompt_name']} v{prompt_config['version']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Model calling logic (TS-WBXAGT-001-POC-COMPONENTS §2.1)

# COMMAND ----------

def call_model(message_thread_text, prompt_template, model_endpoint):
    """Call a Databricks Model Serving endpoint with the classification prompt.
    Returns parsed JSON response or raises on failure.
    """
    # Substitute placeholder
    full_prompt = prompt_template.replace("{{message_thread}}", message_thread_text)

    # Get workspace host and token
    workspace_host = spark.conf.get("spark.databricks.workspaceUrl")
    token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()

    # Use Foundation Model API (pay-per-token)
    endpoint_url = f"https://{workspace_host}/serving-endpoints/{model_endpoint}/invocations"

    payload = {
        "messages": [
            {"role": "system", "content": "You are a JSON-only response bot. Always respond with valid JSON matching the requested schema."},
            {"role": "user", "content": full_prompt}
        ],
        "max_tokens": 1024,
        "temperature": 0.1
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    response = requests.post(endpoint_url, json=payload, headers=headers, timeout=60)
    response.raise_for_status()

    result = response.json()
    content = result["choices"][0]["message"]["content"]

    # Parse JSON from response (strip markdown fences if present)
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    parsed = json.loads(content)
    return parsed


def validate_model_response(parsed):
    """Validate the model response conforms to the expected schema (CON-GRD-02).
    Returns True if valid, raises ValueError otherwise.
    """
    if not isinstance(parsed, dict):
        raise ValueError("Response is not a JSON object")

    intent = parsed.get("intent")
    if intent not in VALID_INTENTS:
        raise ValueError(f"Invalid intent '{intent}'. Must be one of {VALID_INTENTS}")

    if not parsed.get("reasoning"):
        raise ValueError("Missing 'reasoning' field")

    confidence = parsed.get("confidence")
    if confidence is not None and not (0.0 <= float(confidence) <= 1.0):
        raise ValueError(f"Confidence {confidence} outside [0,1] range")

    return True

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Classify tickets (Components §2.2)

# COMMAND ----------

# Get tickets ready for classification (status = NEW)
tickets_to_classify = spark.sql(f"""
    SELECT ticket_id FROM {SILVER_SCHEMA}.tickets
    WHERE current_status = 'NEW'
""").collect()

logger.info(f"Found {len(tickets_to_classify)} tickets to classify")

success_count = 0
failure_count = 0

for ticket_row in tickets_to_classify:
    ticket_id = ticket_row["ticket_id"]

    try:
        # Step 1: Set status to CLASSIFYING
        spark.sql(f"""
            UPDATE {SILVER_SCHEMA}.tickets
            SET current_status = 'CLASSIFYING', updated_at = current_timestamp()
            WHERE ticket_id = '{ticket_id}'
        """)

        # Step 2: Get message thread for this ticket
        messages = spark.sql(f"""
            SELECT sender, message_text, sentiment, message_timestamp
            FROM {SILVER_SCHEMA}.support_messages
            WHERE ticket_id = '{ticket_id}'
            ORDER BY message_timestamp
        """).collect()

        if not messages:
            raise RuntimeError(f"No messages found for ticket {ticket_id}")

        # Format thread as text
        thread_lines = []
        for m in messages:
            thread_lines.append(
                f"[{m['message_timestamp']}] {m['sender']}: {m['message_text']}"
            )
        message_thread_text = "\n".join(thread_lines)

        # Step 3: Call model
        parsed_response = call_model(
            message_thread_text,
            prompt_config["template"],
            prompt_config["model_endpoint"]
        )

        # Step 4: Validate response schema (CON-GRD-02)
        validate_model_response(parsed_response)

        # Step 5: Write classification record
        intent = parsed_response["intent"]
        reasoning = parsed_response["reasoning"]
        extracted_booking_id = parsed_response.get("extracted_booking_id")
        extracted_details = json.dumps(parsed_response.get("extracted_details", {}))
        confidence = parsed_response.get("confidence")

        spark.sql(f"""
            INSERT INTO {SILVER_SCHEMA}.ticket_classification
            VALUES (
                uuid(),
                '{ticket_id}',
                '{intent}',
                {extracted_booking_id if extracted_booking_id is not None else 'NULL'},
                '{extracted_details.replace("'", "''")}',
                '{reasoning.replace("'", "''")}',
                {confidence if confidence is not None else 'NULL'},
                '{prompt_config["model_endpoint"]}',
                '{prompt_config["prompt_name"]}',
                {prompt_config["version"]},
                current_timestamp()
            )
        """)

        # Step 6: Update ticket status to VALIDATING + set intent
        spark.sql(f"""
            UPDATE {SILVER_SCHEMA}.tickets
            SET current_status = 'VALIDATING',
                current_intent = '{intent}',
                updated_at = current_timestamp()
            WHERE ticket_id = '{ticket_id}'
        """)

        # Step 7: Activity log
        spark.sql(f"""
            INSERT INTO {SILVER_SCHEMA}.ticket_activity_log
            VALUES (
                uuid(),
                '{ticket_id}',
                'CLASSIFICATION_RUN',
                'Classified as {intent} using prompt v{prompt_config["version"]} (confidence: {confidence})',
                'SYSTEM',
                current_timestamp()
            )
        """)

        success_count += 1
        logger.info(f"Ticket {ticket_id}: classified as {intent} (confidence={confidence})")

    except Exception as e:
        # FS-CLS-003-POC: fail visibly
        failure_count += 1
        error_msg = str(e).replace("'", "''")
        logger.error(f"Ticket {ticket_id}: classification failed - {e}")

        spark.sql(f"""
            UPDATE {SILVER_SCHEMA}.tickets
            SET current_status = 'CLASSIFICATION_FAILED', updated_at = current_timestamp()
            WHERE ticket_id = '{ticket_id}'
        """)

        spark.sql(f"""
            INSERT INTO {SILVER_SCHEMA}.ticket_activity_log
            VALUES (
                uuid(),
                '{ticket_id}',
                'CLASSIFICATION_RUN',
                'Classification failed: {error_msg[:500]}',
                'SYSTEM',
                current_timestamp()
            )
        """)

# COMMAND ----------

logger.info(f"AI_classify completed. Success: {success_count}, Failed: {failure_count}")
