# Functional Specification: SCO Inbox Agent — MVP (Minimum Viable Product)

| Field | Value |
|---|---|
| Document ID | FS-SCO-001-MVP |
| Version | 1.0 |
| Status | DRAFT |
| Parent | PRD-SCO-001 |
| Owner | AI Projects Analyst, ASM SCO |
| Phase | MVP |
| Predecessor | FS-SCO-001-POC |
| Scope | PR-INT-001, PR-INT-002, PR-TRI-001, PR-TRI-002, PR-TRI-003, PR-TRI-004, PR-TRK-001, PR-TRK-003 |

---

## 1. Overview

This specification defines the MVP phase of the SCO Inbox Agent. The MVP delivers the first validator-usable release: a triaged queue where validators see only actionable requests, correctly typed by object and intent, with an immutable audit trail.

The MVP builds on the POC’s proven ingestion and classification pipeline, adding: language cascade handling, manual promotion from the irrelevant stream, object type and intent identification, full ticket lifecycle, immutable activity log, and the core validator-facing UI.

**What MVP delivers**: validators can begin using the system for daily triage work. Every actionable request has a typed, intentioned ticket. Non-actionable mail is separated but recoverable. All agent actions are auditable.

**What MVP does not deliver**: multi-intent thread decomposition (Pilot), message register (Pilot), irrelevant stream browse view (Pilot), or message register view (Pilot).

---

## 2. Functional requirements

### 2.1 Ingestion

#### FS-INT-001-MVP Mailbox polling and message persistence (full)

- **Implements**: PR-INT-001, CON-GRD-08
- **Description**: The system polls the shared mailbox `sco_procurementdata@asm.com` on a recurring schedule. Every message is persisted with its full content and metadata in governed storage. Nothing is dropped.
- **Acceptance**:
  - AC-1: Given an email arrives at the shared mailbox, when the next ingestion cycle runs, then a message record exists containing: body (plain and HTML), sender address, sender display name, received timestamp, subject, thread ID, message ID, and a reference to every attachment.
  - AC-2: Given an attachment exists on a message, when ingestion completes, then the attachment is stored in governed storage with its original filename, MIME type, size, and a link to the parent message record.
  - AC-3: Given ingestion fails for a specific message, when the cycle completes, then the failure is recorded with error detail and the message is queued for retry on the next cycle. The cycle does not abort.
  - AC-4: Given a message has been previously ingested (same message ID), when the cycle encounters it again, then it is skipped without creating a duplicate record.
- **Error behaviour**:
  - Mailbox connectivity failure: log error, retry on next cycle, raise alert if three consecutive cycles fail.
  - Attachment download failure: persist the message record, mark attachment as `FAILED_DOWNLOAD`, retry next cycle.
  - Storage write failure: do not acknowledge message as processed; it will be retried.
- **Edge cases**:
  - Messages with no body (attachment-only): ingest normally, body fields are empty.
  - Messages with inline images: treated as attachments.
  - Calendar invites and read receipts: ingested like any other message; classification handles them.

#### FS-INT-002-MVP Language cascade before clarification

- **Implements**: PR-INT-002, CON-12
- **Assumptions used**: OQ-13
- **Description**: The system applies the language cascade defined in CON-12 before raising a language clarification. It does not reject a message on first encounter of non-English content.
- **Acceptance**:
  - AC-1: Given a non-English email body, when triage runs, then the message is flagged for language clarification and a draft requesting English resubmission is prepared (draft not sent — human action required per CON-GRD-01).
  - AC-2: Given an English body containing all fields needed for triage, and a non-English attachment, when triage runs, then no language clarification is raised. The message proceeds to classification.
  - AC-3: Given an English body with insufficient information for triage, and a non-English attachment that would supply the missing information, when triage runs, then a language clarification is flagged.
  - AC-4: The language detection operates on the email body first. Attachment language is assessed only when body content is insufficient for classification.
- **Error behaviour**:
  - Language detection inconclusive (mixed-language body): treat as English and proceed. Log the uncertainty.
  - Language detection service unavailable: treat as English and proceed. Log the failure.
