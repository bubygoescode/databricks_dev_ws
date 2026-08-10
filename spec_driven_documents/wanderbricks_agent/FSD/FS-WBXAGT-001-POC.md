# Functional Specification: Wanderbricks Support Ticket Triage & Resolution Agent — POC

| Field | Value |
|---|---|
| Document ID | FS-WBXAGT-001-POC |
| Version | 1.0 |
| Status | DRAFT |
| Parent | PRD-WBXAGT-001 |
| Owner | AI Projects Analyst |
| Phase | POC |
| Scope | Full feature set (all of PRD-WBXAGT-001 Section 7) — per explicit direction, this POC is not narrowed the way FS-SCO-001-POC was |

---

## 1. Overview

This specification covers the complete POC: silver transform, LLM-based classification, reference validation, ticket lifecycle, a Databricks App, and gold-layer reporting — the full loop described in `PROBLEM_STATEMENT.md` Section 6 ("Expected output"). Unlike FS-SCO-001-POC, nothing here is deferred to a later phase; MVP/Pilot phases for this project don't exist yet and aren't drafted speculatively (PRD-WBXAGT-001 Section 5).

**What POC delivers**: bronze→silver→gold pipeline, intent classification with extraction, five reference-validation checks, a ticket status lifecycle with activity log, and a Databricks App for review and approve/reject.

**What POC does not deliver**: multi-intent decomposition, any write-back to a real system, auto-resolution without human review (PRD-WBXAGT-001 Section 6 non-goals — these are permanent non-goals for this project, not deferred-to-later-phase items).

---

## 2. Functional requirements

### 2.1 Ingestion / silver transform

#### FS-ING-001-POC Flatten message threads
- **Implements**: WBX-ING-001
- **Description**: The silver transform reads bronze `customer_support_logs`, explodes the `messages[]` array into one row per message, and writes to a silver messages table.
- **Acceptance**:
  - AC-1: Given a ticket with N messages, when transform runs, then N rows exist in silver, each with ticket_id, sender, message text, sentiment, and timestamp.
  - AC-2: Message order within a ticket is preserved (derivable by timestamp).
- **Error behaviour**: A malformed/null `messages` array on a bronze row results in zero silver rows for that ticket and a logged warning — not a transform failure that blocks other tickets.

#### FS-ING-002-POC Conform reference data
- **Implements**: WBX-ING-002
- **Description**: Bronze `bookings`, `booking_updates`, `properties`, `hosts`, `users` are read, typed, and written to silver in a form the validation step (Section 2.3) can join against directly.
- **Acceptance**:
  - AC-1: Every bronze row has a corresponding silver row, unless filtered — any filter (e.g. dropping rows with a null primary key) is documented in the TS data model.
  - AC-2: Silver reference tables carry the same primary keys as bronze, joinable without transformation.
- **Error behaviour**: A row failing type conformance (e.g. unparseable date) is excluded from silver with a logged reason, not silently coerced.

### 2.2 Classification

#### FS-CLS-001-POC Classify ticket intent
- **Implements**: WBX-CLS-001
- **Description**: For each ticket with flattened messages available, a Model Serving endpoint is called with the message thread and asked to classify intent into exactly one of the six-value taxonomy (PRD CON-01).
- **Acceptance**:
  - AC-1: Given a ticket's messages, when classification runs, then exactly one of `CANCELLATION | MODIFICATION | REFUND | COMPLAINT | GENERAL_QUESTION | NOT_ACTIONABLE` is recorded.
  - AC-2: A plain-language reasoning summary is recorded alongside the intent.
- **Error behaviour**: See FS-CLS-003-POC.

