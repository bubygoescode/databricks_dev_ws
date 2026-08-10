# Technical Specification: WBXAGT POC — Pipeline Components

| Field | Value |
|---|---|
| Document ID | TS-ING-001-WBXAGT-POC, TS-CLS-001-WBXAGT-POC, TS-VAL-001-WBXAGT-POC, TS-RPT-001-WBXAGT-POC, TS-TOPO-001-WBXAGT-POC |
| Parent | TS-WBXAGT-001-POC-INDEX.md |
| Status | DRAFT |

Tables referenced below are defined in [TS-WBXAGT-001-POC-DATA-MODEL.md](TS-WBXAGT-001-POC-DATA-MODEL.md). The Databricks App is specified separately in [TS-WBXAGT-001-POC-APP.md](TS-WBXAGT-001-POC-APP.md).

---

## 0. Agent topology (TS-TOPO-001-WBXAGT-POC)

One Databricks Workflow, four sequential tasks, scheduled every 15 minutes (TOQ-02):

| Task | Type | Calls a model? | Implements |
|---|---|---|---|
| `silver_transform` | Python/PySpark | No | FS-ING-001-POC, FS-ING-002-POC |
| `classify` | Python | **Yes** | FS-CLS-001-POC, FS-CLS-002-POC, FS-CLS-003-POC |
| `validate` | Python/PySpark | No | FS-VAL-001-POC..005-POC |
| `gold_aggregate` | Python/PySpark | No | FS-RPT-001-POC..003-POC |

The App (separate module) is not a Job task — it's an always-on deployable reading/writing `silver.tickets` and `silver.ticket_activity_log` directly via SQL warehouse, independent of the pipeline schedule.

Coordination is entirely through `silver.tickets.current_status`, same pattern as SCO Agent's `messages.processing_state` — each task reads only what the previous task committed, keeping tasks independently retryable.

---

## 1. `silver_transform` task (implements FS-ING-001-POC, FS-ING-002-POC)

### 1.1 Logic

1. Read `bronze.customer_support_logs`. For each row not yet represented in `silver.support_messages` (checked by ticket_id): explode `messages[]`, insert one row per message into `silver.support_messages` (FS-ING-001-POC AC-1/AC-2).
2. For each new `ticket_id` seen, upsert a row into `silver.tickets` with `current_status = 'NEW'` if not already present.
3. Read `bronze.{bookings, booking_updates, properties, hosts, users}`; type-conform and upsert (MERGE on primary key) into the corresponding `silver.*` tables (FS-ING-002-POC AC-1/AC-2). A row failing type conformance (e.g. unparseable `message_timestamp`) is excluded with a logged reason, not coerced (FS-ING-002-POC error behaviour).
4. Append a `SYSTEM`-actor `ticket_activity_log` row for each newly created ticket (`event_type = 'STATUS_CHANGE'`, detail: "Ticket created from ingested support thread").

### 1.2 Error behaviour

| Failure | Behaviour |
|---|---|
| Malformed/null `messages[]` on a bronze row | Zero silver message rows for that ticket, logged warning; other tickets in the batch are unaffected (FS-ING-001-POC error behaviour) |
| Reference row fails type conformance | Excluded from silver with a logged reason (FS-ING-002-POC error behaviour) |

---

## 2. `classify` task (implements FS-CLS-001-POC, FS-CLS-002-POC, FS-CLS-003-POC)

### 2.1 Model call (TOQ-01)

Input: all `silver.support_messages` rows for a given `ticket_id` with `silver.tickets.current_status = 'NEW'`, concatenated in timestamp order.

Call a Databricks Model Serving endpoint requesting a schema-constrained JSON response:

```json
{
  "intent": "CANCELLATION" | "MODIFICATION" | "REFUND" | "COMPLAINT" | "GENERAL_QUESTION" | "NOT_ACTIONABLE",
  "reasoning": "<plain language>",
  "extracted_booking_id": <integer or null>,
  "extracted_details": { "...": "intent-specific fields, e.g. requested_check_in/requested_check_out for MODIFICATION, stated_reason for REFUND" },
  "confidence": <float 0-1>
}
```

Use structured/constrained outputs, not free-text parsing (CON-GRD-02) — a malformed response is a failure (2.3), never coerced into a guess (product principle 3, FS-CLS-002-POC AC-1).

### 2.2 Logic

1. Set `silver.tickets.current_status = 'CLASSIFYING'`.
2. Call the model (2.1).
3. On success: insert a `silver.ticket_classification` row; update `silver.tickets.current_status = 'VALIDATING'` and `current_intent`; append a `ticket_activity_log` row (`event_type = 'CLASSIFICATION_RUN'`).
4. On failure/malformed response: `current_status = 'CLASSIFICATION_FAILED'`, log the error, no `ticket_classification` row written (FS-CLS-003-POC).

