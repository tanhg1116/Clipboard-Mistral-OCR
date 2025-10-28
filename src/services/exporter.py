from __future__ import annotations

import io
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List, Optional

import streamlit as st

from .state import ExportJob, Session, SessionFile, get_active_file
from ..utils.range_parse import parse_page_range


HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>
  <style>
    body {{ font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 2rem; line-height: 1.5; }}
    h1,h2,h3 {{ margin-top: 1.2em; }}
    pre, code {{ background: #f6f8fa; padding: 0.2em 0.4em; }}
    hr {{ border: none; border-top: 1px solid #ddd; margin: 2rem 0; }}
    .page {{ page-break-after: always; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def _collect_pages_markdown(session_file: SessionFile, page_numbers: List[int], job: ExportJob) -> List[str]:
    job.stage = "Collecting pages"
    pages_md: List[str] = []
    for i, p in enumerate(page_numbers, start=1):
        md = session_file.raw_edits.get(p)
        if md is None:
            cache_entry = session_file.ocr_cache.get(p)
            md = cache_entry.markdown if cache_entry else ""
        pages_md.append(md or "")
        job.progress = int(10 + 40 * i / max(1, len(page_numbers)))
        if job.cancel_flag:
            break
    return pages_md


def _markdown_to_html(md: str) -> str:
    # Streamlit doesn't expose markdown->html directly; fallback simple conversion.
    # For production, consider markdown2 or mistune to convert.
    try:
        import markdown as mdlib  # optional
        return mdlib.markdown(md, extensions=["extra", "tables", "codehilite"])  # type: ignore
    except Exception:
        # naive fallback
        return "<pre>" + (md.replace("<", "&lt;").replace(">", "&gt;")) + "</pre>"


def _build_html_document(session: Session, session_file: SessionFile, page_numbers: List[int], job: ExportJob) -> bytes:
    job.stage = "Rendering HTML"
    pages_md = _collect_pages_markdown(session_file, page_numbers, job)
    parts: List[str] = []
    for idx, md in enumerate(pages_md, start=1):
        parts.append(f"<div class='page'>\n{_markdown_to_html(md)}\n</div>")
        job.progress = int(50 + 30 * idx / max(1, len(pages_md)))
        if job.cancel_flag:
            return b""
    html = HTML_TEMPLATE.format(title=session.title, body="\n<hr/>\n".join(parts))
    return html.encode("utf-8")


def _html_to_pdf_bytes(html_bytes: bytes) -> bytes:
    # Try WeasyPrint; if not available, raise and let caller downgrade to .md
    try:
        from weasyprint import HTML  # type: ignore
        pdf_io = io.BytesIO()
        HTML(string=html_bytes.decode("utf-8")).write_pdf(pdf_io)
        return pdf_io.getvalue()
    except Exception as e:
        raise RuntimeError("PDF engine unavailable: " + str(e))


def start_export_job(executor: ThreadPoolExecutor, session_id: str, range_text: str, fmt: str) -> str:
    sessions: Dict[str, Session] = st.session_state["sessions"]
    session = sessions[session_id]
    session_file = get_active_file(session)
    if not session_file:
        raise ValueError("No active file to export")

    job = ExportJob(session_id=session_id, format=fmt, status="queued", progress=0, stage="queued")
    st.session_state.setdefault("jobs", {})[session_id] = job
    job_id = f"job-{session_id}-{int(datetime.now().timestamp())}"

    def _run():
        job.status = "running"
        try:
            target_file = session.files.get(session_file.file_id, session_file)
            total_pages = target_file.num_pages or 1
            pages = (
                parse_page_range(range_text, total_pages=total_pages)
                if range_text.strip().lower() != "all"
                else list(range(1, total_pages + 1))
            )
            if not pages:
                raise ValueError("No pages to export")
            if job.cancel_flag:
                job.status = "cancelled"
                return

            html_bytes = _build_html_document(session, target_file, pages, job)
            if job.cancel_flag:
                job.status = "cancelled"
                return

            if fmt == "pdf":
                job.stage = "Converting to PDF"
                try:
                    pdf_bytes = _html_to_pdf_bytes(html_bytes)
                    job.output_bytes = pdf_bytes
                    job.output_name = f"{session.title.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                except Exception as e:
                    job.error = str(e)
                    job.status = "error"
                    return
            else:
                # md export: concatenate with headers
                job.stage = "Preparing Markdown"
                md_pages = _collect_pages_markdown(target_file, pages, job)
                combined = []
                for i, md in enumerate(md_pages, start=1):
                    combined.append(f"# Page {pages[i-1]}\n\n{md}\n")
                job.output_bytes = "\n\n".join(combined).encode("utf-8")
                job.output_name = f"{session.title.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

            if not job.cancel_flag:
                job.progress = 100
                job.stage = "Ready"
                job.status = "done"
            else:
                job.status = "cancelled"
        except Exception as e:
            job.error = str(e)
            job.status = "error"

    executor.submit(_run)
    return job_id


def get_job_status(session_id: str) -> Optional[ExportJob]:
    return st.session_state.get("jobs", {}).get(session_id)


def cancel_export_job(session_id: str) -> None:
    job = st.session_state.get("jobs", {}).get(session_id)
    if job:
        job.cancel_flag = True
