# Technical Specification: SCO Inbox Agent — POC — Data Model

| Field | Value |
|---|---|
| Document ID | TS-DATA-001-POC |
| Parent | TS-SCO-001-POC-INDEX.md, FS-SCO-001-POC |
| Status | DRAFT |

> **⚠ Accuracy flag**: every catalog/schema/table name and DDL statement below is **proposed by this document**, not confirmed against any pre-existing ASM data estate. Nothing here has been checked against real Unity Catalog contents. Before running any DDL, re-verify against the actual `sandbox_others` catalog — check for naming collisions, existing conventions, or a schema this should join into instead of duplicating. Correct this file directly, or ask for a recheck once the real catalog contents are known.

---

## 0. Namespace

| Level | Value | Why |
|---|---|---|
| Catalog | `sandbox_others` | Only catalog this project is authorized to read/write (see `guardrails/CATALOG_POLICY.md`) |
| Schema | `sco_agent_poc` | Isolated per-phase schema so POC objects are easy to identify and tear down without touching MVP/Pilot objects later. **Proposed** — rename if ASM has a house schema-naming convention this should follow instead |
| Volume | `sandbox_others.sco_agent_poc.attachments` | Attachment binaries (see TOQ-04 in the index) |

All tables below live at `sandbox_others.sco_agent_poc.<table>`.

---

## 1. Setup

```sql
CREATE SCHEMA IF NOT EXISTS sandbox_others.sco_agent_poc
  COMMENT 'SCO Inbox Agent - POC phase. See spec_driven_documents/sco_agent/TSD.';

CREATE VOLUME IF NOT EXISTS sandbox_others.sco_agent_poc.attachments
  COMMENT 'Attachment binaries for ingested SCO mailbox messages (POC).';
```

---

## 2. Ingestion tables (implements FS-INT-001-POC)

### 2.1 `messages`

One row per ingested email. Primary key `message_id` is the mail system's own message ID, which is what FS-INT-001-POC AC-3 dedups on.

```sql
CREATE TABLE IF NOT EXISTS sandbox_others.sco_agent_poc.messages (
  message_id           STRING NOT NULL COMMENT 'Mail system message ID. Dedup key (FS-INT-001-POC AC-3).',
  thread_id            STRING COMMENT 'Mail system conversation/thread ID.',
  subject               STRING,
  sender_address        STRING NOT NULL,
  sender_display_name   STRING,
  body_plain            STRING,
  body_html             STRING,
  received_at           TIMESTAMP NOT NULL,
  ingested_at           TIMESTAMP NOT NULL COMMENT 'When this pipeline persisted the record, not when the mail arrived.',
  processing_state      STRING NOT NULL COMMENT 'RECEIVED | CLASSIFYING | IRRELEVANT | TICKET_CREATED | CLASSIFICATION_FAILED. See state machine, FSD Section 3.1.',
  CONSTRAINT messages_pk PRIMARY KEY (message_id)
)
USING DELTA
COMMENT 'Ingested SCO mailbox messages. Implements FS-INT-001-POC.';
```

`processing_state` is intentionally on this table rather than a separate state table — POC has no need for state history, only current state (FSD Section 3.1 marks IRRELEVANT/TICKET_CREATED as terminal, CLASSIFICATION_FAILED as ad-hoc retry).

### 2.2 `attachments`

```sql
CREATE TABLE IF NOT EXISTS sandbox_others.sco_agent_poc.attachments (
  attachment_id     STRING NOT NULL COMMENT 'Generated (e.g. UUID), not from the mail system.',
  message_id        STRING NOT NULL COMMENT 'FK to messages.message_id.',
  original_filename STRING NOT NULL,
  mime_type         STRING,
  size_bytes         BIGINT,
  volume_path        STRING COMMENT 'Path under the attachments volume once downloaded. NULL if download failed.',
  download_status    STRING NOT NULL COMMENT 'OK | FAILED_DOWNLOAD. See FS-INT-001-POC error behaviour.',
  ingested_at         TIMESTAMP NOT NULL,
  CONSTRAINT attachments_pk PRIMARY KEY (attachment_id),
  CONSTRAINT attachments_message_fk FOREIGN KEY (message_id) REFERENCES sandbox_others.sco_agent_poc.messages (message_id)
)
USING DELTA
COMMENT 'Attachment metadata for ingested messages. Binary content in the attachments volume. Implements FS-INT-001-POC AC-2.';
```

Note: FS-INT-001-POC says inline images are stored as attachments for POC but not parsed — no special handling needed here beyond storing them like any other attachment.

---

## 3. Classification table (implements FS-TRI-001-POC)

