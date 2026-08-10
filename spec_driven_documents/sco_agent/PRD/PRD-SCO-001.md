# Product Requirements Document: SCO Inbox Agent

| Field | Value |
|---|---|
| Document ID | PRD-SCO-001 |
| Version | 0.1 (DRAFT, awaiting review) |
| Status | NOT APPROVED. Downstream generation is blocked until status is APPROVED. |
| Replaces | BRD-SCO-001. Requirement IDs migrated `BR-` to `PR-`, area and number unchanged |
| Owner | AI Projects Analyst, ASM SCO |
| Product owner | SCO Procurement Master Data team |
| Target platform | Databricks (Apps, Agent Bricks, Unity Catalog) |
| Source | SCO team requirements list plus SAP Data Flow Field Mapping (Real Time Data) |
| Downstream artefacts | FS-SCO-001 (Functional Spec), TS-SCO-001 (Technical Spec) |

> **This is a living document.** It is revised whenever we learn something that changes what we should build. A revision is not a change request and does not require re-baselining. Requirements marked `HYPOTHESIS` are expected to change once validators use the product.

---

## 0. Instructions for downstream agents

1. This document defines **who has the problem, what the product does about it, and how we will know it worked**. It does not define implementation. Technology choices belong in the TS.
2. Every requirement has a stable ID of the form `PR-<AREA>-<NNN>`. **Never renumber, merge or delete an ID.** Superseded requirements are marked `[SUPERSEDED by PR-xxx-nnn]` and retained.
3. Every FS item you generate cites at least one PR ID. Every TS item cites at least one FS ID. Untraceable items are defects.
4. **Section 9 (Constraints) is not negotiable and not a hypothesis.** Those rules come from SAP and from ASM policy. Do not optimise them away, simplify them, or treat a validator's disagreement as grounds to change them.
5. **Section 6 (Non-goals) tells you what not to build.** Agents are prone to helpfully adding capability. If a non-goal makes the product feel incomplete, that is intentional.
6. Items marked `OPEN` carry an assumed default in Section 11. Build against the default and emit a warning list of every default relied upon.
7. Requirements marked `HYPOTHESIS` are the SCO team's best guess, not a validated need. Build them, instrument them, and expect them to change.
8. Do not resolve ambiguity silently. Where a requirement is unclear and no default exists, stop and raise it.
9. Priority uses MoSCoW. Release is `R1` to `R5` per Section 7. Release order is by user value, not technical convenience.

---

## 1. The problem

The SCO procurement master data team runs a shared mailbox, `sco_procurementdata@asm.com`. Requests to create, update or delete SAP purchasing master data arrive there as free-text email with attachments, from internal requestors, in varying quality and occasionally in languages nobody on the team reads.

For every request, a validator today must:

- read the message and work out whether it needs action at all
- work out what kind of request it is, and for which objects
- transcribe values from the email or a scanned PDF into SAP's expected format
- manually look up five separate SAP screens to check whether the request is even valid
- chase the requestor by hand when something is missing
- do all of this without knowing whether a colleague is working on the same request

The costs of this are transcription errors reaching SAP, inconsistent judgement between team members, avoidable SAP rejections discovered late, duplicated work, and no record of why any request was accepted or refused.

**What we are building**: an agentic intake, extraction and validation layer in front of SAP that does the reading, transcribing and checking, and presents a validator with a decision rather than a task. The validator retains authority over every write.

**What we are explicitly not building**: a system that decides. See Section 6.

## 2. Users

### Validator (primary)

SCO master data team member. Spends their day in the shared mailbox and in SAP.

**Jobs to be done**
- "Tell me what actually needs my attention today."
- "Tell me what is wrong with this request before I waste time on it."
- "Let me fix the bits the machine got wrong, without retyping everything."
- "Don't let me and a colleague both work the same request."
- "Let me get the missing information from the requestor without writing the email myself."

**What they fear**: a system that submits something wrong to SAP under their name.

### Admin (secondary)

SCO lead or AI team member. Needs to see how well the extraction is performing and to configure the product without a code change.

**Jobs to be done**
- "Show me where the model is uncertain, so I know what to improve."
- "Let me change a template or a threshold without raising a ticket."

### Requestor (indirect)

Internal ASM staff. Never opens the product. Experiences it only as clearer, faster replies.

**Job to be done**: "Tell me what you need from me, once, in a way I can act on."

### Commodity Manager (indirect)

Approves defined categories of request. Works entirely outside the product. Approval evidence arrives inside the email thread.

## 3. Success metrics

