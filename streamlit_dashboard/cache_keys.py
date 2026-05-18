"""Small helpers for ``st.cache_data`` keys — keep imports free of Streamlit / ETL modules."""

from __future__ import annotations

import pandas as pd


def dataframe_revision(df: pd.DataFrame | None) -> str:
    """Lightweight fingerprint for cache keys built from panel frames."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return "empty"
    return f"{df.shape}_{pd.util.hash_pandas_object(df, index=True).sum()}"
