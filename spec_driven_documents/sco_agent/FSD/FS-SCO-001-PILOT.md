# Functional Specification: SCO Inbox Agent — Pilot (Production Pilot)

| Field | Value |
|---|---|
| Document ID | FS-SCO-001-PILOT |
| Version | 1.0 |
| Status | DRAFT |
| Parent | PRD-SCO-001 |
| Owner | AI Projects Analyst, ASM SCO |
| Phase | Pilot |
| Predecessor | FS-SCO-001-MVP |
| Scope | PR-TRI-002 (completion), PR-TRI-005, PR-TRK-004 |

---

## 1. Overview

This specification defines the Pilot phase of the SCO Inbox Agent. The Pilot completes the full R1 scope and prepares the system for production operation with real validator teams.

The Pilot adds the remaining R1 capabilities not delivered in MVP: multi-intent thread decomposition, the full message register, and the complete irrelevant stream browse experience. It also hardens all MVP capabilities to production-grade reliability.

**What Pilot delivers**: the complete R1 feature set — a triaged queue where validators see only actionable requests, correctly typed, with a ticket each, multi-intent threads correctly decomposed, and a complete auditable register of all mailbox traffic.

**What Pilot does not deliver**: field value extraction (R2), SAP validation (R3), requestor communication (R4), or production writeback (R5).

---

## 2. Functional requirements

### 2.1 Classification (completion)

#### FS-TRI-002-PILOT Irrelevant stream browse view (full)

- **Implements**: PR-TRI-002 (completion of MVP partial coverage)
- **Description**: The irrelevant stream is fully browsable with search by sender, subject, date range, and body keyword. This completes the browse capability that MVP delivered in basic form.
- **Acceptance**:
  - AC-1: Given a message in the irrelevant stream, when a validator promotes it, then a ticket is created in the relevant (create/update) stream and the activity log records: message ID, promotion action, acting user, timestamp.
  - AC-2: The irrelevant stream is browsable with search by sender, subject, date range, and body keyword.
  - AC-3: Given a promoted message, when it enters the relevant stream, then its original classification reasoning remains visible (not overwritten), and a new log entry records the promotion.
- **Error behaviour**:
  - Promotion of an already-promoted message: rejected with a message identifying the existing ticket.
- **Edge cases**:
  - Promoting a message from a thread where another message already has a ticket: allowed. The new ticket is linked to the same thread.
  - Search returning large result sets: paginated, with a maximum of 100 results per page.

#### FS-TRI-005-PILOT Multi-intent thread decomposition

- **Implements**: PR-TRI-005
- **Assumptions used**: OQ-03
- **Description**: A single email thread may contain multiple distinct intents. Each intent produces an independent ticket, linked to the originating thread. Each ticket is validated and approved independently.
- **Acceptance**:
  - AC-1: Given a thread with N distinct intents (e.g., "Create PIR for X, Create Source List for Y, Delete old PIR for Z"), when triage completes, then N tickets exist, each with its own object type and intent.
  - AC-2: All tickets from the same thread share a thread link, visible on each ticket.
  - AC-3: Each ticket is independently assignable, lockable, and approvable. Progress on one does not affect another.
  - AC-4: Given a thread where intents are ambiguous or overlapping, when triage runs, then the system creates tickets for the intents it can identify and flags the ambiguity for validator review.
- **Error behaviour**:
  - Cannot determine intent boundaries: create a single ticket for the thread, flag it as requiring manual decomposition.
- **Edge cases**:
  - A follow-up email in a thread that adds a new intent to an already-triaged thread: new intent produces a new ticket linked to the same thread.
  - Duplicate intents within a single email (same vendor, material, intent stated twice): produce one ticket, not two.
  - Thread with 10+ intents: all are decomposed individually. No artificial cap on ticket count per thread.
  - Intent expressed across multiple messages in a thread (part in first email, part in reply): each message is classified independently per FS-TRI-001-MVP; cross-message intent synthesis is not performed.

### 2.2 Ticket lifecycle (completion)

#### FS-TRK-004-PILOT Message register

