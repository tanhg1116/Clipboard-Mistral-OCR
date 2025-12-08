from __future__ import annotations

import io
import os
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import asdict
from typing import Dict, Optional

import streamlit as st

from src.services.state import ensure_app_state, Session
from src.ui.session_sidebar import render_session_sidebar
from src.ui.main_panes import render_main_panes
from src.services.exporter import start_export_job, get_job_status, cancel_export_job


# Single global executor for background tasks (exports)
_executor: Optional[ThreadPoolExecutor] = None


def get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="exporter")
    return _executor


# No API key UI; key is loaded from .env by the client


def main() -> None:
    st.set_page_config(page_title="Mistral OCR", layout="wide", initial_sidebar_state="expanded")
    
    # Custom CSS to reduce top padding moderately
    st.markdown("""
        <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 0rem;
        }
        h1, h2, h3 {
            margin-top: 0.5rem;
            margin-bottom: 0.5rem;
        }
        </style>
    """, unsafe_allow_html=True)

    ensure_app_state()

    # Sidebar: session list and actions
    active_session_id = render_session_sidebar()
    session: Session = st.session_state["sessions"][active_session_id]

    # Session title only (compact)
    st.markdown(f"## {session.title}")

    # Main panes with export button passed down
    render_main_panes(session, active_session_id, get_executor())


if __name__ == "__main__":
    main()
