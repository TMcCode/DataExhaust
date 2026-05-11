"""Typography and layout overrides (loaded once per rerun from ``app.py``)."""

from __future__ import annotations

import streamlit as st

# Editorial pairing: serif display + humanist sans (not Inter/system defaults).
_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,450&family=Karla:ital,wght@0,400;0,600;0,700;1,400&display=swap');

.stApp {
  font-family: "Karla", "Helvetica Neue", Arial, sans-serif;
  font-size: 16px;
}

h1 {
  font-family: "Cormorant Garamond", "Georgia", "Times New Roman", serif !important;
  font-weight: 600 !important;
  font-size: clamp(1.85rem, 3vw, 2.55rem) !important;
  letter-spacing: -0.02em !important;
  line-height: 1.15 !important;
  color: #1a1816 !important;
  border-bottom: 1px solid #d9d0c2;
  padding-bottom: 0.5rem;
  margin-bottom: 1rem !important;
}

h2, h3 {
  font-family: "Cormorant Garamond", "Georgia", serif !important;
  font-weight: 600 !important;
  letter-spacing: -0.015em !important;
  color: #24211d !important;
}

h2 { font-size: 1.65rem !important; margin-top: 1.5rem !important; }
h3 { font-size: 1.28rem !important; margin-top: 1.1rem !important; }

.stMarkdown p, .stMarkdown li {
  font-size: 1.02rem !important;
  line-height: 1.72 !important;
  color: #2a2622 !important;
}

.stMarkdown a {
  color: #345240 !important;
  text-underline-offset: 2px;
}

.stMarkdown code {
  font-family: ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace !important;
  font-size: 0.88em !important;
  background: #ebe4d9 !important;
  padding: 0.12em 0.35em !important;
  border-radius: 3px !important;
  color: #1f1f1f !important;
}

.stMarkdown pre code {
  background: transparent !important;
  padding: 0 !important;
}

blockquote {
  border-left: 3px solid #3d5346 !important;
  padding-left: 1rem !important;
  margin: 1rem 0 !important;
  color: #454039 !important;
  font-style: italic !important;
}

hr {
  border: none !important;
  border-top: 1px solid #cfc5b8 !important;
  margin: 2rem 0 !important;
}

/*
  Sidebar brand is shown with ``st.logo`` in ``app.py`` (header row + scales via ``stSidebarLogo`` CSS).
  ``st.sidebar`` widgets (e.g. theme toggle) render below multipage nav. Fallback: ``st.image`` path.
*/
[data-testid="stSidebar"] [data-testid="stLogoSpacer"] {
  display: none !important;
}

/*
  Sidebar header row: Streamlit lays out ``st.logo`` plus the collapse control (native order).
  Below that: multipage ``stSidebarNav``, then ``st.sidebar`` widgets — no flex ``order`` hacks.
*/
[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
  display: flex !important;
  justify-content: space-between !important;
  align-items: center !important;
  width: 100% !important;
  height: auto !important;
  min-height: unset !important;
  margin-bottom: 0.35rem !important;
}

[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] {
  transform: translateY(5px) !important;
}

/* Raster logo from ``st.logo`` sits in header row (`data-testid="stSidebarLogo"` on the `<img>`). */
[data-testid="stSidebar"] [data-testid="stSidebarLogo"] {
  width: auto !important;
  height: auto !important;
  max-width: min(calc(100% - 2.25rem), 288px) !important;
  max-height: min(248px, 38vh) !important;
  object-fit: contain !important;
  object-position: left center !important;
  display: block !important;
  margin: 0 !important;
  margin-top: 0.28rem !important; /* optical nudge down vs. collapse row */
}

[data-testid="stSidebar"] [data-testid="stImage"] {
  text-align: left !important;
  margin-bottom: 0 !important;
}

[data-testid="stSidebar"] [data-testid="stImage"] img {
  width: auto !important;
  height: auto !important;
  max-width: min(calc(100% - 2.25rem), 288px) !important;
  max-height: 248px !important;
  object-fit: contain !important;
  object-position: left center !important;
  display: block !important;
  margin: 0 !important;
}

/* ``st.image`` fullscreen toolbar + tooltip — sidebar brand only; leave main-pane images untouched */
[data-testid="stSidebar"] [data-testid="stElementToolbar"],
[data-testid="stSidebar"] [data-testid="stImageToolbar"] {
  display: none !important;
  visibility: hidden !important;
  pointer-events: none !important;
}

[data-testid="stSidebar"] button[title="Fullscreen"],
[data-testid="stSidebar"] button[title="View fullscreen"],
[data-testid="stSidebar"] button[aria-label="Fullscreen"],
[data-testid="stSidebar"] button[aria-label="View fullscreen"] {
  display: none !important;
}

