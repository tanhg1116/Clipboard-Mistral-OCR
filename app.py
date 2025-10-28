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
    st.set_page_config(page_title="Mistral OCR", layout="wide")
    # Sidebar left is used by session sidebar only

    ensure_app_state()

    # Sidebar: session list and actions
    active_session_id = render_session_sidebar()
    session: Session = st.session_state["sessions"][active_session_id]

    # No user-configurable OCR URL/model

    # Top bar: export controls
    st.subheader(session.title)
    exp_col1, exp_col2, exp_col3, exp_col4 = st.columns([2,2,2,2])
    with exp_col1:
        page_range = st.text_input("Export page range (e.g., 1-3,5,9-10)", value="all", key=f"range_{active_session_id}")
    with exp_col2:
        export_pdf = st.button("Export PDF", key=f"exp_pdf_{active_session_id}")
    with exp_col3:
        export_md = st.button("Export .md", key=f"exp_md_{active_session_id}")
    with exp_col4:
        cancel = st.button("Cancel export", key=f"cancel_{active_session_id}")

    if export_pdf or export_md:
        fmt = "pdf" if export_pdf else "md"
        try:
            job_id = start_export_job(get_executor(), active_session_id, page_range, fmt)
        except ValueError as exc:
            st.warning(str(exc))
        else:
            st.toast(f"Started {fmt.upper()} export: {job_id}")

    if cancel:
        cancel_export_job(active_session_id)
        st.toast("Export cancelled")
        

    # Show export job status
    job = get_job_status(active_session_id)
    if job and job.status in {"running", "queued"}:
        st.info(f"Export: {job.status} – {job.progress}% – {job.stage}")
        st.progress(job.progress / 100.0)
        # Gentle polling using sleep then rerun
        import time as _t
        _t.sleep(2)
        st.rerun()
    elif job and job.status == "done":
        file_name = job.output_name
        if job.output_bytes is not None:
            mime = "application/pdf" if job.format == "pdf" else "text/markdown"
            st.download_button(
                label=f"Download {file_name}",
                data=job.output_bytes,
                file_name=file_name,
                mime=mime,
                use_container_width=True,
                key=f"dl_{active_session_id}_{file_name}",
            )
        else:
            st.error("Export finished but no data present.")

    # Main panes
    render_main_panes(session)


if __name__ == "__main__":
    main()
