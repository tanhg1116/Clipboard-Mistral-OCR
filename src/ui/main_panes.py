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


def _load_session_file(session: Session, *, name: str, content: bytes, is_pdf: bool, force_rerun: bool = False) -> None:
    """Register a file with the session and make it active."""
    file_id = _hash_bytes(content)

    if file_id in session.files:
        if session.active_file_id != file_id:
            session.active_file_id = file_id
            st.toast(f"Switched to {name}")
            if force_rerun:
                st.rerun()
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
    # Always rerun after loading a new file to update the UI
    st.rerun()


def _resolve_active_file(session: Session) -> SessionFile | None:
    active = get_active_file(session)
    if not active:
        return None
    session.active_file_id = active.file_id
    return active


def render_main_panes(session: Session, active_session_id: str = None, executor = None) -> None:
    # Three-column layout: Screenshot | Rendered MD | Raw MD Editor
    col_screenshot, col_rendered, col_raw = st.columns([1, 1, 1])
    
    # Get active file first
    session_files = list(session.files.values())
    active_file = _resolve_active_file(session)
    
    # Column 1: Screenshot/Image viewer
    with col_screenshot:
        st.markdown("### 📄 Document")
        
        if active_file:
            if active_file.is_pdf:
                # Ensure num_pages is accurate
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
                
                # Clamp current_page
                clamped = max(1, min(active_file.current_page or 1, active_file.num_pages or 1))
                if clamped != active_file.current_page:
                    active_file.current_page = clamped

                # Render PDF with fixed height
                from src.components.pdf_viewer.viewer import render_pdf
                render_pdf(active_file)
                
                # Navigation controls below
                c1, c2, c3 = st.columns([1, 2, 1])
                with c1:
                    if st.button("◀", disabled=active_file.current_page <= 1, help="Previous", use_container_width=True):
                        active_file.current_page = max(1, active_file.current_page - 1)
                with c2:
                    page = st.number_input(
                        "Page",
                        min_value=1,
                        max_value=max(1, active_file.num_pages or 1),
                        value=int(active_file.current_page),
                        step=1,
                        key=f"page_{session.id}_{active_file.file_id}",
                        label_visibility="collapsed",
                        help=f"Page {active_file.current_page} of {active_file.num_pages}"
                    )
                    if page != active_file.current_page:
                        active_file.current_page = int(page)
                with c3:
                    if st.button("▶", disabled=active_file.current_page >= (active_file.num_pages or 1), help="Next", use_container_width=True):
                        active_file.current_page = active_file.current_page + 1
            else:
                st.image(active_file.bytes, use_container_width=True)
        
        # File selector
        if session_files:
            option_ids = [f.file_id for f in session_files]
            selected_idx = 0
            if session.active_file_id in option_ids:
                selected_idx = option_ids.index(session.active_file_id)
            else:
                session.active_file_id = option_ids[0]
            label_map = {f.file_id: f.name for f in session_files}
            chosen_id = st.selectbox(
                "Files",
                options=option_ids,
                index=selected_idx,
                format_func=lambda fid: label_map[fid],
                key=f"file_picker_{session.id}",
                label_visibility="collapsed"
            )
            # Update active file and force rerun if changed
            if chosen_id != session.active_file_id:
                session.active_file_id = chosen_id
                st.rerun()
        
        # Upload controls
        uploaded = st.file_uploader(
            label="Upload", 
            type=["pdf", "png", "jpg", "jpeg"], 
            key=f"u_{session.id}",
            label_visibility="collapsed"
        )
        if uploaded is not None:
            content = uploaded.getvalue()
            file_id = _hash_bytes(content)
            
            # Track the last processed upload to prevent re-processing
            last_upload_key = f"last_upload_{session.id}"
            last_upload_id = st.session_state.get(last_upload_key)
            
            # Only process if this is a different upload than last time
            if last_upload_id != file_id:
                st.session_state[last_upload_key] = file_id
                
                if file_id not in session.files:
                    # New file - load it
                    is_pdf = uploaded.type == "application/pdf"
                    _load_session_file(session, name=uploaded.name, content=content, is_pdf=is_pdf, force_rerun=False)
                elif session.active_file_id != file_id:
                    # Existing file but not active - switch to it
                    session.active_file_id = file_id
                    st.toast(f"Switched to {uploaded.name}")
        
        # Paste button
        paste_disabled = ImageGrab is None or Image is None
        if st.button("Paste from clipboard", disabled=paste_disabled, use_container_width=True):
            try:
                grabbed = ImageGrab.grabclipboard()  # type: ignore
            except Exception as exc:
                st.warning(f"Clipboard access failed: {exc}")
                grabbed = None

            pil_image = None
            if isinstance(grabbed, Image.Image):
                pil_image = grabbed.copy()
            elif isinstance(grabbed, list):
                for item in grabbed:
                    if isinstance(item, str):
                        try:
                            with Image.open(item) as opened:  # type: ignore
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
                _load_session_file(session, name=name, content=clipboard_bytes, is_pdf=False, force_rerun=True)

    # Column 2: Rendered Markdown preview
    with col_rendered:
        st.markdown("### 📝 Rendered Markdown")
        
        if not active_file:
            st.info("Upload a document to begin.")
            return

        file_id = active_file.file_id
        current_page = active_file.current_page if active_file.is_pdf else 1
        key = (session.id, file_id, current_page)
        raw_key = f"raw_{session.id}_{file_id}_{current_page}"

        # OCR job state
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
                    st.toast("Cache hit")
                    session.ui[notify_key] = True
                st.session_state[raw_key] = cached
            else:
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
                            ocr_jobs[this_job_id]["result"] = md
                            ocr_jobs[this_job_id]["pages"] = pages_len
                            ocr_jobs[this_job_id]["status"] = "done"
                        except Exception as e:
                            ocr_jobs[this_job_id] = {"status": "error", "cancel": False, "error": str(e)}

                    ocr_exec.submit(_do_ocr, bool(active_file.is_pdf), active_file.bytes, current_page, file_id, job_id)

                job = ocr_jobs.get(job_id)
                if job and job.get("status") == "running":
                    st.info("OCR processing…")
                    if st.button("Cancel OCR", key=f"cancel_ocr_{session.id}_{file_id}_{current_page}"):
                        ocr_jobs[job_id]["cancel"] = True
                        st.toast("Cancel requested")
                    time.sleep(1.2)
                    st.rerun()
                elif job and job.get("status") == "done":
                    md = job.get("result") or ""
                    pages_len = int(job.get("pages") or (active_file.num_pages or 1))
                    set_cached_markdown(key, md)
                    active_file.ocr_cache[current_page] = OcrEntry(markdown=md, source="api", updated_at=None)  # type: ignore
                    active_file.raw_edits[current_page] = md
                    st.session_state[raw_key] = md
                    if active_file.is_pdf:
                        active_file.num_pages = max(active_file.num_pages or 1, pages_len)
                    ocr_jobs.pop(job_id, None)
                elif job and job.get("status") == "error":
                    st.error(f"OCR failed: {job.get('error')}")
                    md_text = ""

        # Rendered preview with scrollbar
        display_text = st.session_state.get(raw_key, md_text or "")
        rendered_container = st.container(height=500, border=True)
        with rendered_container:
            if display_text:
                st.markdown(display_text)
            else:
                st.caption("No content yet")
        
        # Re-OCR button
        running = (st.session_state.get("ocr_jobs", {}).get(job_id, {}).get("status") == "running")
        if st.button("Re-OCR this page", disabled=running, use_container_width=True):
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
        
        # Export button
        if st.button("Export", use_container_width=True):
            st.session_state[f"show_export_dialog_{active_session_id}"] = True
        
        # Export dialog modal
        if st.session_state.get(f"show_export_dialog_{active_session_id}", False):
            with st.container(border=True):
                st.markdown("#### Export Document")
                
                # Check if export is running
                from src.services.exporter import get_job_status, cancel_export_job, start_export_job
                job = get_job_status(active_session_id) if active_session_id else None
                
                if job and job.status in {"running", "queued"}:
                    # Show progress and cancel button
                    st.info(f"Export in progress: {job.progress}%")
                    st.progress(job.progress / 100.0)
                    if st.button("Cancel Export", key=f"cancel_export_modal_{active_session_id}", use_container_width=True):
                        cancel_export_job(active_session_id)
                        st.toast("Export cancelled")
                        st.rerun()
                    # Gentle polling
                    time.sleep(1.5)
                    st.rerun()
                elif job and job.status == "done":
                    # Show download button
                    st.success("Export complete!")
                    file_name = job.output_name
                    if job.output_bytes is not None:
                        mime = "application/pdf" if job.format == "pdf" else "text/markdown"
                        st.download_button(
                            label=f"Download {file_name}",
                            data=job.output_bytes,
                            file_name=file_name,
                            mime=mime,
                            use_container_width=True,
                            key=f"dl_modal_{active_session_id}",
                        )
                    if st.button("Close", key=f"close_export_done_{active_session_id}", use_container_width=True):
                        st.session_state[f"show_export_dialog_{active_session_id}"] = False
                        st.rerun()
                else:
                    # Show export form
                    page_range = st.text_input(
                        "Page range",
                        value="all",
                        key=f"export_range_modal_{active_session_id}",
                        help="e.g., 1-3,5,9-10 or 'all'"
                    )
                    
                    export_format = st.radio(
                        "Export format",
                        options=["PDF", "Markdown"],
                        key=f"export_format_modal_{active_session_id}",
                        horizontal=True
                    )
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Start Export", key=f"start_export_modal_{active_session_id}", use_container_width=True):
                            fmt = "pdf" if export_format == "PDF" else "md"
                            try:
                                start_export_job(executor, active_session_id, page_range, fmt)
                                st.toast(f"Started {fmt.upper()} export")
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))
                    with col2:
                        if st.button("Cancel", key=f"cancel_dialog_{active_session_id}", use_container_width=True):
                            st.session_state[f"show_export_dialog_{active_session_id}"] = False
                            st.rerun()

    # Column 3: Raw Markdown Editor
    with col_raw:
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

    # Column 3: Raw Markdown Editor
    with col_raw:
        st.markdown("### ✏️ Raw Markdown Editor")
        
        new_md = st.text_area(
            "Edit markdown",
            value=st.session_state.get(raw_key, md_text or ""),
            height=500,
            key=raw_key,
            label_visibility="collapsed",
        )
        if new_md != md_text:
            active_file.raw_edits[current_page] = new_md
        
        # Copy button
        if st.button("Copy", use_container_width=True):
            txt = active_file.raw_edits.get(current_page, md_text or "")
            if pyperclip is None:
                st.warning("Clipboard support unavailable")
            else:
                try:
                    pyperclip.copy(txt)
                    st.toast("Copied to clipboard")
                except Exception as exc:
                    st.error(f"Copy failed: {exc}")


