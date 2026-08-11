# Technical Specification: WBXAGT POC — Data Model

| Field | Value |
|---|---|
| Document ID | TS-DATA-001-WBXAGT-POC |
| Parent | TS-WBXAGT-001-POC-INDEX.md, FS-WBXAGT-001-POC |
| Status | DRAFT |

Bronze source (already created, not redefined here): `sandbox_others.bronze_datasample_wanderbricks.{customer_support_logs, bookings, booking_updates, properties, hosts, users, property_images}`, copied from `samples.wanderbricks`. Column names/types below for `bookings`, `booking_updates`, `properties`, `hosts`, `users` are taken directly from the bronze table definitions (verified via `databricks tables get`, not guessed).

---

## 0. Namespaces

| Layer | Schema | Why |
|---|---|---|
| Bronze | `sandbox_others.bronze_datasample_wanderbricks` | Already created |
| Silver | `sandbox_others.silver_wanderbricks_agent` | New |
| Gold | `sandbox_others.gold_wanderbricks_agent` | New |

```sql
CREATE SCHEMA IF NOT EXISTS sandbox_others.silver_wanderbricks_agent
  COMMENT 'WBXAGT POC - conformed data + agent state. See spec_driven_documents/wanderbricks_agent/TSD.';

CREATE SCHEMA IF NOT EXISTS sandbox_others.gold_wanderbricks_agent
  COMMENT 'WBXAGT POC - reporting aggregates. See spec_driven_documents/wanderbricks_agent/TSD.';
```

---

## 1. Silver: flattened messages (implements FS-ING-001-POC)

```sql
CREATE TABLE IF NOT EXISTS sandbox_others.silver_wanderbricks_agent.support_messages (
  message_id        STRING NOT NULL COMMENT 'Generated (e.g. ticket_id + array index or UUID).',
  ticket_id          STRING NOT NULL COMMENT 'FK to bronze customer_support_logs.ticket_id.',
  sender              STRING COMMENT 'From the exploded messages[] struct.',
  message_text        STRING,
  sentiment            STRING COMMENT 'Categorical value as stored in bronze (not a numeric score) - e.g. positive/neutral/negative.',
  message_timestamp    STRING COMMENT 'As stored in bronze (STRING type there); cast to TIMESTAMP here if parseable.',
  user_id               BIGINT COMMENT 'Denormalized from parent customer_support_logs row, for convenience.',
  support_agent_id      STRING COMMENT 'Denormalized from parent row.',
  ingested_at            TIMESTAMP NOT NULL,
  CONSTRAINT support_messages_pk PRIMARY KEY (message_id)
)
USING DELTA
COMMENT 'One row per message, exploded from bronze messages[]. Implements FS-ING-001-POC.';
```

---

## 2. Silver: conformed reference tables (implements FS-ING-002-POC)

Straight typed pass-throughs of bronze, same primary keys, joinable without transformation (FS-ING-002-POC AC-2). Columns match the verified bronze schema.

