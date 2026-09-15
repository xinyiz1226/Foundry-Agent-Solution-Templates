"""One fixed, read-only SQL probe with bounded output and verified TLS."""

from __future__ import annotations

import ipaddress
import queue
import socket
import threading
from decimal import Decimal
from typing import Any
from uuid import UUID

import certifi
import pytds

from .config import Settings

SQL_SCOPE = "https://database.windows.net/.default"
TOOL_NAME = "probe_private_sql"
TOOL_DEFINITION = {
    "type": "function",
    "name": TOOL_NAME,
    "description": "Read the isolated approved SQL probe view and report connection/permission evidence. No arguments or arbitrary SQL.",
    "strict": True,
    "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
}
PERMISSIONS = {
    "base_select": ("reporting.pilot_probe", "OBJECT", "SELECT"),
    "base_insert": ("reporting.pilot_probe", "OBJECT", "INSERT"),
    "base_update": ("reporting.pilot_probe", "OBJECT", "UPDATE"),
    "base_delete": ("reporting.pilot_probe", "OBJECT", "DELETE"),
    "view_select": ("reporting.v_pilot_probe", "OBJECT", "SELECT"),
    "view_insert": ("reporting.v_pilot_probe", "OBJECT", "INSERT"),
    "view_update": ("reporting.v_pilot_probe", "OBJECT", "UPDATE"),
    "view_delete": ("reporting.v_pilot_probe", "OBJECT", "DELETE"),
    "view_alter": ("reporting.v_pilot_probe", "OBJECT", "ALTER"),
    "view_control": ("reporting.v_pilot_probe", "OBJECT", "CONTROL"),
    "schema_alter": ("reporting", "SCHEMA", "ALTER"),
    "schema_control": ("reporting", "SCHEMA", "CONTROL"),
    "database_create_table": (None, "DATABASE", "CREATE TABLE"),
    "database_create_view": (None, "DATABASE", "CREATE VIEW"),
    "database_alter_any_schema": (None, "DATABASE", "ALTER ANY SCHEMA"),
    "database_control": (None, "DATABASE", "CONTROL"),
}

# This SQL is assembled only from module constants, never from model/user input.
_PERMISSION_SQL = ",\n    ".join(
    f"HAS_PERMS_BY_NAME({'DB_NAME()' if name is None else chr(39) + name + chr(39)}, "
    f"'{kind}', '{permission}') AS {alias}"
    for alias, (name, kind, permission) in PERMISSIONS.items()
)
PROBE_SQL = f"""SELECT TOP (2)
    p.probe_id, CAST(p.label AS nvarchar(101)) AS label, p.amount,
    CAST(USER_NAME() AS nvarchar(128)) AS database_principal,
    (SELECT CASE WHEN DATALENGTH(sid) = 16 THEN CAST(sid AS uniqueidentifier) ELSE NULL END
     FROM sys.database_principals WHERE principal_id = USER_ID()) AS database_principal_sid,
    CAST(DB_NAME() AS nvarchar(128)) AS database_name,
    {_PERMISSION_SQL}
FROM (VALUES (1)) AS expected(probe_id)
LEFT JOIN reporting.v_pilot_probe AS p ON p.probe_id = expected.probe_id;"""
EXPECTED_FIXTURE = {"probe_id": 1, "label": "private-sql-probe", "amount": "42.00"}
EXPECTED_PRINCIPAL = "bpi_probe_agent"
_PRIVATE_NETWORKS = tuple(ipaddress.ip_network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))


class ProbeFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def resolve_candidates(server: str, timeout: int) -> list[str]:
    """Bound the wait for the OS resolver, whose underlying call cannot be cancelled."""
    results: queue.Queue = queue.Queue(maxsize=1)

    def resolve() -> None:
        try:
            results.put(socket.getaddrinfo(server, 1433, type=socket.SOCK_STREAM))
        except Exception:
            results.put(None)

    threading.Thread(target=resolve, daemon=True, name="sql-probe-dns").start()
    try:
        records = results.get(timeout=timeout)
    except queue.Empty:
        raise ProbeFailure("dns_timeout", "SQL DNS resolution exceeded the configured connection timeout.") from None
    if not records:
        raise ProbeFailure("dns_failed", "The SQL FQDN could not be resolved.")
    addresses = sorted({record[4][0] for record in records})
    if not addresses or len(addresses) > 16:
        raise ProbeFailure("dns_failed", "SQL DNS returned an invalid or excessive address set.")
    return addresses


def _private(address: str) -> bool:
    parsed = ipaddress.ip_address(address)
    return any(parsed in network for network in _PRIVATE_NETWORKS)

