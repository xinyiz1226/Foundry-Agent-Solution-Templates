"""Short-lived operator proof, in addition to App Service's OIDC login."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import json
import math
from threading import Lock
import time
from uuid import UUID

import httpx
import jwt

from .workbench_client import WorkbenchError


class AuthorizationError(WorkbenchError):
    """Safe to display; never includes claims, tokens, or provider responses."""


@dataclass(frozen=True)
class OperatorPolicy:
    tenant_id: str
    client_id: str
    operator_id: str
    max_age_seconds: int = 900

    def __post_init__(self) -> None:
        for name in ("tenant_id", "client_id", "operator_id"):
            value = getattr(self, name)
            try:
                if type(value) is not str or str(UUID(value)) != value.lower():
                    raise ValueError
            except ValueError:
                raise AuthorizationError("Invalid operator policy: canonical identity UUIDs are required.") from None
            object.__setattr__(self, name, value.lower())
        if type(self.max_age_seconds) is not int or not 60 <= self.max_age_seconds <= 3600:
            raise AuthorizationError("Invalid operator policy: maximum token age must be 60-3600 seconds.")


class OperatorAuthorizer:
    def __init__(
        self, policy: OperatorPolicy, *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.policy = policy
        self._clock = clock
        self._lock = Lock()
        self._keys: dict[str, jwt.PyJWK] = {}
        self._keys_until = 0.0
        self._retry_after = 0.0
        self._http = httpx.Client(
            transport=transport, timeout=5, follow_redirects=False, trust_env=False,
        )

    def close(self) -> None:
        self._http.close()

    def _signing_key(self, key_id: str) -> jwt.PyJWK:
        with self._lock:
            if self._clock() >= self._keys_until:
                if self._clock() < self._retry_after:
                    raise AuthorizationError("Sign-in verification is unavailable. Access is blocked.")
                self._retry_after = self._clock() + 30
                self._keys = {}
                with self._http.stream(
                    "GET", f"https://login.microsoftonline.com/{self.policy.tenant_id}/discovery/v2.0/keys",
                ) as response:
                    if response.status_code != 200:
                        raise AuthorizationError("Sign-in verification is unavailable. Access is blocked.")
                    content = bytearray()
                    for part in response.iter_bytes(chunk_size=8192):
                        content.extend(part)
                        if len(content) > 65536:
                            raise ValueError
                data = json.loads(content)
                if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
                    raise ValueError
                keys = {}
                for key in data["keys"]:
                    if not isinstance(key, dict):
                        raise ValueError
                    key_id_value = key.get("kid")
                    if not isinstance(key_id_value, str) or not key_id_value or key_id_value in keys:
                        raise ValueError
                    if key.get("kty") != "RSA" or key.get("use") != "sig" or key.get("alg", "RS256") != "RS256":
                        continue
                    issuer = f"https://login.microsoftonline.com/{self.policy.tenant_id}/v2.0"
                    key_issuer = key.get("issuer", issuer)
                    if not isinstance(key_issuer, str) or key_issuer.replace("{tenantid}", self.policy.tenant_id) != issuer:
                        continue
                    keys[key_id_value] = jwt.PyJWK.from_dict(key, algorithm="RS256")
                if not keys:
                    raise ValueError
                self._keys = keys
                self._keys_until = self._clock() + 300
            if key_id not in self._keys:
                raise ValueError
            return self._keys[key_id]

    def authorize(self, id_tokens: Sequence[str]) -> None:
        if isinstance(id_tokens, str) or len(id_tokens) != 1 or not id_tokens[0]:
            raise AuthorizationError("Sign in with the approved account. Exactly one ID token is required.")
        token = id_tokens[0]
        if type(token) is not str or len(token) > 16384:
            raise AuthorizationError("The sign-in proof is invalid. Sign in again.")
        try:
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256" or header.get("typ") != "JWT" or "crit" in header
                or not isinstance(header.get("kid"), str) or not 1 <= len(header["kid"]) <= 128
            ):
                raise ValueError
            claims = jwt.decode(
                token, self._signing_key(header["kid"]).key,
                algorithms=["RS256"], audience=self.policy.client_id,
                issuer=f"https://login.microsoftonline.com/{self.policy.tenant_id}/v2.0",
                options={
                    "require": ["exp", "iat", "nbf", "tid", "oid", "ver"],
                    "verify_exp": False, "verify_iat": False, "verify_nbf": False,
                    "strict_aud": True,
                },
            )
            if (
                claims["tid"] != self.policy.tenant_id
                or claims["oid"] != self.policy.operator_id or claims["ver"] != "2.0"
            ):
                raise AuthorizationError("This account is not an authorized operator.")
            now = self._clock()
            if not math.isfinite(now):
                raise ValueError
            if any(type(claims[key]) is not int for key in ("iat", "nbf", "exp")):
                raise ValueError
            if claims["iat"] > now or claims["nbf"] > now:
                raise ValueError
            if now >= min(claims["exp"], claims["iat"] + self.policy.max_age_seconds):
                raise AuthorizationError("Sign-in proof expired. Sign in again and reconnect the page.")
        except httpx.HTTPError:
            raise AuthorizationError("Sign-in verification is unavailable. Access is blocked.") from None
        except (jwt.PyJWTError, ValueError, KeyError, TypeError):
            raise AuthorizationError("The sign-in proof is invalid. Sign in again.") from None