```sql
CREATE TABLE IF NOT EXISTS sandbox_others.silver_wanderbricks_agent.bookings (
  booking_id      BIGINT NOT NULL,
  user_id          BIGINT,
  property_id       BIGINT,
  check_in           DATE,
  check_out          DATE,
  guests_count        INT,
  total_amount          FLOAT,
  status                 STRING COMMENT 'Confirmed values: pending, confirmed, cancelled, completed.',
  created_at              TIMESTAMP,
  updated_at              TIMESTAMP,
  CONSTRAINT silver_bookings_pk PRIMARY KEY (booking_id)
)
USING DELTA
COMMENT 'Conformed pass-through of bronze bookings. Implements FS-ING-002-POC.';

CREATE TABLE IF NOT EXISTS sandbox_others.silver_wanderbricks_agent.booking_updates (
  booking_update_id  BIGINT NOT NULL,
  booking_id          BIGINT NOT NULL,
  user_id              BIGINT,
  property_id           BIGINT,
  check_in                DATE,
  check_out               DATE,
  guests_count             INT,
  total_amount               FLOAT,
  status                      STRING,
  created_at                    TIMESTAMP,
  updated_at                     TIMESTAMP,
  CONSTRAINT silver_booking_updates_pk PRIMARY KEY (booking_update_id)
)
USING DELTA
COMMENT 'Conformed pass-through of bronze booking_updates. Implements FS-ING-002-POC.';

CREATE TABLE IF NOT EXISTS sandbox_others.silver_wanderbricks_agent.properties (
  property_id        BIGINT NOT NULL,
  host_id              BIGINT,
  destination_id        BIGINT,
  title                   STRING,
  description               STRING,
  base_price                  FLOAT,
  property_type                 STRING,
  max_guests                     INT,
  bedrooms                        INT,
  bathrooms                        INT,
  property_latitude                  FLOAT,
  property_longitude                  FLOAT,
  created_at                            DATE,
  CONSTRAINT silver_properties_pk PRIMARY KEY (property_id)
)
USING DELTA
COMMENT 'Conformed pass-through of bronze properties. No active/status column exists (confirmed by profiling - PRD OQ-02). Implements FS-ING-002-POC.';

CREATE TABLE IF NOT EXISTS sandbox_others.silver_wanderbricks_agent.hosts (
  host_id       BIGINT NOT NULL,
  name           STRING,
  email           STRING,
  phone            STRING,
  is_verified        BOOLEAN,
  is_active           BOOLEAN,
  rating                FLOAT,
  country                STRING,
  joined_at               DATE,
  CONSTRAINT silver_hosts_pk PRIMARY KEY (host_id)
)
USING DELTA
COMMENT 'Conformed pass-through of bronze hosts. Implements FS-ING-002-POC.';

CREATE TABLE IF NOT EXISTS sandbox_others.silver_wanderbricks_agent.users (
  user_id        BIGINT NOT NULL,
  email           STRING,
  name             STRING,
  country            STRING,
  user_type           STRING,
  is_business           BOOLEAN,
  company_name           STRING,
  created_at               TIMESTAMP,
  CONSTRAINT silver_users_pk PRIMARY KEY (user_id)
)
USING DELTA
COMMENT 'Conformed pass-through of bronze users. Implements FS-ING-002-POC.';
```

---

## 3. Silver: classification (implements FS-CLS-001-POC, FS-CLS-002-POC, FS-CLS-004-POC)

### 3.1 `prompt_registry` — versioned prompt templates (implements FS-CLS-004-POC)

Prompts used by any AI/LLM component in this project are never hardcoded inline — they're stored here, addressable by name + version, so a new prompt version (e.g. `v2` of the intent-classification prompt) can be added without a code change to the calling task.

```sql
CREATE TABLE IF NOT EXISTS sandbox_others.silver_wanderbricks_agent.prompt_registry (
  prompt_name     STRING NOT NULL COMMENT 'e.g. "ticket_intent_classification". Groups versions of the same logical prompt.',
  version           INT NOT NULL COMMENT 'Monotonically increasing per prompt_name, starting at 1.',
  template            STRING NOT NULL COMMENT 'The prompt template text. Placeholders (e.g. {{message_thread}}) are substituted by the calling task at call time.',
  model_endpoint         STRING COMMENT 'The Model Serving endpoint this version was designed/tested against, if pinned.',
  is_active                BOOLEAN NOT NULL COMMENT 'Exactly one version per prompt_name should be TRUE at a time - the default used when a version is not explicitly pinned (FS-CLS-004-POC AC-3).',
  notes                      STRING COMMENT 'Changelog: what changed in this version and why.',
  created_by                    STRING NOT NULL,
  created_at                      TIMESTAMP NOT NULL,
  CONSTRAINT prompt_registry_pk PRIMARY KEY (prompt_name, version)
)
USING DELTA
COMMENT 'Versioned prompt templates for AI components. Implements FS-CLS-004-POC.';
```

Append-only, same convention as `ticket_classification` below — a new prompt version is a new row, never an edit to an existing version's `template` (so past classifications stay reproducible against the exact template that produced them). Flipping `is_active` to promote a new default version IS an update, but only ever to that one boolean column, on one row at a time (the newly active row), never to `template`.

### 3.2 `ticket_classification`

