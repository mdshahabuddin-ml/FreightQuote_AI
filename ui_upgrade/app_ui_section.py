# ---------------- UI ----------------
# Enterprise UI (fq_ui.py). All authentication logic above is unchanged.

import fq_ui

ss = st.session_state
ss.setdefault("user", None)
ss.setdefault("flash", None)
ss.setdefault("auth_mode", "Sign In")

fq_ui.inject_base_css()


def _sign_out():
    for key in ("user", "fq_page", "fq_copilot_history", "fq_pending_q", "customer_view",
                "selected_login_role", "otp_email", "otp_verified_email"):
        ss.pop(key, None)
    ss.user = None
    ss.auth_mode = "Sign In"


# ---- Signed-in view ----
if ss.user:
    if ss.flash:
        st.toast(ss.flash)
        ss.flash = None
    fq_ui.render_app(ss.user, db_path=DB_PATH, on_sign_out=_sign_out)
    st.stop()


# ---- Signed-out view (Sign In / Register / Forgot Password) ----
if ss.get("next_mode"):
    ss.auth_mode = ss.pop("next_mode")
mode = ss.auth_mode


def _set_mode(new_mode):
    ss.auth_mode = new_mode


fq_ui.inject_login_css(mode)

# Phase 1 RBAC: the selected workspace must match the account's database role.
ROLE_ALIASES = {
    "admin": "admin",
    "operations manager": "operations manager",
    "freight broker": "freight broker",
    "auditor": "auditor",
    "customer": "customer",
}

