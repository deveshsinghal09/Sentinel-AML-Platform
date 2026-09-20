"""Optional Streamlit compatibility launcher for Sentinel AML."""
from __future__ import annotations

import streamlit as st


st.set_page_config(
    page_title="Sentinel AML",
    page_icon="🔎",
    layout="wide",
)

st.title("🔎 Sentinel AML")
st.info(
    "The production analyst experience is the routed React workspace. "
    "This lightweight page remains available for Python-only environments."
)
st.markdown(
    """
    ### Agentic investigation flow

    ```
    Query → Intent extraction → Dynamic plan → Selective AML tools
          → Risk decision → Explanation → Escalation → Audit trace
    ```

    ### Local services

    1. Start the API with `uvicorn api.main:app --reload`.
    2. Start the React workspace from `frontend/` with `npm run dev`.
    3. Use this compatibility page only when the React runtime is unavailable.

    Raw transaction evidence, local DuckDB files, and environment credentials
    remain outside source control.
    """
)
