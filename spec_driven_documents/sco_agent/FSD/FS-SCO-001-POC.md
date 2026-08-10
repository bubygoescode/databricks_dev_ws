# Functional Specification: SCO Inbox Agent — POC (Proof of Concept)

| Field | Value |
|---|---|
| Document ID | FS-SCO-001-POC |
| Version | 1.0 |
| Status | DRAFT |
| Parent | PRD-SCO-001 |
| Owner | AI Projects Analyst, ASM SCO |
| Phase | POC |
| Scope | PR-INT-001 (partial), PR-TRI-001 (partial), PR-TRK-001 (partial) |

---

## 1. Overview

This specification defines the POC phase of the SCO Inbox Agent. The POC proves technical feasibility of the core pipeline: polling the shared mailbox, classifying messages into three streams, and creating tickets for relevant requests.

The POC is an internal-only demonstration. It has no user-facing UI, no production error recovery, and no SLA. Its purpose is to validate that the classification model can reliably separate actionable from non-actionable email, and that the ingestion pipeline handles real mailbox traffic without data loss.

**What POC delivers**: a working end-to-end pipeline from mailbox poll to ticket creation, exercised against live (or shadow-mode) traffic.

**What POC does not deliver**: language cascade (MVP), manual promotion (MVP), object type/intent identification (MVP), multi-intent decomposition (Pilot), message register (Pilot), activity log immutability guarantees (MVP), or any UI.

---

## 2. Functional requirements

### 2.1 Ingestion

#### FS-INT-001-POC Mailbox polling and message persistence (core)

- **Implements**: PR-INT-001 (partial)
- **Description**: The system polls the shared mailbox `sco_procurementdata@asm.com` on a recurring schedule. Every message is persisted with its full content and metadata. Duplicate messages are not re-ingested.
- **Acceptance**:
  - AC-1: Given an email arrives at the shared mailbox, when the next ingestion cycle runs, then a message record exists containing: body (plain and HTML), sender address, sender display name, received timestamp, subject, thread ID, message ID, and a reference to every attachment.
  - AC-2: Given an attachment exists on a message, when ingestion completes, then the attachment is stored with its original filename, MIME type, size, and a link to the parent message record.
  - AC-3: Given a message has been previously ingested (same message ID), when the cycle encounters it again, then it is skipped without creating a duplicate record.
- **Error behaviour**:
  - Mailbox connectivity failure: log error, retry on next cycle.
  - Attachment download failure: persist the message record, mark attachment as `FAILED_DOWNLOAD`.
  - Storage write failure: do not acknowledge message as processed; it will be retried.
- **POC limitations**:
  - No alerting on consecutive cycle failures (deferred to MVP).
  - No governed storage requirement (any accessible storage is acceptable for POC).
  - Inline images are stored as attachments but not parsed.

### 2.2 Classification

#### FS-TRI-001-POC Three-stream classification (core)

- **Implements**: PR-TRI-001 (partial)
- **Description**: Every ingested message is classified into exactly one of three streams: irrelevant, relevant (create/update), or relevant (Source List hard delete). Classification reasoning is logged.
- **Acceptance**:
  - AC-1: Given a non-actionable email (e.g., "Thank you for...", read receipts, out-of-office replies, spam), when triage runs, then it enters the irrelevant stream.
  - AC-2: Given an actionable request for PIR or Source List creation or update, when triage runs, then it enters the relevant (create/update) stream.
  - AC-3: Given an actionable request for Source List hard deletion, when triage runs, then it enters the relevant (hard delete) stream.
  - AC-4: Given any classification decision, when it is recorded, then a log entry includes: message ID, chosen stream, reasoning summary, and timestamp.
- **Error behaviour**:
  - Classification model failure: message enters a `CLASSIFICATION_FAILED` state, logged for manual inspection.
  - Timeout during classification: same as model failure.
- **POC limitations**:
  - Ambiguous messages may be misclassified without review mechanism (manual promotion deferred to MVP).
  - No validator-facing queue (deferred to MVP).
  - Email containing only an attachment with no body: classified as `CLASSIFICATION_FAILED` for POC; full attachment-based classification deferred to MVP.

### 2.3 Ticket lifecycle

#### FS-TRK-001-POC Ticket creation and identity (core)