| ID | Metric | Baseline | Target | How measured |
|---|---|---|---|---|
| M-01 | Median validator minutes per request | To capture pre-launch (OQ-14) | 50% reduction | Time tracking on ticket open to approve |
| M-02 | Requests failing SAP validation after submission | To capture pre-launch | Near zero | SAP rejection log |
| M-03 | Field-level extraction accuracy | Manual transcription rate, to capture | Target set once baseline known (OQ-14) | Scored against a human-labelled sample |
| M-04 | Requests actioned by two validators simultaneously | Unknown, believed non-zero | Zero | System lock telemetry |
| M-05 | Validator override rate per field | None | Falling over time | Every override is an implicit correction label. Rising rate on a field means extraction is degrading |
| M-06 | Round trips to requestor per completed request | To capture pre-launch | Reduced | Count of outbound clarifications per ticket |

M-05 is the metric that tells you whether the product is getting better or worse in production. Instrument it from R2.

## 4. Product principles

These resolve arguments that will otherwise recur every sprint.

1. **The validator decides, the agent prepares.** Anything irreversible needs a human hand on it. This is a co-pilot, not an autopilot, and that is a product decision rather than a technical limitation.
2. **Surface problems, do not hide them.** A validator opening a ticket sees everything wrong with it immediately. Hunting for issues is the failure we are removing.
3. **Never invent a value.** Missing means missing. A plausible guess in a master data field is worse than a blank one, because it will not be questioned.
4. **Show your working.** Every extracted value points at where it came from. Every automated decision states its reason in plain language.
5. **Fail visibly.** Silent degradation is the failure mode that will destroy trust in this product. Prefer a loud stop to a quiet guess.

## 5. Scope by release

See Section 7 for what each release contains and why it is sequenced that way.

## 6. Non-goals

Things we are deliberately not doing, with reasons, so nobody helpfully adds them.

| Non-goal | Reason |
|---|---|
| Automating Source List hard deletion | Irreversible and low volume. The value of automating it does not justify the risk. The UI shows the control and the backend refuses. See PR-DEL-001 |
| Auto-assigning tickets to validators | The team asked for manual assignment. Revisit only if they ask |
| Translating foreign-language documents | We ask the requestor for English instead. Machine translation of a price or a part number introduces a silent error class we cannot detect |
| Object types beyond PIR and Source List | Not in the current mailbox volume. Adding them speculatively adds schema complexity for no user |
| Any communication outside ASM | Policy. Not a product decision |
| Deciding on the validator's behalf | Product principle 1. Even where confidence is high |
| Reopening submitted tickets to correct SAP errors | Deferred. See Section 12. Two approaches are on the table and neither has been chosen |

## 7. Release plan

Sequenced by user value delivered, not by technical dependency order.

| Release | Theme | What the validator gets | Requirements |
|---|---|---|---|
| **R1** | Stop reading irrelevant mail | A triaged queue. Only actionable requests, correctly typed, with a ticket each | PR-INT-001, PR-INT-002, PR-TRI-001 to PR-TRI-005, PR-TRK-001, PR-TRK-003, PR-TRK-004 |
| **R2** | Stop transcribing | Fields already extracted, normalised and pointing at their source. Conflicts and poor scans flagged | PR-EXT-001 to PR-EXT-005, PR-VAL-001, PR-TRK-002 |
| **R3** | Stop checking SAP by hand | Every SAP precondition checked on open. Problems visible immediately. Nothing lost to a colleague working the same ticket | PR-VAL-002 to PR-VAL-009, PR-LOCK-001 to PR-LOCK-003 |
| **R4** | Close the loop | Draft replies to requestors, an approval gate that cannot be passed while something is wrong, and a package ready for SAP | PR-COM-001 to PR-COM-004, PR-APV-001, PR-APV-002, PR-SAP-001, PR-SAP-002, PR-DOC-001, PR-DEL-001 |
| **R5** | Production writeback | Approved requests reach SAP production, with confirmation and requestor notification | PR-SAP-003 to PR-SAP-005, PR-APV-003 |

R1 alone is shippable and useful. If the project were cancelled after R1, the team would still be better off. Every release should meet that bar.

---

## 8. Requirements

Format per requirement:

- **User need** is the SCO team's own voice where the source material gave it. This is the *why*, and it survives when the requirement is rewritten.
- **Requirement** is what the product does.
- **Status** is `VALIDATED` (the need is confirmed) or `HYPOTHESIS` (a reasonable guess to be tested in use).

### R1: Triage

#### PR-INT-001 Ingest all mailbox traffic
- **User need**: "Review all emails that come into sco_procurementdata@asm.com"
- **Requirement**: The product ingests every email arriving at the shared mailbox, including attachments. Nothing is dropped.
- **Priority**: MUST | **Release**: R1 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given an email arrives, when the next ingestion cycle runs, then a record exists with body, sender, timestamp, thread ID and all attachments.
  - AC-2: Given ingestion fails for a message, when the cycle completes, then the failure is logged and retried. No message is silently dropped.

