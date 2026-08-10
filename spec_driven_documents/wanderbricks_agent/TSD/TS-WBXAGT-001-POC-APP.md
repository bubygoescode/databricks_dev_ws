# Technical Specification: WBXAGT POC — Databricks App

| Field | Value |
|---|---|
| Document ID | TS-APP-001-WBXAGT-POC |
| Parent | TS-WBXAGT-001-POC-INDEX.md, FS-WBXAGT-001-POC |
| Status | DRAFT |

This module is new relative to the SCO Agent TSD pattern — SCO's own POC deferred any UI to MVP. This POC includes the App from the start (per explicit direction, see PRD-WBXAGT-001 Section 5).

---

## 0. Stack (TOQ-03, TOQ-04)

- **Framework**: Streamlit, deployed as a Databricks App. Simplest option for an internal review tool; no separate hosting/auth to stand up.
- **Data access**: Databricks SQL connector, querying the warehouse used by the pipeline, reading/writing `sandbox_others.silver_wanderbricks_agent.*` directly. No caching layer in POC — every view queries live.
- **Identity**: Databricks Apps' built-in OAuth. The logged-in user's email is the reviewer identity written to `tickets.assigned_reviewer` and `ticket_activity_log.actor` on any App-initiated action (TOQ-04). No separate login/user-management system.

---

## 1. Queue view (implements FS-APP-001-POC)

**Route**: `/` (landing page)

**Query**:
```sql
SELECT t.ticket_id, t.current_status, t.current_intent,
       COUNT(v.validation_id) FILTER (WHERE v.result != 'PASS') AS flag_count
FROM sandbox_others.silver_wanderbricks_agent.tickets t
LEFT JOIN sandbox_others.silver_wanderbricks_agent.ticket_validation v
  ON t.ticket_id = v.ticket_id
WHERE t.current_status = :status_filter  -- optional, defaults to showing all
GROUP BY t.ticket_id, t.current_status, t.current_intent
ORDER BY t.updated_at DESC
```

**Acceptance mapping**: FS-APP-001-POC AC-1 — table with ticket ID, status, intent, flag count columns; a status filter dropdown (`NEW`/`VALIDATED`/`APPROVED`/`REJECTED`/`CLASSIFICATION_FAILED`/all).

---

## 2. Ticket detail view (implements FS-APP-002-POC)

**Route**: `/ticket/{ticket_id}`

Four sections, each a separate query, per FS-APP-002-POC AC-1:

1. **Message thread**: `SELECT * FROM silver.support_messages WHERE ticket_id = :id ORDER BY message_timestamp`
2. **Extracted fields**: latest `silver.ticket_classification` row for the ticket (`ORDER BY classified_at DESC LIMIT 1`) — intent, extracted_booking_id, extracted_details_json (parsed and rendered field-by-field), reasoning, confidence
3. **Validation results**: all `silver.ticket_validation` rows for the ticket (FS-VAL-005-POC — all results at once, no per-check navigation)
4. **Activity log**: all `silver.ticket_activity_log` rows for the ticket, `ORDER BY occurred_at`

---

## 3. Approve/Reject action (implements FS-APP-003-POC)

### 3.1 Approve

1. Read current `silver.ticket_validation` rows for the ticket.
2. If any `result = 'FAIL'`: require a non-empty override reason input before enabling the Approve button (FS-APP-003-POC AC-2).
3. On click:
   ```sql
   UPDATE sandbox_others.silver_wanderbricks_agent.tickets
   SET current_status = 'APPROVED', assigned_reviewer = :reviewer_email, updated_at = current_timestamp()
   WHERE ticket_id = :id;

   INSERT INTO sandbox_others.silver_wanderbricks_agent.ticket_activity_log
     (log_id, ticket_id, event_type, detail, actor, occurred_at)
   VALUES (uuid(), :id, 'STATUS_CHANGE', 'Approved by reviewer', :reviewer_email, current_timestamp());

   -- only if an override reason was required/provided:
   INSERT INTO sandbox_others.silver_wanderbricks_agent.ticket_activity_log
     (log_id, ticket_id, event_type, detail, actor, occurred_at)
   VALUES (uuid(), :id, 'OVERRIDE', :override_reason, :reviewer_email, current_timestamp());
   ```
4. Both inserts and the update happen in one transaction — no partial state (FS-APP-003-POC AC-3, no action bypasses the log).

### 3.2 Reject

Same pattern, `current_status = 'REJECTED'`, no override reason required (FS-APP-003-POC AC-3) — a single `STATUS_CHANGE` log entry, `detail = 'Rejected by reviewer'` (optionally with a free-text rejection note, not required).

### 3.3 Acceptance mapping

| FS AC | Where enforced |
|---|---|
| AC-1 (all-PASS approve works) | 3.1 steps 2–3, no override branch taken |
| AC-2 (FAIL requires override reason) | 3.1 step 2 (UI-level gate) — **note**: this is a UI-level guard, not a server-side constraint in POC. TS-TEST-001-WBXAGT-POC should include a test attempting to bypass the UI and call the update directly, to confirm whether this needs a server-side check before a later phase relies on it |
| AC-3 (reject always available, always logged) | 3.2 |

---

## 4. What's deliberately not built

- No multi-reviewer conflict handling (SCO Agent's ticket-locking pattern, PR-LOCK-001..003) — out of scope, not mentioned in PRD-WBXAGT-001's requirements at all. If two reviewers act on the same ticket concurrently in POC, last-write-wins on `tickets.current_status`. Flag if this becomes a real problem during testing.
- No admin-only confidence gating (PRD Section 6 non-goal) — confidence is visible in the detail view to the single reviewer role.