/*
  Sidebar user widgets sit **below** multipage ``stSidebarNav`` (same ``with st.sidebar:`` bucket).
*/
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
  padding-top: 0.75rem !important;
  padding-bottom: 0 !important;
  margin-bottom: 0 !important;
  margin-top: 0 !important;
}

/* Sidebar theme: compact secondary icon button + ``st.columns`` label row (``render_sidebar_theme_toggle``) */
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="stHorizontalBlock"]:has(
    button[kind="secondary"]
  ) {
  align-items: center !important;
}

[data-testid="stSidebar"]
  [data-testid="stSidebarUserContent"]
  [data-testid="stHorizontalBlock"]:has(button[kind="secondary"])
  [data-testid="stCaptionContainer"] {
  margin-block: 0 !important;
  padding-top: 0 !important;
  display: flex !important;
  align-items: center !important;
  min-height: 2.75rem !important;
}

/* Sidebar theme: compact secondary icon button (see ``render_sidebar_theme_toggle``) */
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] button[kind="secondary"],
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="baseButton-secondary"],
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="stBaseButton-secondary"] {
  width: 2.75rem !important;
  height: 2.75rem !important;
  min-height: unset !important;
  min-width: 2.75rem !important;
  padding: 0 !important;
  border-radius: 14px !important;
  border: 1px solid rgba(100, 95, 86, 0.38) !important;
  background: rgba(250, 247, 242, 0.98) !important;
  box-shadow: none !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
}

[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] button[kind="secondary"] > div,
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="baseButton-secondary"] > div,
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="stBaseButton-secondary"] > div {
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  width: 100% !important;
  height: 100% !important;
  margin: 0 !important;
  padding: 0 !important;
  min-height: 0 !important;
}

[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] button[kind="secondary"] p,
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="baseButton-secondary"] p,
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="stBaseButton-secondary"] p {
  font-size: 1.05rem !important;
  margin: 0 !important;
  line-height: 1 !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
}

[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] button[kind="secondary"] span[data-testid="stIconMaterial"],
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="baseButton-secondary"] span[data-testid="stIconMaterial"],
[data-testid="stSidebar"]
  [data-testid="stSidebarUserContent"]
  [data-testid="stBaseButton-secondary"]
  span[data-testid="stIconMaterial"] {
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  line-height: 0 !important;
}

[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] button[kind="secondary"] span[data-testid="stIconMaterial"] svg,
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] button[kind="secondary"] svg,
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="baseButton-secondary"] svg,
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="stBaseButton-secondary"] svg {
  width: 1.25rem !important;
  height: 1.25rem !important;
  display: block !important;
}

[data-testid="stSidebar"] [data-testid="stSidebarNav"] {
  margin-top: 0 !important;
  padding-top: 0 !important;
}

[data-testid="stSidebar"] [data-testid="stSidebarNavItems"] {
  padding-top: 0 !important;
  margin-top: 0 !important;
}

[data-testid="stSidebar"] [data-testid="stSidebarNavItems"] > li:first-child {
  margin-top: 0 !important;
}

[data-testid="stSidebarNav"] span,
[data-testid="stSidebarNav"] a {
  font-family: "Karla", sans-serif !important;
  font-size: 0.96rem !important;
  letter-spacing: 0.01em !important;
}

[data-testid="stCaptionContainer"] {
  font-family: "Karla", sans-serif !important;
  color: #5c574f !important;
}

[data-testid="stMetricLabel"] > div {
  font-family: "Karla", sans-serif !important;
}
"""

# Warm charcoal + sage accents (paired with existing light typography rules).
_CSS_DARK = """

html {
  color-scheme: dark !important;
}

.stApp {
  background-color: #141210 !important;
  color: #ebe7df !important;
}

[data-testid="stAppViewContainer"] > .main {
  background-color: #141210 !important;
}

section[data-testid="stMain"],
section[data-testid="stMain"] > div,
section.main > div,
section[data-testid="stMain"] .block-container {
  background-color: transparent !important;
}

[data-testid="stHeader"] {
  background-color: rgba(20, 18, 16, 0.96) !important;
  backdrop-filter: blur(8px);
}

/*
  Sidebar chevrons use theme ``fadedText60`` — nearly invisible on charcoal.
  ``stExpandSidebarButton`` is the ``>>`` in the main toolbar when the rail is collapsed;
  ``stSidebarCollapseButton`` wraps the ``«`` in the sidebar header.
*/
[data-testid="stExpandSidebarButton"] {
  color: #efede7 !important;
}

[data-testid="stExpandSidebarButton"] svg,
[data-testid="stExpandSidebarButton"] svg path,
[data-testid="stExpandSidebarButton"] span[data-testid="stIconMaterial"],
[data-testid="stExpandSidebarButton"] span[data-testid="stIconMaterial"] svg,
[data-testid="stExpandSidebarButton"] span[data-testid="stIconMaterial"] svg path,