#### PR-INT-002 Handle non-English requests without unnecessary round trips
- **User need**: "Flag out non-English emails and ask requestor to resend in English." Refined by the team: the body is usually English even when an attachment is not, so rejecting on first sight of a foreign language wastes a round trip.
- **Requirement**: The product follows the language cascade in CON-12 before asking a requestor to resend in English.
- **Priority**: MUST | **Release**: R1 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given a non-English email body, when triage runs, then a clarification draft requesting English resubmission is prepared.
  - AC-2: Given an English body with all required fields and a non-English attachment, when triage runs, then no language clarification is raised.
  - AC-3: Given an English body missing fields and an attachment whose key fields are non-English, when extraction completes, then a clarification draft is prepared.

#### PR-TRI-001 Separate what needs action from what does not
- **User need**: "Clearly separate irrelevant emails, relevant emails (creation and update), relevant emails (hard deletion for Source List) for me to action on." Examples of irrelevant given by the team: "Thank you for...", "Can I check if...".
- **Requirement**: Incoming mail is separated into three streams: irrelevant, relevant (create or update), relevant (Source List hard delete).
- **Priority**: MUST | **Release**: R1 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given a non-actionable email, when triage runs, then it enters the irrelevant stream and no ticket is created.
  - AC-2: Given an actionable request, when triage runs, then a ticket is created in the correct stream.
  - AC-3: Every classification records its reasoning in the activity log.

#### PR-TRI-002 Rescue misclassified mail
- **User need**: "Ability to manually review irrelevant emails and push to relevant section if required."
- **Requirement**: A validator can browse the irrelevant stream and promote any message to the relevant stream.
- **Priority**: MUST | **Release**: R1 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given a message in the irrelevant stream, when a validator promotes it, then a ticket is created and the promotion is logged with the acting user.
  - AC-2: The irrelevant stream is browsable and searchable, not hidden.

#### PR-TRI-003 Identify which objects a request concerns
- **User need**: "For relevant emails, I want to know if the request is for PIR, Source List, or both."
- **Requirement**: Every relevant request is typed as PIR, Source List, or both.
- **Priority**: MUST | **Release**: R1 | **Status**: VALIDATED
- **Acceptance**: AC-1: Given a relevant request, when triage completes, then object type is exactly one of `PIR`, `SOURCE_LIST`, `BOTH`, visible on the ticket.

#### PR-TRI-004 Identify what the requestor wants done
- **User need**: "For relevant emails, I want to know if the intent is for creation, update, or hard delete (for Source List)."
- **Requirement**: Every relevant request carries an intent. Hard delete applies to Source List only.
- **Priority**: MUST | **Release**: R1 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given a relevant request, when triage completes, then intent is exactly one of `CREATE`, `UPDATE`, `HARD_DELETE`.
  - AC-2: Given intent `HARD_DELETE` on object type `PIR`, when triage completes, then the request is flagged for validator attention rather than routed to the deletion stream.

#### PR-TRI-005 Handle threads that ask for several things at once
- **User need**: "If an email thread has multiple intents like (1) Create PIR, (2) Create Source List, and (3) Delete old PIR, how does the architecture support this?"
- **Requirement**: One thread may produce several independent requests, each with its own ticket, linked to the originating thread.
- **Priority**: MUST | **Release**: R1 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given a thread with N distinct intents, when triage completes, then N tickets exist, all linked to the thread.
  - AC-2: Each ticket is validated and approved independently.
- **Open**: OQ-03

#### PR-TRK-001 One ticket per request
- **Requirement**: Every relevant request has exactly one ticket with a stable identifier and a defined status lifecycle.
- **Priority**: MUST | **Release**: R1 | **Status**: VALIDATED
- **Acceptance**: AC-1: Given any relevant request, when triage completes, then exactly one ticket exists for it.

#### PR-TRK-003 Show the validator what the agent did
- **User need**: "Ability to show a log of the Agent's activity for each ticket/request."
- **Requirement**: Each ticket carries a readable, ordered log of the agent's actions.
- **Priority**: MUST | **Release**: R1 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given any ticket, when the log is opened, then the validator sees what the agent did, in order, in plain language.
  - AC-2: The log is append-only. No entry can be edited or deleted by any role.

#### PR-TRK-004 Account for every message received
- **User need**: "Ability to track all emails that comes into sco_procurementdata@asm.com."
- **Requirement**: Every message received is registered with its classification and outcome, including those judged irrelevant.
- **Priority**: MUST | **Release**: R1 | **Status**: VALIDATED
- **Acceptance**: AC-1: Given any message received in a period, when the register is queried, then it appears with its classification and outcome.

