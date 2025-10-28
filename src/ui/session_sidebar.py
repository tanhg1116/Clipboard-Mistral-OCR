from __future__ import annotations

from typing import Dict

import streamlit as st

from src.services.state import create_session, delete_session, duplicate_session, get_active_session_id, set_active, Session


def render_session_sidebar() -> str:
    sessions: Dict[str, Session] = st.session_state["sessions"]

    with st.sidebar:
        st.header("Sessions")
        if st.button("New OCR Session", use_container_width=True):
            create_session()

        for sid, s in list(sessions.items()):
            # Track rename mode per-session
            rename_flag_key = f"rename_mode_{sid}"
            if rename_flag_key not in st.session_state:
                st.session_state[rename_flag_key] = False

            cols = st.columns([7, 1, 1, 1])
            with cols[0]:
                if st.session_state[rename_flag_key]:
                    # Wide, readable input; submit with Enter; cancel when empty or on blur via an auxiliary button
                    new = st.text_input(
                        "",
                        value=s.title,
                        key=f"rename_input_{sid}",
                        label_visibility="collapsed",
                        placeholder="Rename session",
                    )
                    c_a, c_b = st.columns([1, 1])
                    with c_a:
                        if st.button("Save", key=f"rename_save_{sid}"):
                            s.title = new.strip() or s.title
                            st.session_state[rename_flag_key] = False
                    with c_b:
                        if st.button("Cancel", key=f"rename_cancel_{sid}"):
                            st.session_state[rename_flag_key] = False
                else:
                    label = s.title
                    if st.session_state.get("active_session_id") == sid:
                        label = f"▶ {label}"
                    if st.button(label, key=f"select_{sid}", use_container_width=True, help="Activate this session"):
                        set_active(sid)
            with cols[1]:
                if st.button("✎", key=f"rename_{sid}", help="Rename session"):
                    st.session_state[rename_flag_key] = True
            with cols[2]:
                if st.button("⎘", key=f"dup_{sid}", help="Duplicate session"):
                    duplicate_session(sid)
            with cols[3]:
                if st.button("🗑", key=f"del_{sid}", help="Delete session"):
                    delete_session(sid)

    return get_active_session_id()
