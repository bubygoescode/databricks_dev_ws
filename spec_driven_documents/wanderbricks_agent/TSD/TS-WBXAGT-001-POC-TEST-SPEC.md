# Technical Specification: WBXAGT POC — Test Specification

| Field | Value |
|---|---|
| Document ID | TS-TEST-001-WBXAGT-POC |
| Parent | TS-WBXAGT-001-POC-INDEX.md |
| Status | DRAFT |

Every FS-WBXAGT-001-POC acceptance criterion and every guardrail (TS index Section 6) has at least one test below.

---

## 1. `silver_transform` tests (FS-ING-001-POC, FS-ING-002-POC)

| Test ID | Covers | Given | When | Then |
|---|---|---|---|---|
| TC-ING-001-01 | FS-ING-001-POC AC-1 | A bronze ticket with N messages | `silver_transform` runs | N rows exist in `silver.support_messages` for that ticket, each with sender/text/sentiment/timestamp |
| TC-ING-001-02 | FS-ING-001-POC AC-2 | A ticket's messages have distinct timestamps | Messages are read | Order by `message_timestamp` matches the original array order |
| TC-ING-001-03 | Error: malformed messages[] | A bronze row has null/malformed `messages` | Transform runs | Zero silver rows for that ticket, warning logged, other tickets unaffected |
| TC-ING-002-01 | FS-ING-002-POC AC-1/AC-2 | Bronze `bookings`/`properties`/`hosts`/`booking_updates`/`users` | Transform runs | Every bronze row has a corresponding silver row with the same primary key, unless excluded (TC-ING-002-02) |
| TC-ING-002-02 | Error: type conformance failure | A reference row has an unparseable field | Transform runs | Row excluded from silver, reason logged, not coerced |

## 2. `classify` task tests (FS-CLS-001-POC..003-POC)

| Test ID | Covers | Given | When | Then |
|---|---|---|---|---|
| TC-CLS-001-01 | AC-1 | A ticket's flattened messages | Classification runs | Exactly one of the six intent values is recorded |
| TC-CLS-001-02 | AC-2 | Any classification | It completes | A reasoning summary is recorded |
| TC-CLS-002-01 | AC-1 | An actionable ticket referencing a booking | Extraction runs | `extracted_booking_id` populated or explicitly NULL — never a guessed value |
| TC-CLS-002-02 | AC-2 | An extracted field | Recorded | Distinguishable from validated reference data (different table/source) |
| TC-CLS-003-01 | Error: model failure | The endpoint errors or times out | Classification attempted | `current_status = 'CLASSIFICATION_FAILED'`, no `ticket_classification` row written, error logged |
| TC-CLS-003-02 | Error: malformed output | The model returns non-schema-conforming JSON | Classification attempted | Same as TC-CLS-003-01 — not partially accepted |

## 3. `validate` task tests (FS-VAL-001-POC..005-POC)

| Test ID | Covers | Given | When | Then |
|---|---|---|---|---|
| TC-VAL-001-01 | WBXCHK-01 pass | `extracted_booking_id` resolves to a `pending` or `confirmed` booking | Validation runs | `PASS` recorded |
| TC-VAL-001-02 | WBXCHK-01 fail (status) | Booking exists but status is `cancelled` or `completed` | Validation runs | `FAIL` recorded, detail names the actual status |
| TC-VAL-001-03 | WBXCHK-01 fail (not found) | `extracted_booking_id` doesn't resolve to any row | Validation runs | Hard `FAIL`, not a skipped check |
| TC-VAL-002-01 | WBXCHK-02/03 pass | Property exists; host `is_active` and `is_verified` both true | Validation runs | Both `PASS` |
| TC-VAL-002-02 | WBXCHK-03 fail | Host `is_active = false` or `is_verified = false` | Validation runs | Host check `FAIL` |
| TC-VAL-003-01 | WBXCHK-04 warn | An unresolved prior `booking_updates` row exists for the same booking | Validation runs | `WARN` recorded, naming the conflicting update ID |
| TC-VAL-003-02 | WBXCHK-04 pass | No prior unresolved update | Validation runs | `PASS` |
| TC-VAL-004-01 | WBXCHK-05 fail | Ticket's `user_id` != booking's `user_id` | Validation runs | Hard `FAIL` |
| TC-VAL-004-02 | WBXCHK-05 pass | IDs match | Validation runs | `PASS` |
| TC-VAL-005-01 | FS-VAL-005-POC AC-1 | A ticket with 5 validation results | App requests them | All 5 returned together, no per-check call needed |