### R2: Extraction

#### PR-EXT-001 Extract into the SAP-ready shape
- **User need**: "Extract info accurately from request into structured PIR/SL format."
- **Requirement**: Request information is extracted into the structured PIR or Source List schema from both body and attachments.
- **Priority**: MUST | **Release**: R2 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given a relevant request, when extraction completes, then every schema field is either populated or explicitly marked missing.
  - AC-2: Each field records its source location so a validator can verify it.
  - AC-3: The product never infers or defaults a value absent from the source. Absent means missing, not zero or blank.

#### PR-EXT-002 Keep confidence out of the validator's view
- **User need**: "Confidence score is only shown to specific users (admins), not to the validators."
- **Requirement**: Confidence is computed per field, persisted always, and shown only to admins.
- **Priority**: MUST | **Release**: R2 | **Status**: **HYPOTHESIS**
- **Rationale for the hypothesis flag**: the stated concern is that displayed scores anchor validator judgement. That is plausible and untested. Instrument override behaviour so the decision can be revisited with evidence rather than reargued from opinion.
- **Acceptance**:
  - AC-1: Given a validator session, when a ticket renders, then no confidence score appears in the UI or in any API response served to that session.
  - AC-2: Given an admin session, then per-field confidence is available.
  - AC-3: Confidence is persisted for every field regardless of visibility.

#### PR-EXT-003 Flag disagreement between sources
- **User need**: "Compare between extracted info and email/attachment."
- **Requirement**: Where the body and an attachment disagree on a field, the conflict is flagged naming both values and both sources.
- **Priority**: MUST | **Release**: R2 | **Status**: VALIDATED
- **Acceptance**: AC-1: Given a field differing between body and attachment, when validation runs, then a conflict flag names both values and sources.

#### PR-EXT-004 Normalise to SAP's expectations
- **User need**: "PDT: Must be converted to weeks (round up). Price in two decimal places (non JPY and KRW). Whole number for prices in JPY and KRW."
- **Requirement**: Extracted values are normalised per CON-01 to CON-03 before validation, with the original retained.
- **Priority**: MUST | **Release**: R2 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: PDT is in weeks, rounded up.
  - AC-2: Non-JPY, non-KRW prices carry exactly two decimal places.
  - AC-3: JPY and KRW prices are whole numbers.
  - AC-4: The pre-normalisation value is retained.

#### PR-EXT-005 Flag scans nobody can read
- **User need**: "Flag out low quality attachments." Paired with: "Within the email draft, there is a special button for the user to click which amends the draft to address the low quality image."
- **Requirement**: Attachments too poor for reliable extraction are flagged, and the draft editor offers a one-click amendment requesting a better copy.
- **Priority**: MUST | **Release**: R2 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given a low-quality attachment, when triage completes, then the ticket carries a flag naming it.
  - AC-2: Given that flag, when the validator activates the draft control, then the draft is amended to request a legible copy.

#### PR-VAL-001 Say what is missing
- **User need**: "Ensure completeness of info/values input for PIR/SL requests. Flag out missing information."
- **Requirement**: Every mandatory field absent from a request is listed individually as a blocking issue.
- **Priority**: MUST | **Release**: R2 | **Status**: VALIDATED
- **Acceptance**: AC-1: Given one or more mandatory fields absent, when validation runs, then each is listed individually.

#### PR-TRK-002 Record everything
- **User need**: "Metadata tables to track all activities."
- **Requirement**: Every state change, agent action, validation run, override, draft, send, approval and writeback is recorded with actor, timestamp and payload.
- **Priority**: MUST | **Release**: R2 | **Status**: VALIDATED
- **Acceptance**: AC-1: Given any of the above events, when it occurs, then a record exists with actor, timestamp and payload.

### R3: Validation and collaboration

#### PR-LOCK-001 Stop two people working the same request
- **User need**: "I want to ensure that when I am working on a request (opening the ticket), no one else can action on the same request."
- **Requirement**: Opening a ticket takes an exclusive lock. Others get a read-only view.
- **Priority**: MUST | **Release**: R3 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given A holds a ticket, when B opens it, then B sees read-only and an indicator naming A.
  - AC-2: Given A holds a ticket, when B attempts to approve, override or send, then the action is rejected.
  - AC-3: Locks release on close and on inactivity timeout.
- **Open**: OQ-15

#### PR-LOCK-002 Show who is on what
- **User need**: "Show who is working on what request (indicator/popup info to tell the user)."
- **Requirement**: Every queue view shows the current holder of each locked ticket.
- **Priority**: MUST | **Release**: R3 | **Status**: VALIDATED
- **Acceptance**: AC-1: Given any queue view, when rendered, then every locked ticket displays its holder.