with st.container(key="fq_login"):
    hero_col, form_col = st.columns([1.08, 1], gap=None)
    with hero_col:
        fq_ui.render_login_hero()
    with form_col:
        with st.container(key="fq_auth_panel"):
            fq_ui.render_auth_header(mode)

            if ss.flash:
                st.success(ss.flash)
                ss.flash = None

            # ---- Sign In ----
            if mode == "Sign In":
                with st.form("signin_form", border=False):
                    identity = st.text_input("Email or username", max_chars=254)
                    password = st.text_input("Password", type="password",
                                             max_chars=MAX_PASSWORD_LENGTH)
                    st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)
                    c_submit, c_links = st.columns([1, 2.2], vertical_alignment="center")
                    with c_submit:
                        submit = st.form_submit_button("Sign in", type="primary")
                    with c_links:
                        with st.container(horizontal=True, horizontal_alignment="right",
                                          key="fq_auth_links"):
                            st.form_submit_button("Register", type="tertiary",
                                                  on_click=_set_mode, args=("Register",))
                            st.form_submit_button("Forgot password", type="tertiary",
                                                  on_click=_set_mode, args=("Forgot Password",))

                if submit and ss.auth_mode == "Sign In":
                    user, error = authenticate(identity, password)
                    if user:
                        selected_role = ss.get("selected_login_role")
                        actual_role = str(user["role"]).strip().casefold()
                        expected_role = ROLE_ALIASES.get(
                            str(selected_role).strip().casefold()) if selected_role else None
                        verified_role = ROLE_ALIASES.get(actual_role)

                        if expected_role is None:
                            st.warning("Please select a workspace before signing in.")
                        elif verified_role is None:
                            st.error("Your account has an unrecognized role. "
                                     "Please contact an administrator.")
                        elif expected_role != verified_role:
                            st.error(f"Access denied: this account is assigned the "
                                     f"{user['role']} role, not {selected_role}. "
                                     "Select the workspace assigned to your account.")
                        else:
                            ss.user = {"id": user["id"], "username": user["username"],
                                       "email": user["email"], "role": user["role"]}
                            st.rerun()
                    else:
                        st.error(error)

                fq_ui.render_role_chips(ss.get("selected_login_role"))

            # ---- Register ----
            elif mode == "Register":
                with st.form("register_form", clear_on_submit=False, border=False):
                    username = st.text_input("Username", max_chars=50)
                    email = st.text_input("Email address", max_chars=254)
                    password = st.text_input("Password", type="password",
                                             max_chars=MAX_PASSWORD_LENGTH)
                    confirm = st.text_input("Confirm password", type="password",
                                            max_chars=MAX_PASSWORD_LENGTH)
                    st.markdown('<div class="fq-auth-heading" style="font-size:13px">Security questions'
                                ' <span style="font-weight:400;color:#6b7280">(used to reset your '
                                'password)</span></div>', unsafe_allow_html=True)
                    reg_answers = [
                        st.text_input(question, max_chars=100, key=f"reg_{column}")
                        for column, question in SECURITY_QUESTIONS
                    ]
                    c_submit, c_links = st.columns([1, 1.4], vertical_alignment="center")
                    with c_submit:
                        submit = st.form_submit_button("Create account", type="primary")
                    with c_links:
                        with st.container(horizontal=True, horizontal_alignment="right",
                                          key="fq_auth_links"):
                            st.form_submit_button("Back to sign in", type="tertiary",
                                                  on_click=_set_mode, args=("Sign In",))

                if submit and ss.auth_mode == "Register":
                    ok, msg = register_user(username, email, password, confirm, reg_answers)
                    if ok:
                        ss.flash = msg
                        ss.next_mode = "Sign In"
                        st.rerun()
                    else:
                        st.error(msg)

            # ---- Forgot Password ----
            else:
                method = st.radio("Reset method", ["Security questions", "Email OTP"],
                                  horizontal=True, key="reset_method",
                                  label_visibility="collapsed")

                # -- Method 1: security questions --
                if method == "Security questions":
                    with st.form("reset_answers_form", border=False):
                        identity = st.text_input("Email or username", max_chars=254)
                        reset_answers = [
                            st.text_input(question, max_chars=100, key=f"reset_{column}")
                            for column, question in SECURITY_QUESTIONS
                        ]
                        new_password = st.text_input("New password", type="password",
                                                     max_chars=MAX_PASSWORD_LENGTH, key="qa_new_pw")
                        confirm_password = st.text_input("Confirm new password", type="password",
                                                         max_chars=MAX_PASSWORD_LENGTH,
                                                         key="qa_confirm_pw")
                        change = st.form_submit_button("Reset password", type="primary")

                    if change:
                        ok, msg = reset_with_answers(identity, reset_answers, new_password,
                                                     confirm_password)
                        if ok:
                            ss.flash = msg
                            ss.next_mode = "Sign In"
                            st.rerun()
                        else:
                            st.error(msg)

                # -- Method 2: email OTP --
                else:
                    with st.form("request_otp_form", border=False):
                        email = st.text_input("Registered email address", max_chars=254)
                        send = st.form_submit_button("Send OTP", type="primary")

                    if send:
                        email = normalize_email(email)
                        if not EMAIL_RE.fullmatch(email):
                            st.error("Enter a valid email address.")
                        else:
                            try:
                                ok, msg = request_otp(email)
                                if ok:
                                    ss.otp_email = email
                                    ss.pop("otp_verified_email", None)
                                    st.success(msg)
                                else:
                                    st.warning(msg)
                            except Exception as exc:
                                st.error("Email delivery failed. Check SMTP_EMAIL / SMTP_APP_PASSWORD, "
                                         "or use the Security questions option.")
                                print("SMTP error:", type(exc).__name__, str(exc)[:200])

                    reset_email = ss.get("otp_email")

                    if reset_email and ss.get("otp_verified_email") != reset_email:
                        st.caption(f"OTP requested for: {reset_email}")
                        with st.form("verify_otp_form", border=False):
                            otp = st.text_input("6-digit OTP", max_chars=6)
                            verify = st.form_submit_button("Verify OTP")
                        if verify:
                            ok, msg = verify_otp(reset_email, otp)
                            if ok:
                                ss.otp_verified_email = reset_email
                                st.rerun()
                            else:
                                st.error(msg)

                    if reset_email and ss.get("otp_verified_email") == reset_email:
                        st.success("OTP verified. Set your new password.")
                        with st.form("reset_password_form", border=False):
                            new_password = st.text_input("New password", type="password",
                                                         max_chars=MAX_PASSWORD_LENGTH,
                                                         key="otp_new_pw")
                            confirm_password = st.text_input("Confirm new password", type="password",
                                                             max_chars=MAX_PASSWORD_LENGTH,
                                                             key="otp_confirm_pw")
                            change = st.form_submit_button("Reset password", type="primary")
                        if change:
                            ok, msg = reset_password(reset_email, new_password, confirm_password)
                            if ok:
                                ss.pop("otp_email", None)
                                ss.pop("otp_verified_email", None)
                                ss.flash = msg
                                ss.next_mode = "Sign In"
                                st.rerun()
                            else:
                                st.error(msg)

                st.button("Back to sign in", type="tertiary", key="fq_back_signin",
                          on_click=_set_mode, args=("Sign In",))
