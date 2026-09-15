"""Cloud UI wiring; credentials and routing are shared, caller identity is not."""

import atexit
from collections.abc import Iterator
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import os
import time
from typing import TYPE_CHECKING

import streamlit as st
from azure.identity import ManagedIdentityCredential

from .workbench_auth import AuthorizationError, OperatorAuthorizer, OperatorPolicy
from .workbench_client import WorkbenchError
from .workbench_ui import render_workbench

if TYPE_CHECKING:
    from .cloud_workbench_client import CloudWorkbenchClient


@dataclass(frozen=True)
class CloudSettings:
    policy: OperatorPolicy
    project_endpoint: str
    agent_name: str

    @classmethod
    def from_environment(cls) -> "CloudSettings":
        try:
            policy = OperatorPolicy(
                os.environ["INFORMATION_EXTRACTION_WEB_TENANT_ID"],
                os.environ["INFORMATION_EXTRACTION_WEB_CLIENT_ID"],
                os.environ["INFORMATION_EXTRACTION_WEB_OPERATOR_ID"],
                int(os.environ.get("INFORMATION_EXTRACTION_WEB_MAX_TOKEN_AGE", "900")),
            )
            return cls(
                policy, os.environ["INFORMATION_EXTRACTION_PROJECT_ENDPOINT"],
                os.environ["INFORMATION_EXTRACTION_AGENT_NAME"],
            )
        except (KeyError, ValueError):
            raise AuthorizationError("Cloud authorization configuration is missing or invalid. Access is blocked.") from None


@st.cache_resource(show_spinner=False)
def _authorizer(policy: OperatorPolicy) -> OperatorAuthorizer:
    authorizer = OperatorAuthorizer(policy, clock=lambda: time.time())
    atexit.register(authorizer.close)
    return authorizer


def _authorize(settings: CloudSettings) -> None:
    if CloudSettings.from_environment() != settings:
        raise AuthorizationError("The operator policy or cloud configuration changed. Reload the page.")
    _authorizer(settings.policy).authorize(st.context.headers.get_all("X-MS-TOKEN-AAD-ID-TOKEN"))


@st.cache_resource(show_spinner=False)
def _cloud_client(settings: CloudSettings) -> "CloudWorkbenchClient":
    from .cloud_workbench_client import CloudWorkbenchClient

    with ExitStack() as stack:
        credential = stack.enter_context(ManagedIdentityCredential())
        client = stack.enter_context(CloudWorkbenchClient(
            settings.project_endpoint, settings.agent_name, credential,
            authorize=lambda: _authorize(settings),
        ))
        resources = stack.pop_all()
        atexit.register(resources.close)
        return client


@contextmanager
def _client_scope(settings: CloudSettings) -> Iterator["CloudWorkbenchClient"]:
    yield _cloud_client(settings)


def _login_links() -> None:
    st.link_button("Sign out", "/.auth/logout")
    st.link_button("Sign in / reconnect", "/.auth/login/aad?post_login_redirect_uri=%2F")


def render_cloud_workbench() -> None:
    st.set_page_config(page_title="Information extraction", layout="wide")
    st.title("Information extraction")
    st.info("Cloud synthetic workbench. Deployment and live authorization validation are separate gates.")
    try:
        settings = CloudSettings.from_environment()
        _authorize(settings)
        render_workbench(
            lambda: _client_scope(settings), authorize=lambda: _authorize(settings),
            poll_seconds=10, on_error=_login_links,
        )
    except WorkbenchError as error:
        st.error(str(error))
        _login_links()
