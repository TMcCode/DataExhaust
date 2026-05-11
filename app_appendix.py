#!/usr/bin/env python3
"""Appendix pages for the MLP Restaurant SSS dashboard.

Run from the repo root with: ``streamlit run app_appendix.py``.
"""

from __future__ import annotations

from pathlib import Path


def _load_repo_dotenv() -> None:
    """So ``MLP_GCS_SNAPSHOT_URI`` and other keys in repo ``.env`` apply under ``streamlit run``."""
    try:
        from dotenv import load_dotenv

        repo = Path(__file__).resolve().parent
        load_dotenv(repo / ".env", override=True)
        cwd = Path.cwd() / ".env"
        if cwd.resolve() != (repo / ".env").resolve():
            load_dotenv(cwd, override=True)
    except ImportError:
        pass


_load_repo_dotenv()

from streamlit_dashboard.credentials import apply_streamlit_secrets

apply_streamlit_secrets()

import streamlit as st

from streamlit_dashboard.theme import inject_global_styles, render_sidebar_theme_toggle

_REPO_ROOT = Path(__file__).resolve().parent


def _resolve_brand_logo_path() -> Path | None:
    """Prefer ``assets/`` (packaged layout); fall back to repo-root PNG (some clones only keep that copy)."""
    for rel in (
        _REPO_ROOT / "assets" / "WaterBendLogo.png",
        _REPO_ROOT / "WaterBendLogo.png",
    ):
        if rel.is_file():
            return rel
    return None


st.set_page_config(
    page_title="MLP Restaurant SSS Appendix",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.session_state.setdefault("dark_mode", False)

_logo_path = _resolve_brand_logo_path()
_has_st_logo = callable(getattr(st, "logo", None))
if _logo_path is not None and _has_st_logo:
    try:
        st.logo(str(_logo_path), size="large")
    except (TypeError, ValueError):
        st.logo(str(_logo_path))

inject_global_styles(dark_mode=bool(st.session_state.dark_mode))

with st.sidebar:
    if _logo_path is not None and not _has_st_logo:
        st.image(str(_logo_path), use_container_width=True)
    render_sidebar_theme_toggle()

_BASE = "streamlit_dashboard/pages"

pages = [
    st.Page(f"{_BASE}/peer_basket_metrics.py", title="Peer basket (quarterly)"),
    st.Page(f"{_BASE}/industry_backdrop.py", title="Industry backdrop"),
    st.Page(f"{_BASE}/google_trends_peer.py", title="Google Trends vs peer"),
    st.Page(f"{_BASE}/gtrends_peer_compare.py", title="GTrends vs peer (all)"),
    st.Page(f"{_BASE}/gtrends_index_lab.py", title="GTrends index lab (temp)"),
    st.Page(f"{_BASE}/company_deep_dive.py", title="Company deep dive"),
    st.Page(f"{_BASE}/predictive_power.py", title="Predictive power"),
]

try:
    _nav = st.navigation(pages, expanded=True)
except TypeError:
    _nav = st.navigation(pages)
_nav.run()