[data-testid="stSidebarCollapseButton"] svg,
[data-testid="stSidebarCollapseButton"] svg path,
[data-testid="stSidebarCollapseButton"] span[data-testid="stIconMaterial"],
[data-testid="stSidebarCollapseButton"] span[data-testid="stIconMaterial"] svg,
[data-testid="stSidebarCollapseButton"] span[data-testid="stIconMaterial"] svg path {
  color: #efede7 !important;
  fill: #efede7 !important;
}

[data-testid="stSidebar"],
[data-testid="stSidebar"] section,
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
  background-color: #1c1a17 !important;
  color: #e3ded6 !important;
}

[data-testid="stSidebar"] [data-testid="stSidebarNav"] span,
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {
  color: #d8d3c9 !important;
}

[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
  color: #9e978b !important;
}

[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] button[kind="secondary"],
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="baseButton-secondary"],
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="stBaseButton-secondary"] {
  background: rgba(45, 42, 38, 0.98) !important;
  border-color: rgba(218, 210, 196, 0.22) !important;
}

[data-testid="stAppViewContainer"] {
  background-color: #141210 !important;
}

label[data-testid="stWidgetLabel"] p,
label[data-testid="stWidgetLabel"] span,
[data-testid="stWidgetLabel"] {
  color: #d0cac0 !important;
}

[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
div[data-testid="stMarkdownContainer"] > div {
  color: #dbd6cb !important;
}

.stTabs [data-baseweb="tab"],
.stTabs button[data-baseweb="tab"] {
  color: #c9c4bb !important;
}

.stTabs [aria-selected="true"] {
  color: #f7f4ed !important;
}

h1 {
  color: #f7f4ed !important;
  border-bottom-color: #3f3b34 !important;
}

h2, h3 {
  color: #f0ebe3 !important;
}

.stMarkdown p, .stMarkdown li {
  color: #d8d3c9 !important;
}

.stMarkdown a {
  color: #9cbf9f !important;
}

blockquote {
  border-left-color: #5d825f !important;
  color: #c4bdb0 !important;
}

hr {
  border-top-color: #4a463e !important;
}

.stMarkdown code {
  background: #2a2723 !important;
  color: #f2ede5 !important;
}

[data-testid="stCaptionContainer"] {
  color: #9e978b !important;
}

[data-testid="stMetricLabel"] *,
[data-testid="stMetricLabel"] > div {
  color: #a8a096 !important;
}

[data-testid="stMetricValue"] {
  color: #f5f2eb !important;
}

[data-baseweb="base-input"],
[data-baseweb="textarea"],
[data-testid="stTextInput"],
[data-testid="stSelectbox"],
[data-testid="stNumberInput"],
[data-testid="stDateInput"],
[data-testid="stSlider"] div[role="slider"] {
  --tw-ring-color: transparent;
}

[data-testid="stExpandableDetails"] summary,
[data-testid="stExpander"] summary,
details summary {
  color: #eae6df !important;
}

[data-testid="stVerticalBlockBorderWrapper"],
hr[data-testid="stMarkdownHorizontalRule"] {
  border-color: #3f3b34 !important;
}

/* Dataframe chrome (readable grid) */
[data-testid="stDataFrame"],
[data-testid="stTable"] table {
  color: #e3ded6 !important;
}

iframe[title="streamlit_pdf_viewer"], iframe {
  color-scheme: dark;
}
"""


def inject_global_styles(*, dark_mode: bool = False) -> None:
    blob = _CSS + (_CSS_DARK if dark_mode else "")
    st.markdown(f"<style>{blob}</style>", unsafe_allow_html=True)


def _flip_dark_theme() -> None:
    st.session_state["dark_mode"] = not bool(st.session_state.get("dark_mode", False))


def render_sidebar_theme_toggle() -> None:
    """Moon/sun icon toggle with a caption to the right; call inside ``with st.sidebar:``."""

    is_dark = bool(st.session_state.get("dark_mode", False))
    # Light UI → moon (switch to dark). Dark UI → sun (switch to light).
    icon = "☀️" if is_dark else "🌙"
    mode_label = "Dark mode" if is_dark else "Light mode"

    col_btn, col_label = st.columns([1, 4], gap="small")
    with col_btn:
        kw = dict(
            key="wb_sidebar_theme_btn",
            type="secondary",
            on_click=_flip_dark_theme,
        )

        try:
            st.button("", icon=icon, **kw)
        except TypeError:
            st.button(icon, **kw)
    with col_label:
        st.caption(mode_label)

    st.markdown("Tim McLynn  \nFast Casual Case Study  \nMay 11, 2026")