#### PR-LOCK-003 Keep assignment in human hands
- **User need**: "Ticket Assignment approach: Manual Assignment preferred."
- **Requirement**: Tickets are assigned manually. The product does not auto-assign.
- **Priority**: MUST | **Release**: R3 | **Status**: **HYPOTHESIS**
- **Rationale for the hypothesis flag**: stated as a preference, not a constraint. Revisit if queue volume makes manual assignment a bottleneck. Do not revisit without the team asking.

#### PR-VAL-002 Check against real SAP data
- **User need**: "Validate extracted information on-demand with current SAP data."
- **Requirement**: Extracted data is checked against the five SAP read sources in Section 10. Each check records pass, fail or warning, and the age of the data it used.
- **Priority**: MUST | **Release**: R3 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given a ticket is opened, when validation runs, then all applicable checks execute and record an outcome.
  - AC-2: Every result records the SAP snapshot timestamp it used.
  - AC-3: A validator can re-run validation on demand.
- **Open**: OQ-02. Interim source is ADLS until SAP read APIs exist. That is a TS concern; this document requires only that data currency be visible.

#### PR-VAL-003 Do not let unapproved requests through
- **User need**: "Flag out relevant requests that lack Commodity Manager's (CM) approval and ask requestor to obtain necessary approval."
- **Requirement**: Requests requiring CM approval with no evidence in the thread are blocked, and a draft requesting approval is prepared.
- **Priority**: MUST | **Release**: R3 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given a request needing CM approval with no evidence, when validation runs, then a blocking issue is raised.
  - AC-2: Evidence found in the thread is linked to the ticket as the basis for clearing the check.
- **Open**: OQ-16

#### PR-VAL-004 Catch bulk requests
- **User need**: "Flag requests that consists of more than 50 unique Parts numbers (NOT QTY)."
- **Requirement**: Requests with more than 50 unique part numbers are flagged and routed to the extended approval path. The count is of distinct parts, never quantities.
- **Priority**: MUST | **Release**: R3 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given 51 or more unique parts, when validation runs, then the bulk flag is raised.
  - AC-2: Given 50 unique parts with a total quantity above 50, when validation runs, then the bulk flag is NOT raised.
- **Open**: OQ-06

#### PR-VAL-005 Catch duplicates SAP cannot yet see
- **User need**: From the team's worked example: request A.1 is approved and written to SAP, and five minutes later duplicate A.2 arrives in a new thread. SAP validation will not catch it because the snapshot has not refreshed.
- **Requirement**: Duplicates are detected against the product's own record of approved and in-flight writes, not only against the SAP snapshot.
- **Priority**: MUST | **Release**: R3 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given a request matching one approved within the lookback window, when validation runs, then a duplicate warning names the prior ticket, regardless of snapshot age.
  - AC-2: Detection does not depend on SAP data currency.
  - AC-3: The warning is overridable with a recorded reason. It is not a hard block.
- **Open**: OQ-01

#### PR-VAL-006 Show every problem the moment the ticket opens
- **User need**: "I want to know immediately what are the problems (missing info, lack CM approval, etc.) detected in this request, the moment I open the ticket."
- **Requirement**: Opening a ticket presents the complete set of detected problems without further navigation.
- **Priority**: MUST | **Release**: R3 | **Status**: VALIDATED
- **Acceptance**: AC-1: Given a ticket with N issues, when opened, then all N are visible immediately, each stating what is wrong and where it was found.

#### PR-VAL-007 Let the validator fix anything
- **User need**: "Ability to overwrite all extracted fields (if needed)."
- **Requirement**: Every extracted field is editable by the lock holder, with the prior value retained.
- **Priority**: MUST | **Release**: R3 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Every field is editable by the lock holder.
  - AC-2: Every override records prior value, new value, user and timestamp.
  - AC-3: Overriding re-runs the affected checks.

#### PR-VAL-008 Catch what changes on an update
- **User need**: "If User requests for PIR update, we need to know if the existing PIR's currency and UoM matches the request... if there is a price change... we need to know if there is a Reason Code provided."
- **Requirement**: PIR updates are checked for currency and UoM mismatch against the existing record, and for price change without a reason code.
- **Priority**: MUST | **Release**: R3 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given currency or UoM differing from the existing PIR, when validation runs, then a blocking mismatch issue is raised.
  - AC-2: Given a detected price change with no reason code in the email, when validation runs, then a blocking issue is raised.
- **Open**: OQ-05

#### PR-VAL-009 Know what a deletion covers
- **User need**: "If User requests for PIR deletion, we need to know if the PIR deletion is for a particular POrg or for all POrgs for that material."
- **Requirement**: PIR deletion requests without explicit scope are blocked pending clarification.
- **Priority**: MUST | **Release**: R3 | **Status**: VALIDATED
- **Acceptance**: AC-1: Given a deletion request with no explicit POrg scope, when validation runs, then a blocking issue is raised and a clarification draft prepared.
- **Open**: OQ-04