- **Implements**: PR-TRK-001 (partial)
- **Description**: Every message classified as relevant has exactly one ticket with a stable, system-generated identifier.
- **Acceptance**:
  - AC-1: Given any relevant message, when classification completes, then exactly one ticket exists for it with a unique, immutable ticket ID.
  - AC-2: The ticket ID is a human-readable sequential identifier (format: `SCO-NNNNNN`).
  - AC-3: Given a ticket is created, then its initial status is `NEW`.
  - AC-4: The ticket record contains: ticket ID, status, source message reference, thread ID, and created timestamp.
- **Error behaviour**:
  - ID generation collision: retry with next sequential value. Log the collision.
- **POC limitations**:
  - No object type or intent on the ticket (deferred to MVP).
  - No assignee field (deferred to MVP).
  - No status transitions beyond `NEW` (deferred to MVP).
  - No activity log immutability enforcement (deferred to MVP).

---

## 3. State machines

### 3.1 Message lifecycle (POC)

```
RECEIVED -> CLASSIFYING -> [IRRELEVANT | TICKET_CREATED | CLASSIFICATION_FAILED]
```

| State | Entry condition | Exit condition |
|---|---|---|
| RECEIVED | Message persisted by ingestion | Classification starts |
| CLASSIFYING | Classification process begins | Classification completes or fails |
| IRRELEVANT | Classification output: not actionable | Terminal for POC |
| TICKET_CREATED | Ticket successfully created | Terminal for POC |
| CLASSIFICATION_FAILED | Classification error | Manual retry (ad hoc) |

### 3.2 Ticket lifecycle (POC)

```
NEW (terminal for POC)
```

| State | Entry condition | Exit condition |
|---|---|---|
| NEW | Ticket created by triage | No transitions in POC |

---

## 4. POC success criteria

The POC is successful if:

1. **Ingestion completeness**: 100% of messages arriving during the test period are persisted (no silent drops).
2. **Deduplication**: No duplicate records created across multiple polling cycles.
3. **Classification accuracy**: ≥85% agreement with human classification on a labelled sample of ≥50 messages.
4. **Pipeline reliability**: The pipeline completes ≥95% of cycles without unrecoverable failure over a 5-day test period.
5. **Latency**: Classification completes within 30 seconds of message ingestion for ≥95% of messages.

---

## 5. Mapping table

| PR Requirement | FS Coverage | Status | Notes |
|---|---|---|---|
| PR-INT-001 | FS-INT-001-POC | PARTIAL | Core persistence and dedup; no alerting, no governed storage mandate |
| PR-TRI-001 | FS-TRI-001-POC | PARTIAL | Three-stream classification; no manual promotion, no ambiguity handling |
| PR-TRK-001 | FS-TRK-001-POC | PARTIAL | Ticket creation with ID; no object type, intent, or lifecycle transitions |
| PR-INT-002 | — | DEFERRED TO MVP | Language cascade not in POC scope |
| PR-TRI-002 | — | DEFERRED TO MVP | Manual promotion not in POC scope |
| PR-TRI-003 | — | DEFERRED TO MVP | Object type identification not in POC scope |
| PR-TRI-004 | — | DEFERRED TO MVP | Intent identification not in POC scope |
| PR-TRI-005 | — | DEFERRED TO PILOT | Multi-intent decomposition not in POC scope |
| PR-TRK-003 | — | DEFERRED TO MVP | Immutable activity log not in POC scope |
| PR-TRK-004 | — | DEFERRED TO PILOT | Message register not in POC scope |

---

## 6. Assumptions relied upon

| OQ ID | Default used | Where relied upon |
|---|---|---|
| — | None | POC does not rely on open-question defaults |

---

## 7. Constraints and guardrails exercised

| ID | How exercised in POC |
|---|---|
| CON-GRD-08 | FS-INT-001-POC stores attachments and email content (governed storage not enforced in POC but structure supports migration) |

---

## 8. Transition to MVP

Upon POC success, the following items carry forward to MVP with full specification:

1. Ingestion pipeline is hardened with alerting (3-consecutive-failure rule) and governed storage.
2. Classification gains manual promotion, ambiguity handling, and attachment-based classification.
3. Tickets gain object type, intent, assignee, and status lifecycle.
4. Activity log with immutability guarantees is introduced.
5. Validator-facing UI views are introduced.
6. Language cascade (FS-INT-002) is added.