#### FS-CLS-002-POC Extract request details
- **Implements**: WBX-CLS-002
- **Description**: For tickets classified with an actionable intent (not `GENERAL_QUESTION`/`NOT_ACTIONABLE`), the model additionally extracts the referenced `booking_id` and request specifics (e.g. requested new dates for `MODIFICATION`, stated reason for `REFUND`), constrained to a JSON schema.
- **Acceptance**:
  - AC-1: Given an actionable ticket, when extraction completes, then `booking_id` is populated or explicitly marked absent — never guessed (PRD product principle 3).
  - AC-2: Every extracted field is tagged as model-derived, distinct from validated reference data pulled from silver tables in Section 2.3.
- **Error behaviour**: A response that doesn't conform to the constrained schema is treated as extraction failure (FS-CLS-003-POC), not partially accepted.

#### FS-CLS-003-POC Fail visibly on classification/extraction error
- **Implements**: WBX-CLS-003
- **Description**: Model call failure, timeout, or a non-schema-conforming response sets the ticket to `CLASSIFICATION_FAILED`.
- **Acceptance**: AC-1: Given any of the above failures, when classification is attempted, then `ticket_status = CLASSIFICATION_FAILED`, the error is logged, and no classification row is written for that attempt.
- **Error behaviour**: Ad hoc manual retry, same pattern as FS-TRI-001-POC in SCO Agent — POC does not need an automated retry loop.

### 2.3 Validation

#### FS-VAL-001-POC Booking existence and modifiability check
- **Implements**: WBX-VAL-001
- **Description**: WBXCHK-01 — for any ticket with an extracted `booking_id`, check the silver `bookings` table for existence and a status in the modifiable set (PRD OQ-01 default: `pending`, `confirmed`).
- **Acceptance**: AC-1: Given an extracted `booking_id`, when validation runs, then a result (`PASS`/`FAIL`/`WARN`) is recorded naming the booking's actual status.
- **Error behaviour**: A `booking_id` that doesn't resolve to any silver row is a hard `FAIL`, not a skipped check.

#### FS-VAL-002-POC Property/host standing check
- **Implements**: WBX-VAL-002
- **Description**: WBXCHK-02/03 — resolve the booking's `property_id` and the property's `host_id`; check host `is_active` and `is_verified`. Property status check is existence-only until PRD OQ-02 is resolved.
- **Acceptance**: AC-1: Given a validated booking, when this check runs, then both property and host results are recorded, or property is explicitly marked "existence-only, no status field available."

#### FS-VAL-003-POC Conflicting update detection
- **Implements**: WBX-VAL-003
- **Description**: WBXCHK-04 — check silver `booking_updates` for any prior unresolved update on the same `booking_id`.
- **Acceptance**: AC-1: Given a booking with an existing in-flight update, when a new ticket references it, then a `WARN` is recorded naming the prior update's ID. AC-2: This is a warning, not a hard block — mirrors SCO PR-VAL-005's overridable-warning pattern.

