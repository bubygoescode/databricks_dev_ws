# Technical Specification: SCO Inbox Agent — POC — Test Specification

| Field | Value |
|---|---|
| Document ID | TS-TEST-001-POC |
| Parent | TS-SCO-001-POC-INDEX.md |
| Status | DRAFT |

Every FS-SCO-001-POC acceptance criterion and every guardrail exercised by POC (per index Section 5) has at least one test below. Component references point at [TS-SCO-001-POC-COMPONENTS.md](TS-SCO-001-POC-COMPONENTS.md).

---

## 1. Ingest task tests (FS-INT-001-POC)

| Test ID | Covers | Given | When | Then |
|---|---|---|---|---|
| TC-INT-001-01 | AC-1 | An email arrives at the shared mailbox | Next ingestion cycle runs | A `messages` row exists with body (plain + HTML), sender address, sender display name, received timestamp, subject, thread ID, message ID all populated |
| TC-INT-001-02 | AC-2 | A message has one or more attachments | Ingestion completes | Each attachment has an `attachments` row with original filename, MIME type, size, and `message_id` FK set |
| TC-INT-001-03 | AC-3 | A message with a given `message_id` was already ingested | The same message is seen again in a later cycle | No duplicate `messages` row is created; row count for that `message_id` stays 1 |
| TC-INT-001-04 | Error: connectivity failure | The mailbox connection is unavailable | An ingestion cycle runs | The cycle logs the error and does not advance the delta token; the next cycle retries |
| TC-INT-001-05 | Error: attachment download failure | An attachment fails to download | Ingestion completes | The parent `messages` row is still persisted; the attachment row has `download_status = 'FAILED_DOWNLOAD'` and `volume_path = NULL` |
| TC-INT-001-06 | Error: storage write failure | A Delta write fails mid-batch | The cycle completes | The affected message is not marked processed (delta token not advanced); it is retried next cycle without becoming a duplicate |

---

## 2. Classify task tests (FS-TRI-001-POC)

| Test ID | Covers | Given | When | Then |
|---|---|---|---|---|
| TC-TRI-001-01 | AC-1 | A non-actionable email (e.g. "Thank you for...", read receipt, out-of-office, spam) | Triage runs | Message enters `IRRELEVANT`; a `classification_log` row records `stream = 'IRRELEVANT'` |
| TC-TRI-001-02 | AC-2 | An actionable PIR or Source List creation/update request | Triage runs | Message classified `RELEVANT_CREATE_UPDATE` |
| TC-TRI-001-03 | AC-3 | An actionable Source List hard-deletion request | Triage runs | Message classified `RELEVANT_HARD_DELETE` |
| TC-TRI-001-04 | AC-4 | Any classification decision | It is recorded | `classification_log` row includes message ID, chosen stream, reasoning summary, timestamp |
| TC-TRI-001-05 | Error: model failure | The Model Serving endpoint returns an error or malformed/non-schema-conforming output | Classification is attempted | `messages.processing_state = 'CLASSIFICATION_FAILED'`; no `classification_log` row written; error logged |
| TC-TRI-001-06 | Error: timeout | The model call exceeds the configured timeout | Classification is attempted | Same as TC-TRI-001-05 |
| TC-TRI-001-07 | POC limitation | A message has an attachment but no usable body text | Classification runs | `processing_state = 'CLASSIFICATION_FAILED'` (attachment-based classification is out of POC scope) |

---

## 3. Ticket task tests (FS-TRK-001-POC)

| Test ID | Covers | Given | When | Then |
|---|---|---|---|---|
| TC-TRK-001-01 | AC-1 | A message classified relevant | The ticket task runs | Exactly one `tickets` row exists for it, with a unique `ticket_id` |
| TC-TRK-001-02 | AC-2 | A ticket is created | — | `ticket_id` matches `SCO-NNNNNN` format |
| TC-TRK-001-03 | AC-3 | A ticket is created | — | `status = 'NEW'` |
| TC-TRK-001-04 | AC-4 | A ticket is created | — | Row contains ticket ID, status, source message reference, thread ID, created timestamp — all non-null |
| TC-TRK-001-05 | Error: ID collision | Two ticket-task runs attempt to claim the same `next_value` concurrently (simulate via concurrent conditional `UPDATE`) | Both attempt to commit | Exactly one succeeds; the other's `UPDATE` affects 0 rows, retries, and succeeds with the next value; the collision is logged; no two tickets ever share an ID |

---

## 4. Guardrail tests

| Test ID | Guardrail | Given | When | Then |
|---|---|---|---|---|
| TC-GRD-08-01 | CON-GRD-08 | An attachment is downloaded | Storage is checked | The binary is written to the `sandbox_others.sco_agent_poc.attachments` Unity Catalog volume, not to ungoverned storage (e.g. local disk, an untracked cloud bucket) |

---

## 5. POC-level success criteria tests (FSD Section 4)

These run against the 5-day test period / live-or-shadow traffic described in the FSD, not as isolated unit tests.

| Test ID | Criterion | Measurement | Pass threshold |
|---|---|---|---|
| TC-POC-01 | Ingestion completeness | Compare mailbox message count (via Graph/IMAP) against `messages` row count over the test period | 100% — zero silent drops |
| TC-POC-02 | Deduplication | Count distinct `message_id` vs. total row count in `messages` after repeated polling cycles over the same mail | Equal — zero duplicates |
| TC-POC-03 | Classification accuracy | Score `classification_log.stream` against a human-labelled sample of ≥50 messages | ≥85% agreement |
| TC-POC-04 | Pipeline reliability | % of scheduled Job runs completing all three tasks without unrecoverable failure, over 5 days | ≥95% |
| TC-POC-05 | Latency | Time from `messages.received_at`/`ingested_at` to the corresponding `classification_log.classified_at`, p95 | ≤30 seconds |

---

## 6. Traceability check

Every FS-SCO-001-POC AC (Section 2 of the FSD) and every guardrail listed in the TS index (Section 5) maps to at least one test above. No FS acceptance criterion or exercised guardrail is uncovered.
