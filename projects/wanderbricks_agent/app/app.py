"""
WBXAGT POC - Wanderbricks Support Ticket Triage & Resolution App
"""
import streamlit as st
import json
import uuid
import os
from datetime import datetime
from databricks import sql as dbsql
from databricks.sdk import WorkspaceClient

SILVER_SCHEMA = "sandbox_others.silver_wanderbricks_agent"
DEFAULT_ICON = "\u26aa"
STATUS_ICONS = {
    "NEW": "\U0001f7e1",
    "VALIDATED": "\U0001f7e0",
    "APPROVED": "\U0001f7e2",
    "REJECTED": "\U0001f534",
    "CLASSIFICATION_FAILED": "\u26ab",
}
RESULT_ICONS = {"PASS": "\u2705", "FAIL": "\u274c", "WARN": "\u26a0\ufe0f"}


@st.cache_resource
def get_connection():
    w = WorkspaceClient()
    http_path = os.environ.get("DATABRICKS_SQL_HTTP_PATH", "/sql/1.0/warehouses/0311a41d65a98815")
    token = w.config.authenticate()
    access_token = token.get("Authorization", "").replace("Bearer ", "")
    return dbsql.connect(
        server_hostname=w.config.host.replace("https://", ""),
        http_path=http_path,
        access_token=access_token,
    )


def get_reviewer_email():
    try:
        w = WorkspaceClient()
        return w.current_user.me().user_name
    except Exception:
        return "unknown_reviewer@wanderbricks.com"


def execute_query(query):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(query)
    if cursor.description:
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    return []


def execute_statement(statement):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(statement)


# Page Config
st.set_page_config(page_title="WBXAGT - Ticket Triage", page_icon="\U0001f3ab", layout="wide")

if "selected_ticket" not in st.session_state:
    st.session_state.selected_ticket = None


def render_queue_view():
    st.title("\U0001f3ab Wanderbricks Ticket Triage Queue")

    status_options = ["ALL", "NEW", "VALIDATED", "APPROVED", "REJECTED", "CLASSIFICATION_FAILED"]
    selected_status = st.selectbox("Filter by status", status_options)

    where_clause = ""
    if selected_status != "ALL":
        where_clause = "WHERE t.current_status = '{}'".format(selected_status)

    query = """
        SELECT t.ticket_id, t.current_status, t.current_intent,
               COUNT(CASE WHEN v.result != 'PASS' THEN 1 END) AS flag_count,
               t.updated_at
        FROM {schema}.tickets t
        LEFT JOIN {schema}.ticket_validation v ON t.ticket_id = v.ticket_id
        {where}
        GROUP BY t.ticket_id, t.current_status, t.current_intent, t.updated_at
        ORDER BY t.updated_at DESC
        LIMIT 100
    """.format(schema=SILVER_SCHEMA, where=where_clause)

    try:
        tickets = execute_query(query)
    except Exception as e:
        st.error("SQL Error: {}".format(e))
        return

    if not tickets:
        st.info("No tickets found.")
        return

    st.markdown("**{} tickets**".format(len(tickets)))

    for ticket in tickets:
        col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 1, 1])
        with col1:
            tid = ticket["ticket_id"]
            if st.button("\U0001f3ab {}".format(tid), key="btn_{}".format(tid)):
                st.session_state.selected_ticket = tid
                st.rerun()
        with col2:
            status = ticket["current_status"]
            icon = STATUS_ICONS.get(status, DEFAULT_ICON)
            st.write("{} {}".format(icon, status))
        with col3:
            st.write(ticket["current_intent"] or "\u2014")
        with col4:
            flags = ticket["flag_count"]
            if flags > 0:
                st.write("\u26a0\ufe0f {}".format(flags))
            else:
                st.write("\u2705 0")
        with col5:
            ts = ticket["updated_at"]
            st.write(str(ts)[:16] if ts else "")


