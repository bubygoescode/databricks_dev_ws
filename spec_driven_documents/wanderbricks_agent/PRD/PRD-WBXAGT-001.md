# Product Requirements Document: Wanderbricks Support Ticket Triage & Resolution Agent

| Field | Value |
|---|---|
| Document ID | PRD-WBXAGT-001 |
| Version | 0.1 (DRAFT) |
| Status | DRAFT — feasibility spike, not a real product initiative. See `PROBLEM_STATEMENT.md` |
| Parent | `PROBLEM_STATEMENT.md` |
| Owner | AI Projects Analyst (same role as SCO Agent, exercising the same process) |
| Target platform | Databricks (Apps, Model Serving / Agent Bricks, Unity Catalog) |
| Data source | `samples.wanderbricks` (Databricks sample dataset), copied to `sandbox_others.bronze_datasample_wanderbricks` |
| Downstream artefacts | FS-WBXAGT-001-POC (Functional Spec), TS-WBXAGT-001-POC (Technical Spec) |

> **This document exists to test the spec-driven process, not to ship a real product.** There is no real Wanderbricks business. Rigor is intentionally proportional: enough structure to drive a coherent FSD/TSD and stay traceable, without the production-grade weight of PRD-SCO-001 (no legal/compliance constraints, no multi-year release plan, no real users to interview). Where this document is thinner than PRD-SCO-001, that is deliberate, not an oversight.

---

## 0. Instructions for downstream agents

Same rules as PRD-SCO-001, restated for this project:

1. This document defines the problem and what the product does about it. Implementation choices belong in the TS.
2. Every requirement has a stable ID `WBX-<AREA>-<NNN>`. Never renumber, merge, or delete an ID.
3. Every FS item cites at least one WBX requirement ID. Every TS item cites at least one FS ID.
4. **Section 8 (Constraints) is not negotiable.** CON-GRD entries are guardrails, enforced in code and covered by a negative test.
5. Section 6 (Non-goals) is intentional scope restriction, not an oversight — do not helpfully add capability from there.
6. Per the user's direction: **this POC delivers the full feature set** described in Section 5 (silver, gold, pipeline, agent, App) — unlike PRD-SCO-001's POC, which deliberately narrowed scope. Do not further narrow POC scope without asking.
7. Do not resolve genuine ambiguity silently — Section 10 (Open Questions) exists for exactly that. Build against the stated default and flag reliance on it.

---

## 1. The problem

See `PROBLEM_STATEMENT.md` Sections 1–2 for full context. Summary: Wanderbricks' (fictional) support team works a shared ticket queue where each ticket is a free-text conversation thread. Today, an agent must read the thread, work out intent, identify the relevant booking, and manually cross-check booking/property/host data before knowing whether a request is valid — the same shape of problem SCO Agent solves for procurement email, replicated here on safe sample data.

**What we are building**: an agentic pipeline that classifies ticket intent, extracts request details, validates them against reference data, and presents the result in a review App. A human decides; the agent prepares.

**What we are explicitly not building**: see Section 6.

## 2. Users

Fictional, for framing purposes only (there is no real Wanderbricks team to interview):

### Reviewer (primary)
A support agent equivalent to SCO's Validator. Works the ticket queue in the App, sees detected intent + extracted fields + validation results, and approves or rejects.

**Jobs to be done**: "Tell me what this ticket is actually asking for." "Tell me if it's even valid before I act on it." "Let me override the agent's call when I disagree, with a reason."

### Analyst (secondary)
Reviews gold-layer output (intent distribution, resolution metrics, sentiment trends) to judge whether the agent is working.

## 3. Success metrics

Since there's no real baseline or business to measure, these metrics are about whether the *technical approach* works, not business ROI:

| ID | Metric | Target | How measured |
|---|---|---|---|
| M-01 | Pipeline reliability | ≥95% of scheduled runs complete bronze→silver→gold without unrecoverable failure | Job run history |
| M-02 | Classification accuracy | ≥80% agreement with a human-labelled sample of ≥50 tickets | Scored sample |
| M-03 | Validation correctness | 100% of WBXCHK checks (Section 9) return the correct result on a hand-verified sample of ≥20 tickets | Scored sample |
| M-04 | App round-trip works | Approve/reject in the App correctly updates `ticket_status` and is reflected in gold metrics within one pipeline cycle | Manual verification |
| M-05 | Reviewer override rate | Instrumented from day one (not a target — a signal). Rising override rate on a field means extraction/classification is degrading | Override log |

