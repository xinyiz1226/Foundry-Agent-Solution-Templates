"""Local Streamlit entry point; never starts an extraction worker."""

import os

import streamlit as st

from information_extraction.workbench_client import WorkbenchClient
from information_extraction.workbench_ui import render_workbench


st.set_page_config(page_title="Information extraction", layout="wide")
st.title("Information extraction")
st.info("Local synthetic preview. No Azure resources or real models are used.")
render_workbench(lambda: WorkbenchClient(os.environ.get(
    "INFORMATION_EXTRACTION_BACKEND_URL", "http://127.0.0.1:8765",
)))
