# Technical Specification: Wanderbricks Support Ticket Triage & Resolution Agent — POC (Index)

| Field | Value |
|---|---|
| Document ID | TS-WBXAGT-001-POC |
| Version | 0.1 (DRAFT) |
| Parent | FS-WBXAGT-001-POC |
| Owner | AI Projects Analyst |
| Phase | POC (full feature set — see FS-WBXAGT-001-POC Section 1) |
| Target platform | Databricks: Workflows (Jobs), Unity Catalog, Model Serving / Agent Bricks, Databricks Apps |
| Catalog in scope | `sandbox_others` only (see `guardrails/CATALOG_POLICY.md`) |

---

## 0. How this document is organized

| Module | Contents |
|---|---|
| [TS-WBXAGT-001-POC-DATA-MODEL.md](TS-WBXAGT-001-POC-DATA-MODEL.md) | Silver and gold schema: DDL, column detail. Bronze already exists (`sandbox_others.bronze_datasample_wanderbricks`) and is described only by reference. |
| [TS-WBXAGT-001-POC-COMPONENTS.md](TS-WBXAGT-001-POC-COMPONENTS.md) | Pipeline design: silver transform, classification agent, validation, gold aggregation. Cites parent FS IDs. |
| [TS-WBXAGT-001-POC-APP.md](TS-WBXAGT-001-POC-APP.md) | Databricks App design: views, read/write pattern, identity. New relative to the SCO Agent TSD pattern, since this POC includes an App from the start. |
| [TS-WBXAGT-001-POC-TEST-SPEC.md](TS-WBXAGT-001-POC-TEST-SPEC.md) | Test cases covering every FS acceptance criterion and guardrail. |

---

## 1. Scope

Implements all of FS-WBXAGT-001-POC Section 2 (§2.1–§2.6) — silver transform, classification, validation, ticket tracking, App, and gold reporting. Nothing is deferred; see FS-WBXAGT-001-POC Section 1 for why this differs from the SCO Agent TSD pattern.

## 2. Architecture overview

```
   samples.wanderbricks (read-only)
            │  (already copied)
            ▼
   sandbox_others.bronze_datasample_wanderbricks
            │
            ▼
   ┌───────────────────────────────────────────────────────────┐
   │              Databricks Workflow (Job)                     │
   │                                                              │
   │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
   │  │ silver_   │─▶│ classify │─▶│ validate │─▶│ gold_        │ │
   │  │ transform │  │ (LLM)    │  │          │  │ aggregate    │ │
   │  └──────────┘  └──────────┘  └──────────┘  └─────────────┘ │
   └───────────────────────────────────────────────────────────┘
            │                │              │            │
            ▼                ▼              ▼            ▼
   silver.support_    silver.ticket_  silver.ticket_  gold.*
   messages,          classification, validation,
   silver.bookings/                   silver.tickets
   properties/hosts/                  (status),
   booking_updates/                   silver.ticket_
   users                              activity_log
                                              ▲
                                              │  read/write via SQL warehouse
                                    ┌─────────┴─────────┐
                                    │  Databricks App    │
                                    │  (reviewer queue +  │
                                    │   approve/reject)   │
                                    └─────────────────────┘
```

Same task-per-stage pattern as SCO Agent's TS-TOPO-001-POC, plus the App as a separate always-on deployable reading/writing silver directly (not a Job task — see APP module).

## 3. Traceability mapping

| FS ID | TS module | Coverage |
|---|---|---|
| FS-ING-001-POC, FS-ING-002-POC | Components §1 | FULL |
| FS-CLS-001-POC, FS-CLS-002-POC, FS-CLS-003-POC | Components §2.1-2.2 | FULL |
| FS-CLS-004-POC | Components §2.0, Data Model §3.1 (`prompt_registry`) | FULL |
| FS-VAL-001-POC..005-POC | Components §3 | FULL |
| FS-TRK-001-POC, FS-TRK-002-POC | Components §4 (shared across tasks + App) | FULL |
| FS-RPT-001-POC..003-POC | Components §5 | FULL |
| FS-APP-001-POC..003-POC | App module | FULL |

No FS-WBXAGT-001-POC requirement is uncovered.

## 4. Technical decisions confirmed by data profiling

Unlike the SCO Agent TSD (which left several TOQs genuinely open), two of this project's open questions were resolved by directly querying the copied bronze data before writing this TS:

| PRD OQ | Resolution |
|---|---|
| OQ-01 (booking status values) | Confirmed exactly 4 values: `pending` (31,575 rows), `confirmed` (17,948), `cancelled` (15,285), `completed` (7,439). Modifiable set = `{pending, confirmed}`, matching the PRD's assumed default exactly. |
| OQ-02 (property status field) | Confirmed: `properties` has no active/status column. WBXCHK-02 is existence-only, as the PRD defaulted. |

## 5. Remaining technical assumptions

| ID | Question | Proposed default | Impact if wrong |
|---|---|---|---|
| TOQ-01 | Which model/endpoint performs classification + extraction? | A Databricks Model Serving endpoint (Agent Bricks classification agent, or a foundation model with constrained JSON output) — same pattern as SCO Agent TOQ-03 | Swappable behind the same interface, no downstream impact |
| TOQ-02 | Pipeline schedule? | Every 15 minutes (looser than SCO's 5-min — this is a review-queue workload, not near-real-time triage) | Cosmetic, tune without a design change |
| TOQ-03 | Databricks App framework? | Streamlit (simplest for an internal review tool on Databricks Apps) | Isolated to the App module; no schema impact |
| TOQ-04 | Reviewer identity source? | Databricks Apps' built-in OAuth — the logged-in user's email is the reviewer identity for FS-APP-003-POC AC-1/AC-2, no separate login system | If Apps auth isn't suitable, falls back to a manual reviewer-name input field — App module only |

## 6. Guardrails and constraints exercised

| ID | How exercised |
|---|---|
| CON-GRD-01 | App module — status changes only via explicit Approve/Reject actions |
| CON-GRD-02 | Components §2 — constrained JSON output from the classification model |
| CON-GRD-03 | All objects live in `sandbox_others` (Data Model module) |
| CON-GRD-04 | No component calls anything outside `sandbox_others` |
| CON-GRD-05 | Data Model module — `ticket_activity_log` is append-only by design (no UPDATE/DELETE path in any component) |

## 7. Non-goals (inherited from FSD Section 1 / PRD Section 6)

Do not build: multi-intent decomposition, any write-back to a system outside `sandbox_others`, auto-resolution without human review.

## 8. Where the implementation lives

This TSD is docs-only, under `spec_driven_documents/wanderbricks_agent/`. The code implementing it lives in a separate sibling location, `projects/wanderbricks_agent/` — an empty container as of this writing. Specs and implementation are kept out of the same tree deliberately, but the internal layout of `projects/wanderbricks_agent/` (whether it's a Databricks Asset Bundle, how it's organized, file names) is a build-time decision for whoever/whatever implements this TSD (e.g. Genie Code), not something prescribed here.

The one piece of actual naming guidance that does apply, wherever the implementation ends up: the `silver_`/`gold_`/`AI_` file-naming convention in `TS-WBXAGT-001-POC-COMPONENTS.md` Section 0.

`projects/sco_agent/` does not exist yet — created the same way, later, once WBXAGT proves the pattern out (per `PROBLEM_STATEMENT.md` Section 1).
