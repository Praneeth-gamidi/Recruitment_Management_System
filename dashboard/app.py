from __future__ import annotations

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None


if st is not None:
    st.set_page_config(page_title="Recruitment Management System")
    st.title("Recruitment Management System")
    st.write("The live, database-backed recruiter workspace is served by the FastAPI application.")
    st.link_button("Open recruiter workspace", "http://127.0.0.1:8000/ui/")
    st.caption("Start the API with `python main.py` before opening the workspace.")