```sql
CREATE TABLE IF NOT EXISTS sandbox_others.silver_wanderbricks_agent.ticket_classification (
  classification_id     STRING NOT NULL COMMENT 'Generated (e.g. UUID).',
  ticket_id               STRING NOT NULL COMMENT 'FK to bronze customer_support_logs.ticket_id.',
  intent                    STRING NOT NULL COMMENT 'CANCELLATION | MODIFICATION | REFUND | COMPLAINT | GENERAL_QUESTION | NOT_ACTIONABLE. FS-CLS-001-POC AC-1.',
  extracted_booking_id        BIGINT COMMENT 'NULL if not extractable - never guessed (FS-CLS-002-POC AC-1).',
  extracted_details_json         STRING COMMENT 'JSON blob of intent-specific extracted fields (e.g. requested dates for MODIFICATION, stated reason for REFUND). Shape varies by intent, hence STRING/JSON rather than fixed columns.',
  reasoning_summary                STRING NOT NULL COMMENT 'FS-CLS-001-POC AC-2.',
  confidence                         DOUBLE COMMENT 'Numeric 0-1, per TOQ/OQ-04. Persisted but not gated in the App (PRD Section 6 non-goal).',
  model_endpoint                       STRING COMMENT 'Serving endpoint / model version, for reproducibility.',
  prompt_name                            STRING NOT NULL COMMENT 'FK to prompt_registry.prompt_name. FS-CLS-004-POC AC-1.',
  prompt_version                           INT NOT NULL COMMENT 'FK to prompt_registry.version (with prompt_name). Exact template used for this classification, for reproducibility/audit.',
  classified_at                              TIMESTAMP NOT NULL,
  CONSTRAINT ticket_classification_pk PRIMARY KEY (classification_id),
  CONSTRAINT ticket_classification_prompt_fk FOREIGN KEY (prompt_name, prompt_version)
    REFERENCES sandbox_others.silver_wanderbricks_agent.prompt_registry (prompt_name, version)
)
USING DELTA
COMMENT 'Classification + extraction output per ticket. Implements FS-CLS-001-POC, FS-CLS-002-POC.';
```

Append-only by convention (a retried classification after `CLASSIFICATION_FAILED` gets a new row, not an update) — same convention as SCO Agent's `classification_log`.

---

## 4. Silver: validation (implements FS-VAL-001-POC..005-POC)

```sql
CREATE TABLE IF NOT EXISTS sandbox_others.silver_wanderbricks_agent.ticket_validation (
  validation_id     STRING NOT NULL COMMENT 'Generated (e.g. UUID).',
  ticket_id           STRING NOT NULL,
  check_id              STRING NOT NULL COMMENT 'WBXCHK-01 .. WBXCHK-05, per PRD-WBXAGT-001 Section 9.',
  result                  STRING NOT NULL COMMENT 'PASS | FAIL | WARN.',
  detail                     STRING NOT NULL COMMENT 'Human-readable: what was checked and what was found.',
  checked_at                    TIMESTAMP NOT NULL,
  CONSTRAINT ticket_validation_pk PRIMARY KEY (validation_id)
)
USING DELTA
COMMENT 'One row per WBXCHK result per ticket. Implements FS-VAL-001-POC..005-POC.';
```

---

## 5. Silver: ticket state (implements FS-TRK-001-POC, FS-TRK-002-POC)

### 5.1 `tickets` — current state, what the App primarily reads/writes

```sql
CREATE TABLE IF NOT EXISTS sandbox_others.silver_wanderbricks_agent.tickets (
  ticket_id          STRING NOT NULL COMMENT 'Same as bronze customer_support_logs.ticket_id.',
  current_status        STRING NOT NULL COMMENT 'NEW | CLASSIFYING | CLASSIFICATION_FAILED | VALIDATING | VALIDATED | APPROVED | REJECTED. FS-TRK-001-POC.',
  current_intent            STRING COMMENT 'Denormalized latest intent, for the queue view (FS-APP-001-POC).',
  assigned_reviewer            STRING COMMENT 'Reviewer email, set on Approve/Reject via Databricks Apps OAuth identity (TOQ-04).',
  created_at                      TIMESTAMP NOT NULL,
  updated_at                        TIMESTAMP NOT NULL,
  CONSTRAINT tickets_pk PRIMARY KEY (ticket_id)
)
USING DELTA
COMMENT 'Current ticket state. Implements FS-TRK-001-POC.';
```

### 5.2 `ticket_activity_log` — append-only, what FS-TRK-002-POC requires