```sql
CREATE TABLE IF NOT EXISTS sandbox_others.sco_agent_poc.classification_log (
  classification_id  STRING NOT NULL COMMENT 'Generated (e.g. UUID).',
  message_id          STRING NOT NULL COMMENT 'FK to messages.message_id.',
  stream               STRING NOT NULL COMMENT 'IRRELEVANT | RELEVANT_CREATE_UPDATE | RELEVANT_HARD_DELETE. See FS-TRI-001-POC AC-1..3.',
  reasoning_summary    STRING NOT NULL COMMENT 'Plain-language reasoning. FS-TRI-001-POC AC-4.',
  model_endpoint       STRING COMMENT 'Serving endpoint / model version used, for reproducibility.',
  latency_ms           BIGINT,
  classified_at         TIMESTAMP NOT NULL,
  CONSTRAINT classification_log_pk PRIMARY KEY (classification_id),
  CONSTRAINT classification_log_message_fk FOREIGN KEY (message_id) REFERENCES sandbox_others.sco_agent_poc.messages (message_id)
)
USING DELTA
COMMENT 'Classification decisions and reasoning per message. Implements FS-TRI-001-POC AC-4.';
```

Append-only by convention in POC (not yet enforced — activity-log immutability enforcement is explicitly deferred past POC per FSD Section 2.3 POC limitations). A message reclassified after a `CLASSIFICATION_FAILED` retry gets a new row here, not an update to the old one, so history isn't lost even before enforcement exists.

---

## 4. Ticketing table (implements FS-TRK-001-POC)

### 4.1 `tickets`

```sql
CREATE TABLE IF NOT EXISTS sandbox_others.sco_agent_poc.tickets (
  ticket_id            STRING NOT NULL COMMENT 'Format SCO-NNNNNN. FS-TRK-001-POC AC-2.',
  status                STRING NOT NULL COMMENT 'NEW only, in POC. FS-TRK-001-POC AC-3.',
  source_message_id     STRING NOT NULL COMMENT 'FK to messages.message_id.',
  thread_id              STRING,
  created_at             TIMESTAMP NOT NULL,
  CONSTRAINT tickets_pk PRIMARY KEY (ticket_id),
  CONSTRAINT tickets_message_fk FOREIGN KEY (source_message_id) REFERENCES sandbox_others.sco_agent_poc.messages (message_id)
)
USING DELTA
COMMENT 'One row per relevant message. Implements FS-TRK-001-POC.';
```

### 4.2 `ticket_id_counter`

Backs the sequential `SCO-NNNNNN` ID. A plain Delta `IDENTITY` column would not produce FSD's documented "ID generation collision: retry with next sequential value" error path (identity columns don't collide) — so FSD's own error behaviour implies a manually-managed counter instead, and that's what this table is for.

```sql
CREATE TABLE IF NOT EXISTS sandbox_others.sco_agent_poc.ticket_id_counter (
  counter_name  STRING NOT NULL COMMENT 'Fixed value "SCO", allows future counters without a schema change.',
  next_value     BIGINT NOT NULL,
  CONSTRAINT ticket_id_counter_pk PRIMARY KEY (counter_name)
)
USING DELTA
COMMENT 'Atomic sequence source for ticket IDs. See TS-SCO-001-POC-COMPONENTS.md Section 3 for the increment logic.';

-- seed row, run once
INSERT INTO sandbox_others.sco_agent_poc.ticket_id_counter (counter_name, next_value)
VALUES ('SCO', 1);
```

If a native, collision-free counter is acceptable after all (i.e. the FSD's collision language was aspirational rather than a hard requirement), this table and the retry logic in Components §3 can be replaced with a Delta `GENERATED ALWAYS AS IDENTITY` column — flag this back if that's the preferred simplification.

---

## 5. Entity relationship summary

```
messages 1───N attachments
messages 1───N classification_log
messages 1───0..1 tickets   (only relevant messages get a ticket)
ticket_id_counter            (standalone, no FK — sequence source only)
```

---

## 6. Which tables need review

Per the request to flag this explicitly: **all six objects above** (`messages`, `attachments`, `classification_log`, `tickets`, `ticket_id_counter`, and the `attachments` volume) are newly proposed by this document. None were verified against existing Databricks catalog contents beyond confirming `sandbox_others` itself exists and is writable. Before running the DDL in Section 1–4:

1. Check `sandbox_others` for an existing `sco_agent_poc`-equivalent schema or naming convention.
2. Confirm no naming collision with other sandbox work in the same catalog.
3. Confirm the `attachments` volume location/quota is acceptable.

If any of the above turns up something different, correct this file (or ask for a recheck) before the Components module's code is implemented against it.
