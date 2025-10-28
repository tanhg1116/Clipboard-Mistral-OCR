from __future__ import annotations

import io
import hashlib
from concurrent.futures import ThreadPoolExecutor
import time
import pyperclip
import streamlit as st
from PIL import Image, ImageGrab

from src.services.state import Session, OcrEntry, SessionFile, get_active_file
from src.services.cache import (
    read_memo_markdown,
    set_cached_markdown,
    invalidate_markdown,
)
from src.mistral_client import (
    ocr_pdf_pages_markdown,
    ocr_image_markdown,
)


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:12]


def _load_session_file(session: Session, *, name: str, content: bytes, is_pdf: bool) -> None:
    """Register a file with the session and make it active."""
    file_id = _hash_bytes(content)

    if file_id in session.files:
        session.active_file_id = file_id
        st.toast(f"Switched to {name}")
        return

    num_pages = 1
    if is_pdf:
        try:
            import PyPDF2  # type: ignore

            reader = PyPDF2.PdfReader(io.BytesIO(content))
            num_pages = len(reader.pages)
        except Exception:
            num_pages = 1

    session_file = SessionFile(
        file_id=file_id,
        name=name,
        bytes=content,
        is_pdf=is_pdf,
        num_pages=num_pages,
        current_page=1,
    )

    session.files[file_id] = session_file
    session.active_file_id = file_id
    st.toast(f"Loaded {name}")


def _resolve_active_file(session: Session) -> SessionFile | None:
    active = get_active_file(session)
    if not active:
        return None
    session.active_file_id = active.file_id
    return active