- **Implements**: PR-TRK-004, CON-GRD-07
- **Description**: Every message received at the mailbox is registered with its classification outcome, regardless of whether it was deemed relevant. The register is queryable by time period.
- **Acceptance**:
  - AC-1: Given any message received in a period, when the register is queried for that period, then the message appears with: message ID, received timestamp, sender, subject, classification (irrelevant / relevant-create-update / relevant-hard-delete / classification-failed), and outcome (ticket ID if relevant, or "no action" if irrelevant).
  - AC-2: The register supports filtering by: date range, classification, sender, and keyword in subject.
  - AC-3: Given a message that was promoted from irrelevant to relevant, when the register is queried, then it shows the current (promoted) classification with a note indicating original classification.
- **Error behaviour**:
  - Register write failure: does not block ingestion. The message is marked as `REGISTER_PENDING` and retried.
- **Edge cases**:
  - Backfill: messages ingested during POC and MVP phases that predate the register are backfilled from existing message records on Pilot deployment.
  - Register query spanning a period with no messages: returns an empty result set, not an error.

---

## 3. Production hardening

The Pilot phase hardens all MVP capabilities to production-grade standards. The following requirements apply across the system:

### 3.1 Reliability

- **SLA**: The ingestion pipeline must achieve ≥99.5% cycle completion rate over any rolling 7-day window.
- **Recovery**: Any single-message failure must not affect processing of other messages in the same cycle.
- **Alerting**: Alert on 3 consecutive cycle failures (per FS-INT-001-MVP). Alert on classification accuracy dropping below 80% over a rolling 24-hour window (measured against validator corrections).

### 3.2 Performance

- **Ingestion latency**: Messages are persisted within 5 minutes of arrival at the mailbox under normal load.
- **Classification latency**: Classification completes within 30 seconds of message ingestion for ≥95% of messages.
- **UI responsiveness**: Validator queue and ticket detail views render within 2 seconds at P95.

### 3.3 Data integrity

- **Activity log**: Immutability is enforced at the storage layer, not just the application layer. Direct database access cannot bypass the append-only constraint.
- **Message register**: Complete — no message may exist in the system without a corresponding register entry. A background reconciliation job runs daily to detect and repair gaps.
- **Governed storage**: All attachments and email content are stored in Unity Catalog–governed volumes with appropriate access controls.

### 3.4 Observability

- **Metrics exported**: ingestion cycle count, messages per cycle, classification distribution (irrelevant/relevant/failed), tickets created per day, promotion rate, average classification latency.
- **Dashboard**: An admin-facing dashboard surfaces the above metrics with 24-hour, 7-day, and 30-day views.
- **Audit trail**: Every system action is traceable from the activity log through to infrastructure logs.

---

## 4. Screen and interaction definitions

### 4.1 Validator queue view

*(Carried forward from MVP, unchanged)*

- **Primary view**: list of tickets in states `NEW` and `OPEN`, sorted by received timestamp (oldest first).
- **Columns**: Ticket ID, Status, Object Type, Intent, Sender, Subject (truncated), Received Date, Assignee.
- **Filters**: Status, Object Type, Intent, Date range.
- **Actions**: Open ticket, Assign to self.

### 4.2 Irrelevant stream view (full — Pilot)

- **Purpose**: browsable archive of messages classified as irrelevant.
- **Columns**: Message ID, Sender, Subject, Received Date, Classification Reason (truncated).
- **Filters**: Sender, Date range, Keyword search (subject and body).
- **Actions**: Promote to relevant stream (creates ticket).
- **Search**: full-text search across subject and body content. Results ranked by relevance with date as tiebreaker.

### 4.3 Ticket detail view (Pilot)

*(Carried forward from MVP with additions)*

- **Header**: Ticket ID, Status, Object Type, Intent, Assignee.
- **Body**: Original email content (body, rendered HTML or plain text), attachment list with download links.
- **Activity log panel**: chronological list of all actions, expandable.
- **Actions available**: Assign, Cancel.
- **Thread link**: if multiple tickets exist for the same thread (including from multi-intent decomposition), a link to all sibling tickets with their status.
- **Decomposition indicator**: if the ticket was produced by multi-intent decomposition, a badge indicating "1 of N from thread" with navigation to siblings.

### 4.4 Message register view (Pilot)

- **Purpose**: complete register of all received messages.
- **Columns**: Message ID, Received Date, Sender, Subject, Classification, Outcome (ticket link or "no action").
- **Filters**: Date range, Classification, Sender, Subject keyword.
- **Export**: register data exportable as CSV for compliance reporting.