- **Edge cases**:
  - Body is entirely a forwarded chain in another language: assess the most recent message in the chain.
  - Body contains technical terms in another language (e.g., German part descriptions): does not trigger non-English classification if surrounding text is English.

### 2.2 Classification

#### FS-TRI-001-MVP Three-stream classification (full)

- **Implements**: PR-TRI-001, CON-GRD-07
- **Description**: Every ingested message is classified into exactly one of three streams: irrelevant, relevant (create/update), or relevant (Source List hard delete). Classification reasoning is recorded in the activity log.
- **Acceptance**:
  - AC-1: Given a non-actionable email (e.g., "Thank you for...", "Can I check if...", read receipts, out-of-office replies, spam), when triage runs, then it enters the irrelevant stream. No ticket is created.
  - AC-2: Given an actionable request for PIR or Source List creation or update, when triage runs, then it enters the relevant (create/update) stream. A ticket is created.
  - AC-3: Given an actionable request for Source List hard deletion, when triage runs, then it enters the relevant (hard delete) stream. A ticket is created.
  - AC-4: Given any classification decision, when it is recorded, then the activity log entry includes: message ID, chosen stream, reasoning summary, timestamp, and actor (system).
  - AC-5: Given a message that is ambiguous between streams, when triage runs, then it is placed in the relevant (create/update) stream and flagged for validator review. Ambiguity is not hidden.
- **Error behaviour**:
  - Classification model failure: message enters a `CLASSIFICATION_FAILED` state, visible in the validator queue, retryable manually.
  - Timeout during classification: same as model failure.
- **Edge cases**:
  - Reply to an existing thread where the original was already triaged: classify the new message independently; it may add a new intent.
  - Email containing only an attachment with no body text: classify based on attachment content if parseable; flag for review if not.

#### FS-TRI-002-MVP Manual promotion from irrelevant stream

- **Implements**: PR-TRI-002, CON-GRD-07
- **Description**: A validator can promote any message from the irrelevant stream to the relevant stream, creating a ticket. The promotion and the acting user are logged.
- **Acceptance**:
  - AC-1: Given a message in the irrelevant stream, when a validator promotes it, then a ticket is created in the relevant (create/update) stream and the activity log records: message ID, promotion action, acting user, timestamp.
  - AC-2: Given a promoted message, when it enters the relevant stream, then its original classification reasoning remains visible (not overwritten), and a new log entry records the promotion.
- **Error behaviour**:
  - Promotion of an already-promoted message: rejected with a message identifying the existing ticket.
- **MVP limitations**:
  - Promotion is available via the ticket detail or a basic list interface. The full browsable irrelevant stream view with search (sender, subject, date range, body keyword) is deferred to Pilot.

#### FS-TRI-003-MVP Object type identification

- **Implements**: PR-TRI-003
- **Description**: Every relevant request is typed as `PIR`, `SOURCE_LIST`, or `BOTH`. The type is displayed on the ticket.
- **Acceptance**:
  - AC-1: Given a relevant request, when triage completes, then the ticket carries exactly one object type value from the set {`PIR`, `SOURCE_LIST`, `BOTH`}.
  - AC-2: Given a request that mentions only purchasing info records or pricing, when triage runs, then object type is `PIR`.
  - AC-3: Given a request that mentions only source lists or approved suppliers at a plant, when triage runs, then object type is `SOURCE_LIST`.
  - AC-4: Given a request that mentions both, when triage runs, then object type is `BOTH`.
  - AC-5: Given a request where object type cannot be determined, when triage runs, then the ticket is flagged for validator review with object type set to `BOTH` as a conservative default.
- **Error behaviour**:
  - Object type not determinable even after body and attachment analysis: set `BOTH`, flag for review, log reasoning.

#### FS-TRI-004-MVP Intent identification

