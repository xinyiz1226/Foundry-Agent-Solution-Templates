"""Local configured UI; all extraction runs in the separate authenticated backend."""

import os

import streamlit as st

from information_extraction.configured_client import ConfiguredClient, ConfiguredWorkbenchError
from information_extraction.configured_ui import render_configured_workbench


def client_scope():
    url = os.environ.get("INFORMATION_EXTRACTION_CONFIGURED_BACKEND_URL")
    token = os.environ.get("INFORMATION_EXTRACTION_CONFIGURED_TOKEN")
    if not url or not token:
        raise ConfiguredWorkbenchError(
            "Configured backend connection is missing. Start the local configured-workbench launcher."
        )
    return ConfiguredClient(url, token)


st.set_page_config(page_title="Configured extraction — local", layout="wide")
st.title("Configured extraction")
render_configured_workbench(client_scope)