M-05 mirrors PRD-SCO-001's M-05 deliberately — proving that pattern transfers is part of what this spike is testing.

## 4. Product principles

Carried over from PRD-SCO-001 because they're general to this class of product, not SCO-specific:

1. **The reviewer decides, the agent prepares.** No `ticket_status` change without an explicit human action.
2. **Surface problems, don't hide them.** All validation results are visible the moment a ticket opens.
3. **Never invent a value.** Missing/unextractable means missing, not a guess.
4. **Show your working.** Every classification records its reasoning; every validation result names what it checked.
5. **Fail visibly.** A classification or validation failure is a visible state (`CLASSIFICATION_FAILED`), never a silent default.

## 5. Scope

Single phase for now: **POC**, and per explicit direction it carries the **full feature set** — no MVP/Pilot narrowing games this time. Covers:

- Silver transform (message explosion, reference conforming)
- LLM-based intent classification + extraction
- Reference validation (WBXCHK-01..05, Section 9)
- Ticket status lifecycle + activity log
- A Databricks App (queue view, approve/reject)
- Gold-layer aggregates (intent distribution, resolution metrics, sentiment trends)

MVP/Pilot phases are not defined yet — out of scope until POC proves the approach out. Do not draft them speculatively.

## 6. Non-goals

| Non-goal | Reason |
|---|---|
| Multi-intent decomposition (one thread → several tickets) | SCO Agent itself defers this past its own POC (PR-TRI-005 is Pilot-scope). Matching that phase boundary here keeps the two projects comparable |
| Any write-back to a real system | There is no real Wanderbricks backend. "Resolution" means updating our own `ticket_status`, nothing external |
| Auto-resolution without human review | Product principle 1 |
| Intent categories the sample data can't exercise | Don't invent taxonomy the `customer_support_logs` content doesn't actually support — validate the taxonomy against real message content during classification design, not guessed upfront |
| Admin-only confidence gating (PR-EXT-002's pattern in SCO) | Single reviewer role in this POC; no admin/validator split to gate against. Confidence is still recorded (Section 7, WBX-CLS requirements), just not access-controlled |

## 7. Requirements

Format: **User need** (framed in the fictional Reviewer/Analyst voice) → **Requirement** → **Acceptance**.

### Ingestion / silver transform

#### WBX-ING-001 Flatten message threads
- **User need**: "I need to read individual messages, not a nested blob, to work a ticket."
- **Requirement**: Bronze `customer_support_logs.messages[]` is exploded into one row per message, preserving ticket_id, sender, message text, sentiment, and timestamp.
- **Priority**: MUST
- **Acceptance**: AC-1: Given a ticket with N messages, when silver transform runs, then N rows exist in the silver messages table, each linked to the ticket.

#### WBX-ING-002 Conform reference data
- **User need**: "I need booking/property/host data queryable in a consistent shape to validate against."
- **Requirement**: Bronze `bookings`, `booking_updates`, `properties`, `hosts`, `users` are conformed (typed, deduplicated, nulls handled) into silver views/tables usable by the validation step.
- **Priority**: MUST
- **Acceptance**: AC-1: Every bronze row has a corresponding silver row unless explicitly filtered (and if filtered, the filter reason is documented in the TS).

### Classification

#### WBX-CLS-001 Classify ticket intent
- **Requirement**: Each ticket is classified into exactly one of: `CANCELLATION`, `MODIFICATION`, `REFUND`, `COMPLAINT`, `GENERAL_QUESTION`, `NOT_ACTIONABLE`.
- **Priority**: MUST
- **Acceptance**: AC-1: Given a ticket's flattened messages, when classification runs, then exactly one intent is recorded with a reasoning summary.

#### WBX-CLS-002 Extract request details
- **Requirement**: For intents other than `GENERAL_QUESTION`/`NOT_ACTIONABLE`, the referenced `booking_id` and the specifics of the request (e.g. new dates, refund reason) are extracted, when present in the text.
- **Priority**: MUST
- **Acceptance**: AC-1: Given a ticket referencing a booking, when classification completes, then `booking_id` is extracted or explicitly marked absent — never guessed. AC-2: Every extracted field records that it came from the model, distinct from validated/reference data.

#### WBX-CLS-003 Fail visibly on classification error
- **Requirement**: Model failure or a non-schema-conforming response results in a `CLASSIFICATION_FAILED` state, not a guessed default.
- **Priority**: MUST
- **Acceptance**: AC-1: Given a model error or malformed output, when classification is attempted, then the ticket is marked `CLASSIFICATION_FAILED` and logged.

### Validation

#### WBX-VAL-001 Check the booking exists and is modifiable
- **Requirement**: For any intent referencing a booking, the extracted `booking_id` is checked against silver `bookings` for existence and a modifiable status (see WBXCHK-01, Section 9; the exact set of "modifiable" statuses is OQ-01).
- **Priority**: MUST
- **Acceptance**: AC-1: Given an extracted `booking_id`, when validation runs, then a pass/fail/warn result is recorded naming what was checked.

#### WBX-VAL-002 Check property/host allow the request
- **Requirement**: The property and host tied to the booking are checked for active/verified status (WBXCHK-02, WBXCHK-03).
- **Priority**: MUST
- **Acceptance**: AC-1: A result is recorded for both checks, or explicitly marked not-applicable if the relevant status fields don't exist (OQ-02).

#### WBX-VAL-003 Detect conflicting in-flight updates
- **Requirement**: If `booking_updates` already has a pending/unresolved update for the same booking, this is flagged (WBXCHK-04) — mirrors SCO's duplicate-detection pattern (PR-VAL-005).
- **Priority**: MUST
- **Acceptance**: AC-1: Given a booking with an existing in-flight update, when a new ticket references the same booking, then a conflict warning is raised naming the prior update.

#### WBX-VAL-004 Show every result immediately
- **Requirement**: Opening a ticket in the App shows all validation results without further navigation (mirrors SCO PR-VAL-006).
- **Priority**: MUST
- **Acceptance**: AC-1: Given a ticket with N validation results, when opened in the App, then all N are visible immediately.

### Ticket tracking

#### WBX-TRK-001 Ticket status lifecycle
- **Requirement**: Each ticket has a status: `NEW` → `CLASSIFYING` → `VALIDATED` → (`APPROVED` | `REJECTED`), or `CLASSIFICATION_FAILED`.
- **Priority**: MUST
- **Acceptance**: AC-1: Given any ticket, its status is always exactly one of the above. AC-2: Transitions only move forward (no backward transition without an explicit reset action).

#### WBX-TRK-002 Activity log per ticket
- **Requirement**: Each ticket carries an append-only log of classification, validation, and reviewer decisions.
- **Priority**: MUST
- **Acceptance**: AC-1: Given any ticket, the log shows what happened, in order, in plain language.

### Databricks App

#### WBX-APP-001 Ticket queue view
- **Requirement**: The App lists tickets with their current status, detected intent, and a flag count from validation.
- **Priority**: MUST
- **Acceptance**: AC-1: Given tickets in any status, when the queue loads, then each is listed with status, intent, and flag count.

#### WBX-APP-002 Ticket detail view
- **Requirement**: Opening a ticket shows the message thread, extracted fields, all validation results (WBX-VAL-004), and the activity log.
- **Priority**: MUST
- **Acceptance**: AC-1: All of the above render on a single ticket detail screen.

#### WBX-APP-003 Approve/reject action
- **Requirement**: The reviewer can approve or reject a ticket. Approving when a hard-fail validation exists requires an explicit override reason (mirrors SCO PR-VAL-007's override pattern); rejecting never requires one.
- **Priority**: MUST
- **Acceptance**: AC-1: Given all validations pass, when the reviewer approves, then `ticket_status` becomes `APPROVED`, logged with reviewer identity and timestamp. AC-2: Given a hard-fail validation, when the reviewer attempts to approve, then an override reason is required and recorded. AC-3: No approve/reject action bypasses the activity log.

### Reporting (gold)

#### WBX-RPT-001 Intent distribution
- **Requirement**: Gold layer aggregates ticket counts by intent over time.
- **Priority**: SHOULD

#### WBX-RPT-002 Resolution metrics
- **Requirement**: Gold layer computes resolution time (ticket creation to approve/reject) and override rate.
- **Priority**: SHOULD

#### WBX-RPT-003 Sentiment trend
- **Requirement**: Gold layer aggregates message-level sentiment by day and by intent.
- **Priority**: SHOULD

---

## 8. Constraints

### 8.1 Business rules

| ID | Rule | Note |
|---|---|---|
| CON-01 | Fixed intent taxonomy: `CANCELLATION`, `MODIFICATION`, `REFUND`, `COMPLAINT`, `GENERAL_QUESTION`, `NOT_ACTIONABLE` | Revisit only if sample data shows a category this doesn't cover |
| CON-02 | A booking is "modifiable" only while its status is in the allowed set | Exact status values are OQ-01 — must be confirmed against real data before implementation |

### 8.2 Guardrails

| ID | Guardrail |
|---|---|
| CON-GRD-01 | No `ticket_status` change without an explicit reviewer action in the App |
| CON-GRD-02 | Model output constrained to schema — no invented intents, no populating an absent field |
| CON-GRD-03 | All Unity Catalog reads/writes confined to `sandbox_others` (this project's own data guardrail — see `guardrails/CATALOG_POLICY.md`). `samples` is read-only source access, revoked once no longer needed |
| CON-GRD-04 | No write-back to any system outside `sandbox_others` — there is no real backend to write to |
| CON-GRD-05 | The per-ticket activity log is append-only |

---

## 9. Reference validation checks (WBXCHK)

Mirrors PRD-SCO-001 Section 10 (SAPCHK). These are the reference-data checks the validation step (WBX-VAL-001..003) runs.

| ID | Source | Inputs | Check |
|---|---|---|---|
| WBXCHK-01 | `bookings` | Extracted `booking_id` | Booking exists and its status is in the modifiable set (OQ-01) |
| WBXCHK-02 | `properties` | Booking's `property_id` | Property exists (no confirmed "active" flag yet — OQ-02) |
| WBXCHK-03 | `hosts` | Property's `host_id` | Host `is_active` and `is_verified` are both true |
| WBXCHK-04 | `booking_updates` | `booking_id` | No unresolved prior update already recorded for this booking |
| WBXCHK-05 | `users` | Ticket's `user_id`, booking's `user_id` | The ticket's requester matches the booking's owner (identity check — a guest shouldn't be able to request changes to someone else's booking) |

---

## 10. Open questions

Build against the default; report every default relied upon, same convention as PRD-SCO-001.

| ID | Question | Assumed default | Blocking? |
|---|---|---|---|
| OQ-01 | What are the actual distinct values of `bookings.status`? | Unknown until profiled. Default: treat `pending` and `confirmed` as modifiable, anything else (e.g. `cancelled`, `completed`) as not. **Must be confirmed against real data before WBX-VAL-001 is implemented** | Yes, for WBX-VAL-001 |
| OQ-02 | Does `properties` have an active/status field? Column list captured so far didn't show one | Default: WBXCHK-02 checks existence only until profiling confirms otherwise | No |
| OQ-03 | How is "resolution time" (M-01/WBX-RPT-002) computed — is there a natural timestamp, or do we rely entirely on our own `ticket_status` transition timestamps? | Default: our own transition timestamps, since bronze data has no resolution concept | No |
| OQ-04 | Confidence score format for WBX-CLS-001/002 — numeric 0–1, or categorical (high/medium/low)? | Default: numeric 0–1 from the model, no UI gating (Section 6 non-goal) | No |

---

## 11. Traceability

Same rule as PRD-SCO-001 Section 14: the FS must cite parent WBX IDs; the TS must cite parent FS IDs; any requirement absent from the next layer's mapping table is a gap reported before implementation begins.
