"""Safe metadata for an anonymous browser-login probe; never serialize raw headers."""

from collections.abc import Mapping
import re
from urllib.parse import urlsplit
from uuid import UUID


def observe_response(
    status_code: int, headers: Mapping[str, str], *,
    expected_host: str, tenant_id: str, accept: str,
) -> dict[str, str | int | bool | None]:
    """Classify a single response without following redirects or inspecting its body."""
    if (
        type(status_code) is not int or not 100 <= status_code <= 599
        or re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", expected_host) is None
        or accept not in ("text/html", "*/*")
    ):
        raise ValueError("Invalid anonymous-probe configuration.")
    tenant = str(UUID(tenant_id))
    host = expected_host.lower()

    def header(name: str) -> str:
        return next((value for key, value in headers.items() if key.lower() == name), "")

    location = header("location")
    kind = "missing"
    location_host = None
    location_path = None
    if location:
        kind = "unexpected"
        try:
            target = urlsplit(location)
            clean = target.username is None and target.password is None and target.port in (None, 443)
            local = (
                (not target.scheme and not target.netloc and location.startswith("/"))
                or (target.scheme == "https" and target.hostname == host)
            )
            if clean and local and target.path == "/.auth/login/aad":
                kind = "site_aad_login"
                location_host = host
                location_path = target.path
            elif (
                clean and target.scheme == "https" and target.hostname == "login.microsoftonline.com"
                and target.path == f"/{tenant}/oauth2/v2.0/authorize"
            ):
                kind = "tenant_authorize"
                location_host = target.hostname
                location_path = target.path
        except ValueError:
            kind = "invalid"
    content_type = header("content-type").split(";", 1)[0].strip().lower()
    safe_types = {"text/html", "text/plain", "application/json", "application/problem+json", "application/octet-stream"}
    request_id = header("x-ms-request-id")
    if re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", request_id) is None:
        request_id = None
    return {
        "status_code": status_code,
        "accept": accept,
        "content_type": content_type if content_type in safe_types else ("other" if content_type else None),
        "request_id": request_id,
        "has_location": bool(location),
        "location_kind": kind,
        "location_host": location_host,
        "location_path": location_path,
        "login_redirect": status_code in (302, 303, 307) and kind in ("site_aad_login", "tenant_authorize"),
    }
