from __future__ import annotations

from typing import Dict, Tuple

import streamlit as st

_MEMO_FALLBACK: Dict[str, Dict[Tuple[str, str, int], str]] = {"ocr": {}}

# Cache pure data results. Key by composite key to isolate per session/file/page.


@st.cache_data(show_spinner=False)
def get_cached_markdown(key: Tuple[str, str, int]) -> str | None:
    return None


def set_cached_markdown(key: Tuple[str, str, int], value: str) -> None:
    # st.cache_data cannot be set directly; emulate via a dict in session_state or fallback to process dict
    try:
        cache: Dict[str, Dict[Tuple[str, str, int], str]] = st.session_state.setdefault("_memo_cache", {})  # type: ignore
        bucket = cache.setdefault("ocr", {})
        bucket[key] = value
    except Exception:
        _MEMO_FALLBACK.setdefault("ocr", {})[key] = value


def read_memo_markdown(key: Tuple[str, str, int]) -> str | None:
    try:
        cache: Dict[str, Dict[Tuple[str, str, int], str]] = st.session_state.setdefault("_memo_cache", {})  # type: ignore
        return cache.get("ocr", {}).get(key)
    except Exception:
        return _MEMO_FALLBACK.get("ocr", {}).get(key)


def invalidate_markdown(key: Tuple[str, str, int]) -> None:
    try:
        cache: Dict[str, Dict[Tuple[str, str, int], str]] = st.session_state.setdefault("_memo_cache", {})  # type: ignore
        bucket = cache.setdefault("ocr", {})
        if key in bucket:
            del bucket[key]
    except Exception:
        bucket = _MEMO_FALLBACK.setdefault("ocr", {})
        if key in bucket:
            del bucket[key]
