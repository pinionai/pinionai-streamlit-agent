"""Customer session history in the sidebar of the Streamlit chat apps (chat.py, chat_one_time_load.py).

The agent's "Session Login" setting decides what is offered: nothing ("none"), a password sign-in with
sign-up ("password"), or a texted code ("phone_otp"). Signed in, the customer can list, resume and sign out.
Every client method is looked up before it is used, so the apps also run on older pinionai releases.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

import streamlit as st

logger = logging.getLogger(__name__)

_NOTICES = "customer_history_notices"
Runner = Callable[[Coroutine[Any, Any, Any]], Any]


def _notice(kind: str, text: str) -> None:
    """Queues a message for the next run: one written just before st.rerun() is never seen."""
    st.session_state.setdefault(_NOTICES, []).append((kind, text))


def _show_notices() -> None:
    for kind, text in st.session_state.pop(_NOTICES, []):
        getattr(st, kind, st.info)(text)


def sign_in_type(client: Any) -> str:
    """The agent's customer sign-in method; an agent copy without one offers no sign-in."""
    return (getattr(client, "var", None) or {}).get("resumeSessionAuthType") or "none"


async def retire_client(old_client: Any) -> None:
    """Ends the conversation that a resumed one replaces. A live agent on it is told the customer left,
    as End Chat does, and the client is closed even when ending the live-agent connection fails."""
    try:
        if hasattr(old_client, "end_grpc_chat_session"):
            await old_client.end_grpc_chat_session(send_goodbye=bool(getattr(old_client, "transfer_requested", "")))
    except Exception as e:
        logger.warning("Could not end the live-agent connection of the replaced conversation: %s", e)
    finally:
        if hasattr(old_client, "close"):
            await old_client.close()


def _load_sessions(client: Any, run: Runner) -> None:
    if hasattr(client, "list_customer_sessions"):
        st.session_state.customer_sessions = run(client.list_customer_sessions())


def _finish_sign_in(client: Any, run: Runner, success: str) -> None:
    try:
        _load_sessions(client, run)
    except Exception as e:
        _notice("warning", f"Previous sessions could not be loaded: {e}")
    st.session_state.clear_customer_password = True
    _notice("success", success)


def _signed_in(client: Any, run: Runner) -> None:
    st.caption("Signed in. Only sessions linked to this customer are listed.")
    if st.button("Refresh sessions", key="refresh_customer_sessions"):
        try:
            _load_sessions(client, run)
        except Exception as e:
            if getattr(client, "_customer_access_token", None):
                st.error(f"Could not load previous sessions: {e}")
            else:
                _notice("info", "Your sign-in has expired. Sign in again to see your sessions.")
                st.session_state.customer_sessions = []
                st.rerun()
    sessions = [session for session in st.session_state.customer_sessions if session.get("uid")]
    if sessions:
        by_uid = {session["uid"]: session for session in sessions}
        session_uid = st.selectbox(
            "Previous session",
            options=list(by_uid),
            format_func=lambda uid: f"{by_uid[uid].get('name') or 'Untitled session'} — {uid}",
            key="customer_session_uid",
        )
        selected = by_uid.get(session_uid) or {}
        if selected.get("summary"):
            st.caption(selected["summary"])
        if st.button("Resume selected session", key="resume_customer_session"):
            if not hasattr(client, "resume_customer_session"):
                st.error("Resuming customer sessions is not supported by the current client library.")
            else:
                restored = None
                try:
                    with st.spinner("Restoring conversation..."):
                        restored = run(client.resume_customer_session(session_uid))
                except Exception as e:
                    st.error(f"Could not resume session: {e}")
                if restored is not None:
                    st.session_state.pinion_client = restored
                    st.session_state.end_chat_clicked = False  # an ended chat can be followed by a resumed one
                    run(retire_client(client))
                    st.rerun()
    if st.button("Sign out", key="customer_sign_out"):
        try:
            if hasattr(client, "logout_customer"):
                run(client.logout_customer())
        except Exception as e:
            logger.warning("Customer sign-out was not confirmed: %s", e)
        if getattr(client, "_customer_access_token", None):
            client._customer_access_token = None  # older client libraries keep a token the API has rejected
        st.session_state.customer_sessions = []
        _notice("info", "Signed out. This conversation stays in your customer history.")
        st.rerun()