- **Implements**: PR-TRI-004
- **Description**: Every relevant request carries an intent: `CREATE`, `UPDATE`, or `HARD_DELETE`. Hard delete applies to Source List only. A `HARD_DELETE` intent on `PIR` object type is flagged for validator attention.
- **Acceptance**:
  - AC-1: Given a relevant request, when triage completes, then the ticket carries exactly one intent from the set {`CREATE`, `UPDATE`, `HARD_DELETE`}.
  - AC-2: Given intent `HARD_DELETE` on object type `PIR`, when triage completes, then the ticket is flagged for validator attention with a specific warning: "Hard delete intent detected on PIR — requires manual review."
  - AC-3: Given intent `HARD_DELETE` on object type `SOURCE_LIST`, when triage completes, then the ticket enters the relevant (hard delete) stream normally.
  - AC-4: Given a request where intent cannot be determined, when triage runs, then the ticket is flagged for validator review with reasoning explaining the ambiguity.
- **Error behaviour**:
  - Conflicting signals (e.g., subject says "create" but body says "update"): flag for review, log both signals.

### 2.3 Ticket lifecycle

#### FS-TRK-001-MVP Ticket creation and identity (full)

- **Implements**: PR-TRK-001, CON-GRD-07
- **Description**: Every relevant request has exactly one ticket with a stable, system-generated identifier and a defined status lifecycle.
- **Acceptance**:
  - AC-1: Given any relevant request, when triage completes, then exactly one ticket exists for it with a unique, immutable ticket ID.
  - AC-2: The ticket ID is a human-readable sequential identifier (format: `SCO-NNNNNN`).
  - AC-3: Given a ticket is created, then its initial status is `NEW`.
  - AC-4: The ticket record contains: ticket ID, status, object type, intent, source message reference, thread ID, created timestamp, and current assignee (initially null).
- **Error behaviour**:
  - ID generation collision: retry with next sequential value. Log the collision.
- **Edge cases**:
  - Ticket creation fails after classification succeeds: the message remains in the relevant stream in a `TICKET_PENDING` state, visible to validators.

#### FS-TRK-003-MVP Activity log

- **Implements**: PR-TRK-003, CON-GRD-07
- **Description**: Each ticket carries a readable, time-ordered, append-only log of all agent and human actions. The log is immutable — no entry can be edited or deleted by any role.
- **Acceptance**:
  - AC-1: Given any ticket, when the activity log is opened, then the validator sees every action taken on the ticket in chronological order, in plain language.
  - AC-2: Each log entry contains: timestamp, actor (system or user identity), action type, action detail in plain language, and any referenced entity IDs.
  - AC-3: Given any attempt to edit or delete a log entry (via UI or API), then the attempt is refused and logged as a security event.
  - AC-4: The activity log records at minimum: creation, classification, promotion, status change, assignment, and any system error or retry.
- **Error behaviour**:
  - Log write failure: the triggering action is rolled back. An action without its log entry is a defect.
- **Edge cases**:
  - High-frequency actions (e.g., rapid retries): each is logged individually; no deduplication or batching.

---

## 3. State machines

### 3.1 Message lifecycle (MVP)

```
RECEIVED -> CLASSIFYING -> CLASSIFIED -> [IRRELEVANT | TICKET_CREATED | CLASSIFICATION_FAILED]
                                              |
                                         PROMOTED -> TICKET_CREATED
```

| State | Entry condition | Exit condition |
|---|---|---|
| RECEIVED | Message persisted by ingestion | Classification starts |
| CLASSIFYING | Classification process begins | Classification completes or fails |
| CLASSIFIED | Classification result available | Ticket created or message filed as irrelevant |
| IRRELEVANT | Classification output: not actionable | Validator promotes (→ PROMOTED) or remains |
| PROMOTED | Validator promotes from irrelevant | Ticket created |
| TICKET_CREATED | Ticket successfully created | Terminal for message lifecycle |
| CLASSIFICATION_FAILED | Classification error | Manual retry or promotion |

### 3.2 Ticket lifecycle (MVP)

```
NEW -> [OPEN | CANCELLED]
```

| State | Entry condition | Exit condition |
|---|---|---|
| NEW | Ticket created by triage or promotion | Validator opens, or ticket cancelled |
| OPEN | Validator begins work | Pilot+ extends with further states |
| CANCELLED | Validator determines ticket invalid | Terminal |

