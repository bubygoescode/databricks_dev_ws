# Technical Specification: SCO Inbox Agent — POC (Index)

| Field | Value |
|---|---|
| Document ID | TS-SCO-001-POC |
| Version | 0.1 (DRAFT) |
| Status | DRAFT — PRD-SCO-001 is NOT APPROVED; proceeding on the product owner's direction to draft ahead of formal sign-off (see PRD Section 0) |
| Parent | FS-SCO-001-POC |
| Owner | AI Projects Analyst, ASM SCO |
| Phase | POC |
| Target platform | Databricks: Workflows (Jobs), Unity Catalog (managed tables + volumes), Model Serving / Agent Bricks |
| Catalog in scope | `sandbox_others` only, per project guardrail (see `guardrails/CATALOG_POLICY.md`) |

---

## 0. How this document is organized

This TS is split into modules so each stays within a comfortable context window for both human and LLM readers/editors. Read this index first; it links to the rest.

| Module | Contents |
|---|---|
| [TS-SCO-001-POC-DATA-MODEL.md](TS-SCO-001-POC-DATA-MODEL.md) | Unity Catalog schema: catalog/schema/table/volume definitions, DDL, column-level detail. **Flagged for accuracy review** — table/schema names here are proposed, not confirmed against any existing ASM data estate. |
| [TS-SCO-001-POC-COMPONENTS.md](TS-SCO-001-POC-COMPONENTS.md) | Ingestion, classification, and ticketing component designs. Cites parent FS IDs. Includes agent topology (which parts are plain ETL vs. an LLM/agent call). |
| [TS-SCO-001-POC-TEST-SPEC.md](TS-SCO-001-POC-TEST-SPEC.md) | Test cases covering every FS acceptance criterion and every guardrail touched by POC. |

When MVP/Pilot TS documents are written, follow the same module split (data model / components / test spec) rather than one growing file per phase.

---

## 1. Scope

Implements, per FS-SCO-001-POC Section 2:

| FS ID | Area | TS module |
|---|---|---|
| FS-INT-001-POC | Mailbox polling and message persistence | Components §1, Data Model §2 |
| FS-TRI-001-POC | Three-stream classification | Components §2, Data Model §3 |
| FS-TRK-001-POC | Ticket creation and identity | Components §3, Data Model §4 |

Out of scope for this TS (per FSD Section 1 "What POC does not deliver"): language cascade, manual promotion, object type/intent identification, multi-intent decomposition, message register, activity-log immutability, any UI. Do not build these now.

---

## 2. Architecture overview

```
                    ┌─────────────────────────────────────────────┐
                    │           Databricks Workflow (Job)          │
                    │        schedule: every 5 min (proposed)      │
                    │                                               │
   Shared mailbox   │  ┌──────────┐   ┌──────────────┐  ┌────────┐ │
   sco_procurement-  ──▶│ Ingest   │──▶│ Classify     │──▶│ Ticket │ │
   data@asm.com      │  │  task    │   │  task        │  │  task  │ │
   (Graph API)       │  └────┬─────┘   └──────┬───────┘  └───┬────┘ │
                    │       │                │              │       │
                    └───────┼────────────────┼──────────────┼───────┘
                            ▼                ▼              ▼
                     messages,         classification_log  tickets
                     attachments        (+ model call to
                     (Delta + Volume)    serving endpoint)
                            └──────────────┬──────────────┘
                                           ▼
                          Unity Catalog: sandbox_others.sco_agent_poc
```

Three tasks, one Job, run sequentially and scheduled. Each task is idempotent (safe to re-run) — see Components module for per-task retry/error behaviour matching FS-*-POC "Error behaviour" sections.

Only the classification task calls an LLM/agent. Ingestion and ticketing are conventional ETL/Python tasks — there is no need to route mailbox parsing or ticket-ID assignment through a model.

---

## 3. Traceability mapping

| PR ID | FS ID | TS ID(s) | Coverage | Notes |
|---|---|---|---|---|
| PR-INT-001 (partial) | FS-INT-001-POC | TS-INT-001-POC | FULL (of FS scope) | See Components §1 |
| PR-TRI-001 (partial) | FS-TRI-001-POC | TS-TRI-001-POC | FULL (of FS scope) | See Components §2 |
| PR-TRK-001 (partial) | FS-TRK-001-POC | TS-TRK-001-POC | FULL (of FS scope) | See Components §3 |
| — | — | TS-DATA-001-POC | — | Data model underpinning all three; see Data Model module |
| — | — | TS-TOPO-001-POC | — | Job/task orchestration; see Components §0 |

No FS-SCO-001-POC requirement is uncovered by this TS. No gap to report at this phase.

---

## 4. Technical assumptions and open questions

These are TS-level decisions the FS/PRD did not specify (technology choice belongs in the TS per PRD Section 0 rule 1). Each has a proposed default so work can proceed; each should be confirmed or corrected rather than silently trusted.

| ID | Question | Proposed default | Impact if wrong |
|---|---|---|---|
| TOQ-01 | What protocol/API reaches the shared mailbox? | Microsoft Graph API (app-only auth, `Mail.Read` on the shared mailbox), using delta query for incremental polling | If the mailbox isn't Exchange Online/M365, swap for IMAP — isolated to the Ingest component, no schema impact |
| TOQ-02 | Polling interval? | 5 minutes | Cosmetic — tune without a design change |
| TOQ-03 | Which model/endpoint performs 3-way classification? | A Databricks Model Serving endpoint (Agent Bricks classification agent or a foundation model with a constrained JSON output schema) | Swappable behind the same interface (Components §2); no downstream impact if the endpoint changes |
| TOQ-04 | Where do attachment binaries live? | Unity Catalog Volume (`sandbox_others.sco_agent_poc.attachments`), metadata + path in the `attachments` Delta table | FSD only requires "any accessible storage" for POC; this default is chosen so migrating to CON-GRD-08 governed storage later needs no redesign |
| TOQ-05 | How is the sequential `SCO-NNNNNN` ticket ID generated, given FSD's stated collision-and-retry error behaviour implies a non-native counter? | A dedicated counter row updated via optimistic-concurrency `MERGE`, retried on write conflict | See Data Model §4 and Components §3 for the exact mechanism |
| TOQ-06 | Which catalog/schema hosts POC objects? | Catalog `sandbox_others` (only catalog Claude/this project is authorized to touch — see `guardrails/CATALOG_POLICY.md`), schema `sco_agent_poc` | Confirm the schema name doesn't collide with anything already in `sandbox_others` |

---

## 5. Guardrails and constraints exercised by POC

| ID | Constraint/guardrail | How exercised |
|---|---|---|
| CON-GRD-08 | Attachments and email content stay in governed storage, access enforced by Unity Catalog | Delta tables + UC Volume under `sandbox_others.sco_agent_poc`, access controlled via UC grants (POC does not yet enforce production-grade governed storage per FSD's own POC limitation — structure supports migrating to it without a redesign) |

No other constraint/guardrail from PRD Section 9 is exercised in POC — object-type/intent, CM approval, SAP validation, locking, communication, and approval-gate constraints all belong to later phases per the FSD scope table.

---

## 6. Non-goals (inherited from FSD Section 1)

Do not build in this TS: language cascade, manual promotion of misclassified mail, object type/intent identification, multi-intent decomposition, message register, activity-log immutability, alerting on consecutive failures, or any UI. These belong to MVP/Pilot TS documents.
