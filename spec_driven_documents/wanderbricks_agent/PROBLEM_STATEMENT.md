# Problem Statement: Wanderbricks Support Ticket Triage & Resolution Agent (WBXAGT)

| Field | Value |
|---|---|
| Status | DRAFT — seed document for PRD-WBXAGT-001 |
| Purpose | Prove spec-driven, LLM-assisted development end-to-end (PRD → FSD → TSD → build) on synthetic data, before attempting the real SCO Agent, which is blocked on production O365 mailbox access |
| Data | `sandbox_others.bronze_datasample_wanderbricks`, copied from `samples.wanderbricks` (Databricks-provided sample dataset) |

---

## 1. Why this exercise exists

The real target is **SCO Agent** (`spec_driven_documents/sco_agent/`) — an agentic intake/triage layer in front of SAP for procurement master-data requests arriving by email. That project is real, but its data source is a production mailbox, which raises access, risk, and timeline questions that shouldn't block learning whether the *development approach itself* — PRD → FSD → TSD → agentic pipeline → App, built largely by an LLM from spec — actually works.

This project (WBXAGT) exists to answer that question cheaply: build a structurally equivalent agent against a safe, already-available sample dataset (`samples.wanderbricks`), touching the same shape of problem — unstructured text needing intent detection, extraction, and cross-checks against reference data before a decision — and the same target architecture (Databricks Apps, a data pipeline, a silver/gold layer, an agentic/LLM component). What we learn here — what worked, what the spec-driven process missed, where the LLM needed hand-holding — feeds directly into how SCO Agent gets built once its mailbox access is sorted out.

**This is not a real product initiative.** There is no real business, no real users, no real cost of the current "process" — it's fictional, built on Databricks' sample travel-booking dataset (`wanderbricks`: bookings, properties, hosts, users, and a support-ticket table with free-text message threads). Treat the narrative below as a plausible, well-shaped stand-in problem, not a validated need.

## 2. The stand-in problem

Wanderbricks (fictional, sample-data-only) is a property-booking platform. Its support team works a shared ticket queue (`customer_support_logs`): each ticket is a thread of free-text messages between a guest and a support agent, covering things like cancellations, date/guest-count changes, refund requests, property complaints, and general questions.

Today (fictionally), an agent working a ticket must:
- read the thread and work out what's actually being asked
- figure out which booking it concerns
- manually check the booking's status, the property's details, and the host's standing across several tables before knowing whether the request is even valid
- decide how to respond, with no structured record of why

This is the same shape of problem SCO Agent solves for procurement email: unstructured intake, intent classification, cross-reference validation against reference data, then a decision — a human retains authority over the outcome, but the agent does the reading, classifying, and checking.

## 3. What we're building

An agentic pipeline that:
1. Reads `customer_support_logs` threads
2. Uses an LLM to classify each thread's intent (cancellation, modification, refund, complaint, general question, not-actionable) and extract the relevant structured details (which booking, what's being requested)
3. Validates the request against reference data (`bookings`, `booking_updates`, `properties`, `hosts`, `users`) — is the booking real, is it still in a modifiable state, does the host/property allow what's being asked, is there already a conflicting update in flight
4. Presents the result — ticket, detected intent, extracted fields, validation outcome — in a minimal Databricks App for review
5. Sits on top of a bronze → silver → gold pipeline: bronze is the raw copied sample data (already done), silver conforms/cleans it (parsed messages, normalized references, joined booking/property/host context), gold aggregates it for reporting (resolution metrics, intent distribution, sentiment trend)

## 4. What we're explicitly not building (yet)

- **Multi-intent decomposition** (one thread containing several distinct asks, each needing its own ticket) — SCO Agent itself defers this past its own POC; matching that here keeps the phase boundary consistent
- **Any write-back to a real system** — there is no real Wanderbricks backend. "Resolution" means marking the ticket resolved in our own tables, not calling any external API
- **Auto-resolution without human review** — same product principle as SCO Agent: the agent prepares, a human decides
- **Full intent taxonomy coverage in one pass** — start with the intents the sample data actually supports; don't invent categories the data can't exercise

## 5. How this maps to SCO Agent's structure

| SCO Agent | WBXAGT (this project) |
|---|---|
| Shared mailbox, free-text email threads | `customer_support_logs`, free-text message threads |
| PIR/Source List create/update requests | Booking cancellation/modification/refund requests |
| SAP validation reads (Vendor Master, Material Master, Open PO, ...) | `bookings`, `properties`, `hosts`, `booking_updates` |
| Ticket, validator queue, approval gate | Same pattern, same terminology |
| Target platform: Databricks (Apps, Agent Bricks, Unity Catalog) | Same, plus this POC includes the App from the start (SCO's own POC deferred it to MVP — deliberately not mirrored here, since proving the App-building path is part of the point) |

## 6. Expected output

**Bronze** (done) — `sandbox_others.bronze_datasample_wanderbricks`: 7 raw tables copied as-is from `samples.wanderbricks`.

**Silver** — `sandbox_others.silver_wanderbricks_agent`:
- `support_messages` — bronze's nested `messages[]` array exploded into one row per message (ticket_id, sender, message, sentiment, timestamp)
- `ticket_classification` — LLM output per ticket: intent (`CANCELLATION` / `MODIFICATION` / `REFUND` / `COMPLAINT` / `GENERAL_QUESTION` / `NOT_ACTIONABLE`), extracted `booking_id`, extracted request details, reasoning, confidence
- `ticket_validation` — one row per check per ticket: does the booking exist, is it still modifiable, does the host/property allow the request, is there a conflicting `booking_updates` already in flight (mirrors SCO's SAPCHK reference checks)
- `ticket_status` — ticket_id, current status (`NEW` → `VALIDATED` → `APPROVED`/`REJECTED`), assigned reviewer, timestamps — what the App reads/writes

**Gold** — `sandbox_others.gold_wanderbricks_agent`:
- `intent_distribution` — ticket counts by intent over time
- `resolution_metrics` — resolution time, approve/reject rate, override rate (SCO's M-05 analog)
- `sentiment_trends` — sentiment by day/intent

**Pipeline** — one Databricks Workflow, tasks run in sequence: `silver_transform` (explode messages, conform bookings/properties/hosts) → `classify` (LLM call, writes `ticket_classification`) → `validate` (reference checks, writes `ticket_validation`) → `gold_aggregate`. Same shape as SCO's ingest→classify→ticket job.

**AI agent** — the `classify` task: calls a Databricks Model Serving endpoint (Agent Bricks classification agent or a foundation model with constrained JSON output) per ticket, reading `support_messages`, writing `ticket_classification`. Runs as a Workflow job task (developed/tested in a notebook first, then scheduled — not a standalone interactive-only notebook).

**App** — one Databricks App: a ticket queue showing intent, extracted fields, and validation results per ticket, with an approve/reject action that updates `ticket_status`. Reads/writes silver tables directly.

## 7. Next steps

1. Formalize this into `PRD-WBXAGT-001` (mirrors `PRD-SCO-001`'s structure: users, success metrics, product principles, release plan, requirements with stable IDs, constraints, reference-validation table, open questions)
2. `FS-WBXAGT-001-POC` — functional spec for POC scope
3. `TS-WBXAGT-001-POC` — technical spec (data model already partly done: `sandbox_others.bronze_datasample_wanderbricks`; needs silver/gold design, agent/App design)
4. Build, and report back what the spec-driven process got right or wrong
