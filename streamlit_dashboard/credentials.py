"""Map Streamlit Cloud / local ``st.secrets`` into env so ``sheets_client`` can open the workbook."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def apply_streamlit_secrets() -> None:
    """If ``GOOGLE_SHEETS_CREDENTIALS`` is unset and no local default key exists, materialize secrets.

    ``GOOGLE_SERVICE_ACCOUNT_JSON`` — paste the full service-account JSON object as a single TOML
    string (Streamlit Secrets) or a dict if loaded from another host.
    Writes a temp ``*.json`` and sets ``GOOGLE_SHEETS_CREDENTIALS``.
    """
    if os.environ.get("GOOGLE_SHEETS_CREDENTIALS"):
        return

    repo_parent = Path(__file__).resolve().parent.parent
    default_key = repo_parent / "data-exhaust-key.json"
    if default_key.is_file():
        return

    try:
        import streamlit as st
    except ImportError:
        return

    if not hasattr(st, "secrets"):
        return

    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in st.secrets:
        return
    raw = st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"]

    if isinstance(raw, dict):
        body = json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    elif isinstance(raw, str):
        body = raw.strip().encode("utf-8")
    else:
        return

    fd, path = tempfile.mkstemp(prefix="streamlit_ga_", suffix=".json")
    os.close(fd)
    Path(path).write_bytes(body)
    os.environ["GOOGLE_SHEETS_CREDENTIALS"] = path