def _password_sign_in(client: Any, run: Runner) -> None:
    can_sign_up = hasattr(client, "register_customer")
    tabs = st.tabs(["Sign In", "Sign Up"]) if can_sign_up else [st.container()]
    with tabs[0]:
        with st.form("customer_sign_in_form"):
            identifier = st.text_input("Phone, email or ID", key="customer_identifier")
            password = st.text_input("Password", type="password", key="customer_password")
            sign_in = st.form_submit_button("Sign in")
        if sign_in:
            signed_in = False
            try:
                with st.spinner("Signing in..."):
                    run(client.login_customer(identifier, password))
                signed_in = True
            except Exception as e:
                st.error(f"Could not sign in: {e}")
            if signed_in:
                _finish_sign_in(client, run, "Signed in. This active conversation is now linked to your customer account.")
                st.rerun()
    if can_sign_up:
        with tabs[1]:
            with st.form("customer_sign_up_form"):
                reg_identifier = st.text_input("Phone or email", key="customer_signup_identifier")
                reg_password = st.text_input("Password", type="password", key="customer_signup_password")
                reg_first = st.text_input("First name", key="customer_signup_first")
                reg_last = st.text_input("Last name", key="customer_signup_last")
                sign_up = st.form_submit_button("Sign up")
            if sign_up:
                signed_up = False
                try:
                    with st.spinner("Creating account..."):
                        run(client.register_customer(reg_identifier, reg_password, first_name=reg_first, last_name=reg_last))
                    signed_up = True
                except Exception as e:
                    st.error(f"Could not sign up: {e}")
                if signed_up:
                    _finish_sign_in(client, run, "Signed in. This active conversation is now linked to your customer account.")
                    st.rerun()


def _phone_sign_in(client: Any, run: Runner) -> None:
    challenge_id = st.session_state.get("customer_otp_challenge_id")
    if challenge_id:
        with st.form("customer_otp_verify_form"):
            code = st.text_input("Verification code", type="password", max_chars=6)
            verify_code = st.form_submit_button("Verify code")
        if verify_code:
            verified = False
            try:
                with st.spinner("Verifying code..."):
                    run(client.verify_customer_otp(challenge_id, code))
                verified = True
            except Exception as e:
                st.error(f"Could not verify phone sign-in: {e}")
            if verified:
                st.session_state.pop("customer_otp_challenge_id", None)
                _finish_sign_in(client, run, "Signed in. This active conversation is now linked to your customer account.")
                st.rerun()
        if st.button("Request another code", key="request_another_customer_otp"):
            st.session_state.pop("customer_otp_challenge_id", None)
            st.rerun()
        return

    can_sign_up = hasattr(client, "register_customer_otp")
    tabs = st.tabs(["Sign In", "Sign Up"]) if can_sign_up else [st.container()]
    with tabs[0]:
        with st.form("customer_otp_request_form"):
            phone = st.text_input("Saved phone number", placeholder="+15551234567")
            request_code = st.form_submit_button("Send verification code")
        if request_code:
            requested = None
            try:
                with st.spinner("Requesting verification code..."):
                    requested = run(client.request_customer_otp(phone))
            except Exception as e:
                st.error(f"Could not request phone sign-in: {e}")
            if requested:
                st.session_state.customer_otp_challenge_id = requested
                _notice("info", "If the phone number is eligible, a verification code has been sent.")
                st.rerun()
    if can_sign_up:
        with tabs[1]:
            with st.form("customer_otp_register_form"):
                reg_phone = st.text_input("Phone number", placeholder="+15551234567", key="customer_otp_reg_phone")
                reg_first = st.text_input("First name", key="customer_otp_reg_first")
                reg_last = st.text_input("Last name", key="customer_otp_reg_last")
                register_code = st.form_submit_button("Sign up with phone")
            if register_code:
                requested = None
                try:
                    with st.spinner("Sending verification code..."):
                        requested = run(client.register_customer_otp(reg_phone, first_name=reg_first, last_name=reg_last))
                except Exception as e:
                    st.error(f"Could not register phone: {e}")
                if requested:
                    st.session_state.customer_otp_challenge_id = requested
                    _notice("info", "Verification code has been sent.")
                    st.rerun()


def render_customer_history(client: Any, run: Runner) -> None:
    """The sidebar's "Conversation history" section for the active client."""
    st.session_state.setdefault("customer_sessions", [])
    if st.session_state.pop("clear_customer_password", False):
        st.session_state["customer_password"] = ""
        st.session_state["customer_signup_password"] = ""
    with st.sidebar:
        st.subheader("Conversation history")
        _show_notices()
        if getattr(client, "_customer_access_token", None):
            _signed_in(client, run)
            return
        auth_type = sign_in_type(client)
        if auth_type == "phone_otp":
            if hasattr(client, "request_customer_otp") and hasattr(client, "verify_customer_otp"):
                _phone_sign_in(client, run)
            else:
                st.info("Customer authentication is not supported by the current client library.")
        elif auth_type == "password":
            if hasattr(client, "login_customer"):
                _password_sign_in(client, run)
            else:
                st.info("Customer authentication is not supported by the current client library.")
        else:
            st.info("Customer session history sign-in is disabled for this agent.")