### R4: Closing the loop

#### PR-COM-001 Write the chasing email for me
- **User need**: "Ability to auto-draft email to get the necessary information - with human validation required before sending the email out."
- **Requirement**: A draft addressing every blocking issue is prepared. No email leaves without an explicit human send.
- **Priority**: MUST | **Release**: R4 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given blocking issues, when the draft panel opens, then a draft exists addressing every one.
  - AC-2: The draft is fully editable.
  - AC-3: No email is sent without a human send action. Hard constraint, CON-GRD-01.

#### PR-COM-002 One click for the unreadable-scan case
- **User need**: See PR-EXT-005. The team asked for a dedicated button rather than retyping the request each time.
- **Requirement**: The draft editor offers a control amending the draft to address a flagged low-quality attachment.
- **Priority**: SHOULD | **Release**: R4 | **Status**: VALIDATED

#### PR-COM-003 Consistent wording
- **User need**: "Email template."
- **Requirement**: Drafts are generated from maintained templates, editable by admins without a code change.
- **Priority**: MUST | **Release**: R4 | **Status**: VALIDATED
- **Acceptance**: AC-1: Every draft type maps to a named template editable by an admin.

#### PR-COM-004 Never mail outside ASM
- **User need**: "Emails should not be sent to non-ASM emails."
- **Requirement**: Sending to a non-ASM domain is refused at send time.
- **Priority**: MUST | **Release**: R4 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given a draft addressed outside ASM, when send is attempted, then it is blocked, shown and logged.
  - AC-2: The check runs at send time, not only at draft time.
- **Open**: OQ-13

#### PR-APV-001 Do not let me approve something broken
- **User need**: "For the Approve button to be clickable, it must pass the missing info check, SAP validation check, Commodity Manager approval check."
- **Requirement**: Approve is available only when all three checks pass, enforced server side.
- **Priority**: MUST | **Release**: R4 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given any check failing, when the ticket renders, then approve is unavailable and the blocking reasons are stated.
  - AC-2: The gate is enforced server side. Client-side only is a defect.

#### PR-APV-002 Make me confirm
- **User need**: "When user clicks approve, the popup will ask user to confirm, user clicks Yes and status changes to approve."
- **Requirement**: Approval requires a confirmation step. On confirmation, status becomes approved and a write package is produced.
- **Priority**: MUST | **Release**: R4 | **Status**: VALIDATED
- **Acceptance**: AC-1: Given approve is selected and confirmed, then status becomes `APPROVED`, a package is produced, and the action is logged with user and timestamp.

#### PR-SAP-001 Produce something SAP can take
- **User need**: "Store the approved request in structured schema (SAP-specific package file), ready to be pushed to SAP Quality."
- **Requirement**: Approval produces a structured package conforming to the agreed SAP schema, retrievable and linked to the ticket.
- **Priority**: MUST | **Release**: R4 | **Status**: VALIDATED

#### PR-SAP-002 Tell me whether it landed
- **User need**: "I want to know the status of SAP Quality module writeback."
- **Requirement**: Ticket status reflects `PENDING`, `WRITTEN` or `FAILED`, with the SAP response retained.
- **Priority**: MUST | **Release**: R4 | **Status**: VALIDATED
- **Open**: OQ-08. Behind a feature flag until APIs are confirmed.

#### PR-DOC-001 Keep the evidence
- **User need**: "Uploading of .msg outlook as evidence/supporting document for the Creation/Update of PIR/SL."
- **Requirement**: The source `.msg` can be uploaded, stored against the ticket and retrieved. Attachment to the SAP record where APIs permit.
- **Priority**: MUST | **Release**: R4 | **Status**: VALIDATED
- **Open**: OQ-09

#### PR-DEL-001 Let me do deletions myself
- **User need**: "I want to manually review and execute deletion myself in SAP." Described by the team as: included in the wireframe but inactive in the backend.
- **Requirement**: Deletion controls appear and are disabled with an explanation. No code path issues a delete to SAP.
- **Priority**: MUST | **Release**: R4 | **Status**: VALIDATED
- **Acceptance**:
  - AC-1: Given a deletion ticket, when rendered, then controls are visible, disabled and explained.
  - AC-2: No delete code path exists. Hard constraint, CON-GRD-04.

### R5: Production

#### PR-SAP-003 Write to production
- **Requirement**: Approved requests are pushed to the SAP PRODUCTION module with writeback status reported.
- **Priority**: MUST | **Release**: R5 | **Status**: VALIDATED
- **Open**: OQ-08