## 4. Ticket state tests (FS-TRK-001-POC, FS-TRK-002-POC)

| Test ID | Covers | Given | When | Then |
|---|---|---|---|---|
| TC-TRK-001-01 | AC-1 | Any ticket | Queried at any time | `current_status` is exactly one of the defined values |
| TC-TRK-001-02 | AC-2 | A ticket in `NEW` | An attempt is made to set it directly to `APPROVED` | Rejected/not possible through any component — only forward, one-step-at-a-time transitions exist in the codebase |
| TC-TRK-002-01 | AC-1 | Any activity log entry | An attempt is made to UPDATE or DELETE it | No code path exists to do so (static check: no UPDATE/DELETE statement targets `ticket_activity_log` anywhere in the codebase) |
| TC-TRK-002-02 | AC-2 | A ticket with multiple events | Log is read | Entries are ordered by `occurred_at`, each human-readable |

## 5. App tests (FS-APP-001-POC..003-POC)

| Test ID | Covers | Given | When | Then |
|---|---|---|---|---|
| TC-APP-001-01 | AC-1 | Tickets across multiple statuses | Queue view loads | Each row shows ticket ID, status, intent, flag count |
| TC-APP-002-01 | AC-1 | A ticket with messages, extraction, validation, and log entries | Detail view opens | All four render without further navigation |
| TC-APP-003-01 | AC-1 | A ticket with all `PASS` validations | Reviewer clicks Approve | `current_status = 'APPROVED'`, logged with reviewer email + timestamp |
| TC-APP-003-02 | AC-2 | A ticket with a `FAIL` validation | Reviewer attempts Approve without a reason | Blocked until a reason is entered; once entered, both a `STATUS_CHANGE` and an `OVERRIDE` log entry are written |
| TC-APP-003-03 | AC-3 | Any ticket | Reviewer clicks Reject | No reason required; `current_status = 'REJECTED'`, logged identically to Approve |
| TC-APP-003-04 | Server-side gap flagged in TS-APP module §3.3 | A `FAIL`-validation ticket | The App's update statement is called directly, bypassing the UI reason prompt | **Expected to currently succeed without a reason** — this test exists to confirm and document the gap, not to assert correct behaviour. Escalate before this pattern reaches a phase where it matters. |

## 6. Gold aggregation tests (FS-RPT-001-POC..003-POC)

| Test ID | Covers | Given | When | Then |
|---|---|---|---|---|
| TC-RPT-001-01 | FS-RPT-001-POC AC-1 | Classified tickets for a given day | `gold_aggregate` runs | `intent_distribution` counts by intent sum to the day's total classified count |
| TC-RPT-002-01 | FS-RPT-002-POC AC-1 | Tickets reaching `APPROVED`/`REJECTED` on a given day | `gold_aggregate` runs | `resolution_metrics` row exists for that day with non-null `avg_resolution_minutes`, correct approve/reject/override counts |
| TC-RPT-003-01 | FS-RPT-003-POC AC-1 | Messages with sentiment values on a given day | `gold_aggregate` runs | `sentiment_trend` rows exist per intent/sentiment_category combination present that day |
| TC-RPT-00X-02 | Idempotency (Components §5.2) | `gold_aggregate` runs twice for the same day | Second run completes | Gold tables reflect the same values, not doubled (upsert, not append) |

## 7. Guardrail tests

| Test ID | Guardrail | Given | When | Then |
|---|---|---|---|---|
| TC-GRD-01-01 | CON-GRD-01 | Any ticket | Its status is inspected after any pipeline run alone (no App action) | Status never reaches `APPROVED`/`REJECTED` without a corresponding App-initiated log entry |
| TC-GRD-02-01 | CON-GRD-02 | The classification model returns free text instead of the constrained schema | `classify` runs | Treated as failure (TC-CLS-003-02), not parsed loosely |
| TC-GRD-03-01 | CON-GRD-03 | Any table created by this project | Its full name is inspected | Catalog is always `sandbox_others` |
| TC-GRD-05-01 | CON-GRD-05 | `ticket_activity_log` | Codebase is searched for UPDATE/DELETE against it | None found (same as TC-TRK-002-01) |

## 8. Traceability check

Every FS-WBXAGT-001-POC acceptance criterion and every guardrail in TS-WBXAGT-001-POC-INDEX.md Section 6 maps to at least one test above. No known gap, except the App's UI-only override enforcement (TC-APP-003-04), which is deliberately flagged rather than silently left uncovered.
