import streamlit as st
from datetime import date

from quote_service import (
    init_quotes_table,
    create_quote,
    list_my_quotes,
    VALID_CARGO_TYPES,
    VALID_CONTAINER_TYPES,
)


def render_customer_quotes(user, view_mode='request'):
    if not user or not user.get("id"):
        st.error("Please sign in first.")
        return

    init_quotes_table()

    if view_mode == 'request':
        st.header("Request a Freight Quote")
        st.caption("Enter your shipment details to submit a quote request.")

        with st.form("customer_freight_quote_form"):
            col1, col2 = st.columns(2)

            with col1:
                origin = st.text_input(
                    "Origin port",
                    placeholder="e.g. Mumbai",
                    max_chars=100,
                )
                cargo = st.selectbox(
                    "Cargo type",
                    sorted(VALID_CARGO_TYPES),
                )
                quantity = st.number_input(
                    "Number of containers / units",
                    min_value=1,
                    max_value=10000,
                    value=1,
                    step=1,
                )

            with col2:
                destination = st.text_input(
                    "Destination port",
                    placeholder="e.g. Singapore",
                    max_chars=100,
                )
                container = st.selectbox(
                    "Container type",
                    sorted(VALID_CONTAINER_TYPES),
                )
                shipment_date = st.date_input(
                    "Planned shipment date",
                    min_value=date.today(),
                    value=date.today(),
                )

            notes = st.text_area(
                "Additional shipment details (optional)",
                max_chars=1000,
            )

            submitted = st.form_submit_button(
                "Submit Freight Quote Request",
                type="primary",
                use_container_width=True,
            )

        if submitted:
            try:
                quote_id = create_quote(
                    user=user,
                    origin_port=origin,
                    destination_port=destination,
                    cargo_type=cargo,
                    container_type=container,
                    quantity=int(quantity),
                    shipment_date=shipment_date.isoformat(),
                    notes=notes,
                )
                st.success("Quote request submitted successfully.")
                st.code(quote_id, language=None)
                st.info(
                    "Status: Pending. This is a request record, "
                    "not a confirmed price or booking."
                )
            except (ValueError, TypeError) as exc:
                st.error(str(exc))
            except Exception as exc:
                # Do not display database paths or internal exception details.
                st.error(
                    "The quote could not be saved. "
                    "Check the application logs for details."
                )
                print("Quote submission error:", type(exc).__name__)

    if view_mode == 'quotes':
        st.divider()
        st.subheader("My Quote Requests")

        try:
            quotes = list_my_quotes(user)

            if not quotes:
                st.info("You have not submitted any quote requests yet.")
            else:
                for quote in quotes:
                    with st.container(border=True):
                        st.markdown(
                            f"**{quote['origin_port']} → "
                            f"{quote['destination_port']}**"
                        )
                        st.write("Request ID:", quote["id"])
                        st.write("Status:", quote["status"])
                        st.write("Cargo:", quote["cargo_type"])
                        st.write("Container:", quote["container_type"])
                        st.write("Quantity:", quote["quantity"])
                        st.write("Shipment date:", quote["shipment_date"])
                        if quote["notes"]:
                            st.write("Notes:", quote["notes"])

        except Exception as exc:
            st.error("Could not load quote requests. Check the application logs.")
            print("Quote retrieval error:", type(exc).__name__)