### 2.3 Error behaviour

Same as FS-CLS-003-POC: model failure, timeout, or non-schema-conforming output → `CLASSIFICATION_FAILED`, retried ad hoc (no automated retry loop in POC, matching SCO Agent's equivalent pattern).

---

## 3. `validate` task (implements FS-VAL-001-POC..005-POC / WBXCHK-01..05)

### 3.1 Logic

For each ticket with `current_status = 'VALIDATING'` and an actionable intent (not `GENERAL_QUESTION`/`NOT_ACTIONABLE`):

1. **WBXCHK-01** (FS-VAL-001-POC): look up `extracted_booking_id` in `silver.bookings`. Not found → `FAIL`. Found with `status NOT IN ('pending','confirmed')` → `FAIL`, detail names the actual status. Found and modifiable → `PASS`.
2. **WBXCHK-02/03** (FS-VAL-002-POC): resolve `bookings.property_id` → `silver.properties`; `properties.host_id` → `silver.hosts`. Property: `PASS` if found (existence-only, no status field — confirmed by profiling, Data Model §2). Host: `PASS` only if `is_active = true AND is_verified = true`, else `FAIL`.
3. **WBXCHK-04** (FS-VAL-003-POC): query `silver.booking_updates` for any row with the same `booking_id` not yet resolved (POC definition of "resolved": no corresponding `APPROVED`/`REJECTED` ticket references it — simplest available signal given `booking_updates` itself carries no resolution flag). Found → `WARN`, naming the conflicting `booking_update_id`. Not found → `PASS`.
4. **WBXCHK-05** (FS-VAL-004-POC): compare the ticket's `user_id` (denormalized on `silver.support_messages`/bronze `customer_support_logs`) against `silver.bookings.user_id`. Mismatch → `FAIL`. Match → `PASS`.
5. Insert one `silver.ticket_validation` row per check (five per actionable ticket; `GENERAL_QUESTION`/`NOT_ACTIONABLE` tickets get zero validation rows and move straight to `VALIDATED`).
6. Update `silver.tickets.current_status = 'VALIDATED'`. Append a `ticket_activity_log` row (`event_type = 'VALIDATION_RUN'`, detail summarizing pass/fail/warn counts).

### 3.2 Error behaviour

A `booking_id` that doesn't resolve to any silver row is a hard `FAIL` for WBXCHK-01, not a skipped check (FS-VAL-001-POC error behaviour) — the ticket still reaches `VALIDATED` (validation *ran*, it just found a problem); it's the App's Approve gate (see App module) that blocks on `FAIL` results, not this task.

---

## 4. Shared: ticket state updates

Any component that changes `silver.tickets.current_status` or `current_intent` MUST, in the same transaction/batch:
1. Update the `tickets` row.
2. Append a corresponding `ticket_activity_log` row with a plain-language `detail`.

This is not a separate task — it's a rule every task (and the App) follows, so `ticket_activity_log` is always a complete, ordered record (FS-TRK-002-POC AC-2) with no gap between what happened and what's logged.

---

## 5. `gold_aggregate` task (implements FS-RPT-001-POC..003-POC)

### 5.1 Logic

Runs after `validate` completes each cycle. For the current day (and backfillable for prior days if the pipeline was down):

1. **`intent_distribution`** (FS-RPT-001-POC): `GROUP BY DATE(classified_at), intent` over `silver.ticket_classification`, `COUNT(*)`. Upsert into `gold.intent_distribution`.
2. **`resolution_metrics`** (FS-RPT-002-POC): for tickets reaching `APPROVED`/`REJECTED` that day (per `ticket_activity_log` `STATUS_CHANGE` events), compute `avg(resolution_minutes)` = time between the `NEW`-creation activity-log entry and the terminal-status entry (PRD OQ-03 default); count approvals, rejections, and `OVERRIDE` events (App module AC-2); `override_rate = override_count / (approve_count + reject_count)`. Upsert into `gold.resolution_metrics`.
3. **`sentiment_trend`** (FS-RPT-003-POC): `GROUP BY DATE(message_timestamp), intent (joined from ticket_classification), sentiment_category` over `silver.support_messages`, `COUNT(*)`. Upsert into `gold.sentiment_trend`.

### 5.2 Error behaviour

A gold aggregation failure does not block the next pipeline cycle's `silver_transform`/`classify`/`validate` — gold is a downstream reporting concern, re-computed idempotently (upsert, not append) each run.