#### PR-SAP-004 Confirm what actually landed
- **Requirement**: After a successful write, the created or updated record is read back and presented against the approved values.
- **Priority**: SHOULD | **Release**: R5 | **Status**: **HYPOTHESIS**
- **Open**: OQ-10. The source material carried a heading with no content beneath it. This requirement is our proposal, not the team's stated need.

#### PR-SAP-005 Tell the requestor it is done
- **Requirement**: The requestor is notified when their request completes in SAP. Subject to PR-COM-004.
- **Priority**: SHOULD | **Release**: R5 | **Status**: **HYPOTHESIS**
- **Open**: OQ-10. As above.

#### PR-APV-003 Approve price increases properly
- **User need**: "Approval for PIR Price Increase: MFG Plant Request: ? IF Spares Plant Request: ?"
- **Requirement**: **BLOCKED.** The approvers and thresholds for both paths do not exist. Generate the configurable structure only. Do not generate logic.
- **Priority**: MUST | **Release**: R5 | **Status**: BLOCKED
- **Open**: OQ-07

---

## 9. Constraints

**Not hypotheses. Not subject to product iteration.** These come from SAP behaviour and ASM policy. A validator disliking one is not grounds to change it.

### 9.1 Business rules

| ID | Rule | Note |
|---|---|---|
| CON-01 | PDT is converted to weeks and rounded **up** | Source unit ambiguous, OQ-11 |
| CON-02 | Prices in currencies other than JPY and KRW: exactly two decimal places | |
| CON-03 | Prices in JPY and KRW: whole numbers | |
| CON-04 | More than 50 **unique part numbers** triggers the extended approval path. Distinct parts, never quantity | OQ-06 |
| CON-05 | Outbound email only to ASM domains | OQ-13 |
| CON-06 | Key information unobtainable in English triggers a resend-in-English request | |
| CON-07 | Approve requires missing-info, SAP validation and CM approval checks all passing | |
| CON-08 | Where open POs exist for the material, plant and vendor, PIR Price Valid From is the **oldest** PO Document date | |
| CON-09 | Confidence scores: admins only | |
| CON-10 | Source List hard deletion is manual in SAP. UI control present, inactive | |
| CON-11 | Ticket assignment is manual | |
| CON-12 | Language cascade: intent from the body first, extract as much as possible from the body, consult attachments only if insufficient, escalate to the requestor only if key attachment information is non-English | |

Every rule requires at least one automated test. Rules with thresholds require tests at, below and above the threshold.

### 9.2 Guardrails

Enforced in code, covered by a negative test, not bypassable by configuration.

| ID | Guardrail |
|---|---|
| CON-GRD-01 | No outbound email without an explicit human send action |
| CON-GRD-02 | No outbound email to a non-ASM domain |
| CON-GRD-03 | No SAP write unless PR-APV-001 and PR-APV-002 are both satisfied |
| CON-GRD-04 | No SAP delete operation exists in any code path |
| CON-GRD-05 | Confidence never returned to a non-admin session, in UI or API |
| CON-GRD-06 | Model output constrained to schema. No invented fields, no populating absent values |
| CON-GRD-07 | The activity log is append-only and immutable to all roles |
| CON-GRD-08 | Attachments and email content stay in governed storage, access enforced by Unity Catalog |
| CON-GRD-09 | Ticket locks enforced server side |
| CON-GRD-10 | Every automated block or clearance records a human-readable reason |

---

## 10. SAP validation reference

Source: SAP Data Flow Field Mapping (Real Time Data).

| ID | Source | Transaction | Inputs | Outputs | Check |
|---|---|---|---|---|---|
| SAPCHK-01 | PIR List | ME1M | Vendor code, Material Number (ASM part number), Purchase Organization | PIR number, Valid To Date | Valid PIR for Vendor-Material-POrg already exists. Does its currency and UoM match the request? |
| SAPCHK-02 | Source List | ME0M | Material Number, Plant | Material Number, Plant, Valid From, Valid To, Vendor code, POrg, Fixed supplier indicator, Materials Planning | Vendor is already a fixed source for the Material and Plant |
| SAPCHK-03 | Vendor Master | LFA1 / MKVZ | Vendor code | Vendor code, Purchase Organization, Currency, Vendor master status, Purchasing Group, Confirmation Control | Vendor extended to the requested POrg; VM status not FFD; Vendor currency equals PIR currency |
| SAPCHK-04 | Material Master | MARA, MARC | Material Number | Material Number, Plant, Procurement type, Plant-Specific Material Status | MM extended to the requested Plant; Procurement Type is F; P-S Mat. Status is not `IN` |
| SAPCHK-05 | Open PO | ME2M (Scope of List `ALV`, Selection Parameters `WE101`) | Material or Part No, Plant, Vendor code | PO Number, Item, Material, PO Document date | If open POs exist, use the oldest PO Document date as PIR Price Valid From |