> **Note**: MVP defines the initial operable states. Pilot hardens these with full edge-case coverage. R2+ extends with EXTRACTING, VALIDATING, etc.

---

## 4. Screen and interaction definitions

### 4.1 Validator queue view

- **Primary view**: list of tickets in states `NEW` and `OPEN`, sorted by received timestamp (oldest first).
- **Columns**: Ticket ID, Status, Object Type, Intent, Sender, Subject (truncated), Received Date, Assignee.
- **Filters**: Status, Object Type, Intent, Date range.
- **Actions**: Open ticket, Assign to self.

### 4.2 Ticket detail view (MVP)

- **Header**: Ticket ID, Status, Object Type, Intent, Assignee.
- **Body**: Original email content (body, rendered HTML or plain text), attachment list with download links.
- **Activity log panel**: chronological list of all actions, expandable.
- **Actions available in MVP**: Assign, Cancel, Promote (for messages accessible from failed/irrelevant states).
- **Thread link**: if multiple tickets exist for the same thread, a link to sibling tickets.

### 4.3 Irrelevant stream access (MVP — basic)

- **Purpose**: basic list of messages classified as irrelevant, accessible from the validator interface.
- **Columns**: Message ID, Sender, Subject, Received Date.
- **Actions**: Promote to relevant stream (creates ticket).
- **MVP limitation**: Full search capability (sender, date range, keyword in subject and body) deferred to Pilot.

---

## 5. Mapping table

| PR Requirement | FS Coverage | Status | Notes |
|---|---|---|---|
| PR-INT-001 | FS-INT-001-MVP | COVERED | Full specification |
| PR-INT-002 | FS-INT-002-MVP | COVERED | Full specification |
| PR-TRI-001 | FS-TRI-001-MVP | COVERED | Full specification |
| PR-TRI-002 | FS-TRI-002-MVP | COVERED | Promotion available; full browse view deferred to Pilot |
| PR-TRI-003 | FS-TRI-003-MVP | COVERED | Full specification |
| PR-TRI-004 | FS-TRI-004-MVP | COVERED | Full specification |
| PR-TRI-005 | — | DEFERRED TO PILOT | Multi-intent decomposition not in MVP scope |
| PR-TRK-001 | FS-TRK-001-MVP | COVERED | Full specification |
| PR-TRK-003 | FS-TRK-003-MVP | COVERED | Full specification |
| PR-TRK-004 | — | DEFERRED TO PILOT | Message register not in MVP scope |

---

## 6. Assumptions relied upon

| OQ ID | Default used | Where relied upon |
|---|---|---|
| OQ-13 | ASM domain list is `asm.com` only (held as configuration) | FS-INT-002-MVP (language clarification targets ASM addresses only) |

---

## 7. Constraints and guardrails exercised

| ID | How exercised in MVP |
|---|---|
| CON-12 | FS-INT-002-MVP implements the full language cascade |
| CON-GRD-01 | FS-INT-002-MVP prepares draft but does not send (human action required) |
| CON-GRD-07 | FS-TRK-003-MVP enforces append-only immutable activity log; FS-TRI-001-MVP AC-4 logs every classification; FS-TRK-001-MVP logs creation |
| CON-GRD-08 | FS-INT-001-MVP stores attachments and email content in governed storage |

---

## 8. Transition to Pilot

Upon MVP delivery, the following items carry forward to Pilot with full specification:

1. Multi-intent thread decomposition (FS-TRI-005) — the most complex classification capability.
2. Message register (FS-TRK-004) — compliance-grade accounting of all received messages.
3. Full irrelevant stream browse view with search by sender, subject, date range, and body keyword.
4. Message register view with filtering.
5. All edge cases from MVP items hardened under production load.
6. Performance and reliability targets for production SLA.

---

## 9. Warnings: defaults relied upon

Per CLAUDE.md rule 6, the following open-question defaults were relied upon in this specification:

1. **OQ-13** (ASM domain list): Built against "`asm.com` only, held as configuration." If additional domains are added, no FS change required (configuration change only).