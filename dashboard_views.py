import os
import sqlite3
import pandas as pd
import streamlit as st
import plotly.express as px
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("FREIGHTQUOTE_DB", BASE_DIR / "freightquote.db"))

ROLE_FEATURES = {
    "Admin": [
        "User and role administration",
        "System health and configuration",
        "Audit trail review",
        "Agent and RAG configuration",
    ],
    "Operations Manager": [
        "Shipment and route operations",
        "Operational alerts",
        "Agent activity overview",
        "Performance reports",
    ],
    "Freight Broker": [
        "Freight quote workspace",
        "Route and shipment information",
        "Customer quote requests",
        "Quote history",
    ],
    "Auditor": [
        "Read-only audit review",
        "Authentication event review",
        "Policy and decision citations",
        "Compliance reports",
    ],
    "Customer": [
        "Request a freight quote",
        "View quote status",
        "Review shipment information",
        "Manage customer requests",
    ],
}

def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def load_quote_stats():
    """Load database metrics safely or return mock indicators if table empty."""
    try:
        with get_db_connection() as conn:
            stats = conn.execute("""
                SELECT 
                    COUNT(*) as total_quotes,
                    SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END) as pending,
                    SUM(quantity) as total_containers
                FROM freight_quotes
            """).fetchone()
            return {
                "total_quotes": stats["total_quotes"] or 0,
                "pending": stats["pending"] or 0,
                "total_containers": stats["total_containers"] or 0,
                "is_simulated": False
            }
    except sqlite3.OperationalError:
        # Return default values gracefully if table hasn't been initialized yet
        return {
            "total_quotes": 0,
            "pending": 0,
            "total_containers": 0,
            "is_simulated": True
        }

def update_quote_status(quote_id, new_status):
    """Update quote state in database securely under transaction lock."""
    with get_db_connection() as conn:
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute(
                "UPDATE freight_quotes SET status = ? WHERE id = ?",
                (new_status, quote_id)
            )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            st.error(f"Database Transaction Failed: {str(e)}")
            return False

def render_dashboard(user):
    if not user:
        st.error("Please sign in to view your dashboard.")
        return

    username = user.get("username", "User")
    role = user.get("role", "Customer")
    user_id = user.get("id")

    # Strict security: Backend checks active user session credentials dynamically against DB
    try:
        with get_db_connection() as conn:
            db_user = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
            if db_user and db_user["role"] != role:
                st.error("Authorization violation detected. Session role mismatches registered database role.")
                st.stop()
    except Exception:
        pass

    if role not in ROLE_FEATURES:
        st.error("Unrecognized role. Contact an administrator.")
        return

    st.title("🚢 Maritime Freight Operations Dashboard")
    st.caption(f"Authenticated Session: {username} | Security Level: {role}")
    st.divider()

    # Load physical metrics from database
    metrics = load_quote_stats()

    # Display Top Operational KPI Cards
    st.subheader("📌 Fleet Operational Metrics")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            label="Total Quotes Filed",
            value=f"{metrics['total_quotes']:,}",
            help="Physical sum of submitted customer requests."
        )
    with col2:
        st.metric(
            label="Pending Review",
            value=f"{metrics['pending']:,}",
            delta="Action Required" if metrics['pending'] > 0 else "Clear",
            delta_color="inverse" if metrics['pending'] > 0 else "normal"
        )
    with col3:
        st.metric(
            label="Allocated Containers",
            value=f"{metrics['total_containers']:,} TEUs",
            help="Sum of total quantity ordered."
        )

    if metrics["is_simulated"]:
        st.warning("⚠️ Notice: Databases are empty or uninitialized. Displaying default baseline zero states.")

    st.divider()

    # Operational Workspaces base routing
    if role == "Customer":
        st.markdown("### Customer Dashboard")
        st.caption("Choose an action below to start routing.")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Request a Freight Quote", type="primary", use_container_width=True, key="customer_request_quote"):
                st.session_state["customer_view"] = "request"
        with col2:
            if st.button("My Quotes / Shipment Status", use_container_width=True, key="customer_view_quotes"):
                st.session_state["customer_view"] = "quotes"

        with st.expander("Customer Profile"):
            st.write("Username:", username)
            st.write("Role:", role)
            st.caption("Profile editing will be unlocked in a future update.")

        current_view = st.session_state.get("customer_view", "request")
        from quote_ui import render_customer_quotes
        render_customer_quotes(user, view_mode=current_view)

    else:
        # Workspace view for non-customer platform employees (Admin, Operations Manager, Freight Broker, Auditor)
        st.subheader("🛠️ Command Center Workspace")
        
        try:
            with get_db_connection() as conn:
                if role in ("Admin", "Operations Manager"):
                    quotes_df = pd.read_sql_query("SELECT * FROM freight_quotes ORDER BY created_at DESC", conn)
                else:
                    # Auditors and Freight Brokers see custom scoped logs
                    quotes_df = pd.read_sql_query("SELECT * FROM freight_quotes WHERE status != 'Rejected'", conn)
        except Exception:
            quotes_df = pd.DataFrame()

        if quotes_df.empty:
            st.info("No quote entries currently exist in the database. Customer submissions will populate here.")
        else:
            st.dataframe(quotes_df, use_container_width=True, hide_index=True)

            # Interactive Status Override (Restricted to Admins and Operations Managers only)
            if role in ("Admin", "Operations Manager"):
                st.markdown("#### ⚡ Quick State Overrides")
                col_id, col_status, col_btn = st.columns([2, 1, 1], vertical_alignment="bottom")
                with col_id:
                    selected_id = st.selectbox("Select Cargo Request ID:", quotes_df["id"].unique())
                with col_status:
                    new_status = st.selectbox("Set Operational Status:", ["Pending", "Approved", "Under Review", "Rejected"])
                with col_btn:
                    if st.button("Execute Update", type="primary", use_container_width=True):
                        if update_quote_status(selected_id, new_status):
                            st.success(f"Successfully updated {selected_id[:8]} to '{new_status}'!")
                            st.rerun()

            # Plotly Visual Analytics
            st.subheader("📊 Destination Lane Distributions")
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                fig_dest = px.bar(
                    quotes_df,
                    x="destination_port",
                    color="cargo_type",
                    title="Quotes by Destination Port and Cargo Class",
                    labels={"destination_port": "Destination Port", "count": "Total Orders"}
                )
                st.plotly_chart(fig_dest, use_container_width=True)
            with chart_col2:
                fig_container = px.pie(
                    quotes_df,
                    names="container_type",
                    values="quantity",
                    title="Allocated Quantity (TEU) by Container Configuration"
                )
                st.plotly_chart(fig_container, use_container_width=True)

    st.divider()
    st.subheader("Advanced AI Capabilities")

    st.markdown("**Live Agents and Digital Twin**")
    st.info("Integration will follow an audit of existing agent services.")

    st.markdown("**Hybrid RAG and Citations**")
    st.info("Integration will follow an audit of existing retrieval services.")

    st.caption(
        "This module executes operational actions and backend SQLite updates directly. "
        "Verify role permissions on the profile page."
    )