def render_detail_view(ticket_id):
    st.title("\U0001f3ab Ticket: {}".format(ticket_id))

    if st.button("\u2190 Back to Queue"):
        st.session_state.selected_ticket = None
        st.rerun()

    # Messages
    st.subheader("\U0001f4ac Message Thread")
    messages = execute_query("""
        SELECT sender, message_text, sentiment, message_timestamp
        FROM {schema}.support_messages
        WHERE ticket_id = '{tid}'
        ORDER BY message_timestamp
    """.format(schema=SILVER_SCHEMA, tid=ticket_id))
    for msg in messages:
        icon = "\U0001f464" if msg["sender"] == "user" else "\U0001f9d1\u200d\U0001f4bb"
        st.markdown("**{} {}** ({}) \u2014 _{}_".format(
            icon, msg["sender"], msg["message_timestamp"], msg["sentiment"]))
        st.markdown("> {}".format(msg["message_text"]))
        st.divider()

    # Classification
    st.subheader("\U0001f50d Classification & Extracted Fields")
    classification = execute_query("""
        SELECT intent, extracted_booking_id, extracted_details_json,
               reasoning_summary, confidence, prompt_name, prompt_version, classified_at
        FROM {schema}.ticket_classification
        WHERE ticket_id = '{tid}'
        ORDER BY classified_at DESC LIMIT 1
    """.format(schema=SILVER_SCHEMA, tid=ticket_id))
    if classification:
        cls = classification[0]
        c1, c2, c3 = st.columns(3)
        c1.metric("Intent", cls["intent"])
        conf = cls["confidence"]
        c2.metric("Confidence", "{:.2f}".format(conf) if conf else "N/A")
        c3.metric("Booking ID", cls["extracted_booking_id"] or "Not found")
        st.markdown("**Reasoning:** {}".format(cls["reasoning_summary"]))
        if cls["extracted_details_json"]:
            try:
                st.json(json.loads(cls["extracted_details_json"]))
            except Exception:
                st.code(cls["extracted_details_json"])
    else:
        st.warning("No classification yet.")

    # Validations
    st.subheader("\u2705 Validation Results")
    validations = execute_query("""
        SELECT check_id, result, detail, checked_at
        FROM {schema}.ticket_validation
        WHERE ticket_id = '{tid}'
        ORDER BY check_id
    """.format(schema=SILVER_SCHEMA, tid=ticket_id))
    if validations:
        for v in validations:
            icon = RESULT_ICONS.get(v["result"], "\u2753")
            st.markdown("{} **{}** [{}]: {}".format(icon, v["check_id"], v["result"], v["detail"]))
    else:
        st.info("No validation results yet.")

    # Activity Log
    st.subheader("\U0001f4dd Activity Log")
    log_entries = execute_query("""
        SELECT event_type, detail, actor, occurred_at
        FROM {schema}.ticket_activity_log
        WHERE ticket_id = '{tid}'
        ORDER BY occurred_at
    """.format(schema=SILVER_SCHEMA, tid=ticket_id))
    for entry in log_entries:
        st.markdown("- **{}** | `{}` | {} _(by {})_".format(
            entry["occurred_at"], entry["event_type"], entry["detail"], entry["actor"]))

    # Approve/Reject
    st.subheader("\U0001f44d Reviewer Actions")
    ticket_info = execute_query("""
        SELECT current_status FROM {schema}.tickets WHERE ticket_id = '{tid}'
    """.format(schema=SILVER_SCHEMA, tid=ticket_id))
    current_status = ticket_info[0]["current_status"] if ticket_info else None

    if current_status == "VALIDATED":
        has_fail = any(v["result"] == "FAIL" for v in validations)
        col_a, col_r = st.columns(2)

        with col_a:
            st.markdown("#### Approve")
            override_reason = ""
            if has_fail:
                st.warning("FAIL validations present. Override reason required.")
                override_reason = st.text_area("Override reason (required)", key="override")
            if st.button("\u2705 Approve", disabled=(has_fail and not override_reason.strip()), type="primary"):
                reviewer = get_reviewer_email()
                execute_statement("""
                    UPDATE {schema}.tickets
                    SET current_status = 'APPROVED', assigned_reviewer = '{rev}',
                        updated_at = current_timestamp()
                    WHERE ticket_id = '{tid}'
                """.format(schema=SILVER_SCHEMA, rev=reviewer, tid=ticket_id))
                log_id = str(uuid.uuid4())
                execute_statement("""
                    INSERT INTO {schema}.ticket_activity_log
                    SELECT '{lid}', '{tid}', 'STATUS_CHANGE',
                           'Approved by reviewer', '{rev}', current_timestamp()
                """.format(schema=SILVER_SCHEMA, lid=log_id, tid=ticket_id, rev=reviewer))
                if override_reason.strip():
                    oid = str(uuid.uuid4())
                    reason_esc = override_reason.replace("'", "''")
                    execute_statement("""
                        INSERT INTO {schema}.ticket_activity_log
                        SELECT '{oid}', '{tid}', 'OVERRIDE',
                               '{reason}', '{rev}', current_timestamp()
                    """.format(schema=SILVER_SCHEMA, oid=oid, tid=ticket_id, reason=reason_esc, rev=reviewer))
                st.success("Ticket APPROVED")
                st.rerun()

        with col_r:
            st.markdown("#### Reject")
            rejection_note = st.text_area("Rejection note (optional)", key="reject_note")
            if st.button("\u274c Reject", type="secondary"):
                reviewer = get_reviewer_email()
                detail_text = "Rejected by reviewer"
                if rejection_note.strip():
                    detail_text += ": {}".format(rejection_note.strip())
                detail_esc = detail_text.replace("'", "''")
                execute_statement("""
                    UPDATE {schema}.tickets
                    SET current_status = 'REJECTED', assigned_reviewer = '{rev}',
                        updated_at = current_timestamp()
                    WHERE ticket_id = '{tid}'
                """.format(schema=SILVER_SCHEMA, rev=reviewer, tid=ticket_id))
                rid = str(uuid.uuid4())
                execute_statement("""
                    INSERT INTO {schema}.ticket_activity_log
                    SELECT '{rid}', '{tid}', 'STATUS_CHANGE',
                           '{detail}', '{rev}', current_timestamp()
                """.format(schema=SILVER_SCHEMA, rid=rid, tid=ticket_id, detail=detail_esc, rev=reviewer))
                st.success("Ticket REJECTED")
                st.rerun()
    elif current_status in ("APPROVED", "REJECTED"):
        st.info("Ticket already {}.".format(current_status.lower()))
    else:
        st.info("Status is '{}' \u2014 not ready for review.".format(current_status))


# Main Router
if st.session_state.selected_ticket:
    render_detail_view(st.session_state.selected_ticket)
else:
    render_queue_view()
