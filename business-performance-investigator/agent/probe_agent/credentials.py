"""Explicit identity selection: production never discovers developer credentials."""

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

from .config import Settings


def create_credential(settings: Settings):
    if settings.local_development:
        return DefaultAzureCredential(
            exclude_interactive_browser_credential=True,
            require_envvar=False,
        )
    if settings.client_id:
        return ManagedIdentityCredential(client_id=settings.client_id)
    return ManagedIdentityCredential()