#### FS-VAL-004-POC Requester identity check
- **Implements**: (WBXCHK-05, supports WBX-VAL-001..003's integrity)
- **Description**: Confirm the ticket's `user_id` matches the booking's `user_id`.
- **Acceptance**: AC-1: Given a mismatch, when validation runs, then a hard `FAIL` is recorded — a guest cannot action another guest's booking.

#### FS-VAL-005-POC Show all results immediately
- **Implements**: WBX-VAL-004
- **Description**: All validation results for a ticket (FS-VAL-001..004-POC) are available as a single set the App reads in one call — no per-check navigation.
- **Acceptance**: AC-1: Given a ticket with N results, when the App requests them, then all N are returned together.

### 2.4 Ticket tracking

#### FS-TRK-001-POC Ticket status lifecycle
- **Implements**: WBX-TRK-001
- **Description**: Ticket status moves `NEW` → `CLASSIFYING` → (`CLASSIFICATION_FAILED` | `VALIDATING` → `VALIDATED`) → (`APPROVED` | `REJECTED`).
- **Acceptance**:
  - AC-1: A ticket's status is always exactly one of the above values.
  - AC-2: Forward-only transitions; no direct jump (e.g. `NEW` → `APPROVED`) skipping intermediate states.
- **Error behaviour**: See state machine, Section 3.

#### FS-TRK-002-POC Activity log
- **Implements**: WBX-TRK-002
- **Description**: Every classification attempt, validation run, and reviewer action appends to a per-ticket activity log.
- **Acceptance**: AC-1: The log is append-only — no update or delete path exists for any log entry. AC-2: Each entry is human-readable and ordered by timestamp.

### 2.5 Databricks App

#### FS-APP-001-POC Ticket queue view
- **Implements**: WBX-APP-001
- **Description**: The App's landing view lists tickets with status, classified intent, and a count of non-`PASS` validation flags, filterable by status.
- **Acceptance**: AC-1: Given tickets across multiple statuses, when the queue loads, then each row shows ticket ID, status, intent, and flag count.

#### FS-APP-002-POC Ticket detail view
- **Implements**: WBX-APP-002
- **Description**: Selecting a ticket shows its message thread (FS-ING-001-POC output), extracted fields (FS-CLS-002-POC), all validation results (FS-VAL-005-POC), and the activity log (FS-TRK-002-POC).
- **Acceptance**: AC-1: All four elements render on one screen without further navigation.

#### FS-APP-003-POC Approve/reject action
- **Implements**: WBX-APP-003
- **Description**: The reviewer can approve or reject from the ticket detail view. Approve is blocked pending an override reason if any validation result is a hard `FAIL` (FS-VAL-001-POC, FS-VAL-004-POC); a `WARN`-only ticket (e.g. FS-VAL-003-POC conflict) can be approved without an override, but the warning stays visible in the log.
- **Acceptance**:
  - AC-1: Given no `FAIL` results, when the reviewer clicks Approve, then `ticket_status = APPROVED`, logged with reviewer identity and timestamp.
  - AC-2: Given a `FAIL` result, when the reviewer clicks Approve, then an override reason is required before the action completes; the reason is recorded in the activity log.
  - AC-3: Reject is always available without a reason requirement, and is logged identically to Approve.

### 2.6 Reporting (gold)

#### FS-RPT-001-POC Intent distribution
- **Implements**: WBX-RPT-001
- **Description**: Gold aggregate: ticket count by intent, by day.
- **Acceptance**: AC-1: Given classified tickets, when gold aggregation runs, then counts by intent/day are available and sum to the total classified ticket count for that period.

#### FS-RPT-002-POC Resolution metrics
- **Implements**: WBX-RPT-002
- **Description**: Gold aggregate: time from `NEW` to `APPROVED`/`REJECTED` (using our own status-transition timestamps per PRD OQ-03), approve/reject rate, and override rate (from FS-APP-003-POC AC-2 events).
- **Acceptance**: AC-1: Metrics are computable per day and cumulatively.

#### FS-RPT-003-POC Sentiment trend
- **Implements**: WBX-RPT-003
- **Description**: Gold aggregate: message-level `sentiment` (from FS-ING-001-POC) aggregated by day and by classified intent.
- **Acceptance**: AC-1: Given messages with a sentiment value, when gold aggregation runs, then a trend series is available by day and by intent.

---

## 3. State machine

### 3.1 Ticket lifecycle

```
NEW -> CLASSIFYING -> CLASSIFICATION_FAILED (terminal, ad hoc manual retry)
                    -> VALIDATING -> VALIDATED -> APPROVED (terminal)
                                                -> REJECTED (terminal)
```

| State | Entry condition | Exit condition |
|---|---|---|
| NEW | Silver transform produces messages for a ticket not yet classified | Classification starts |
| CLASSIFYING | Classification (FS-CLS-001/002-POC) begins | Success → VALIDATING. Failure → CLASSIFICATION_FAILED |
| CLASSIFICATION_FAILED | Model error or malformed output | Manual retry (ad hoc), re-enters CLASSIFYING |
| VALIDATING | Classification succeeded | All checks (FS-VAL-001..004-POC) complete → VALIDATED |
| VALIDATED | All validation checks recorded | Reviewer acts in the App → APPROVED or REJECTED |
| APPROVED | Reviewer approves (FS-APP-003-POC AC-1/AC-2) | Terminal |
| REJECTED | Reviewer rejects (FS-APP-003-POC AC-3) | Terminal |

---

## 4. POC success criteria

Mirrors PRD-WBXAGT-001 Section 3 (M-01..M-05):

1. **Pipeline reliability**: ≥95% of scheduled pipeline runs complete bronze→silver→gold without unrecoverable failure.
2. **Classification accuracy**: ≥80% agreement with a human-labelled sample of ≥50 tickets.
3. **Validation correctness**: 100% correct WBXCHK results on a hand-verified sample of ≥20 tickets.
4. **App round-trip**: Approve/reject in the App updates `ticket_status` and is reflected in gold metrics within one pipeline cycle.
5. **Override rate instrumented**: every FS-APP-003-POC AC-2 override is captured and queryable from day one.

---

## 5. Mapping table

| WBX Requirement | FS Coverage | Status |
|---|---|---|
| WBX-ING-001 | FS-ING-001-POC | FULL |
| WBX-ING-002 | FS-ING-002-POC | FULL |
| WBX-CLS-001 | FS-CLS-001-POC | FULL |
| WBX-CLS-002 | FS-CLS-002-POC | FULL |
| WBX-CLS-003 | FS-CLS-003-POC | FULL |
| WBX-VAL-001 | FS-VAL-001-POC | FULL |
| WBX-VAL-002 | FS-VAL-002-POC | FULL |
| WBX-VAL-003 | FS-VAL-003-POC | FULL |
| WBX-VAL-004 | FS-VAL-005-POC | FULL |
| WBX-TRK-001 | FS-TRK-001-POC | FULL |
| WBX-TRK-002 | FS-TRK-002-POC | FULL |
| WBX-APP-001 | FS-APP-001-POC | FULL |
| WBX-APP-002 | FS-APP-002-POC | FULL |
| WBX-APP-003 | FS-APP-003-POC | FULL |
| WBX-RPT-001 | FS-RPT-001-POC | FULL |
| WBX-RPT-002 | FS-RPT-002-POC | FULL |
| WBX-RPT-003 | FS-RPT-003-POC | FULL |

No PRD-WBXAGT-001 requirement is uncovered — every WBX ID maps to exactly one FS item, consistent with this POC delivering the full feature set (PRD Section 5).

---

## 6. Assumptions relied upon

| OQ ID | Default used | Where relied upon |
|---|---|---|
| OQ-01 | `pending`/`confirmed` treated as modifiable statuses | FS-VAL-001-POC |
| OQ-02 | Property check is existence-only (no confirmed status field) | FS-VAL-002-POC |
| OQ-03 | Resolution time computed from our own status-transition timestamps | FS-RPT-002-POC |
| OQ-04 | Confidence stored as numeric 0–1, not gated in UI | FS-CLS-001/002-POC (confidence not surfaced in App per PRD Section 6 non-goal, but should still be persisted by the TS for future use) |

All four are unresolved in the PRD and must be reconfirmed once real column value profiling happens in the TS/implementation stage — flag back if any default turns out wrong.

---

## 7. Constraints and guardrails exercised

| ID | How exercised |
|---|---|
| CON-GRD-01 | FS-APP-003-POC — no status change without explicit reviewer action |
| CON-GRD-02 | FS-CLS-001/002-POC — schema-constrained model output; malformed response is a failure, not a partial accept |
| CON-GRD-03 | All tables live in `sandbox_others` (see TS data model) |
| CON-GRD-04 | No component in this FS calls anything outside `sandbox_others` |
| CON-GRD-05 | FS-TRK-002-POC — append-only activity log |
