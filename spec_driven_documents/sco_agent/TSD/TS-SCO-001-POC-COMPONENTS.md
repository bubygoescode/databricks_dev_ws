# Technical Specification: SCO Inbox Agent — POC — Components

| Field | Value |
|---|---|
| Document ID | TS-INT-001-POC, TS-TRI-001-POC, TS-TRK-001-POC, TS-TOPO-001-POC |
| Parent | TS-SCO-001-POC-INDEX.md |
| Status | DRAFT |

Tables referenced below are defined in [TS-SCO-001-POC-DATA-MODEL.md](TS-SCO-001-POC-DATA-MODEL.md).

---

## 0. Agent topology (TS-TOPO-001-POC)

One Databricks Workflow (Job), three sequential tasks, scheduled every 5 minutes (TOQ-02):

| Task | Type | Calls a model? | Implements |
|---|---|---|---|
| `ingest` | Python/PySpark notebook or `.py` task | No | FS-INT-001-POC |
| `classify` | Python task | **Yes** — calls a Model Serving endpoint | FS-TRI-001-POC |
| `ticket` | Python/PySpark task | No | FS-TRK-001-POC |

Each task reads only what the previous task committed (via `processing_state` on `messages`), so a task failing and retrying does not require re-running earlier tasks. This is what makes the pipeline safe to schedule frequently without building a full workflow engine for POC.

Only `classify` is "agentic" in the PRD's sense — it's the one step making a judgement call, not just moving/structuring data. `ingest` and `ticket` are deterministic ETL and should not be routed through an LLM.

---

## 1. Ingest task (implements FS-INT-001-POC)

### 1.1 Mailbox access (TOQ-01)

Proposed: Microsoft Graph API, application permissions (`Mail.Read`) scoped to the shared mailbox `sco_procurementdata@asm.com`, using an app registration + client-credentials OAuth flow (no interactive user login, no stored mailbox password). Use Graph's delta query (`/users/{mailbox}/mailFolders/inbox/messages/delta`) to fetch only new/changed messages since the last sync token, rather than re-scanning the whole mailbox each cycle.

If the mailbox is not Exchange Online/M365 (unconfirmed — see TOQ-01), swap this for IMAP polling with `UIDNEXT` tracking as the equivalent incremental mechanism. Either way, the dedup check in step 1.3 is the actual data-integrity guarantee — the sync mechanism is just an efficiency layer.

### 1.2 Logic

1. Fetch new/changed messages since the last delta token (or full poll on first run / token expiry).
2. For each message not already in `messages` (checked by `message_id`, matching FS-INT-001-POC AC-3):
   a. Insert a row into `messages` with `processing_state = 'RECEIVED'`.
   b. For each attachment: attempt download to the `attachments` volume; insert a row into `attachments` with `download_status = 'OK'` and `volume_path` set, or `download_status = 'FAILED_DOWNLOAD'` and `volume_path = NULL` on failure (FS-INT-001-POC "Attachment download failure" behaviour).
3. Persist the new delta token only after the batch commits successfully (see error behaviour below) — this bounds re-processing after a crash to at most one batch.

### 1.3 Error behaviour (per FS-INT-001-POC)

| Failure | Behaviour |
|---|---|
| Mailbox connectivity failure | Log error, do not advance the delta token, retry on next scheduled cycle |
| Attachment download failure | Persist the message row regardless; mark that attachment `FAILED_DOWNLOAD` |
| Storage (Delta) write failure | Do not advance the delta token / do not acknowledge the message as processed; next cycle retries it. Dedup on `message_id` makes this retry-safe |

### 1.4 POC limitations (carried from FSD, not addressed here)

No alerting on consecutive failures, no governed-storage enforcement beyond the UC Volume default, inline images stored but not parsed. Do not build these now — MVP scope.

---

## 2. Classify task (implements FS-TRI-001-POC)

### 2.1 Model call (TOQ-03)

Input: `subject` + `body_plain` (fallback to a stripped `body_html` if `body_plain` is empty) for every `messages` row with `processing_state = 'RECEIVED'`. Attachments are **not** part of the POC classification input — FSD explicitly scopes attachment-based classification to MVP, and a body-less, attachment-only message is defined to fail classification in POC (see 2.3).

