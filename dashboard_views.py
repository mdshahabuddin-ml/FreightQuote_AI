import streamlit as st

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

def render_dashboard(user):
    if not user:
        st.error("Please sign in to view your dashboard.")
        return

    username = user.get("username", "User")
    role = user.get("role", "Customer")

    if role not in ROLE_FEATURES:
        st.error("Unrecognized role. Contact an administrator.")
        return

    st.title("FreightQuote AI Dashboard")
    st.caption(f"Signed in as {username} | Role: {role}")
    st.divider()

    st.subheader(f"Welcome, {username}")

    if role == "Customer":
        st.markdown("### Customer Dashboard")
        st.caption("Choose an action to continue.")

        col1, col2 = st.columns(2)

        with col1:
            if st.button(
                "Request a Freight Quote",
                type="primary",
                use_container_width=True,
                key="customer_request_quote",
            ):
                st.session_state["customer_view"] = "request"

        with col2:
            if st.button(
                "My Quotes / Shipment Status",
                use_container_width=True,
                key="customer_view_quotes",
            ):
                st.session_state["customer_view"] = "quotes"

        with st.expander("Customer Profile"):
            st.write("Username:", username)
            st.write("Role:", role)
            st.caption("Profile editing will be implemented in a later step.")

        current_view = st.session_state.get("customer_view", "request")
        from quote_ui import render_customer_quotes
        render_customer_quotes(user, view_mode=current_view)

    else:
        st.markdown("### Your workspace")
        columns = st.columns(2)
        for index, feature in enumerate(ROLE_FEATURES[role]):
            with columns[index % 2]:
                with st.container(border=True):
                    st.markdown(f"**{feature}**")
                    st.caption("Implementation scheduled in the next phase.")

    st.divider()
    st.subheader("Advanced AI Capabilities")

    st.markdown("**Live Agents and Digital Twin**")
    st.info("Integration will follow an audit of existing agent services.")

    st.markdown("**Hybrid RAG and Citations**")
    st.info("Integration will follow an audit of existing retrieval services.")

    st.caption(
        "Dashboard UI scaffold only. Operational actions and backend "
        "authorization are not implemented in this module."
    )