```sql
CREATE TABLE IF NOT EXISTS sandbox_others.silver_wanderbricks_agent.ticket_activity_log (
  log_id       STRING NOT NULL COMMENT 'Generated (e.g. UUID).',
  ticket_id      STRING NOT NULL,
  event_type       STRING NOT NULL COMMENT 'CLASSIFICATION_RUN | VALIDATION_RUN | STATUS_CHANGE | OVERRIDE.',
  detail             STRING NOT NULL COMMENT 'Plain-language description. FS-TRK-002-POC AC-2.',
  actor                 STRING NOT NULL COMMENT 'SYSTEM for pipeline-generated events, reviewer email for App actions.',
  occurred_at             TIMESTAMP NOT NULL,
  CONSTRAINT ticket_activity_log_pk PRIMARY KEY (log_id)
)
USING DELTA
COMMENT 'Append-only activity log. No UPDATE/DELETE path in any component (CON-GRD-05). Implements FS-TRK-002-POC.';
```

No database-level immutability enforcement in POC (same limitation SCO Agent's `classification_log` carries) — enforced by convention (no component ever issues UPDATE/DELETE against this table), not by a UC row-level policy. Flag this as a gap if POC graduates to a phase needing real immutability guarantees.

---

## 6. Gold (implements FS-RPT-001-POC..003-POC)

```sql
CREATE TABLE IF NOT EXISTS sandbox_others.gold_wanderbricks_agent.intent_distribution (
  metric_date    DATE NOT NULL,
  intent           STRING NOT NULL,
  ticket_count       BIGINT NOT NULL,
  CONSTRAINT intent_distribution_pk PRIMARY KEY (metric_date, intent)
)
USING DELTA
COMMENT 'Daily ticket count by intent. Implements FS-RPT-001-POC.';

CREATE TABLE IF NOT EXISTS sandbox_others.gold_wanderbricks_agent.resolution_metrics (
  metric_date         DATE NOT NULL,
  avg_resolution_minutes  DOUBLE,
  approve_count             BIGINT,
  reject_count                BIGINT,
  override_count                 BIGINT,
  override_rate                    DOUBLE COMMENT 'override_count / (approve_count + reject_count).',
  CONSTRAINT resolution_metrics_pk PRIMARY KEY (metric_date)
)
USING DELTA
COMMENT 'Daily resolution-time and override metrics. Implements FS-RPT-002-POC.';

CREATE TABLE IF NOT EXISTS sandbox_others.gold_wanderbricks_agent.sentiment_trend (
  metric_date       DATE NOT NULL,
  intent               STRING NOT NULL,
  sentiment_category      STRING NOT NULL COMMENT 'As stored in silver support_messages.sentiment (categorical, not numeric).',
  message_count               BIGINT NOT NULL,
  CONSTRAINT sentiment_trend_pk PRIMARY KEY (metric_date, intent, sentiment_category)
)
USING DELTA
COMMENT 'Daily message sentiment counts by intent. Implements FS-RPT-003-POC.';
```

---

## 7. Entity relationship summary

```
bronze.customer_support_logs ──▶ silver.support_messages (exploded, 1:N)
                                          │
silver.prompt_registry (1:N versions) ───┤
     │ (prompt_name, version)            │
     ▼                                    │
silver.tickets (1) ──────────────────────┼──▶ silver.ticket_classification (1:N, append-only)
     │                                    │         (FK to prompt_registry)
     │                                    └──▶ silver.ticket_validation (1:N)
     │
     └──▶ silver.ticket_activity_log (1:N, append-only)

silver.bookings ──▶ silver.properties ──▶ silver.hosts   (validation join chain, WBXCHK-01/02/03)
silver.bookings ──▶ silver.booking_updates                (WBXCHK-04)
silver.bookings ──▶ silver.users  (via user_id, cross-checked against ticket's user_id — WBXCHK-05)

gold.* ◀── aggregated from silver.tickets / ticket_classification / ticket_validation / support_messages
```

## 8. Which tables need review

All objects in Sections 1, 3, 4, 5, and 6 (silver classification/validation/state tables, `prompt_registry`, all gold tables) are newly proposed — not verified against any existing convention. Section 2 (silver reference tables) column names/types **are** verified against real bronze schema (via `databricks tables get`), so those are lower-risk than a from-scratch guess. Before running any DDL: confirm no naming collision with other work in `sandbox_others`, and confirm the schema names (`silver_wanderbricks_agent`, `gold_wanderbricks_agent`) fit whatever medallion-layer naming convention the team settles on for future projects.