---

## 5. State machines

### 5.1 Message lifecycle (Pilot — final R1)

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

### 5.2 Ticket lifecycle (Pilot — final R1)

```
NEW -> [OPEN | CANCELLED]
```

| State | Entry condition | Exit condition |
|---|---|---|
| NEW | Ticket created by triage or promotion | Validator opens, or ticket cancelled |
| OPEN | Validator begins work (R3 adds locking) | R2+ extends with EXTRACTING, VALIDATING, etc. |
| CANCELLED | Validator determines ticket invalid | Terminal |

> **Note**: Pilot defines the complete R1 states. R2 adds extraction states, R3 adds validation and lock states, R4 adds approval and writeback states. The state machine is extended per release, never replaced.

---

## 6. Mapping table

| PR Requirement | FS Coverage | Status |
|---|---|---|
| PR-INT-001 | FS-INT-001-MVP | COVERED (delivered in MVP, hardened in Pilot) |
| PR-INT-002 | FS-INT-002-MVP | COVERED (delivered in MVP, hardened in Pilot) |
| PR-TRI-001 | FS-TRI-001-MVP | COVERED (delivered in MVP, hardened in Pilot) |
| PR-TRI-002 | FS-TRI-002-MVP + FS-TRI-002-PILOT | COVERED (promotion in MVP, full browse in Pilot) |
| PR-TRI-003 | FS-TRI-003-MVP | COVERED (delivered in MVP) |
| PR-TRI-004 | FS-TRI-004-MVP | COVERED (delivered in MVP) |
| PR-TRI-005 | FS-TRI-005-PILOT | COVERED |
| PR-TRK-001 | FS-TRK-001-MVP | COVERED (delivered in MVP) |
| PR-TRK-003 | FS-TRK-003-MVP | COVERED (delivered in MVP, hardened in Pilot) |
| PR-TRK-004 | FS-TRK-004-PILOT | COVERED |

All R1 requirements are covered across the MVP and Pilot phases. No requirement is NOT COVERED.

---

## 7. Assumptions relied upon

| OQ ID | Default used | Where relied upon |
|---|---|---|
| OQ-03 | One thread yields N independent tickets linked by thread ID | FS-TRI-005-PILOT |
| OQ-13 | ASM domain list is `asm.com` only (held as configuration) | FS-INT-002-MVP (language clarification targets ASM addresses only) |

---

## 8. Constraints and guardrails exercised

| ID | How exercised in Pilot |
|---|---|
| CON-12 | FS-INT-002-MVP implements the full language cascade (delivered in MVP) |
| CON-GRD-07 | FS-TRK-003-MVP enforces append-only immutable activity log (hardened in Pilot with storage-layer enforcement); FS-TRK-004-PILOT provides complete message accounting |
| CON-GRD-08 | FS-INT-001-MVP stores attachments and email content in governed storage (Pilot enforces Unity Catalog governance) |

---

## 9. Pilot exit criteria

The Pilot is considered successful and ready for steady-state production when:

1. **Feature completeness**: All R1 requirements are implemented and passing acceptance tests.
2. **Classification accuracy**: ≥90% agreement with validator judgement over a rolling 2-week period (measured by promotion rate and validator corrections).
3. **Ingestion completeness**: Zero silent message drops over the pilot period. Register reconciliation reports zero gaps.
4. **Multi-intent accuracy**: ≥80% of multi-intent threads correctly decomposed (measured against validator manual decomposition).
5. **Reliability**: ≥99.5% ingestion cycle completion rate over any rolling 7-day window.
6. **Validator adoption**: ≥2 validators using the system as their primary triage tool for ≥1 week.
7. **No critical defects**: Zero P1 defects open at pilot exit.

---

## 10. Warnings: defaults relied upon

Per CLAUDE.md rule 6, the following open-question defaults were relied upon in this specification:

1. **OQ-03** (multi-intent decomposition): Built against "one message yields N requests, independent tickets, linked by thread ID." If this default changes, FS-TRI-005-PILOT must be revised.
2. **OQ-13** (ASM domain list): Built against "`asm.com` only, held as configuration." If additional domains are added, no FS change required (configuration change only).