def require_private_candidates(server: str, timeout: int, resolver=resolve_candidates) -> list[str]:
    addresses = resolver(server, timeout)
    try:
        valid = (
            isinstance(addresses, list) and 0 < len(addresses) <= 16
            and all(isinstance(address, str) and _private(address) for address in addresses)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ProbeFailure("private_dns_required", "SQL DNS must resolve exclusively to private-network addresses.")
    return addresses


class SqlProbe:
    def __init__(self, settings: Settings, credential: Any, *, connect=None, resolver=None):
        self.settings = settings
        self.credential = credential
        self._connect = connect or pytds.connect
        self._resolve = resolver or resolve_candidates

    def connection_options(self) -> dict[str, Any]:
        def acquire_token() -> str:
            try:
                return self.credential.get_token(SQL_SCOPE).token
            except Exception:
                raise ProbeFailure("identity_failed", "The configured identity could not acquire a SQL token.") from None

        return {
            "dsn": self.settings.server,
            "database": self.settings.database,
            "port": 1433,
            "timeout": self.settings.query_timeout,
            "login_timeout": self.settings.connect_timeout,
            "access_token_callable": acquire_token,
            "cafile": certifi.where(),
            "validate_host": True,
            "enc_login_only": False,
            "disable_connect_retry": True,
            "pooling": False,
            "autocommit": True,
            "as_dict": True,
            "appname": "business-performance-sql-probe",
        }

    def run(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": 1,
            "ok": False,
            "tool": TOOL_NAME,
            "server": self.settings.server,
            "database": self.settings.database,
            "query": PROBE_SQL,
            "limits": {"rows": 2, "queries": 1, "query_timeout_seconds": self.settings.query_timeout, "connect_timeout_seconds": self.settings.connect_timeout},
            "identity_mode": "local_development" if self.settings.local_development else "managed_identity",
            "tls": {"ca_source": "certifi", "hostname_verification": True, "full_session_encryption": True},
        }
        connection = None
        cursor = None
        stage = "dns"
        try:
            addresses = self._resolve(self.settings.server, self.settings.connect_timeout)
            result["dns"] = {
                "candidates": addresses,
                "all_candidates_private": bool(addresses) and all(_private(a) for a in addresses),
                "note": "DNS candidates only, not proof of the connected peer or public-network configuration.",
            }
            if not result["dns"]["all_candidates_private"]:
                raise ProbeFailure("private_dns_required", "SQL DNS must resolve exclusively to private-network addresses.")
            stage = "connect"
            connection = self._connect(**self.connection_options())
            stage = "query"
            cursor = connection.cursor()
            cursor.execute(PROBE_SQL)
            rows = cursor.fetchmany(2)
            if len(rows) != 1:
                raise ProbeFailure("fixture_mismatch", "The approved view did not return exactly one expected probe record.")
            row = rows[0]
            principal = row["database_principal"]
            if not isinstance(principal, str) or not principal or len(principal) > 128:
                raise ProbeFailure("principal_invalid", "SQL did not return a valid authenticated database principal.")
            result["database_principal"] = principal
            sid = row["database_principal_sid"]
            if sid is not None:
                try:
                    sid = str(UUID(str(sid)))
                except ValueError:
                    raise ProbeFailure("principal_sid_invalid", "SQL returned an invalid database principal SID.") from None
            result["database_principal_sid"] = sid
            result["principal_sid_status"] = "available" if sid is not None else "unavailable"
            result["authenticated_database"] = row["database_name"]
            if row["database_name"] != self.settings.database:
                raise ProbeFailure("database_mismatch", "The authenticated database differs from the configured database.")
            if principal != EXPECTED_PRINCIPAL:
                raise ProbeFailure("principal_mismatch", "The authenticated principal is not the dedicated bpi_probe_agent user.")
            amount = row["amount"]
            fixture = {
                "probe_id": row["probe_id"],
                "label": row["label"],
                "amount": format(amount, ".2f") if isinstance(amount, Decimal) else None,
            }
            result["fixture"] = fixture
            result["fixture_matches"] = fixture == EXPECTED_FIXTURE and amount == Decimal("42.00")
            permissions = {name: row[name] for name in PERMISSIONS}
            if any(value is not None and (type(value) is not int or value not in (0, 1)) for value in permissions.values()):
                raise ProbeFailure("permission_metadata_invalid", "SQL returned unexpected permission metadata.")
            result["permissions"] = permissions
            unexpected = [key for key, value in permissions.items() if key != "view_select" and value == 1]
            unknown = [key for key, value in permissions.items() if value is None]
            result["permission_check"] = {
                "status": "unexpected_grants" if unexpected else "incomplete" if unknown else "passed",
                "unexpected_grants": unexpected,
                "unknown": unknown,
                "note": "NULL means unknown (possibly hidden metadata), not denied. These checks do not enumerate every SQL permission.",
            }
            if not result["fixture_matches"]:
                raise ProbeFailure("fixture_mismatch", "The approved view record differs from the deterministic pilot fixture.")
            if permissions["view_select"] != 1 or unexpected:
                raise ProbeFailure("permission_check_failed", "The runtime principal does not match the pilot least-privilege permission contract.")
            if unknown:
                raise ProbeFailure("permission_metadata_incomplete", "Some permission metadata is unavailable; unknown permissions cannot establish least privilege.")
            result["ok"] = True
        except ProbeFailure as exc:
            result["error"] = {"code": exc.code, "message": str(exc)}
        except (TimeoutError, pytds.TimeoutError):
            result["error"] = {"code": f"{stage}_timeout", "message": "The SQL probe exceeded a configured timeout."}
        except Exception:
            result["error"] = {
                "code": f"{stage}_failed",
                "message": "The SQL probe failed. Check private DNS/networking, trusted TLS, identity, and approved-view permissions; raw exception details are intentionally omitted.",
            }
        finally:
            cleanup_failures = []
            for name, resource in (("cursor", cursor), ("connection", connection)):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        cleanup_failures.append(name)
            if cleanup_failures:
                result["ok"] = False
                result["cleanup_failed"] = True
                result["cleanup_failed_resources"] = cleanup_failures
                if "error" in result:
                    result["primary_error"] = result["error"]
                result["error"] = {
                    "code": "cleanup_failed",
                    "message": "SQL probe resources did not close cleanly; raw exception details are omitted.",
                }
        return result