def render_main_panes(session: Session) -> None:
    left, right = st.columns([1, 1])

    # Left pane: viewer and navigation
    with left:
        uploaded = st.file_uploader("Upload PDF or Image", type=["pdf", "png", "jpg", "jpeg"], key=f"u_{session.id}")
        if uploaded is not None:
            content = uploaded.getvalue()
            is_pdf = uploaded.type == "application/pdf"
            _load_session_file(session, name=uploaded.name, content=content, is_pdf=is_pdf)

        paste_disabled = ImageGrab is None or Image is None
        paste_help = "Pillow ImageGrab is unavailable on this platform" if paste_disabled else "Use the clipboard image without saving a file"
        paste_clicked = st.button(
            "Paste image from clipboard",
            key=f"paste_clip_{session.id}",
            disabled=paste_disabled,
            help=paste_help,
        )

        if paste_clicked and not paste_disabled:
            try:
                grabbed = ImageGrab.grabclipboard()  # type: ignore[operator]
            except Exception as exc:  # pragma: no cover - clipboard access can fail per OS policy
                st.warning(f"Clipboard access failed: {exc}")
                grabbed = None

            pil_image = None
            if isinstance(grabbed, Image.Image):
                pil_image = grabbed.copy()
            elif isinstance(grabbed, list):
                for item in grabbed:
                    if isinstance(item, str):
                        try:
                            with Image.open(item) as opened:  # type: ignore[attr-defined]
                                pil_image = opened.copy()
                            break
                        except Exception:
                            continue

            if pil_image is None:
                st.warning("Clipboard does not contain an image.")
            else:
                buffer = io.BytesIO()
                if pil_image.mode not in ("RGB", "RGBA"):
                    pil_image = pil_image.convert("RGBA")
                pil_image.save(buffer, format="PNG")
                buffer.seek(0)
                clipboard_bytes = buffer.read()
                name = f"clipboard-{time.strftime('%Y%m%d-%H%M%S')}.png"
                _load_session_file(session, name=name, content=clipboard_bytes, is_pdf=False)

        file_options = list(session.files.values())
        if file_options:
            option_ids = [f.file_id for f in file_options]
            selected_idx = 0
            if session.active_file_id in option_ids:
                selected_idx = option_ids.index(session.active_file_id)
            else:
                session.active_file_id = option_ids[0]
            label_map = {f.file_id: f.name for f in file_options}
            chosen_id = st.selectbox(
                "Select loaded file",
                options=option_ids,
                index=selected_idx,
                format_func=lambda fid: label_map[fid],
                key=f"file_picker_{session.id}",
                help="Switch between files uploaded in this session",
            )
            if chosen_id != session.active_file_id:
                session.active_file_id = chosen_id

        active_file = _resolve_active_file(session)

        if active_file:
            st.caption(f"File: {active_file.name}  •  Pages: {active_file.num_pages}")

        if active_file:
            if active_file.is_pdf:
                # Ensure num_pages is accurate before rendering controls
                if not active_file.num_pages or active_file.num_pages <= 1:
                    try:
                        import fitz  # type: ignore
                        doc = fitz.open(stream=active_file.bytes, filetype="pdf")
                        active_file.num_pages = len(doc)
                        doc.close()
                    except Exception:
                        try:
                            import PyPDF2  # type: ignore
                            reader = PyPDF2.PdfReader(io.BytesIO(active_file.bytes))
                            active_file.num_pages = len(reader.pages)
                        except Exception:
                            active_file.num_pages = active_file.num_pages or 1
                # Clamp current_page within bounds now that we know num_pages
                clamped = max(1, min(active_file.current_page or 1, active_file.num_pages or 1))
                if clamped != active_file.current_page:
                    active_file.current_page = clamped
                # Controls FIRST
                c1, c2, c3 = st.columns([1, 2, 1])
                with c1:
                    disabled_prev = active_file.current_page <= 1
                    if st.button("◀ Prev", disabled=disabled_prev):
                        active_file.current_page = max(1, active_file.current_page - 1)
                with c2:
                    page_key = f"page_input_{session.id}_{active_file.file_id}"
                    page = st.number_input(
                        "Page",
                        min_value=1,
                        max_value=max(1, active_file.num_pages or 1),
                        value=int(active_file.current_page),
                        step=1,
                        key=page_key,
                    )
                    if page != active_file.current_page:
                        active_file.current_page = int(page)
                with c3:
                    disabled_next = active_file.current_page >= (active_file.num_pages or 1)
                    if st.button("Next ▶", disabled=disabled_next):
                        active_file.current_page = active_file.current_page + 1

                # Render AFTER updating current_page
                from src.components.pdf_viewer.viewer import render_pdf

                render_pdf(active_file)
            else:
                st.image(active_file.bytes, caption=active_file.name, use_container_width=True)

    # Right pane: OCR result and editor
    with right:
        tab1, tab2 = st.tabs(["Rendered Markdown", "Raw Markdown"])

        if not active_file:
            st.info("Upload a PDF or image to begin.")
            return

        file_id = active_file.file_id
        current_page = active_file.current_page if active_file.is_pdf else 1
        key = (session.id, file_id, current_page)
        raw_key = f"raw_{session.id}_{file_id}_{current_page}"

        # OCR job state (per page)
        ocr_jobs = st.session_state.setdefault("ocr_jobs", {})
        job_id = f"{session.id}:{file_id}:{current_page}"
        ocr_exec: ThreadPoolExecutor = st.session_state.setdefault("ocr_exec", ThreadPoolExecutor(max_workers=1))

        md_text = active_file.raw_edits.get(current_page)
        if md_text is None:
            cached = read_memo_markdown(key)
            if cached is not None:
                md_text = cached
                active_file.ocr_cache[current_page] = OcrEntry(markdown=cached, source="cache", updated_at=None)  # type: ignore
                active_file.raw_edits[current_page] = cached
                notify_key = f"cache_notified_{session.id}_{file_id}_{current_page}"
                if not session.ui.get(notify_key):
                    st.toast("Cache hit – loaded OCR from memory")
                    session.ui[notify_key] = True
                st.session_state[raw_key] = cached
            else:
                # Start background OCR if not already running
                job = ocr_jobs.get(job_id)
                if not job:
                    ocr_jobs[job_id] = {"status": "running", "cancel": False, "error": None, "result": None, "pages": None}

                    def _do_ocr(pdf: bool, file_bytes: bytes, expect_page: int, expect_file_id: str, this_job_id: str):
                        try:
                            if pdf:
                                pages_md = ocr_pdf_pages_markdown(file_bytes)
                                pages_len = len(pages_md) or 1
                                idx = max(1, min(expect_page, pages_len)) - 1
                                md = pages_md[idx] if pages_md else ""
                            else:
                                pages_len = 1
                                md = ocr_image_markdown(file_bytes)
                            if ocr_jobs.get(this_job_id, {}).get("cancel"):
                                ocr_jobs[this_job_id]["status"] = "cancelled"
                                return
                            # Don't touch st.session_state/session from worker; stash result for UI thread to consume
                            ocr_jobs[this_job_id]["result"] = md
                            ocr_jobs[this_job_id]["pages"] = pages_len
                            ocr_jobs[this_job_id]["status"] = "done"
                        except Exception as e:
                            ocr_jobs[this_job_id] = {"status": "error", "cancel": False, "error": str(e)}

                    ocr_exec.submit(_do_ocr, bool(active_file.is_pdf), active_file.bytes, current_page, file_id, job_id)

                # Running/error UI
                job = ocr_jobs.get(job_id)
                if job and job.get("status") == "running":
                    st.info("OCR processing…")
                    if st.button("Cancel OCR", key=f"cancel_ocr_{session.id}_{file_id}_{current_page}"):
                        ocr_jobs[job_id]["cancel"] = True
                        st.toast("Cancel requested")
                    # Gentle polling without using deprecated/unsupported APIs
                    time.sleep(1.2)
                    st.rerun()
                elif job and job.get("status") == "done":
                    # Consume result produced by background worker
                    md = job.get("result") or ""
                    pages_len = int(job.get("pages") or (active_file.num_pages or 1))
                    # Update cache and UI state in main thread
                    set_cached_markdown(key, md)
                    active_file.ocr_cache[current_page] = OcrEntry(markdown=md, source="api", updated_at=None)  # type: ignore
                    active_file.raw_edits[current_page] = md
                    st.session_state[raw_key] = md
                    # Update num_pages conservatively for PDFs
                    if active_file.is_pdf:
                        active_file.num_pages = max(active_file.num_pages or 1, pages_len)
                    # Remove job entry to avoid re-processing
                    ocr_jobs.pop(job_id, None)
                elif job and job.get("status") == "error":
                    st.error(f"OCR failed: {job.get('error')}")
                    md_text = ""

        # Action buttons
        c1, c2 = st.columns([1, 1])
        with c1:
            running = (st.session_state.get("ocr_jobs", {}).get(job_id, {}).get("status") == "running")
            if st.button("Re-OCR this page", disabled=running):
                invalidate_markdown(key)
                if job_id in ocr_jobs:
                    ocr_jobs.pop(job_id, None)
                ocr_jobs[job_id] = {"status": "running", "cancel": False, "error": None}

                def _redo(pdf: bool, file_bytes: bytes, expect_page: int, expect_file_id: str, this_job_id: str):
                    try:
                        if pdf:
                            pages_md = ocr_pdf_pages_markdown(file_bytes)
                            pages_len = len(pages_md) or 1
                            idx = max(1, min(expect_page, pages_len)) - 1
                            md = pages_md[idx] if pages_md else ""
                        else:
                            pages_len = 1
                            md = ocr_image_markdown(file_bytes)
                        if ocr_jobs.get(this_job_id, {}).get("cancel"):
                            ocr_jobs[this_job_id]["status"] = "cancelled"
                            return
                        ocr_jobs[this_job_id]["result"] = md
                        ocr_jobs[this_job_id]["pages"] = pages_len
                        ocr_jobs[this_job_id]["status"] = "done"
                    except Exception as e:
                        ocr_jobs[this_job_id] = {"status": "error", "cancel": False, "error": str(e)}

                ocr_exec.submit(_redo, bool(active_file.is_pdf), active_file.bytes, current_page, file_id, job_id)

        with c2:
            if st.button("Copy to clipboard"):
                txt = active_file.raw_edits.get(current_page, md_text or "")
                if pyperclip is None:
                    st.warning("Clipboard support unavailable; install pyperclip on the server.")
                else:
                    try:
                        pyperclip.copy(txt)
                    except Exception as exc:  # pragma: no cover - backend dependent
                        st.error(f"Clipboard copy failed: {exc}")
                    else:
                        st.toast("Copied to clipboard")

        # Tabs content
        with tab2:
            new_md = st.text_area(
                "Raw Markdown",
                value=st.session_state.get(raw_key, md_text or ""),
                height=500,
                key=raw_key,
            )
            if new_md != md_text:
                active_file.raw_edits[current_page] = new_md
        with tab1:
            st.markdown(active_file.raw_edits.get(current_page, md_text or ""))

        # No additional clipboard handling needed when pyperclip is available