Applicability: SAPCHK-01, 03, 04, 05 for PIR. SAPCHK-02, 03, 04 for Source List. Type `BOTH` runs all five.

---

## 11. Open questions

Build against the default. Report every default relied upon.

| ID | Question | Assumed default | Owner | Blocking? |
|---|---|---|---|---|
| OQ-01 | How to detect a duplicate arriving within the SAP refresh window? | Match on business key (vendor, material, POrg, plant, intent) against the product's own approved and in-flight write log, 24-hour lookback, independent of the SAP snapshot. Overridable warning | SCO + AI team | No |
| OQ-02 | How often is SAP data pulled? | 15-minute scheduled refresh, plus on-demand at ticket open and immediately before approve, rate limited per ticket | Data engineering | No |
| OQ-03 | How does the architecture support multiple intents per thread? | One message yields N requests, independent tickets, linked by thread ID | AI team | No |
| OQ-04 | PIR deletion: one POrg or all? | Scope must be explicit. If absent, block and clarify | SCO | No |
| OQ-05 | Is a reason code mandatory for a price change? | Yes. Block approval without one | SCO | No |
| OQ-06 | Is the over-50-parts approval chain (manager, MDM, finance) still required? | Retain all three, implemented as a configurable chain | Commodity team | No |
| OQ-07 | Approvers and thresholds for PIR price increases, MFG and spares? | **No safe default.** Configurable structure only | SCO | **YES for PR-APV-003** |
| OQ-08 | When are SAP write APIs available? | Package file in R4. Quality writeback behind a flag, default off | SAP team | No |
| OQ-09 | Can `.msg` files attach to SAP records via API? | Store in governed storage linked to the ticket. Defer SAP attachment | SAP team | No |
| OQ-10 | The source material had headings for SAP data review and requestor notification with no content | Proposed as PR-SAP-004 and PR-SAP-005, both R5, both HYPOTHESIS | SCO | No |
| OQ-11 | PDT source unit before conversion? | Days. Weeks = ceiling(days / 7). Round up any stated fraction | SCO | No |
| OQ-12 | The source material contained an incomplete bullet reading only "Flag out" | No default. Ask the SCO team what was intended | SCO | No |
| OQ-13 | Authoritative ASM domain list? | `asm.com` only, held as configuration | IT | No |
| OQ-14 | Baselines: volume, headcount, handling time, acceptable accuracy? | Two-week pre-launch observation before targets are set | AI team | No |
| OQ-15 | Ticket lock inactivity timeout? | 30 minutes, configurable, warning before release | SCO | No |
| OQ-16 | Which categories require CM approval? | All price-affecting PIR creations and updates. Needs confirmation | SCO | No |
| OQ-17 | Audit retention period? | 7 years, pending records policy | Compliance | No |

---

## 12. Deferred

**Correcting an error after SAP submission.** Two approaches were raised: a completed-tickets tab supporting date-range lookup and reopening, or correction directly in SAP by an experienced user. Neither has been chosen. Do not implement either.

---

## 13. Release readiness

A release ships when:

1. Every `MUST` requirement in that release has passing acceptance tests.
2. Every guardrail touched by that release has a passing negative test.
3. Every constraint exercised by that release has a passing test, including boundaries.
4. The assumptions report has been reviewed and signed off by the product owner.
5. The release delivers standalone value. If the project stopped here, the team would still be better off.

For R2 and later, add: extraction accuracy measured against the labelled sample and meeting the target under OQ-14.

---

## 14. Traceability

The FS must contain, per PR requirement: functional requirements `FS-<area>-<nnn>` each citing a parent PR ID, screen and interaction definitions, state machines for Ticket and Request, error and edge behaviour for every acceptance criterion, and a mapping table with any uncovered requirement marked `NOT COVERED`.

The TS must contain, per FS requirement: component, data model, interface and agent-topology definitions citing parent FS IDs, test specifications covering every acceptance criterion and every guardrail, and a mapping table.

Any PR requirement absent from the FS mapping, or any FS requirement absent from the TS mapping, is a gap reported before implementation begins.

## 15. ID migration from BRD-SCO-001

`BR-<AREA>-<NNN>` becomes `PR-<AREA>-<NNN>`. Area and number are unchanged, so `BR-VAL-004` is `PR-VAL-004`. Business rules `BRL-NN` become `CON-NN`. Guardrails `GRD-NN` become `CON-GRD-NN`. NFRs move to the TS, where they belong. `OQ-NN` and `SAPCHK-NN` are unchanged.