Call a Databricks Model Serving endpoint (an Agent Bricks classification agent, or a foundation model behind a constrained/structured output schema) requesting exactly one of:

```json
{ "stream": "IRRELEVANT" | "RELEVANT_CREATE_UPDATE" | "RELEVANT_HARD_DELETE",
  "reasoning": "<plain language, one or two sentences>" }
```

Use a JSON-schema-constrained response (structured outputs / function-calling, whichever the chosen endpoint supports) rather than free-text parsing — a malformed response should be treated as a model failure (2.3), not silently coerced into a guess. This also anticipates CON-GRD-06 ("model output constrained to schema") from the PRD, which applies from R2 onward but is cheap to satisfy from POC.

### 2.2 Logic

1. For each `messages` row in `RECEIVED` state: set `processing_state = 'CLASSIFYING'`.
2. Call the model (2.1).
3. On success: insert a `classification_log` row (stream, reasoning, model endpoint, latency); set `messages.processing_state` to `IRRELEVANT` if stream is `IRRELEVANT`, otherwise leave it for the `ticket` task to move to `TICKET_CREATED` (see Section 3).
4. On failure or timeout: set `processing_state = 'CLASSIFICATION_FAILED'`, log the error. No `classification_log` row is written for a failed attempt.

### 2.3 Error behaviour (per FS-TRI-001-POC)

| Failure | Behaviour |
|---|---|
| Classification model failure | `processing_state = 'CLASSIFICATION_FAILED'`, logged for manual inspection |
| Timeout during classification | Same as model failure |
| Message has an attachment but no usable body | `processing_state = 'CLASSIFICATION_FAILED'` (POC does not attempt attachment-based classification) |

`CLASSIFICATION_FAILED` is retried ad hoc per the FSD state machine (Section 3.1) — POC does not need an automated retry loop, a validator/operator re-triggers it manually.

---

## 3. Ticket task (implements FS-TRK-001-POC)

### 3.1 Logic

For each `messages` row with `processing_state` in (`CLASSIFYING`-completed-relevant, i.e. classified `RELEVANT_CREATE_UPDATE` or `RELEVANT_HARD_DELETE` per the latest `classification_log` row and not yet ticketed):

1. Generate the next ticket ID:
   ```sql
   -- optimistic concurrency: read, compute, conditional update; retry on conflict
   SELECT next_value FROM sandbox_others.sco_agent_poc.ticket_id_counter WHERE counter_name = 'SCO';
   -- candidate_id = next_value; new_value = next_value + 1
   UPDATE sandbox_others.sco_agent_poc.ticket_id_counter
     SET next_value = <new_value>
     WHERE counter_name = 'SCO' AND next_value = <next_value>;  -- 0 rows affected => collision, retry from SELECT
   ```
   Format as `SCO-NNNNNN` (zero-padded to 6 digits) from `candidate_id`. This directly implements FS-TRK-001-POC's documented "ID generation collision: retry with next sequential value" behaviour.
2. Insert into `tickets`: `ticket_id`, `status = 'NEW'`, `source_message_id`, `thread_id` (copied from `messages`), `created_at = now()`.
3. Set `messages.processing_state = 'TICKET_CREATED'`.

### 3.2 Error behaviour (per FS-TRK-001-POC)

| Failure | Behaviour |
|---|---|
| ID generation collision (conditional UPDATE affects 0 rows) | Retry the SELECT/UPDATE cycle with the next value; log the collision |

### 3.3 POC limitations (carried from FSD, not addressed here)

No object type/intent on the ticket, no assignee, no status transitions beyond `NEW`, no activity-log immutability enforcement. MVP scope.

---

## 4. Interfaces summary

| Task | Reads | Writes |
|---|---|---|
| `ingest` | Graph API / IMAP | `messages`, `attachments` |
| `classify` | `messages` (RECEIVED), Model Serving endpoint | `messages` (state), `classification_log` |
| `ticket` | `messages` (classified, relevant), `ticket_id_counter` | `tickets`, `messages` (state), `ticket_id_counter` |

No task calls another task directly — coordination is entirely through `messages.processing_state`, which keeps each task independently retryable and testable.
